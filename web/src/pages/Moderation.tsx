import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { fetchModQueue, moderateLbEntry, resolveLbAppeal } from "../lib/api";
import { Card } from "../components/ui/Card";
import { CardSkeleton } from "../components/ui/Skeleton";
import { ClubModeration } from "../components/clubs/ClubModeration";

const inputCls = "min-h-11 w-full rounded-md border border-border bg-surface-2 px-3 text-sm text-text-primary";

export function ModerationPage() {
  const queryClient = useQueryClient();
  const q = useQuery({ queryKey: ["lb-mod"], queryFn: fetchModQueue, retry: false });
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const done = { onSuccess: () => { setError(null); queryClient.invalidateQueries({ queryKey: ["lb-mod"] }); }, onError: (e: Error) => setError(e.message) };
  const act = useMutation({ mutationFn: (v: { id: string; action: string }) => moderateLbEntry(v.id, v.action, reasons[v.id] ?? ""), ...done });
  const resolve = useMutation({ mutationFn: (v: { id: number; outcome: "upheld" | "overturned" }) => resolveLbAppeal(v.id, v.outcome, reasons[`a${v.id}`] ?? ""), ...done });
  const setReason = (key: string, v: string) => setReasons((r) => ({ ...r, [key]: v }));

  return (
    <div className="flex flex-col gap-4 lg:gap-5">
      <div>
        <Link to="/settings/leaderboards" className="text-sm font-medium text-accent hover:underline">
          ← Leaderboards settings
        </Link>
        <h1 className="mt-1 text-lg font-semibold text-text-primary">Moderation</h1>
        <p className="mt-1 text-sm text-text-secondary">Every action needs a written reason, is recorded in an append-only log, and is shown to the athlete.</p>
      </div>
      {q.isLoading && <CardSkeleton lines={4} />}
      {q.isError && <p className="text-sm text-text-secondary">This page isn't available to your account.</p>}
      {error && (
        <p role="alert" data-testid="mod-error" className="rounded-md border border-band-red/30 bg-band-red/10 px-3 py-2 text-sm text-band-red-text">
          {error}
        </p>
      )}
      {q.data && (
        <>
          <Card title={`Reported results (${q.data.reports.length})`}>
            {q.data.reports.length === 0 && <p className="text-sm text-text-secondary">Nothing waiting.</p>}
            {q.data.reports.map((r) => (
              <div key={r.entry_id} data-testid={`mod-report-${r.entry_id}`} className="flex flex-col gap-2 border-t border-border py-3 first:border-t-0">
                <p className="text-sm text-text-primary">
                  {r.board_key} · {r.reporters} {r.reporters === 1 ? "reporter" : "reporters"} · {r.status}
                </p>
                <p className="text-xs text-text-tertiary">{r.reasons.join(", ")}</p>
                <input value={reasons[r.entry_id] ?? ""} onChange={(e) => setReason(r.entry_id, e.target.value)} placeholder="Reason (required)" className={inputCls} data-testid={`mod-reason-${r.entry_id}`} />
                <div className="flex flex-wrap gap-2">
                  {(["hide", "remove", "restore", "dismiss_reports"] as const).map((a) => (
                    <button key={a} type="button" onClick={() => act.mutate({ id: r.entry_id, action: a })} className="min-h-11 rounded-md border border-border px-3 text-sm font-medium text-text-secondary" data-testid={`mod-${a}-${r.entry_id}`}>
                      {a === "dismiss_reports" ? "Dismiss reports" : a[0].toUpperCase() + a.slice(1)}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </Card>
          <Card title={`Open appeals (${q.data.appeals.length})`}>
            {q.data.appeals.length === 0 && <p className="text-sm text-text-secondary">Nothing waiting.</p>}
            {q.data.appeals.map((a) => (
              <div key={a.id} data-testid={`mod-appeal-${a.id}`} className="flex flex-col gap-2 border-t border-border py-3 first:border-t-0">
                <p className="text-sm text-text-primary">Entry is {a.entry_status ?? "gone"}</p>
                <p className="text-sm text-text-secondary">“{a.text}”</p>
                <input value={reasons[`a${a.id}`] ?? ""} onChange={(e) => setReason(`a${a.id}`, e.target.value)} placeholder="Decision reason (required)" className={inputCls} data-testid={`mod-appeal-reason-${a.id}`} />
                <div className="flex gap-2">
                  <button type="button" onClick={() => resolve.mutate({ id: a.id, outcome: "overturned" })} className="min-h-11 rounded-md border border-border px-3 text-sm font-medium text-text-secondary" data-testid={`mod-overturn-${a.id}`}>
                    Overturn (restore)
                  </button>
                  <button type="button" onClick={() => resolve.mutate({ id: a.id, outcome: "upheld" })} className="min-h-11 rounded-md border border-border px-3 text-sm font-medium text-text-secondary">
                    Uphold
                  </button>
                </div>
              </div>
            ))}
          </Card>
        </>
      )}
      {q.data && <ClubModeration />}
    </div>
  );
}
