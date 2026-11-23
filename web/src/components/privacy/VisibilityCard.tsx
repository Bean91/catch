import { formatInstantDate } from "../../lib/localTime";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { appealRestriction, fetchPrivacySummary, fetchRestrictions } from "../../lib/privacy";
import { Card } from "../ui/Card";

const btn = "min-h-11 rounded-md border border-border px-4 text-sm font-medium text-text-primary transition-colors hover:border-accent disabled:opacity-50";

/** What other people can see about you, and the controls that live on their own pages. */
export function VisibilityCard() {
  const summary = useQuery({ queryKey: ["privacy-summary"], queryFn: fetchPrivacySummary });
  const pub = summary.data?.public;
  if (!pub) return null;
  return (
    <Card title="What other people can see">
      <div className="flex flex-col gap-3 text-sm text-text-secondary" data-testid="visibility-card">
        <p>Your training data is private to you. Only what you publish or share on purpose is visible to anyone else:</p>
        <ul className="flex flex-col gap-1">
          <li>
            Public leaderboards:{" "}
            <span className="font-medium text-text-primary">{pub.leaderboard_profile?.active ? `opted in, shown as ${pub.leaderboard_profile.display_mode === "handle" ? "your handle" : "Anonymous rower"}` : "not opted in"}</span>
            {" · "}{pub.published_results} published result{pub.published_results === 1 ? "" : "s"}.{" "}
            <Link to="/settings/leaderboards" className="font-medium text-accent hover:underline">Manage or opt out</Link>
          </li>
          <li>
            Clubs: <span className="font-medium text-text-primary">{pub.club_memberships} membership{pub.club_memberships === 1 ? "" : "s"}</span>. What you share inside each club (results, numbers) is set per club.{" "}
            <Link to="/clubs" className="font-medium text-accent hover:underline">Open Clubs</Link>
          </li>
        </ul>
        <p className="text-xs">
          Opting out takes your published results down. A result a moderator closed stays closed (so republishing can't undo a decision), and posts you wrote in a club stay with
          the club, no longer linked to you, if you delete your account.
        </p>
      </div>
    </Card>
  );
}

export function RestrictionsCard() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["my-restrictions"], queryFn: fetchRestrictions });
  const [text, setText] = useState<Record<number, string>>({});
  const appeal = useMutation({ mutationFn: ({ id, t }: { id: number; t: string }) => appealRestriction(id, t), onSuccess: () => qc.invalidateQueries({ queryKey: ["my-restrictions"] }) });
  const list = q.data?.restrictions ?? [];
  if (list.length === 0) return null;
  return (
    <Card title="Moderation on your account">
      <ul className="flex flex-col gap-3" data-testid="restrictions-card">
        {list.map((r) => (
          <li key={r.id} className="rounded-md border border-border p-3 text-sm">
            <p className="font-medium text-text-primary">{r.active ? "Restricted" : "Ended"}: {r.scope_text}</p>
            <p className="mt-1 text-text-secondary">Reason: {r.reason}</p>
            <p className="text-xs text-text-secondary">Decided by {r.decided_by} on {formatInstantDate(r.created_at, null, { year: "numeric", month: "short", day: "numeric" })}{r.expires_at ? ` · ends ${formatInstantDate(r.expires_at, null, { year: "numeric", month: "short", day: "numeric" })}` : ""}. This never limits your own data, download or account deletion.</p>
            {r.appeal ? (
              <p className="mt-2 text-xs text-text-secondary">Appeal {r.appeal.status}{r.appeal.resolution ? `: ${r.appeal.resolution}` : "."}</p>
            ) : r.active ? (
              <div className="mt-2 flex flex-col gap-2">
                <textarea aria-label="Why should this change?" className="min-h-20 rounded-md border border-border bg-surface-2 p-2 text-text-primary" maxLength={500} value={text[r.id] ?? ""} onChange={(e) => setText({ ...text, [r.id]: e.target.value })} />
                <div><button type="button" className={btn} disabled={!(text[r.id] ?? "").trim() || appeal.isPending} onClick={() => appeal.mutate({ id: r.id, t: text[r.id] })}>Appeal this decision</button></div>
              </div>
            ) : null}
          </li>
        ))}
      </ul>
    </Card>
  );
}
