import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Card } from "../../ui/Card";
import { EmptyState, ErrorState } from "../../ui/EmptyState";
import { decideClubPost, fetchClubCalendar, unlinkClubWorkout } from "../../../lib/api";
import { SESSION_TYPES } from "../../../lib/clubs";
import type { Club, ClubSessionItem } from "../../../lib/types";
import { PrivacyBadge } from "../../coaching/PrivacyBadge";
import { ErrorLine, btn, btnPrimary, refreshClub } from "../ClubBits";
import { LinkWorkoutSheet, ReasonSheet, SessionSheet } from "../ClubSheets";

const typeLabel = (t: string) => SESSION_TYPES.find((x) => x.value === t)?.label ?? t;

export function CalendarTab({ club }: { club: Club }) {
  const qc = useQueryClient();
  const caps = club.capabilities ?? {};
  const cal = useQuery({ queryKey: ["club-calendar", club.club_id], queryFn: () => fetchClubCalendar(club.club_id), retry: false });
  const [planning, setPlanning] = useState(false);
  const [linking, setLinking] = useState<ClubSessionItem | null>(null);
  const [declining, setDeclining] = useState<ClubSessionItem | null>(null);
  const [error, setError] = useState<string | null>(null);
  const approve = useMutation({ mutationFn: (id: number) => decideClubPost(club.club_id, "session", id, "approve"), onSuccess: () => refreshClub(qc, club.club_id), onError: (e: Error) => setError(e.message) });
  const undo = useMutation({ mutationFn: (id: number) => unlinkClubWorkout(club.club_id, id), onSuccess: () => refreshClub(qc, club.club_id), onError: (e: Error) => setError(e.message) });
  return (
    <Card title="Team calendar" action={caps.post ? <button type="button" className={btnPrimary} onClick={() => setPlanning(true)} data-testid="calendar-plan">Plan a session</button> : <PrivacyBadge visibility="club" />}>
      <p className="mb-3 text-xs text-text-tertiary">These are plans for the club, not workouts. Tell the club you took part and it learns only that — never the workout itself.</p>
      {cal.isLoading && <p className="text-sm text-text-tertiary">Loading…</p>}
      {cal.isError && <ErrorState message="Couldn't load the calendar." onRetry={() => cal.refetch()} />}
      {cal.data && cal.data.sessions.length === 0 && <EmptyState message="No team sessions planned." />}
      <ul className="flex flex-col gap-3" data-testid="club-sessions">
        {(cal.data?.sessions ?? []).map((s) => (
          <li key={s.id} data-testid="session-row" data-status={s.status} className="rounded-md border border-border p-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h4 className="text-sm font-semibold text-text-primary">{s.title}</h4>
              <span className="font-mono-nums text-xs text-text-tertiary">{s.date}{s.start_time ? ` · ${s.start_time}` : ""}</span>
            </div>
            <p className="mt-1 text-xs text-text-secondary">
              {typeLabel(s.type)}{s.duration_min ? ` · ${s.duration_min} min` : ""}{s.distance_m ? ` · ${(s.distance_m / 1000).toFixed(1)} km` : ""}
            </p>
            {s.description && <p className="mt-1 text-sm text-text-secondary">{s.description}</p>}
            <div className="mt-2 flex flex-wrap items-center gap-2">
              {s.status === "pending" ? (
                <>
                  <span data-testid="session-status" className="rounded-full border border-border px-2 py-0.5 text-xs text-text-secondary">Waiting for a coach</span>
                  {s.can_approve && <button type="button" className={btnPrimary} onClick={() => approve.mutate(s.id)} data-testid="session-approve">Approve</button>}
                  {caps.take_down_post && <button type="button" className={btn} onClick={() => setDeclining(s)} data-testid="session-decline">Decline</button>}
                </>
              ) : (
                <>
                  <span className="text-xs text-text-tertiary" data-testid="session-count">{s.participants} took part</span>
                  {caps.link_workout && (s.i_took_part ? <button type="button" className={btn} onClick={() => undo.mutate(s.id)} data-testid="session-undo">I didn't take part</button> : <button type="button" className={btn} onClick={() => setLinking(s)} data-testid="session-took-part">I took part</button>)}
                </>
              )}
            </div>
          </li>
        ))}
      </ul>
      <div className="mt-3"><ErrorLine message={error} /></div>
      <SessionSheet open={planning} onOpenChange={setPlanning} club={club} />
      {linking && <LinkWorkoutSheet open onOpenChange={(o) => !o && setLinking(null)} clubId={club.club_id} session={linking} defaultShare={!!club.my_prefs?.share_numbers} />}
      {declining && (
        <ReasonSheet open onOpenChange={(o) => !o && setDeclining(null)} testId="session-decision-sheet" title="Decline this session" description="Your reason is written to the club's audit log." label="Reason (required)" submitLabel="Decline"
          onSubmit={(reason) => decideClubPost(club.club_id, "session", declining.id, "reject", reason)} onDone={() => refreshClub(qc, club.club_id)} />
      )}
    </Card>
  );
}
