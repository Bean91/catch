import { formatInstantDate } from "../../../lib/localTime";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Card } from "../../ui/Card";
import { EmptyState, ErrorState } from "../../ui/EmptyState";
import { decideClubPost, fetchClubPosts } from "../../../lib/api";
import type { Club, ClubPost } from "../../../lib/types";
import { PrivacyBadge } from "../../coaching/PrivacyBadge";
import { ErrorLine, btn, btnPrimary, refreshClub } from "../ClubBits";
import { PostSheet, ReasonSheet, ReportSheet } from "../ClubSheets";

export function NewsTab({ club }: { club: Club }) {
  const qc = useQueryClient();
  const caps = club.capabilities ?? {};
  const posts = useQuery({ queryKey: ["club-posts", club.club_id], queryFn: () => fetchClubPosts(club.club_id), retry: false });
  const [composing, setComposing] = useState(false);
  const [rejecting, setRejecting] = useState<{ post: ClubPost; action: "reject" | "hide" } | null>(null);
  const [reporting, setReporting] = useState<ClubPost | null>(null);
  const [error, setError] = useState<string | null>(null);
  const approve = useMutation({ mutationFn: (id: number) => decideClubPost(club.club_id, "announcement", id, "approve"), onSuccess: () => refreshClub(qc, club.club_id), onError: (e: Error) => setError(e.message) });
  return (
    <Card title="Announcements" action={caps.post ? <button type="button" className={btnPrimary} onClick={() => setComposing(true)} data-testid="news-new">New announcement</button> : <PrivacyBadge visibility="club" />}>
      {posts.isLoading && <p className="text-sm text-text-tertiary">Loading…</p>}
      {posts.isError && <ErrorState message="Couldn't load announcements." onRetry={() => posts.refetch()} />}
      {posts.data && posts.data.announcements.length === 0 && <EmptyState message="Nothing posted yet." />}
      <ul className="flex flex-col gap-3" data-testid="club-posts">
        {(posts.data?.announcements ?? []).map((p) => (
          <li key={p.id} data-testid="post-row" data-status={p.status} className="rounded-md border border-border p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h4 className="min-w-0 wrap-anywhere text-sm font-semibold text-text-primary">{p.title}</h4>
              {p.status !== "published" && <span data-testid="post-status" className="rounded-full border border-border px-2 py-0.5 text-xs text-text-secondary">{p.status === "pending" ? "Waiting for a coach" : p.status === "hidden" ? "Taken down" : "Not approved"}</span>}
            </div>
            <p className="mt-1 whitespace-pre-line text-sm text-text-secondary">{p.body}</p>
            <p className="mt-2 text-xs text-text-tertiary">{p.author} · {formatInstantDate(p.created_at, null, { year: "numeric", month: "short", day: "numeric" })}</p>
            {p.decision_reason && <p className="mt-1 text-xs text-text-tertiary">Reason: {p.decision_reason}</p>}
            <div className="mt-2 flex flex-wrap gap-2">
              {p.can_approve && <button type="button" className={btnPrimary} onClick={() => approve.mutate(p.id)} data-testid="post-approve">Approve</button>}
              {p.status === "pending" && caps.take_down_post && <button type="button" className={btn} onClick={() => setRejecting({ post: p, action: "reject" })} data-testid="post-reject">Decline</button>}
              {p.status === "published" && caps.take_down_post && <button type="button" className={btn} onClick={() => setRejecting({ post: p, action: "hide" })} data-testid="post-takedown">Take down</button>}
              {p.status === "published" && <button type="button" className={btn} onClick={() => setReporting(p)} data-testid="post-report">Report</button>}
            </div>
          </li>
        ))}
      </ul>
      <div className="mt-3"><ErrorLine message={error} /></div>
      <PostSheet open={composing} onOpenChange={setComposing} club={club} />
      {rejecting && (
        <ReasonSheet open onOpenChange={(o) => !o && setRejecting(null)} testId="post-decision-sheet" title={rejecting.action === "reject" ? "Decline this post" : "Take this post down"} description="Your reason is written to the club's audit log." label="Reason (required)" submitLabel={rejecting.action === "reject" ? "Decline" : "Take down"}
          onSubmit={(reason) => decideClubPost(club.club_id, "announcement", rejecting.post.id, rejecting.action, reason)} onDone={() => refreshClub(qc, club.club_id)} />
      )}
      {reporting && <ReportSheet open onOpenChange={(o) => !o && setReporting(null)} clubId={club.club_id} targetType="announcement" targetId={String(reporting.id)} subject="this announcement" />}
    </Card>
  );
}
