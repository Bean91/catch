import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { fetchTimeZone, putTimeZone } from "../../lib/api";
import { allZones, deviceZone, setActiveZone, zoneLabel } from "../../lib/localTime";
import { Card } from "../ui/Card";

const INPUT = "min-h-11 w-full rounded-md border border-border bg-bg px-3 text-sm text-text-primary focus:border-accent focus:outline-none";

/** The IANA zone list from the browser itself (no data shipped), with the device's own zone suggested first. */
export function TimeZoneSelect({ value, onChange, id = "tz-select" }: { value: string; onChange: (zone: string) => void; id?: string }) {
  const zones = useMemo(() => allZones(), []);
  const suggested = deviceZone();
  return (
    <select id={id} value={value} onChange={(e) => onChange(e.target.value)} className={INPUT}>
      {suggested && <option value={suggested}>{zoneLabel(suggested)} — this device ({suggested})</option>}
      {zones
        .filter((z) => z !== suggested)
        .map((z) => (
          <option key={z} value={z}>
            {z.replaceAll("_", " ")}
          </option>
        ))}
    </select>
  );
}

/** Settings → Time zone (session 32, docs/time.md). Home zone + "follow my device while travelling", and where Catch thinks you are
 * now. Changing either never changes a workout's time; days are re-read and scores recomputed in the background. */
export function TimeZoneCard() {
  const qc = useQueryClient();
  const query = useQuery({ queryKey: ["time-zone"], queryFn: fetchTimeZone });
  const [draft, setDraft] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: putTimeZone,
    onSuccess: (out) => {
      setActiveZone(out.current_zone);
      setDraft(null);
      void qc.invalidateQueries();
    },
  });
  const data = query.data;
  const home = draft ?? data?.timezone ?? deviceZone() ?? "UTC";

  return (
    <Card title="Time zone">
      {!data ? (
        <p className="text-sm text-text-tertiary">{query.isError ? "Couldn't load your time zone." : "Loading…"}</p>
      ) : (
        <div className="flex flex-col gap-3 text-sm" data-testid="time-zone-card">
          <p className="text-text-secondary">
            Days are counted where you are: a workout keeps the day it happened on, even after you fly home. Showing dates in{" "}
            <span className="font-medium text-text-primary">{zoneLabel(data.current_zone)}</span> now.
          </p>
          <label className="flex flex-col gap-1.5" htmlFor="tz-home">
            <span className="font-medium text-text-primary">Home time zone</span>
            <TimeZoneSelect id="tz-home" value={home} onChange={setDraft} />
          </label>
          {data.timezone == null && (
            <p className="text-xs text-text-tertiary">Not chosen yet — Catch is using {zoneLabel(data.fallback_zone)} until you pick one or open the app on your phone.</p>
          )}
          <label className="flex min-h-11 items-center justify-between gap-3">
            <span className="flex flex-col">
              <span className="font-medium text-text-primary">Follow my device while travelling</span>
              <span className="text-xs text-text-tertiary">Today follows your phone or watch. Off: everything uses your home zone.</span>
            </span>
            <button
              type="button"
              role="switch"
              aria-checked={data.follow_device_zone}
              onClick={() => save.mutate({ follow_device_zone: !data.follow_device_zone })}
              className="min-h-11 min-w-16 rounded-md border border-border px-3 text-sm font-medium text-text-primary"
            >
              {data.follow_device_zone ? "On" : "Off"}
            </button>
          </label>
          <div className="flex items-center gap-3">
            <button
              type="button"
              disabled={draft == null || save.isPending}
              onClick={() => save.mutate({ timezone: home })}
              className="min-h-11 rounded-md bg-accent px-4 text-sm font-medium text-accent-contrast transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              Save time zone
            </button>
            {save.isError && <span role="alert" className="text-band-red-text">{(save.error as Error).message}</span>}
            {save.isSuccess && <span role="status" className="text-text-tertiary">Saved. Past days are being re-read.</span>}
          </div>
        </div>
      )}
    </Card>
  );
}
