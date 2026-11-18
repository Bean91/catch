import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Card } from "../../ui/Card";
import { fetchClubSummary, leaveClub, setClubPrefs } from "../../../lib/api";
import type { Club } from "../../../lib/types";
import { PrivacyBadge } from "../../coaching/PrivacyBadge";
import { ErrorLine, btn, btnDanger, refreshClub } from "../ClubBits";
import { ReportSheet } from "../ClubSheets";

const fmtKm = (m: number | null) => (m === null ? "—" : `${(m / 1000).toFixed(1)} km`);
const fmtH = (s: number | null) => (s === null ? "—" : `${(s / 3600).toFixed(1)} h`);

export function OverviewTab({ club }: { club: Club }) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const [leaving, setLeaving] = useState(false);
  const [reporting, setReporting] = useState(false);
  const summary = useQuery({ queryKey: ["club-summary", club.club_id], queryFn: () => fetchClubSummary(club.club_id), retry: false });
  const prefs = useMutation({ mutationFn: (p: { include_public_results?: boolean; share_numbers?: boolean }) => setClubPrefs(club.club_id, p), onSuccess: () => refreshClub(qc, club.club_id), onError: (e: Error) => setError(e.message) });
  const leave = useMutation({ mutationFn: () => leaveClub(club.club_id), onSuccess: () => { refreshClub(qc); nav("/clubs"); }, onError: (e: Error) => setError(e.message) });
  const caps = club.capabilities ?? {};
  const p = club.my_prefs;
  const s = summary.data;
  return (
    <div className="flex flex-col gap-4" data-testid="club-overview">
      {club.description && (
        <Card title="About">
          <p className="whitespace-pre-line text-sm text-text-primary">{club.description}</p>
          {club.location && <p className="mt-2 text-xs text-text-tertiary">{club.location}</p>}
        </Card>
      )}
      {club.rules && (
        <Card title="Club rules" action={<PrivacyBadge visibility="club" />}>
          <p data-testid="club-rules-text" className="whitespace-pre-line text-sm text-text-primary">{club.rules}</p>
        </Card>
      )}
      <Card title="Team training" action={<PrivacyBadge visibility="club" label="Club-only · totals" />}>
        {s ? (
          <>
            <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4" data-testid="club-summary">
              <div><dt className="text-text-tertiary">Sessions</dt><dd className="font-mono-nums text-lg text-text-primary">{s.sessions}</dd></div>
              <div><dt className="text-text-tertiary">Took part</dt><dd className="font-mono-nums text-lg text-text-primary">{s.participations}</dd></div>
              <div><dt className="text-text-tertiary">Team distance</dt><dd data-testid="club-summary-distance" className="font-mono-nums text-lg text-text-primary">{s.distance_m.suppressed ? "Hidden" : fmtKm(s.distance_m.total)}</dd></div>
              <div><dt className="text-text-tertiary">Team time</dt><dd className="font-mono-nums text-lg text-text-primary">{s.duration_s.suppressed ? "Hidden" : fmtH(s.duration_s.total)}</dd></div>
            </dl>
            <p className="mt-3 text-xs text-text-tertiary">{s.note}</p>
          </>
        ) : (
          <p className="text-sm text-text-tertiary">Loading…</p>
        )}
      </Card>
      <Card title="What you share with this club">
        <div className="flex flex-col gap-3 text-sm text-text-secondary">
          <label className="flex items-start gap-2">
            <input type="checkbox" checked={!!p?.share_numbers} onChange={(e) => prefs.mutate({ share_numbers: e.target.checked })} className="mt-1 h-4 w-4" data-testid="pref-share-numbers" />
            When I say I took part in a team session, also share my distance and time. (They only appear in totals once at least three members share.)
          </label>
          {club.audience === "adult" && (
            <label className="flex items-start gap-2">
              <input type="checkbox" checked={!!p?.include_public_results} onChange={(e) => prefs.mutate({ include_public_results: e.target.checked })} className="mt-1 h-4 w-4" data-testid="pref-public-results" />
              Show my public leaderboard results on this club's board.{club.visibility === "public" ? " This also lets the public board be filtered to this club." : ""}
            </label>
          )}
          <p className="text-xs text-text-tertiary">Your recovery, sleep, weight, nutrition and training are never shared with a club. Coaches see none of it.</p>
        </div>
      </Card>
      <ErrorLine message={error} />
      <div className="flex flex-wrap gap-2">
        {caps.leave &&
          (leaving ? (
            <div role="group" aria-label="Confirm leaving" className="flex w-full flex-col gap-2 rounded-md border border-border p-3">
              <p className="text-sm text-text-secondary">You'll leave {club.name} and your shared results and challenge entries here are removed. {club.visibility === "private" ? "You'll need a new invite to come back." : ""}</p>
              <div className="flex gap-2">
                <button type="button" className={btnDanger} onClick={() => leave.mutate()} data-testid="club-leave-confirm">Leave club</button>
                <button type="button" className={btn} onClick={() => setLeaving(false)}>Stay</button>
              </div>
            </div>
          ) : (
            <button type="button" className={btn} onClick={() => setLeaving(true)} data-testid="club-leave">Leave club</button>
          ))}
        <button type="button" className={btn} onClick={() => setReporting(true)} data-testid="club-report">Report this club</button>
      </div>
      <ReportSheet open={reporting} onOpenChange={setReporting} clubId={club.club_id} targetType="club" targetId={club.club_id} subject="this club" />
    </div>
  );
}
