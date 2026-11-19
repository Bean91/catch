import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { decideConsent, fetchConsentRequest } from "../lib/privacy";
import { Card } from "../components/ui/Card";

const btn = "min-h-11 rounded-md border border-border px-4 text-sm font-medium text-text-primary transition-colors hover:border-accent disabled:opacity-50";

/** An MCP app (Claude Desktop, …) asked to connect to your Catch data. Nothing is granted until you approve here. */
export function OAuthConsentPage() {
  const [params] = useSearchParams();
  const req = params.get("req") ?? "";
  const info = useQuery({ queryKey: ["oauth-consent", req], queryFn: () => fetchConsentRequest(req), enabled: !!req, retry: false });
  const [allowWrite, setAllowWrite] = useState(false);
  const decide = useMutation({
    mutationFn: (approve: boolean) => decideConsent(req, approve, approve ? ["catch:read", ...(allowWrite ? ["catch:write"] : [])] : []),
    onSuccess: (r) => window.location.assign(r.redirect_url),
  });

  if (!req || info.isError) {
    return (
      <Card title="Connect an app">
        <p role="alert" className="text-sm text-band-red-text" data-testid="consent-invalid">
          This link isn't valid any more (it may have expired). Go back to the app and start the connection again.
        </p>
        <Link to="/settings/privacy" className="mt-3 inline-block text-sm font-medium text-accent hover:underline">Privacy settings</Link>
      </Card>
    );
  }
  if (!info.data) return <Card title="Connect an app"><p className="text-sm text-text-secondary">Loading…</p></Card>;
  const wantsWrite = info.data.scopes.some((s) => s.scope === "catch:write");
  return (
    <Card title="Connect an app">
      <div className="flex flex-col gap-4" data-testid="oauth-consent">
        <p className="text-sm text-text-primary">
          <span className="font-semibold">{info.data.client_name}</span> wants to connect to your Catch data.
        </p>
        <p className="text-xs text-text-secondary">
          After you decide you'll be sent to <span className="font-mono-nums text-text-primary">{info.data.redirect_host}</span>. Only continue if you just started this from that app.
        </p>
        <ul className="flex flex-col gap-2 text-sm text-text-secondary">
          <li className="rounded-md border border-border p-3"><span className="font-medium text-text-primary">Read.</span> {info.data.scopes.find((s) => s.scope === "catch:read")?.text}</li>
          {wantsWrite && (
            <li className="rounded-md border border-border p-3">
              <label className="flex items-start gap-3">
                <input type="checkbox" className="mt-1 size-4" checked={allowWrite} onChange={(e) => setAllowWrite(e.target.checked)} data-testid="consent-write" />
                <span><span className="font-medium text-text-primary">Propose changes.</span> {info.data.scopes.find((s) => s.scope === "catch:write")?.text}</span>
              </label>
            </li>
          )}
        </ul>
        <p className="text-xs text-text-secondary">
          It can only see the categories you've allowed the AI to see (Settings → Privacy → AI sharing). It never gets your passwords, AI keys or the ability to delete your account.
          You can end access any time in Privacy. It expires after 90 days unless renewed.
        </p>
        {decide.isError && <p role="alert" className="text-sm text-band-red-text">{(decide.error as Error).message}</p>}
        <div className="flex flex-wrap gap-2">
          <button type="button" className={btn} onClick={() => decide.mutate(false)} disabled={decide.isPending} data-testid="consent-deny">Cancel</button>
          <button type="button" className="min-h-11 rounded-md bg-accent px-4 text-sm font-medium text-white disabled:opacity-50" onClick={() => decide.mutate(true)} disabled={decide.isPending} data-testid="consent-approve">
            Allow
          </button>
        </div>
      </div>
    </Card>
  );
}
