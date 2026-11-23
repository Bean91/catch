import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Card } from "../components/ui/Card";
import { ErrorState } from "../components/ui/EmptyState";
import { Skeleton } from "../components/ui/Skeleton";
import { PrivacyBadge } from "../components/coaching/PrivacyBadge";
import { ErrorLine, btn, btnPrimary, refreshClub } from "../components/clubs/ClubBits";
import { ReportSheet } from "../components/clubs/ClubSheets";
import { decideClubPost, excuseClubWeek, fetchClub, fetchClubChallenge, joinClubChallenge, leaveClubChallenge } from "../lib/api";
import { metricLabel, phaseLabel } from "../lib/clubs";

export function ClubChallengePage() {
  const { id = "", cid = "" } = useParams();
  const challengeId = Number(cid);
  const qc = useQueryClient();
  const club = useQuery({ queryKey: ["club-detail", id], queryFn: () => fetchClub(id), retry: false });
  const ch = useQuery({ queryKey: ["club-challenge", id, challengeId], queryFn: () => fetchClubChallenge(id, challengeId), retry: false });
  const [error, setError] = useState<string | null>(null);
  const [reporting, setReporting] = useState(false);
  const done = () => { setError(null); refreshClub(qc, id); };
  const fail = (e: Error) => setError(e.message);
  const join = useMutation({ mutationFn: () => joinClubChallenge(id, challengeId), onSuccess: done, onError: fail });
  const leave = useMutation({ mutationFn: () => leaveClubChallenge(id, challengeId), onSuccess: done, onError: fail });
  const excuse = useMutation({ mutationFn: (v: { week: string; excused: boolean }) => excuseClubWeek(id, challengeId, v.week, v.excused), onSuccess: done, onError: fail });
  const approve = useMutation({ mutationFn: () => decideClubPost(id, "challenge", challengeId, "approve"), onSuccess: done, onError: fail });

  if (ch.isLoading) return <div className="flex flex-col gap-4"><Skeleton className="h-16" /><Skeleton className="h-40" /></div>;
  if (ch.isError || !ch.data) return <div className="flex flex-col gap-3"><Link to={`/clubs/${id}?tab=challenges`} className="text-sm text-accent hover:underline">← Challenges</Link><ErrorState message="That challenge isn't available." /></div>;
  const c = ch.data;
  const closed = c.phase === "closed";
  return (
    <div className="flex flex-col gap-4" data-testid="challenge-page">
      <Link to={`/clubs/${id}?tab=challenges`} className="text-sm text-accent hover:underline">← {club.data?.name ?? "Club"} · Challenges</Link>
      <header className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold leading-tight tracking-tight text-text-primary sm:text-[1.75rem]">{c.title}</h1>
        <p className="text-sm text-text-secondary">{metricLabel(c.metric)} · {c.start} → {c.end} · <span data-testid="challenge-phase">{phaseLabel(c.phase)}</span>{!closed && c.status === "active" ? ` · settles ${c.settles_on}` : ""}</p>
        {c.description && <p className="text-sm text-text-primary">{c.description}</p>}
      </header>
      {c.status === "pending" && (
        <Card title="Waiting for approval"><p className="text-sm text-text-secondary">In a junior club a coach approves a challenge before members see it.</p>{c.can_approve && <div className="mt-3"><button type="button" className={btnPrimary} onClick={() => approve.mutate()} data-testid="challenge-approve">Approve</button></div>}</Card>
      )}
      <Card title="How it's scored" action={<PrivacyBadge visibility="club" />}>
        <ul className="flex list-disc flex-col gap-1 pl-5 text-sm text-text-secondary" data-testid="challenge-rules">{c.rules.map((r) => <li key={r}>{r}</li>)}</ul>
      </Card>
      {c.status === "active" && (
        <Card title="You">
          {c.joined ? (
            <>
              <p className="text-sm text-text-primary">Your standing: <span data-testid="challenge-my-value" className="font-mono-nums font-semibold">{c.my_value}</span></p>
              {c.metric === "consistency" && c.my_detail?.weeks && (
                <ul className="mt-3 flex flex-col gap-2" data-testid="challenge-weeks">
                  {c.my_detail.weeks.map((w) => (
                    <li key={w.week} className="flex flex-wrap items-center justify-between gap-2 text-sm">
                      <span className="text-text-secondary">Week of {w.week} · <span data-testid="week-state">{w.state.replace("_", " ")}</span>{w.sessions !== undefined ? ` · ${w.sessions}/${c.target_per_week}` : ""}</span>
                      {!closed && <button type="button" className={`${btn} px-3`} onClick={() => excuse.mutate({ week: w.week, excused: w.state !== "excused" })} data-testid="week-excuse">{w.state === "excused" ? "Count this week" : "Excuse this week"}</button>}
                    </li>
                  ))}
                </ul>
              )}
              {c.metric === "consistency" && <p className="mt-2 text-xs text-text-tertiary">Ill, resting or away? Excuse a week — no reason needed and it's never held against you.</p>}
              {!closed && <div className="mt-3"><button type="button" className={btn} onClick={() => leave.mutate()} data-testid="challenge-leave">Opt out of this challenge</button></div>}
            </>
          ) : (
            <>
              <p className="text-sm text-text-secondary">{c.can_join ? "Join to appear in the standings. You can opt out any time, and rest always comes first." : closed ? "This challenge has settled." : "This challenge has ended."}</p>
              {c.can_join && <div className="mt-3"><button type="button" className={btnPrimary} onClick={() => join.mutate()} disabled={join.isPending} data-testid="challenge-join">Join challenge</button></div>}
            </>
          )}
        </Card>
      )}
      <Card title={`Standings · ${c.participants} in`} action={<PrivacyBadge visibility="club" />}>
        {c.standings.length === 0 ? <p className="text-sm text-text-secondary">No one has joined yet.</p> : (
          <ol className="flex flex-col divide-y divide-border" data-testid="challenge-standings">
            {c.standings.map((s) => (
              <li key={s.member_ref} data-testid="standing-row" data-me={s.is_me} className={`flex items-center justify-between py-2 text-sm ${s.is_me ? "rounded-md border border-accent/40 px-2" : ""}`}>
                <span className="flex items-center gap-3"><span className="font-mono-nums w-6 text-text-tertiary">{s.rank}</span><span className="text-text-primary">{s.name}{s.is_me ? " (you)" : ""}</span></span>
                <span className="font-mono-nums text-text-primary">{s.value}</span>
              </li>
            ))}
          </ol>
        )}
        <p className="mt-3 text-xs text-text-tertiary">Equal scores share a rank. Scores come from each member's own connected-source activities and are recomputed only by that member's own account.</p>
      </Card>
      <ErrorLine message={error} />
      <div><button type="button" className={btn} onClick={() => setReporting(true)} data-testid="challenge-report">Report this challenge</button></div>
      <ReportSheet open={reporting} onOpenChange={setReporting} clubId={id} targetType="challenge" targetId={String(challengeId)} subject="this challenge" />
    </div>
  );
}
