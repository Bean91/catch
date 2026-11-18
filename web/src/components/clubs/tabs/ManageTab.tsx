import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Card } from "../../ui/Card";
import {
  decideClubRequest, deleteClub, deleteClubLogo, fetchClubAudit, fetchClubInvites, fetchClubMembers, fetchClubRequests, revokeClubInvite, transferClub, updateClub, uploadClubLogo,
} from "../../../lib/api";
import { CLUB_ACTION_LABEL } from "../../../lib/clubs";
import { resizeImage } from "../../../lib/image";
import type { Club } from "../../../lib/types";
import { ErrorLine, Field, btn, btnDanger, btnPrimary, inputCls, refreshClub } from "../ClubBits";
import { InviteSheet, ReasonSheet } from "../ClubSheets";

export function ManageTab({ club }: { club: Club }) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const caps = club.capabilities ?? {};
  const [error, setError] = useState<string | null>(null);
  const [inviting, setInviting] = useState(false);
  const [declining, setDeclining] = useState<number | null>(null);
  const requests = useQuery({ queryKey: ["club-requests", club.club_id], queryFn: () => fetchClubRequests(club.club_id), enabled: !!caps.see_requests, retry: false });
  const invites = useQuery({ queryKey: ["club-invites", club.club_id], queryFn: () => fetchClubInvites(club.club_id), enabled: !!caps.see_requests, retry: false });
  const audit = useQuery({ queryKey: ["club-audit", club.club_id], queryFn: () => fetchClubAudit(club.club_id), enabled: !!caps.see_audit, retry: false });
  const members = useQuery({ queryKey: ["club-members", club.club_id], queryFn: () => fetchClubMembers(club.club_id), enabled: !!caps.transfer_ownership, retry: false });
  const approve = useMutation({ mutationFn: (id: number) => decideClubRequest(club.club_id, id, true), onSuccess: () => { setError(null); refreshClub(qc, club.club_id); }, onError: (e: Error) => setError(e.message) });
  const revoke = useMutation({ mutationFn: (id: number) => revokeClubInvite(club.club_id, id), onSuccess: () => refreshClub(qc, club.club_id), onError: (e: Error) => setError(e.message) });

  const [edit, setEdit] = useState({ description: club.description ?? "", location: club.location ?? "", rules: club.rules ?? "", visibility: club.visibility, join_policy: club.join_policy });
  const save = useMutation({
    mutationFn: () => updateClub(club.club_id, club.audience === "junior" ? { description: edit.description, rules: edit.rules } : edit),
    onSuccess: () => { setError(null); refreshClub(qc, club.club_id); },
    onError: (e: Error) => setError(e.message),
  });
  const logo = useMutation({
    mutationFn: async (file: File) => uploadClubLogo(club.club_id, await resizeImage(file, 256)),
    onSuccess: () => { setError(null); refreshClub(qc, club.club_id); },
    onError: (e: Error) => setError(e.message),
  });
  const rmLogo = useMutation({ mutationFn: () => deleteClubLogo(club.club_id), onSuccess: () => refreshClub(qc, club.club_id), onError: (e: Error) => setError(e.message) });

  const [handTo, setHandTo] = useState("");
  const [handPreview, setHandPreview] = useState<string | null>(null);
  const transfer = useMutation({
    mutationFn: (confirm: boolean) => transferClub(club.club_id, handTo, confirm),
    onSuccess: (r) => { setError(null); if (r.transferred) { refreshClub(qc, club.club_id); setHandPreview(null); } else setHandPreview(r.preview ?? null); },
    onError: (e: Error) => setError(e.message),
  });
  const [deleting, setDeleting] = useState<string | null>(null);
  const del = useMutation({
    mutationFn: (confirm: boolean) => deleteClub(club.club_id, confirm),
    onSuccess: (r) => { if (r.deleted) { refreshClub(qc); nav("/clubs"); } else setDeleting(r.preview ?? ""); },
    onError: (e: Error) => setError(e.message),
  });

  return (
    <div className="flex flex-col gap-4" data-testid="club-manage">
      {caps.see_requests && (
        <Card title={`Join requests${requests.data ? ` · ${requests.data.requests.length}` : ""}`}>
          {requests.data && requests.data.requests.length === 0 && <p className="text-sm text-text-secondary">No one is waiting.</p>}
          <ul className="flex flex-col gap-3" data-testid="club-requests">
            {(requests.data?.requests ?? []).map((r) => (
              <li key={r.request_id} data-testid="request-row" className="rounded-md border border-border p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-sm font-medium text-text-primary">{r.handle} <span className="text-xs text-text-tertiary">· asking to join as {r.role}</span></span>
                  {r.age_class === "youth" && <span className="rounded-full border border-accent/30 bg-accent/10 px-2 py-0.5 text-xs text-accent">Under 19{r.guardian_consent ? " · guardian agreed" : ""}</span>}
                </div>
                {r.message && <p className="mt-1 text-sm text-text-secondary">“{r.message}”</p>}
                {r.can_decide ? (
                  <div className="mt-2 flex gap-2">
                    <button type="button" className={btnPrimary} onClick={() => approve.mutate(r.request_id)} data-testid="request-approve">Approve</button>
                    <button type="button" className={btn} onClick={() => setDeclining(r.request_id)} data-testid="request-decline">Decline</button>
                  </div>
                ) : (
                  <p data-testid="request-needs-coach" className="mt-2 text-xs text-text-tertiary">{r.role === "coach" ? "Only an owner or admin can approve a coach." : "In a junior club only a coach or the owner approves a young member."}</p>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}

      {caps.see_requests && (
        <Card title="Invite links" action={<button type="button" className={btnPrimary} onClick={() => setInviting(true)} data-testid="invite-new">New invite</button>}>
          {invites.data && invites.data.invites.length === 0 && <p className="text-sm text-text-secondary">No invites yet. {club.audience === "junior" ? "Young members join only by invitation, then a coach approves them." : ""}</p>}
          <ul className="flex flex-col gap-2" data-testid="club-invites">
            {(invites.data?.invites ?? []).map((i) => (
              <li key={i.invite_id} className="flex flex-wrap items-center justify-between gap-2 text-sm">
                <span className="text-text-primary">{i.role === "coach" ? "Coach" : "Athlete"} invite <span className="text-xs text-text-tertiary">· {i.state}{i.state === "active" ? `, expires ${new Date(i.expires_at).toLocaleDateString()}` : ""}{i.max_uses ? ` · ${i.uses ?? 0}/${i.max_uses} used` : ""}</span></span>
                {i.state === "active" && <button type="button" className={`${btn} px-3`} onClick={() => revoke.mutate(i.invite_id)} data-testid="invite-revoke">Revoke</button>}
              </li>
            ))}
          </ul>
        </Card>
      )}

      {caps.edit_club && (
        <Card title="Club details">
          <div className="flex flex-col gap-3">
            <Field label="Description"><textarea value={edit.description} onChange={(e) => setEdit({ ...edit, description: e.target.value })} className={`${inputCls} py-2`} rows={2} maxLength={500} data-testid="edit-description" /></Field>
            {club.audience === "adult" && <Field label="Location"><input value={edit.location} onChange={(e) => setEdit({ ...edit, location: e.target.value })} className={inputCls} maxLength={80} /></Field>}
            <Field label="Club rules"><textarea value={edit.rules} onChange={(e) => setEdit({ ...edit, rules: e.target.value })} className={`${inputCls} py-2`} rows={3} maxLength={2000} /></Field>
            {club.audience === "adult" && (
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Visibility"><select value={edit.visibility} onChange={(e) => setEdit({ ...edit, visibility: e.target.value as Club["visibility"] })} className={inputCls}><option value="private">Private</option><option value="public">Public</option></select></Field>
                <Field label="How people join"><select value={edit.join_policy} onChange={(e) => setEdit({ ...edit, join_policy: e.target.value as Club["join_policy"] })} className={inputCls}><option value="request">By request</option><option value="invite">By invite link</option>{edit.visibility === "public" && <option value="open">Open</option>}</select></Field>
              </div>
            )}
            <div className="flex justify-end"><button type="button" className={btnPrimary} onClick={() => save.mutate()} disabled={save.isPending} data-testid="edit-save">Save details</button></div>
            <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
              <label className={`${btn} inline-flex cursor-pointer items-center`}>
                {club.has_logo ? "Replace logo" : "Add a logo"}
                <input type="file" accept="image/*" className="sr-only" data-testid="logo-input" onChange={(e) => { const f = e.target.files?.[0]; if (f) logo.mutate(f); e.currentTarget.value = ""; }} />
              </label>
              {club.has_logo && <button type="button" className={btn} onClick={() => rmLogo.mutate()} data-testid="logo-remove">Remove logo</button>}
              <span className="text-xs text-text-tertiary">A small image is enough. Anyone who can see this club can see it.</span>
            </div>
          </div>
        </Card>
      )}

      {caps.see_audit && (
        <Card title="Audit log">
          <p className="mb-2 text-xs text-text-tertiary">Every decision, with who made it and why. It can't be edited.</p>
          <ul className="flex flex-col divide-y divide-border text-sm" data-testid="club-audit">
            {(audit.data?.events ?? []).map((e, i) => (
              <li key={i} className="py-2">
                <span className="text-text-primary">{CLUB_ACTION_LABEL[e.action] ?? e.action}</span>
                <span className="text-text-tertiary"> · {e.by ?? "someone"}{e.about ? ` → ${e.about}` : ""} · {new Date(e.at).toLocaleDateString()}</span>
                <p className="text-xs text-text-secondary">{e.reason}</p>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {caps.transfer_ownership && (
        <Card title="Ownership">
          <div className="flex flex-col gap-3">
            <Field label="Hand this club to">
              <select value={handTo} onChange={(e) => { setHandTo(e.target.value); setHandPreview(null); }} className={inputCls} data-testid="transfer-select">
                <option value="">Choose a member…</option>
                {(members.data?.members ?? []).filter((m) => !m.is_me).map((m) => <option key={m.member_ref} value={m.member_ref}>{m.handle} ({m.role})</option>)}
              </select>
            </Field>
            {handPreview && <p role="status" className="rounded-md border border-border bg-surface-2 px-3 py-2 text-sm text-text-secondary" data-testid="transfer-preview">{handPreview}</p>}
            <div className="flex gap-2">
              {!handPreview ? <button type="button" className={btn} disabled={!handTo} onClick={() => transfer.mutate(false)} data-testid="transfer-preview-btn">Preview</button> : <button type="button" className={btnDanger} onClick={() => transfer.mutate(true)} data-testid="transfer-confirm">Hand over</button>}
            </div>
            <div className="border-t border-border pt-3">
              {deleting === null ? <button type="button" className={btnDanger} onClick={() => del.mutate(false)} data-testid="club-delete">Delete this club…</button> : (
                <div role="group" aria-label="Confirm deleting" className="flex flex-col gap-2">
                  <p className="text-sm text-text-secondary" data-testid="delete-preview">{deleting}</p>
                  <div className="flex gap-2"><button type="button" className={btnDanger} onClick={() => del.mutate(true)} data-testid="club-delete-confirm">Delete for everyone</button><button type="button" className={btn} onClick={() => setDeleting(null)}>Keep it</button></div>
                </div>
              )}
            </div>
          </div>
        </Card>
      )}

      <ErrorLine message={error} />
      <InviteSheet open={inviting} onOpenChange={setInviting} club={club} />
      {declining !== null && (
        <ReasonSheet open onOpenChange={(o) => !o && setDeclining(null)} testId="request-decision-sheet" title="Decline this request" description="Your reason is written to the club's audit log and shown to the person." label="Reason (required)" submitLabel="Decline"
          onSubmit={(reason) => decideClubRequest(club.club_id, declining, false, reason)} onDone={() => refreshClub(qc, club.club_id)} />
      )}
    </div>
  );
}
