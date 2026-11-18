import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Card } from "../../ui/Card";
import { EmptyState, ErrorState } from "../../ui/EmptyState";
import { decideClubPost, fetchClubChallenges } from "../../../lib/api";
import { metricLabel, phaseLabel } from "../../../lib/clubs";
import type { Club } from "../../../lib/types";
import { PrivacyBadge } from "../../coaching/PrivacyBadge";
import { ErrorLine, btn, btnPrimary, refreshClub } from "../ClubBits";
import { ChallengeSheet, ReasonSheet } from "../ClubSheets";

export function ChallengesTab({ club }: { club: Club }) {
  const qc = useQueryClient();
  const caps = club.capabilities ?? {};
  const list = useQuery({ queryKey: ["club-challenges", club.club_id], queryFn: () => fetchClubChallenges(club.club_id), retry: false });
  const [creating, setCreating] = useState(false);
  const [declining, setDeclining] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const approve = useMutation({ mutationFn: (id: number) => decideClubPost(club.club_id, "challenge", id, "approve"), onSuccess: () => refreshClub(qc, club.club_id), onError: (e: Error) => setError(e.message) });
  return (
    <Card title="Challenges" action={caps.post ? <button type="button" className={btnPrimary} onClick={() => setCreating(true)} data-testid="challenge-new">New challenge</button> : <PrivacyBadge visibility="club" />}>
      <p className="mb-3 text-xs text-text-tertiary">Capped on purpose: extra volume never earns more, and nothing about weight, calories, recovery or sleep is used. You can opt out any time.</p>
      {list.isLoading && <p className="text-sm text-text-tertiary">Loading…</p>}
      {list.isError && <ErrorState message="Couldn't load challenges." onRetry={() => list.refetch()} />}
      {list.data && list.data.challenges.length === 0 && <EmptyState message="No challenges yet." />}
      <ul className="flex flex-col gap-3" data-testid="club-challenges">
        {(list.data?.challenges ?? []).map((c) => (
          <li key={c.id} data-testid="challenge-row" data-status={c.status} className="rounded-md border border-border p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <Link to={`/clubs/${club.club_id}/challenges/${c.id}`} className="text-sm font-semibold text-accent hover:underline" data-testid="challenge-link">{c.title}</Link>
              <span className="rounded-full border border-border px-2 py-0.5 text-xs text-text-secondary">{phaseLabel(c.phase)}</span>
            </div>
            <p className="mt-1 text-xs text-text-secondary">{metricLabel(c.metric)} · {c.start} → {c.end} · {c.participants} in</p>
            {c.joined && c.my_value && <p className="mt-1 text-sm text-text-primary">You: <span className="font-mono-nums">{c.my_value}</span></p>}
            {c.status === "pending" && (
              <div className="mt-2 flex flex-wrap gap-2">
                {c.can_approve && <button type="button" className={btnPrimary} onClick={() => approve.mutate(c.id)} data-testid="challenge-approve">Approve</button>}
                {caps.take_down_post && <button type="button" className={btn} onClick={() => setDeclining(c.id)} data-testid="challenge-decline">Decline</button>}
              </div>
            )}
          </li>
        ))}
      </ul>
      <div className="mt-3"><ErrorLine message={error} /></div>
      <ChallengeSheet open={creating} onOpenChange={setCreating} club={club} />
      {declining !== null && (
        <ReasonSheet open onOpenChange={(o) => !o && setDeclining(null)} testId="challenge-decision-sheet" title="Decline this challenge" description="Your reason is written to the club's audit log." label="Reason (required)" submitLabel="Decline"
          onSubmit={(reason) => decideClubPost(club.club_id, "challenge", declining, "reject", reason)} onDone={() => refreshClub(qc, club.club_id)} />
      )}
    </Card>
  );
}
