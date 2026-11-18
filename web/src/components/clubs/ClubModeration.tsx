import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Card } from "../ui/Card";
import { fetchClubModDetail, fetchClubModQueue, moderateClub } from "../../lib/api";
import { CLUB_ACTION_LABEL } from "../../lib/clubs";
import { ErrorLine, btn, inputCls } from "./ClubBits";

/** Platform moderators only (the page itself 404s for anyone else). Reporters are never shown; every action needs a reason and lands in the club's audit log. */
export function ClubModeration() {
  const qc = useQueryClient();
  const queue = useQuery({ queryKey: ["club-mod"], queryFn: fetchClubModQueue, retry: false });
  const [open, setOpen] = useState<string | null>(null);
  const detail = useQuery({ queryKey: ["club-mod-detail", open], queryFn: () => fetchClubModDetail(open as string), enabled: !!open, retry: false });
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const act = useMutation({
    mutationFn: (v: { action: string; target_id?: string; target_type?: string }) => moderateClub(open as string, v.action, reason, v.target_id, v.target_type),
    onSuccess: () => { setError(null); setReason(""); setOpen(null); qc.invalidateQueries({ queryKey: ["club-mod"] }); qc.invalidateQueries({ queryKey: ["club-mod-detail"] }); },
    onError: (e: Error) => setError(e.message),
  });
  if (queue.isError) return null;
  return (
    <Card title={`Reported clubs and posts (${queue.data?.reports.length ?? 0})`}>
      {queue.data && queue.data.reports.length === 0 && <p className="text-sm text-text-secondary">Nothing waiting.</p>}
      <ul className="flex flex-col divide-y divide-border" data-testid="club-mod-queue">
        {(queue.data?.reports ?? []).map((r) => (
          <li key={`${r.club_id}-${r.target_type}-${r.target_id}`} className="flex flex-wrap items-center justify-between gap-2 py-3 text-sm">
            <span className="text-text-primary">{r.club_name}{r.audience === "junior" ? " · junior" : ""} <span className="text-xs text-text-tertiary">· {r.target_type} · {r.reports} {r.reports === 1 ? "report" : "reports"} · {r.reasons.join(", ")}</span></span>
            <button type="button" className={btn} onClick={() => setOpen(r.club_id)} data-testid="club-mod-open">Review</button>
          </li>
        ))}
      </ul>
      {open && detail.data && (
        <div className="mt-4 flex flex-col gap-3 border-t border-border pt-4" data-testid="club-mod-detail">
          <p className="text-sm text-text-primary">{detail.data.club.name} · {detail.data.club.audience} · {detail.data.club.visibility} · {detail.data.club.status} · {detail.data.club.member_count} members</p>
          <ul className="text-xs text-text-secondary">{detail.data.reports.map((r, i) => <li key={i}>{r.target_type}{r.about ? ` (${r.about})` : ""}: {r.reason}</li>)}</ul>
          <ul className="flex flex-col gap-1 text-xs text-text-secondary">{detail.data.events.slice(0, 5).map((e, i) => <li key={i}>{CLUB_ACTION_LABEL[e.action] ?? e.action} — {e.reason}</li>)}</ul>
          <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (required)" className={inputCls} data-testid="club-mod-reason" />
          <div className="flex flex-wrap gap-2">
            <button type="button" className={btn} onClick={() => act.mutate({ action: detail.data.club.status === "suspended" ? "restore_club" : "suspend_club" })} data-testid="club-mod-suspend">{detail.data.club.status === "suspended" ? "Restore club" : "Suspend club"}</button>
            {detail.data.reports.filter((r) => r.target_type === "announcement").map((r) => <button key={r.target_id} type="button" className={btn} onClick={() => act.mutate({ action: "hide_announcement", target_id: r.target_id })} data-testid="club-mod-hide">Hide post {r.target_id}</button>)}
            {detail.data.reports.filter((r) => r.target_type === "member").map((r) => <button key={r.target_id} type="button" className={btn} onClick={() => act.mutate({ action: "remove_member", target_id: r.target_id })} data-testid="club-mod-remove">Remove {r.about ?? "member"}</button>)}
            <button type="button" className={btn} onClick={() => detail.data.reports[0] && act.mutate({ action: "dismiss_reports", target_id: detail.data.reports[0].target_id, target_type: detail.data.reports[0].target_type })} data-testid="club-mod-dismiss">Dismiss reports</button>
          </div>
          <ErrorLine message={error} />
        </div>
      )}
    </Card>
  );
}
