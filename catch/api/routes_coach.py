from __future__ import annotations

import json
import secrets
from datetime import date

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from catch.api.deps import get_db, hash_token, require_auth, require_tool_auth
from catch.api.sse import stream_until_disconnected
from catch.coach import chat
from catch.coach import cost as cost_module
from catch.coach import memory
from catch.coach import settings as coach_settings_module
from catch.coach import tools as tools_module
from catch.coach.providers.anthropic_provider import AnthropicProvider
from catch.coach.providers.ollama_provider import OllamaProvider
from catch.core.db import get_session
from catch.core.models import ApiToken, CoachConversation, CoachMessage

# Split in two: tool_router accepts a device bearer token (the MCP server authenticates this
# way so it can run off the Pi), coach_router is cookie-only — a stolen device token must
# never be able to read the Anthropic key, manage tokens, or browse conversation history.
tool_router = APIRouter(dependencies=[Depends(require_tool_auth)])
coach_router = APIRouter(dependencies=[Depends(require_auth)])


def _resolve_test_provider(db: Session):
    prefs = coach_settings_module.get_coach_settings(db)
    if prefs["provider"] == "ollama":
        if not prefs["ollama_base_url"]:
            raise HTTPException(status_code=400, detail="No Ollama URL configured")
        return OllamaProvider(prefs["ollama_base_url"])
    api_key = coach_settings_module.get_decrypted_credential(db, "anthropic")
    if not api_key:
        raise HTTPException(status_code=400, detail="No Anthropic API key configured")
    return AnthropicProvider(api_key)


# --- Shared tool surface (cookie OR device bearer token) --------------------------------


@tool_router.get("/api/coach/tools")
def list_tools():
    return tools_module.anthropic_tool_schemas()


class ToolCallRequest(BaseModel):
    args: dict = {}


@tool_router.post("/api/coach/tools/{name}")
def call_tool_endpoint(name: str, body: ToolCallRequest = Body(default=ToolCallRequest()), db: Session = Depends(get_db)):
    if name not in tools_module.TOOLS:
        raise HTTPException(status_code=404, detail=f"Unknown tool '{name}'")
    try:
        return tools_module.call_tool(db, name, body.args, ctx={})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# --- Conversations ------------------------------------------------------------------------


@coach_router.get("/api/coach/conversations")
def list_conversations(db: Session = Depends(get_db)):
    rows = db.exec(select(CoachConversation).order_by(CoachConversation.updated_at.desc())).all()
    return [
        {
            "id": c.id,
            "title": c.title,
            "created_at": c.created_at,
            "updated_at": c.updated_at,
            "usage": cost_module.conversation_usage(db, c.id),
        }
        for c in rows
    ]


@coach_router.post("/api/coach/conversations")
def create_conversation(db: Session = Depends(get_db)):
    conv = CoachConversation()
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


def _message_dict(row: CoachMessage) -> dict:
    return {
        "id": row.id,
        "role": row.role,
        "blocks": json.loads(row.blocks_json),
        "provider": row.provider,
        "model": row.model,
        "usage": json.loads(row.usage_json) if row.usage_json else None,
        "cost_usd": row.cost_usd,
        "created_at": row.created_at,
    }


