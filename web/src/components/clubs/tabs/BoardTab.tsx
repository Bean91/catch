import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Card } from "../../ui/Card";
import { EmptyState, ErrorState } from "../../ui/EmptyState";
import { fetchClubBoard, withdrawClubResult } from "../../../lib/api";
import type { Club, ClubBoardRow } from "../../../lib/types";
import { PrivacyBadge } from "../../coaching/PrivacyBadge";
import { VerificationBadge } from "../../leaderboards/VerificationBadge";
import { ErrorLine, btn, btnPrimary, inputCls, refreshClub } from "../ClubBits";
import { ShareResultSheet } from "../ClubSheets";

const BOARDS = [["500m", "500 m"], ["1000m", "1,000 m"], ["2000m", "2,000 m"], ["5000m", "5,000 m"], ["6000m", "6,000 m"], ["30min", "30 minutes"], ["60min", "60 minutes"]];

function Rows({ rows, onWithdraw }: { rows: ClubBoardRow[]; onWithdraw: (id: number) => void }) {
  return (
    <ol className="flex flex-col divide-y divide-border">
      {rows.map((r, i) => (
        <li key={`${r.member_ref}-${i}`} data-testid="board-row" data-me={r.is_me} className={`flex flex-wrap items-center justify-between gap-2 py-2 text-sm ${r.is_me ? "rounded-md border border-accent/40 px-2" : ""}`}>
          <span className="flex min-w-0 items-center gap-3">
            <span className="font-mono-nums w-6 text-text-tertiary">{r.rank}</span>
            <span className="truncate text-text-primary">{r.name}{r.is_me ? " (you)" : ""}</span>
          </span>
          <span className="flex items-center gap-2">
            <span className="font-mono-nums text-text-primary">{r.result}</span>
            <VerificationBadge state={r.verification} />
            {r.is_me && r.result_id !== null && r.source === "club" && <button type="button" className={`${btn} px-3`} onClick={() => onWithdraw(r.result_id as number)} data-testid="board-withdraw">Remove</button>}
          </span>
        </li>
      ))}
    </ol>
  );
}

export function BoardTab({ club }: { club: Club }) {
  const qc = useQueryClient();
  const [board, setBoard] = useState("2000m");
  const [sharing, setSharing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const data = useQuery({ queryKey: ["club-board", club.club_id, board], queryFn: () => fetchClubBoard(club.club_id, board), retry: false });
  const withdraw = useMutation({ mutationFn: (id: number) => withdrawClubResult(club.club_id, id), onSuccess: () => refreshClub(qc, club.club_id), onError: (e: Error) => setError(e.message) });
  return (
    <Card title="Club results board" action={<PrivacyBadge visibility="club" />}>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <select value={board} onChange={(e) => setBoard(e.target.value)} className={`${inputCls} w-auto`} aria-label="Distance or time" data-testid="board-select">
          {BOARDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
        <button type="button" className={btnPrimary} onClick={() => setSharing(true)} data-testid="board-share">Share a result</button>
      </div>
      {data.isLoading && <p className="text-sm text-text-tertiary">Loading…</p>}
      {data.isError && <ErrorState message="Couldn't load the board." onRetry={() => data.refetch()} />}
      {data.data && (
        <>
          <p data-testid="board-context" className="mb-2 text-xs text-text-tertiary">{data.data.board_label} · ranked by fastest result · equal results share a rank</p>
          {data.data.ranked.length === 0 ? <EmptyState message="No verified results shared here yet." /> : <Rows rows={data.data.ranked} onWithdraw={(id) => withdraw.mutate(id)} />}
          {data.data.unverified.length > 0 && (
            <div className="mt-4" data-testid="board-unverified">
              <h4 className="mb-1 text-xs font-medium text-text-secondary">Not ranked (can't be authenticated)</h4>
              <Rows rows={data.data.unverified} onWithdraw={(id) => withdraw.mutate(id)} />
            </div>
          )}
          <p className="mt-3 text-xs text-text-tertiary">{data.data.note}</p>
        </>
      )}
      <div className="mt-3"><ErrorLine message={error} /></div>
      <ShareResultSheet open={sharing} onOpenChange={setSharing} clubId={club.club_id} />
    </Card>
  );
}
