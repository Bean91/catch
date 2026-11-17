import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { fetchLbBoard, fetchLbBoards, fetchLbMe } from "../lib/api";
import { EntryRow } from "../components/leaderboards/EntryRow";
import { ReasonSheet } from "../components/leaderboards/ReasonSheet";
import { Card } from "../components/ui/Card";
import { CardSkeleton } from "../components/ui/Skeleton";
import { contextLine } from "../lib/leaderboards";
import type { LbBoardFilters, LbEntry } from "../lib/types";

const selectCls = "min-h-11 w-full rounded-md border border-border bg-surface-2 px-3 text-sm text-text-primary";

export function LeaderboardsPage() {
  const [params, setParams] = useSearchParams();
  const boards = useQuery({ queryKey: ["lb-boards"], queryFn: fetchLbBoards });
  const me = useQuery({ queryKey: ["lb-me"], queryFn: fetchLbMe, retry: false });
  const boardKey = params.get("board") ?? "2000m";
  const filters: LbBoardFilters = {
    age: params.get("age") || undefined,
    weight: (params.get("weight") as LbBoardFilters["weight"]) || undefined,
    club: params.get("club") || undefined,
    verification: (params.get("verification") as LbBoardFilters["verification"]) || undefined,
  };
  const board = useQuery({ queryKey: ["lb-board", boardKey, filters], queryFn: () => fetchLbBoard(boardKey, filters), retry: false });
  const [reporting, setReporting] = useState<LbEntry | null>(null);

  function setParam(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  }

  const unavailable = me.isError || (me.data && !me.data.available);
  const optedIn = me.data?.settings.opted_in;

  return (
    <div className="flex flex-col gap-4 lg:gap-5">
      <div>
        <h1 className="text-lg font-semibold text-text-primary">Leaderboards</h1>
        <p className="mt-1 text-sm text-text-secondary">
          Visible to signed-in Catch users. Only verified results are ranked, each athlete appears once, and equal results share a rank. Results are public only
          when their athlete chose to publish them.
        </p>
      </div>

      {unavailable && (
        <Card>
          <p data-testid="lb-unavailable" className="text-sm text-text-secondary">Leaderboards are only available on the public Catch deployment.</p>
        </Card>
      )}

      {!unavailable && (
        <>
          {me.data && !optedIn && (
            <Card>
              <p className="text-sm text-text-secondary">You're not on the leaderboards. You can read them, and you choose whether to publish anything.</p>
              <Link to="/settings/leaderboards" data-testid="lb-join" className="mt-2 inline-block text-sm font-medium text-accent hover:underline">
                Set up publishing
              </Link>
            </Card>
          )}

          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="lb-filters">
            <label className="flex flex-col gap-1 text-xs text-text-secondary">
              Board
              <select value={boardKey} onChange={(e) => setParam("board", e.target.value)} className={selectCls} data-testid="lb-board">
                {boards.data?.boards.map((b) => (
                  <option key={b.board_key} value={b.board_key}>
                    {b.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs text-text-secondary">
              Age category
              <select value={filters.age ?? ""} onChange={(e) => setParam("age", e.target.value)} className={selectCls} data-testid="lb-age">
                <option value="">Overall</option>
                {boards.data?.age_bands.map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs text-text-secondary">
              Weight
              <select value={filters.weight ?? "any"} onChange={(e) => setParam("weight", e.target.value === "any" ? "" : e.target.value)} className={selectCls} data-testid="lb-weight">
                <option value="any">Open (everyone)</option>
                <option value="lightweight">Lightweight</option>
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs text-text-secondary">
              Results shown
              <select value={filters.verification ?? "verified"} onChange={(e) => setParam("verification", e.target.value === "verified" ? "" : e.target.value)} className={selectCls} data-testid="lb-verification">
                <option value="verified">Verified only</option>
                <option value="include_unverified">Also show unverified</option>
              </select>
            </label>
          </div>
          {me.data && me.data.clubs.length > 0 && (
            <label className="flex flex-col gap-1 text-xs text-text-secondary lg:max-w-xs">
              Club
              <select value={filters.club ?? ""} onChange={(e) => setParam("club", e.target.value)} className={selectCls} data-testid="lb-club">
                <option value="">All athletes</option>
                {me.data.clubs.map((c) => (
                  <option key={c.club_id} value={c.club_id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
          )}

          {board.isLoading && <CardSkeleton lines={5} />}
          {board.isError && <p className="text-sm text-band-red-text">Couldn't load this leaderboard.</p>}
          {board.data && (
            <>
              <p data-testid="lb-context" className="text-sm font-medium text-text-primary">
                {contextLine(board.data.context)}
              </p>
              <p className="text-xs text-text-tertiary">
                Ranked by {board.data.context.ranks_by}. {board.data.context.ties}
              </p>
              {board.data.you && (
                <div data-testid="lb-you">
                  <p className="mb-1 text-xs font-medium text-text-secondary">Your rank</p>
                  <ul>
                    <EntryRow entry={board.data.you} />
                  </ul>
                </div>
              )}
              {board.data.entries.length === 0 ? (
                <Card>
                  <p data-testid="lb-empty" className="text-sm text-text-secondary">No verified results on this board with these filters yet.</p>
                </Card>
              ) : (
                <ul className="flex flex-col gap-2" data-testid="lb-entries">
                  {board.data.entries.map((e) => (
                    <EntryRow key={e.entry_id} entry={e} onReport={setReporting} />
                  ))}
                </ul>
              )}
              {board.data.unverified.length > 0 && (
                <section data-testid="lb-unverified">
                  <h2 className="text-sm font-semibold text-text-primary">Not verified</h2>
                  <p className="mb-2 text-xs text-text-tertiary">Ranked among themselves and never above a verified result.</p>
                  <ul className="flex flex-col gap-2">
                    {board.data.unverified.map((e) => (
                      <EntryRow key={e.entry_id} entry={e} onReport={setReporting} />
                    ))}
                  </ul>
                </section>
              )}
            </>
          )}
        </>
      )}

      {reporting && <ReasonSheet mode="report" entryId={reporting.entry_id} subject={`${reporting.name} · ${reporting.board_label} · ${reporting.result}`} open onOpenChange={(o) => !o && setReporting(null)} />}
    </div>
  );
}
