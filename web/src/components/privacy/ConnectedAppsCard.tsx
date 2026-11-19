import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { endOauthGrant, fetchDeviceTokens, fetchOauthGrants, fetchToolCalls, revokeAllDeviceTokens, revokeDeviceToken } from "../../lib/privacy";
import { Card } from "../ui/Card";

const btn = "min-h-11 rounded-md border border-border px-4 text-sm font-medium text-text-primary transition-colors hover:border-accent disabled:opacity-50";
const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : "never");

export function ConnectedAppsCard() {
  const qc = useQueryClient();
  const tokens = useQuery({ queryKey: ["device-tokens"], queryFn: fetchDeviceTokens });
  const calls = useQuery({ queryKey: ["tool-calls"], queryFn: fetchToolCalls });
  const grants = useQuery({ queryKey: ["oauth-grants"], queryFn: fetchOauthGrants });
  const refresh = () => { qc.invalidateQueries({ queryKey: ["device-tokens"] }); qc.invalidateQueries({ queryKey: ["oauth-grants"] }); };
  const endGrant = useMutation({ mutationFn: endOauthGrant, onSuccess: refresh });
  const revoke = useMutation({ mutationFn: revokeDeviceToken, onSuccess: refresh });
  const revokeAll = useMutation({ mutationFn: revokeAllDeviceTokens, onSuccess: refresh });

  return (
    <Card title="Connected apps and sources">
      <div className="flex flex-col gap-4" data-testid="connected-apps">
        <p className="text-sm text-text-secondary">
          Data sources (Garmin, Withings, Whoop, Concept2) are disconnected in <Link to="/settings/connections" className="font-medium text-accent hover:underline">Connections</Link> —
          that removes the stored credential and, where the provider allows it, ends their access; data already imported stays until you delete it above.
          Apps that use your Catch data (like Claude Desktop) connect with a token you can end at any time:
        </p>
        {tokens.data && tokens.data.length === 0 && (grants.data?.length ?? 0) === 0 && <p className="text-sm text-text-secondary">No apps are connected.</p>}
        <ul className="flex flex-col gap-2" data-testid="oauth-grants">
          {grants.data?.map((g) => (
            <li key={g.grant_id} className="flex items-start justify-between gap-3 rounded-md border border-border p-3">
              <div className="min-w-0 text-sm">
                <p className="font-medium text-text-primary">{g.client_name} <span className="text-xs font-normal text-text-secondary">· {g.scopes.includes("catch:write") ? "can propose changes (you confirm each)" : "read only"}</span></p>
                <p className="text-xs text-text-secondary">Last used {when(g.last_used_at)} · access ends {when(g.expires_at)} unless renewed</p>
              </div>
              <button type="button" className={`${btn} shrink-0`} onClick={() => endGrant.mutate(g.grant_id)} disabled={endGrant.isPending} data-testid={`end-grant-${g.grant_id}`}>End access</button>
            </li>
          ))}
        </ul>
        <ul className="flex flex-col gap-2">
          {tokens.data?.map((t) => (
            <li key={t.id} className="flex items-start justify-between gap-3 rounded-md border border-border p-3">
              <div className="min-w-0 text-sm">
                <p className="font-medium text-text-primary">{t.name} <span className="text-xs font-normal text-text-secondary">· {t.scope === "read" ? "read only" : "can make confirmed changes"}{t.role === "coach" ? " · coach" : ""}</span></p>
                <p className="text-xs text-text-secondary">Last used {when(t.last_used_at)} · expires {when(t.expires_at)}</p>
              </div>
              <button type="button" className={`${btn} shrink-0`} onClick={() => revoke.mutate(t.id)} disabled={revoke.isPending} data-testid={`revoke-token-${t.id}`}>End access</button>
            </li>
          ))}
        </ul>
        {((tokens.data?.length ?? 0) + (grants.data?.length ?? 0)) > 1 && (
          <div><button type="button" className={btn} onClick={() => revokeAll.mutate()} disabled={revokeAll.isPending}>End all app access</button></div>
        )}
        <div>
          <h4 className="text-sm font-medium text-text-primary">Recent activity by apps</h4>
          <p className="text-xs text-text-secondary">What outside apps did through Catch: which tool, and whether it changed anything — never what was asked or answered.</p>
          {calls.data && calls.data.length === 0 && <p className="mt-2 text-sm text-text-secondary">Nothing yet.</p>}
          <ul className="mt-2 flex flex-col gap-1" data-testid="tool-calls">
            {calls.data?.slice(0, 15).map((c, i) => (
              <li key={i} className="flex flex-wrap items-baseline gap-x-2 text-xs text-text-secondary">
                <span className="font-mono-nums text-text-primary">{c.tool}</span>
                <span>{c.via}</span>
                <span>{c.write ? (c.confirmed ? "changed data" : "preview only") : "read"}</span>
                <span>{c.outcome}</span>
                <span className="ml-auto">{when(c.at)}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </Card>
  );
}
