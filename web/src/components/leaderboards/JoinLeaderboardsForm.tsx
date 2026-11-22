import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { lbOptIn } from "../../lib/api";
import type { LbState } from "../../lib/types";
import { Card } from "../ui/Card";

const inputCls = "min-h-11 w-full rounded-md border border-border bg-surface-2 px-3 text-sm text-text-primary placeholder:text-text-tertiary";
const primary = "min-h-11 rounded-md bg-accent px-4 text-sm font-medium text-white disabled:opacity-50";

/** The leaderboard opt-in (session 26), shared by Settings → Leaderboards and the privacy step of first-run setup (session 34). Opting in
 *  only *allows* publishing: every result still needs its own previewed, confirmed publish, so joining makes nothing public by itself. */
export function JoinLeaderboardsForm({ state, title = "Join the leaderboards" }: { state: LbState; title?: string }) {
  const queryClient = useQueryClient();
  const [handle, setHandle] = useState("");
  const [mode, setMode] = useState<"handle" | "anonymous">("handle");
  const [band, setBand] = useState("");
  const [age13, setAge13] = useState(false);
  const [guardian, setGuardian] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const youth = band.startsWith("U");
  const join = useMutation({
    mutationFn: () =>
      lbOptIn({ confirm, handle: mode === "handle" ? handle : undefined, display_mode: mode, self_declared_band: band || undefined, attest_min_age: !band && age13 ? true : band ? true : undefined, attest_guardian: youth && guardian ? true : undefined }),
    onSuccess: () => {
      setError(null);
      queryClient.invalidateQueries({ queryKey: ["lb-me"] });
    },
    onError: (e: Error) => setError(e.message),
  });
  return (
    <Card title={title}>
      <form
        className="flex flex-col gap-3"
        data-testid="lb-join-form"
        onSubmit={(e) => {
          e.preventDefault();
          join.mutate();
        }}
      >
        <fieldset className="flex flex-col gap-2">
          <legend className="text-sm text-text-secondary">How you appear</legend>
          <label className="flex min-h-11 items-center gap-2 text-sm text-text-secondary">
            <input type="radio" name="mode" checked={mode === "handle"} onChange={() => setMode("handle")} className="h-5 w-5" data-testid="lb-mode-handle" /> A public handle I choose
          </label>
          {mode === "handle" && <input value={handle} onChange={(e) => setHandle(e.target.value)} maxLength={24} placeholder="Handle (3–24 characters)" className={inputCls} data-testid="lb-handle" aria-label="Public handle" />}
          <label className="flex min-h-11 items-center gap-2 text-sm text-text-secondary">
            <input type="radio" name="mode" checked={mode === "anonymous"} onChange={() => setMode("anonymous")} className="h-5 w-5" data-testid="lb-mode-anonymous" /> Anonymous rower (no name)
          </label>
          <p className="text-xs text-text-tertiary">Catch never publishes your account name or email. Only the handle you type here, or “Anonymous rower”.</p>
        </fieldset>
        <label className="flex flex-col gap-1.5 text-sm text-text-secondary">
          Age category (optional)
          <select value={band} onChange={(e) => setBand(e.target.value)} className={inputCls} data-testid="lb-band">
            <option value="">I'll skip this — Overall boards only</option>
            {state.age_bands.map((b) => (
              <option key={b} value={b}>
                {b}
              </option>
            ))}
          </select>
          <span className="text-xs text-text-tertiary">
            If your Concept2 profile has a date of birth, Catch uses it instead (and keeps only the category, never the date). Otherwise this is self-declared and labelled that
            way. “U16” means under 16.
          </span>
        </label>
        {!band && (
          <label className="flex min-h-11 items-center gap-2 text-sm text-text-secondary">
            <input type="checkbox" checked={age13} onChange={(e) => setAge13(e.target.checked)} className="h-5 w-5" data-testid="lb-age13" /> I am {state.min_age} or older
          </label>
        )}
        {youth && (
          <label className="flex min-h-11 items-start gap-2 text-sm text-text-secondary">
            <input type="checkbox" checked={guardian} onChange={(e) => setGuardian(e.target.checked)} className="mt-2 h-5 w-5" data-testid="lb-guardian" />
            <span>
              A parent or guardian agrees to this. (Required under {state.guardian_below}. Athletes under 18 appear only under a handle or as anonymous, and only the year of a
              result is ever shown.)
            </span>
          </label>
        )}
        <label className="flex min-h-11 items-start gap-2 text-sm text-text-primary">
          <input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} className="mt-2 h-5 w-5" data-testid="lb-confirm" />
          <span>I want to be able to publish results to the public leaderboards. I can leave and take everything down at any time.</span>
        </label>
        {error && (
          <p role="alert" data-testid="lb-error" className="rounded-md border border-band-red/30 bg-band-red/10 px-3 py-2 text-sm text-band-red-text">
            {error}
          </p>
        )}
        <div className="flex justify-end">
          <button type="submit" disabled={!confirm || join.isPending} data-testid="lb-optin" className={primary}>
            {join.isPending ? "Saving…" : "Opt in"}
          </button>
        </div>
      </form>
    </Card>
  );
}
