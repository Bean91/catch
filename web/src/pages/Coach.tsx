import * as Dialog from "@radix-ui/react-dialog";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import {
  createConversation,
  deleteConversation,
  fetchConversation,
  fetchConversations,
  fetchDailyUsage,
  saveCoachSettings,
  streamMessage,
} from "../lib/api";
import { formatRelativeTime } from "../lib/format";
import { buildTimeline, type TimelineEntry } from "../lib/timeline";
import type { CoachConversation } from "../lib/types";
import { SuggestedPrompts } from "../components/coach/SuggestedPrompts";
import { Timeline } from "../components/coach/Timeline";

const MORNING_BRIEF_PROMPT =
  "Give me my morning brief — how's recovery and strain looking today, and what should today's training look like?";

type Notice = { kind: "error" | "cap" | "provider"; message: string };

function ConversationRow({
  conversation,
  active,
  onSelect,
  onDelete,
}: {
  conversation: CoachConversation;
  active: boolean;
  onSelect: () => void;
  onDelete: () => void;
}) {
  return (
    <div className={`flex items-center gap-2 rounded-md px-2 py-1.5 ${active ? "bg-surface-2" : ""}`}>
      <button type="button" onClick={onSelect} className="min-h-9 flex-1 truncate text-left text-sm text-text-primary">
        {conversation.title ?? "New conversation"}
        <span className="ml-2 text-xs text-text-tertiary">{formatRelativeTime(conversation.updated_at)}</span>
      </button>
      <button
        type="button"
        onClick={onDelete}
        aria-label="Delete conversation"
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-text-tertiary transition-colors hover:text-band-red-text"
      >
        ×
      </button>
    </div>
  );
}

