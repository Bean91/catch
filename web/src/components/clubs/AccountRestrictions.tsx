import { formatInstantDateTime } from "../../lib/localTime";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { authedFetch } from "../../lib/authedFetch";
import { ApiError, isMock } from "../../lib/api";
import { Card } from "../ui/Card";
import { buttonClass } from "../ui/Button";
import { controlSkin } from "../ui/Field";

type ModRestriction = { id: number; user_id: string; scope: string; scope_text: string; active: boolean; reason: string; created_at: string; expires_at: string | null; appeal: { status: string; text: string | null } | null };
type ModAction = { id: number; actor_id: string; action: string; subject_user_id: string; reason: string; at: string };

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  if (isMock) return ({ restrictions: [], actions: [] } as unknown) as T;
  const res = await authedFetch(path, init);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, typeof body.detail === "string" ? body.detail : res.statusText);
  return body as T;
}
const post = (body: unknown): RequestInit => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const inputCls = `${controlSkin} min-h-11 w-full`;
const btn = buttonClass("secondary", "md");

/** Platform-moderator tools for account restrictions: who is restricted from what, appeals, and the append-only action log. Ids and reasons only. */
export function AccountRestrictions() {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["mod-restrictions"], queryFn: () => call<{ restrictions: ModRestriction[] }>("/api/moderation/restrictions"), retry: false });
  const log = useQuery({ queryKey: ["mod-actions"], queryFn: () => call<{ actions: ModAction[] }>("/api/moderation/actions"), retry: false });
  const [form, setForm] = useState({ user_id: "", scope: "publish", reason: "", days: "" });
  const [reasons, setReasons] = useState<Record<number, string>>({});
  const [error, setError] = useState<string | null>(null);
  const done = { onSuccess: () => { setError(null); qc.invalidateQueries({ queryKey: ["mod-restrictions"] }); qc.invalidateQueries({ queryKey: ["mod-actions"] }); }, onError: (e: Error) => setError(e.message) };
  const restrict = useMutation({
    mutationFn: () => call("/api/moderation/restrictions", post({ user_id: form.user_id.trim(), scope: form.scope, reason: form.reason, days: form.days ? Number(form.days) : null })),
    ...done,
  });
  const lift = useMutation({ mutationFn: (id: number) => call(`/api/moderation/restrictions/${id}/lift`, post({ action: "lift", reason: reasons[id] ?? "" })), ...done });
  const resolve = useMutation({ mutationFn: (v: { id: number; outcome: string }) => call(`/api/moderation/restrictions/${v.id}/resolve`, post({ outcome: v.outcome, reason: reasons[v.id] ?? "" })), ...done });

  if (list.isError) return null;
  return (
    <Card title="Account restrictions">
      <div className="flex flex-col gap-4" data-testid="account-restrictions">
        <p className="text-xs text-text-secondary">
          Restrict one social capability of one account. The person is told the reason and that a platform moderator decided it, and can appeal once; a different
          moderator reviews. It never limits their own data, download or deletion. You see ids and reasons only — no one's training or health records.
        </p>
        {error && <p role="alert" className="text-sm text-band-red-text">{error}</p>}
        <div className="flex flex-col gap-2">
          <input aria-label="Account id" placeholder="Account id (from a report)" className={inputCls} value={form.user_id} onChange={(e) => setForm({ ...form, user_id: e.target.value })} />
          <select aria-label="Capability" className={inputCls} value={form.scope} onChange={(e) => setForm({ ...form, scope: e.target.value })}>
            <option value="publish">Publishing results</option>
            <option value="clubs">Creating or joining clubs</option>
            <option value="posting">Posting in clubs</option>
          </select>
          <input aria-label="Days" inputMode="numeric" placeholder="Days (blank = until lifted)" className={inputCls} value={form.days} onChange={(e) => setForm({ ...form, days: e.target.value.replace(/\D/g, "") })} />
          <input aria-label="Reason" placeholder="Reason (required, shown to the person)" className={inputCls} value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} />
          <div><button type="button" className={btn} disabled={!form.user_id.trim() || !form.reason.trim() || restrict.isPending} onClick={() => restrict.mutate()}>Restrict</button></div>
        </div>
        <ul className="flex flex-col gap-2">
          {list.data?.restrictions.map((r) => (
            <li key={r.id} className="rounded-md border border-border p-3 text-sm">
              <p className="text-text-primary">{r.scope_text} · {r.active ? "active" : "ended"} · <span className="font-mono-nums text-xs">{r.user_id}</span></p>
              <p className="text-xs text-text-secondary">{r.reason}{r.appeal ? ` · appeal ${r.appeal.status}: “${r.appeal.text}”` : ""}</p>
              {(r.active || r.appeal?.status === "open") && (
                <div className="mt-2 flex flex-col gap-2">
                  <input aria-label={`Reason for restriction ${r.id}`} placeholder="Decision reason (required)" className={inputCls} value={reasons[r.id] ?? ""} onChange={(e) => setReasons({ ...reasons, [r.id]: e.target.value })} />
                  <div className="flex flex-wrap gap-2">
                    {r.active && <button type="button" className={btn} onClick={() => lift.mutate(r.id)}>Lift</button>}
                    {r.appeal?.status === "open" && (
                      <>
                        <button type="button" className={btn} onClick={() => resolve.mutate({ id: r.id, outcome: "overturned" })}>Overturn appeal</button>
                        <button type="button" className={btn} onClick={() => resolve.mutate({ id: r.id, outcome: "upheld" })}>Uphold</button>
                      </>
                    )}
                  </div>
                </div>
              )}
            </li>
          ))}
        </ul>
        {(log.data?.actions.length ?? 0) > 0 && (
          <details>
            <summary className="cursor-pointer text-sm font-medium text-text-secondary">Action log ({log.data!.actions.length})</summary>
            <ul className="mt-2 flex flex-col gap-1 text-xs text-text-secondary">
              {log.data!.actions.slice(0, 50).map((a) => <li key={a.id}>{formatInstantDateTime(a.at)} · {a.action} · {a.subject_user_id.slice(0, 8)}… · {a.reason}</li>)}
            </ul>
          </details>
        )}
      </div>
    </Card>
  );
}
