import { formatInstantDateTime } from "../lib/localTime";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { fetchStatus } from "../lib/api";
import { formatBytes, formatRelativeTime, formatUptime } from "../lib/format";
import { Card } from "../components/ui/Card";
import { CardSkeleton } from "../components/ui/Skeleton";
import { ErrorState } from "../components/ui/EmptyState";
import { isPublic } from "../lib/deployment";

/** Task Part B.1 — a read-only operational dashboard, not a settings form: per-source sync
 * health, the Garmin key expiry reminder, backup status, disk/DB size, uptime, build. Its own
 * route (not a Settings card) so a push notification's deep link can point straight at it. */
export function StatusPage() {
  const { data, isLoading, isError, refetch } = useQuery({ queryKey: ["status"], queryFn: fetchStatus, refetchInterval: 60_000 });

  if (isLoading || !data) {
    return (
      <div className="flex flex-col gap-4">
        <CardSkeleton lines={3} />
        <CardSkeleton lines={3} />
      </div>
    );
  }
  if (isError) return <ErrorState message="Couldn't load status" onRetry={refetch} />;

  const diskUsedPct = data.disk_total_bytes > 0 ? (1 - data.disk_free_bytes / data.disk_total_bytes) * 100 : 0;

  return (
    <div className="flex flex-col gap-4 lg:gap-5">
      <h1 className="text-lg font-semibold text-text-primary">Status</h1>

      <Card title="Sources">
        <div className="flex flex-col gap-3">
          {data.sources.map((s) => (
            <div key={s.source} className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-3 last:border-0 last:pb-0">
              <div>
                <div className="text-sm font-medium capitalize text-text-primary">{s.source}</div>
                <div className="text-xs text-text-tertiary">
                  {s.connected === false ? (
                    "not connected"
                  ) : s.last_error ? (
                    <span className="text-band-red-text">
                      failed — {s.last_error} ({s.consecutive_failures} in a row)
                    </span>
                  ) : (
                    <>last success {formatRelativeTime(s.last_success_at)}</>
                  )}
                  {s.token_expires_at && <> · token valid until {formatInstantDateTime(s.token_expires_at)}</>}
                </div>
              </div>
            </div>
          ))}
        </div>
      </Card>

      <Card title="Garmin key">
        <p className="text-sm text-text-primary">
          {data.garmin_key_expires_on ? `Expires ${data.garmin_key_expires_on}` : "No expiry reminder set — add one under Connections."}
        </p>
        <Link to="/settings/connections" className="mt-2 inline-block text-sm font-medium text-accent hover:underline">
          Manage connections
        </Link>
      </Card>

      {/* Session 31 (launch audit L-04): the public server reports no disk/backup/uptime to a user (they describe shared
          infrastructure), so these cards showed "0 B", "Uptime 0m" and "No backup has run yet" — false statements. */}
      {!isPublic && (
      <Card title="Backup">
        {data.backup ? (
          <div className="flex flex-col gap-1 text-sm text-text-primary">
            <div>Last local backup: {formatRelativeTime(data.backup.last_backup_at)} ({formatBytes(data.backup.backup_size_bytes)})</div>
            <div>Integrity check: {data.backup.integrity_ok == null ? "—" : data.backup.integrity_ok ? "OK" : "FAILED"}</div>
            <div>
              Off-Pi copy:{" "}
              {data.backup.remote_ok == null
                ? "not attempted yet"
                : data.backup.remote_ok
                  ? `OK (${formatRelativeTime(data.backup.remote_copied_at)})`
                  : "FAILED"}
            </div>
          </div>
        ) : (
          <p className="text-sm text-text-tertiary">No backup has run yet on this instance.</p>
        )}
      </Card>
      )}

      <Card title="System">
        <div className="flex flex-col gap-1 text-sm text-text-primary">
          {!isPublic && (
            <>
              <div>Disk free: {formatBytes(data.disk_free_bytes)} of {formatBytes(data.disk_total_bytes)} ({diskUsedPct.toFixed(0)}% used)</div>
              <div>Database size: {formatBytes(data.db_size_bytes)}</div>
              <div>Uptime: {formatUptime(data.uptime_seconds)}</div>
            </>
          )}
          {data.build && (
            <div>
              Build {data.build.build} · {data.build.commit}
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}