@coach_router.get("/api/coach/conversations/{conversation_id}")
def get_conversation(conversation_id: int, db: Session = Depends(get_db)):
    conv = db.get(CoachConversation, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    rows = db.exec(select(CoachMessage).where(CoachMessage.conversation_id == conversation_id).order_by(CoachMessage.id)).all()
    return {
        "id": conv.id,
        "title": conv.title,
        "created_at": conv.created_at,
        "updated_at": conv.updated_at,
        "messages": [_message_dict(r) for r in rows],
        "usage": cost_module.conversation_usage(db, conversation_id),
    }


@coach_router.delete("/api/coach/conversations/{conversation_id}")
def delete_conversation(conversation_id: int, db: Session = Depends(get_db)):
    conv = db.get(CoachConversation, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    for row in db.exec(select(CoachMessage).where(CoachMessage.conversation_id == conversation_id)).all():
        db.delete(row)
    db.delete(conv)
    db.commit()
    return {"ok": True}


class MessageRequest(BaseModel):
    text: str


@coach_router.post("/api/coach/conversations/{conversation_id}/messages")
def post_message(conversation_id: int, body: MessageRequest, request: Request, db: Session = Depends(get_db)):
    conv = db.get(CoachConversation, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.title is None:
        conv.title = body.text[:60]
        db.commit()

    async def event_stream():
        # A fresh Session, not the request's Depends(get_db) one — its lifecycle relative to
        # a streamed response body isn't reliable (it may close before the generator is done).
        with get_session() as stream_session:
            turn = chat.run_turn(stream_session, conversation_id, body.text)
            # A closed client connection doesn't otherwise stop this turn — confirmed live:
            # killing the client mid-stream against a slow local model left the provider call,
            # the tool execution, and the DB writes all running to completion regardless.
            # stream_until_disconnected polls request.is_disconnected() while waiting on each
            # next event, not just once, so a long gap (the provider "thinking" with nothing
            # to yield yet) still gets cancelled promptly instead of running to completion.
            async for event in stream_until_disconnected(turn, request.is_disconnected):
                yield f"data: {json.dumps(event, default=str)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# --- Models / settings / credentials -------------------------------------------------------


@coach_router.get("/api/coach/models")
async def list_models(provider: str | None = Query(None), db: Session = Depends(get_db)):
    prefs = coach_settings_module.get_coach_settings(db)
    chosen = provider or prefs["provider"]
    if chosen == "ollama":
        if not prefs["ollama_base_url"]:
            raise HTTPException(status_code=400, detail="No Ollama URL configured")
        p = OllamaProvider(prefs["ollama_base_url"])
    else:
        api_key = coach_settings_module.get_decrypted_credential(db, "anthropic")
        if not api_key:
            raise HTTPException(status_code=400, detail="No Anthropic API key configured")
        p = AnthropicProvider(api_key)
    return await p.list_models()


@coach_router.get("/api/coach/settings")
def get_coach_settings_endpoint(db: Session = Depends(get_db)):
    prefs = coach_settings_module.get_coach_settings(db)
    prefs["anthropic_key"] = coach_settings_module.masked_credential_info(db, "anthropic")
    return prefs


@coach_router.put("/api/coach/settings")
def put_coach_settings_endpoint(patch: dict = Body(...), db: Session = Depends(get_db)):
    try:
        return coach_settings_module.update_coach_settings(db, patch)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


class ApiKeyRequest(BaseModel):
    api_key: str


@coach_router.post("/api/coach/key")
def set_anthropic_key(body: ApiKeyRequest, db: Session = Depends(get_db)):
    if not body.api_key.strip():
        raise HTTPException(status_code=422, detail="api_key must not be empty")
    return coach_settings_module.set_credential(db, "anthropic", body.api_key.strip())


@coach_router.delete("/api/coach/key")
def delete_anthropic_key(db: Session = Depends(get_db)):
    coach_settings_module.delete_credential(db, "anthropic")
    return {"ok": True}


@coach_router.post("/api/coach/test-connection")
async def test_connection(db: Session = Depends(get_db)):
    provider = _resolve_test_provider(db)
    return await provider.test_connection()


@coach_router.get("/api/coach/usage/daily")
def daily_usage(db: Session = Depends(get_db)):
    prefs = coach_settings_module.get_coach_settings(db)
    return {"spend_usd": cost_module.today_spend_usd(db), "cap_usd": prefs["daily_cap_usd"]}


# --- Device tokens (for the MCP server) ----------------------------------------------------


@coach_router.get("/api/coach/tokens")
def list_tokens(db: Session = Depends(get_db)):
    rows = db.exec(select(ApiToken)).all()
    return [{"id": r.id, "name": r.name, "created_at": r.created_at, "last_used_at": r.last_used_at} for r in rows]


class TokenRequest(BaseModel):
    name: str


@coach_router.post("/api/coach/tokens")
def create_token(body: TokenRequest, db: Session = Depends(get_db)):
    raw_token = secrets.token_urlsafe(32)
    row = ApiToken(name=body.name, token_hash=hash_token(raw_token))
    db.add(row)
    db.commit()
    db.refresh(row)
    # The raw token is returned exactly once, here — only its hash is ever stored.
    return {"id": row.id, "name": row.name, "token": raw_token, "created_at": row.created_at}


@coach_router.delete("/api/coach/tokens/{token_id}")
def delete_token(token_id: int, db: Session = Depends(get_db)):
    row = db.get(ApiToken, token_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Token not found")
    db.delete(row)
    db.commit()
    return {"ok": True}


# --- Memory (events / goals / facts) -------------------------------------------------------


@coach_router.get("/api/coach/memory")
def get_memory(db: Session = Depends(get_db)):
    return memory.list_all(db)


class FactRequest(BaseModel):
    category: str
    text: str
    valid_until: date | None = None


@coach_router.post("/api/coach/memory/facts")
def create_fact(body: FactRequest, db: Session = Depends(get_db)):
    try:
        fact = memory.remember(db, body.category, body.text, body.valid_until)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return memory._fact_dict(fact)


@coach_router.put("/api/coach/memory/facts/{fact_id}")
def edit_fact(fact_id: int, body: dict = Body(...), db: Session = Depends(get_db)):
    try:
        fact = memory.update_fact(db, fact_id, **body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return memory._fact_dict(fact)


class EventRequest(BaseModel):
    name: str
    date: date
    type: str
    distance: str | None = None
    boat_class: str | None = None
    priority: str | None = None
    goal_time: str | None = None
    result: str | None = None


@coach_router.post("/api/coach/memory/events")
def create_event(body: EventRequest, db: Session = Depends(get_db)):
    try:
        event = memory.add_event(
            db,
            name=body.name,
            date_=body.date,
            type=body.type,
            distance=body.distance,
            boat_class=body.boat_class,
            priority=body.priority,
            goal_time=body.goal_time,
            result=body.result,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return memory._event_dict(event, date.today())


@coach_router.put("/api/coach/memory/events/{event_id}")
def edit_event(event_id: int, body: dict = Body(...), db: Session = Depends(get_db)):
    try:
        event = memory.update_event(db, event_id, **body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return memory._event_dict(event, date.today())


class GoalRequest(BaseModel):
    text: str
    target_date: date | None = None
    status: str = "active"


@coach_router.post("/api/coach/memory/goals")
def create_goal(body: GoalRequest, db: Session = Depends(get_db)):
    try:
        goal = memory.set_goal(db, body.text, body.target_date, body.status)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return memory._goal_dict(goal)


@coach_router.put("/api/coach/memory/goals/{goal_id}")
def edit_goal(goal_id: int, body: GoalRequest, db: Session = Depends(get_db)):
    try:
        goal = memory.set_goal(db, body.text, body.target_date, body.status, goal_id=goal_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return memory._goal_dict(goal)


@coach_router.delete("/api/coach/memory/{ref}")
def delete_memory(ref: str, db: Session = Depends(get_db)):
    try:
        deleted = memory.forget(db, ref)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not deleted:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}