export function CoachPage() {
  const queryClient = useQueryClient();
  const [conversationId, setConversationId] = useState<number | null>(null);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [liveEntries, setLiveEntries] = useState<TimelineEntry[]>([]);
  const [streamingText, setStreamingText] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const conversationsQuery = useQuery({ queryKey: ["coach-conversations"], queryFn: fetchConversations });
  const detailQuery = useQuery({
    queryKey: ["coach-conversation", conversationId],
    queryFn: () => fetchConversation(conversationId as number),
    enabled: conversationId != null,
  });
  const usageQuery = useQuery({ queryKey: ["coach-daily-usage"], queryFn: fetchDailyUsage });

  useEffect(() => {
    setLiveEntries([]);
    setStreamingText(null);
    setNotice(null);
  }, [conversationId]);

  const historyEntries = detailQuery.data ? buildTimeline(detailQuery.data.messages) : [];
  const allEntries = [...historyEntries, ...liveEntries];
  const hasMessages = allEntries.length > 0 || streamingText != null;

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [allEntries.length, streamingText]);

  async function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed || sending) return;
    setInput("");
    setSending(true);
    setNotice(null);

    let convId = conversationId;
    if (convId == null) {
      const conv = await createConversation();
      convId = conv.id;
      setConversationId(convId);
    }

    setLiveEntries((entries) => [...entries, { kind: "text", key: `local-user-${Date.now()}`, role: "user", text: trimmed }]);

    let currentText = "";
    setStreamingText("");
    const flushText = () => {
      if (currentText) {
        const finished = currentText;
        setLiveEntries((entries) => [...entries, { kind: "text", key: `local-asst-${Date.now()}-${entries.length}`, role: "assistant", text: finished }]);
        currentText = "";
      }
      setStreamingText(null);
    };

    try {
      for await (const event of streamMessage(convId, trimmed)) {
        if (event.type === "text") {
          currentText += event.text;
          setStreamingText(currentText);
        } else if (event.type === "tool_call") {
          flushText();
          setLiveEntries((entries) => [
            ...entries,
            { kind: "tool", key: event.id, id: event.id, name: event.name, label: event.label, input: event.input, output: undefined, isError: false, pending: true },
          ]);
        } else if (event.type === "tool_result") {
          setLiveEntries((entries) =>
            entries.map((e) => (e.kind === "tool" && e.id === event.id ? { ...e, output: event.output, isError: event.is_error, pending: false } : e)),
          );
        } else if (event.type === "done") {
          flushText();
        } else if (event.type === "error") {
          flushText();
          setNotice({ kind: "error", message: event.message });
        } else if (event.type === "provider_unavailable") {
          flushText();
          setNotice({ kind: "provider", message: event.message });
        } else if (event.type === "cap_reached") {
          flushText();
          setNotice({ kind: "cap", message: `Daily spend cap reached ($${event.daily_cap_usd.toFixed(2)}) — raise it in Settings to keep going today.` });
        }
      }
    } catch {
      flushText();
      setNotice({ kind: "error", message: "Lost connection to the coach. Try again." });
    } finally {
      setSending(false);
      await queryClient.invalidateQueries({ queryKey: ["coach-conversation", convId] });
      setLiveEntries([]);
      queryClient.invalidateQueries({ queryKey: ["coach-conversations"] });
      queryClient.invalidateQueries({ queryKey: ["coach-daily-usage"] });
    }
  }

  async function switchToAnthropic() {
    await saveCoachSettings({ provider: "anthropic" });
    setNotice(null);
  }

  return (
    <div className="flex h-[calc(100dvh-9.5rem)] flex-col gap-3 lg:h-[calc(100dvh-7rem)]">
      <div className="flex items-center justify-between gap-2">
        <h1 className="text-lg font-semibold text-text-primary">Coach</h1>
        <div className="flex items-center gap-2">
          {usageQuery.data && (
            <span className="font-mono-nums text-xs text-text-tertiary">
              ${usageQuery.data.spend_usd.toFixed(2)}
              {usageQuery.data.cap_usd != null && ` / $${usageQuery.data.cap_usd.toFixed(2)}`} today
            </span>
          )}
          <button
            type="button"
            onClick={() => setHistoryOpen(true)}
            className="min-h-9 rounded-md border border-border px-3 text-xs font-medium text-text-secondary transition-colors hover:border-accent"
          >
            History
          </button>
          <button
            type="button"
            onClick={() => setConversationId(null)}
            className="min-h-9 rounded-md border border-border px-3 text-xs font-medium text-text-secondary transition-colors hover:border-accent"
          >
            New
          </button>
        </div>
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto rounded-lg border border-border bg-surface p-4">
        {!hasMessages ? (
          <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
            <p className="max-w-xs text-sm text-text-tertiary">Ask about today's training, or pick a starting point.</p>
            <SuggestedPrompts onPick={send} />
            <button
              type="button"
              onClick={() => send(MORNING_BRIEF_PROMPT)}
              className="min-h-11 rounded-md bg-accent px-5 text-sm font-medium text-accent-contrast transition-opacity hover:opacity-90"
            >
              Morning brief
            </button>
          </div>
        ) : (
          <Timeline entries={allEntries} streamingText={streamingText ?? undefined} />
        )}
      </div>

      {notice && (
        <div
          className={`flex items-center justify-between gap-3 rounded-md border px-3 py-2 text-xs ${
            notice.kind === "error" ? "border-band-red/30 bg-band-red/10 text-band-red-text" : "border-border bg-surface-2 text-text-secondary"
          }`}
        >
          <span>{notice.message}</span>
          {notice.kind === "provider" && (
            <button type="button" onClick={switchToAnthropic} className="shrink-0 font-medium text-accent hover:underline">
              Switch to Anthropic
            </button>
          )}
        </div>
      )}

      <form
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
        className="flex items-end gap-2"
      >
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send(input);
            }
          }}
          placeholder="Ask your coach…"
          rows={1}
          disabled={sending}
          className="flex-1 resize-none rounded-md border border-border bg-surface-2 px-3 py-2.5 text-sm text-text-primary placeholder:text-text-tertiary focus-visible:outline-none disabled:opacity-60"
        />
        <button
          type="submit"
          disabled={sending || !input.trim()}
          className="min-h-11 shrink-0 rounded-md bg-accent px-4 text-sm font-medium text-accent-contrast transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {sending ? "…" : "Send"}
        </button>
      </form>

      <Dialog.Root open={historyOpen} onOpenChange={setHistoryOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 bg-black/50" />
          <Dialog.Content className="fixed left-1/2 top-1/2 max-h-[80vh] w-[min(92vw,420px)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg border border-border bg-surface p-5 shadow-xl focus:outline-none">
            <Dialog.Title className="text-base font-semibold text-text-primary">Conversations</Dialog.Title>
            <div className="mt-3 flex flex-col gap-1">
              {conversationsQuery.data?.length ? (
                conversationsQuery.data.map((c) => (
                  <ConversationRow
                    key={c.id}
                    conversation={c}
                    active={c.id === conversationId}
                    onSelect={() => {
                      setConversationId(c.id);
                      setHistoryOpen(false);
                    }}
                    onDelete={async () => {
                      await deleteConversation(c.id);
                      if (c.id === conversationId) setConversationId(null);
                      queryClient.invalidateQueries({ queryKey: ["coach-conversations"] });
                    }}
                  />
                ))
              ) : (
                <p className="text-sm text-text-tertiary">No conversations yet.</p>
              )}
            </div>
            <Dialog.Close asChild>
              <button
                type="button"
                className="mt-4 min-h-11 w-full rounded-md border border-border text-sm font-medium text-text-primary transition-colors hover:border-accent"
              >
                Close
              </button>
            </Dialog.Close>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  );
}
