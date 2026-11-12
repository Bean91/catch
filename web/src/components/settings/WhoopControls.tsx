import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { disconnectWhoop, testWhoop } from "../../lib/api";
import type { SyncSourceStatus, WhoopTestResult } from "../../lib/types";

const btn = "min-h-11 rounded-md border border-border px-4 text-sm font-medium text-text-primary transition-colors hover:border-accent disabled:opacity-50";

/** Connect / reconnect / test / disconnect for Whoop. Tokens never reach the browser: the connect
 *  link is a server redirect and the test endpoint returns counts only. */
export function WhoopControls({ status, onSync, syncing }: { status: SyncSourceStatus | undefined; onSync: () => void; syncing: boolean }) {
  const queryClient = useQueryClient();
  const connected = !!status?.token_expires_at;
  const [confirm, setConfirm] = useState(false);
  const [result, setResult] = useState<WhoopTestResult | null>(null);

  const test = useMutation({ mutationFn: testWhoop, onSuccess: setResult });
  const disconnect = useMutation({
    mutationFn: disconnectWhoop,
    onSuccess: () => {
      setConfirm(false);
      setResult(null);
      queryClient.invalidateQueries({ queryKey: ["sync-status"] });
    },
  });

  return (
    <div className="flex w-full flex-col items-stretch gap-2 sm:w-auto sm:items-end" data-testid="whoop-controls">
      <div className="flex flex-wrap gap-2 sm:justify-end">
        <a href="/auth/whoop/start" className={`${btn} inline-flex items-center`}>
          {connected ? "Reconnect" : "Connect Whoop"}
        </a>
        {connected && (
          <>
            <button type="button" onClick={onSync} disabled={syncing} className={btn}>
              {syncing ? "Syncing…" : "Sync now"}
            </button>
            <button type="button" onClick={() => test.mutate()} disabled={test.isPending} className={btn}>
              {test.isPending ? "Testing…" : "Test connection"}
            </button>
            {!confirm && (
              <button type="button" onClick={() => setConfirm(true)} className="min-h-11 px-2 text-sm font-medium text-band-red-text hover:underline">
                Disconnect
              </button>
            )}
          </>
        )}
      </div>
      {confirm && (
        <div role="group" aria-label="Confirm disconnecting Whoop" className="flex flex-col gap-2 rounded-md border border-border p-3 text-sm text-text-secondary">
          <p>Disconnect Whoop? Catch stops syncing and asks Whoop to revoke its access. Data already imported stays.</p>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => disconnect.mutate()} disabled={disconnect.isPending} className="min-h-11 rounded-md border border-band-red/40 px-4 text-sm font-medium text-band-red-text">
              {disconnect.isPending ? "Disconnecting…" : "Disconnect"}
            </button>
            <button type="button" onClick={() => setConfirm(false)} className={btn}>
              Keep it connected
            </button>
          </div>
        </div>
      )}
      {result && (
        <p role="status" data-testid="whoop-test-result" className={`text-xs ${result.connected ? "text-band-green" : "text-band-red-text"}`}>
          {result.connected
            ? `Connected — recovery ${result.recovery?.has_records ? "has data" : "no data yet"}, sleep ${result.sleep?.has_records ? "has data" : "no data yet"}, workouts ${result.workout?.has_records ? "has data" : "none yet"}.`
            : result.error ?? "Not connected."}
        </p>
      )}
    </div>
  );
}
