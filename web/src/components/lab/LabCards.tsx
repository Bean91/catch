import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { fetchHrAtWorkload, fetchLabProgression, fetchPredict2k, fetchRecords, fetchSplitByRate } from "../../lib/api";
import { formatShortDate, formatSplit, formatTimeTenths, splitUnitLabel } from "../../lib/format";
import { METRIC_COLOR } from "../../lib/metricColors";
import type { Predicted2kComponent, RecordEntry, RecordRow } from "../../lib/types";
import { MiniLineChart } from "../charts/MiniLineChart";
import { Badge } from "../ui/Badge";
import { Card } from "../ui/Card";
import { DataTable } from "../ui/DataList";
import { EmptyState, ErrorState } from "../ui/EmptyState";
import { InfoTip } from "../ui/InfoTip";
import { Segmented } from "../ui/Segmented";
import { CardSkeleton } from "../ui/Skeleton";

export type Modality = "rowing_erg" | "bike";

const LABEL_TEXT = { test: "Test", piece: "Piece", training: "Training result" } as const;

export function recordName(key: string): string {
  if (key.endsWith("min_power")) return `Power · ${key.replace("min_power", "")} min or longer`;
  if (key.endsWith("min")) return `${key.replace("min", "")} minutes`;
  return `${Number(key.replace("m", "")).toLocaleString()} m`;
}

function Source({ e }: { e: RecordEntry }) {
  return (
    <span className="flex flex-wrap items-center gap-1">
      <Badge tone="outline">{LABEL_TEXT[e.label]}</Badge>
      {e.verified && <Badge tone="outline">✓ Concept2-verified</Badge>}
    </span>
  );
}

function headline(row: RecordRow, kind: "distance" | "duration" | "power"): string {
  const b = row.best!;
  if (kind === "distance") return formatTimeTenths(b.duration_s);
  if (kind === "duration") return `${Math.round(b.distance_m).toLocaleString()} m`;
  return `${Math.round(b.avg_watts ?? 0)} W`;
}

function detail(row: RecordRow, kind: "distance" | "duration" | "power"): string {
  const b = row.best!;
  const pace = b.pace_s != null ? `${formatSplit(b.pace_s)} ${splitUnitLabel(b.split_m)}` : "";
  if (kind === "power") return `${formatTimeTenths(b.duration_s)} · ${Math.round(b.distance_m).toLocaleString()} m${b.watts_basis === "derived" ? " · watts from pace" : ""}`;
  return [pace, b.avg_watts != null ? `${Math.round(b.avg_watts)} W${b.watts_basis === "derived" ? " (from pace)" : ""}` : ""].filter(Boolean).join(" · ");
}

function RecordRows({ rows, kind }: { rows: RecordRow[]; kind: "distance" | "duration" | "power" }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <ul className="divide-y divide-border/70" data-testid={`records-${kind}`}>
      {rows.map((r) => (
        <li key={r.key} className="py-2.5">
          <div className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
            <span className="text-sm text-text-secondary">{recordName(r.key)}</span>
            {r.best ? (
              <span className="font-mono-nums text-base font-semibold text-text-primary">{headline(r, kind)}</span>
            ) : (
              <span className="text-sm text-text-tertiary">No effort yet</span>
            )}
          </div>
          {r.best && (
            <div className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-text-tertiary">
              <span className="font-mono-nums">{detail(r, kind)}</span>
              <span>{formatShortDate(r.best.date)}</span>
              <Source e={r.best} />
              {r.best.ref && (
                <Link to={r.best.ref} className="text-accent underline">
                  Open
                </Link>
              )}
              {r.history.length > 1 && (
                <button type="button" onClick={() => setOpen(open === r.key ? null : r.key)} className="min-h-9 text-accent underline" aria-expanded={open === r.key}>
                  {open === r.key ? "Hide history" : `History (${r.history.length})`}
                </button>
              )}
            </div>
          )}
          {open === r.key && (
            <ol className="mt-2 flex flex-col gap-1 border-l border-border pl-3 text-xs" data-testid="record-history">
              {r.history
                .slice()
                .reverse()
                .map((h, i) => (
                  <li key={i} className="flex flex-wrap gap-x-2 text-text-secondary">
                    <span className="font-mono-nums text-text-primary">{kind === "duration" ? `${Math.round(h.distance_m).toLocaleString()} m` : kind === "power" ? `${Math.round(h.avg_watts ?? 0)} W` : formatTimeTenths(h.duration_s)}</span>
                    <span>{formatShortDate(h.date)}</span>
                    <span>{LABEL_TEXT[h.label]}</span>
                  </li>
                ))}
            </ol>
          )}
        </li>
      ))}
    </ul>
  );
}

export function RecordsCard({ modality }: { modality: Modality }) {
  const q = useQuery({ queryKey: ["records", modality], queryFn: () => fetchRecords(modality) });
  const [tab, setTab] = useState<"distance" | "duration" | "power">("distance");
  return (
    <Card
      title="Personal records"
      testId="records-card"
      action={
        <InfoTip label="how records are counted">
          A record is your fastest (or furthest, or strongest) whole continuous effort: a Concept2 result or a piece you saved. Interval sessions and estimates never count, and a workout excluded from totals is left out. Distances allow ±2 % (at least 25 m) and times ±30 s, as in the test center.
        </InfoTip>
      }
    >
      <Segmented
        label="Record type"
        size="sm"
        value={tab}
        onChange={setTab}
        className="mb-2"
        options={[
          { value: "distance", label: "Distance" },
          { value: "duration", label: "Time" },
          { value: "power", label: "Power" },
        ]}
      />
      {q.isError ? <ErrorState message="Couldn't load records." onRetry={() => q.refetch()} /> : !q.data ? <CardSkeleton lines={4} /> : <RecordRows rows={q.data[tab]} kind={tab} />}
    </Card>
  );
}

export function ProgressionCard({ modality, from, to }: { modality: Modality; from: string; to: string }) {
  const q = useQuery({ queryKey: ["lab-progression", modality, from, to], queryFn: () => fetchLabProgression(modality, from, to) });
  const [key, setKey] = useState<string | null>(null);
  if (q.isError) return <ErrorState message="Couldn't load progression." onRetry={() => q.refetch()} />;
  if (!q.data) return <CardSkeleton lines={5} />;
  const series = q.data.series;
  if (series.length === 0) {
    return (
      <Card title="Progression" testId="progression-card">
        <EmptyState message="No efforts at a standard distance or time in this period yet — a 2k, 5k, 30 minutes and so on." />
      </Card>
    );
  }
  const current = series.find((s) => s.key === key) ?? series.reduce((a, b) => (b.points.length > a.points.length ? b : a));
  const timed = current.key.endsWith("min");
  const unit = splitUnitLabel(q.data.split_m);
  const withWatts = current.points.filter((p) => p.avg_watts != null);
  return (
    <Card title="Progression" testId="progression-card">
      <Segmented label="Distance or time" size="sm" className="mb-3 max-w-full overflow-x-auto" value={current.key} onChange={setKey} options={series.map((s) => ({ value: s.key, label: recordName(s.key) }))} />
      <p className="mb-1 text-xs text-text-tertiary">
        Average split {unit} for every {recordName(current.key)} effort — rings mark each new best. Faster is higher.
      </p>
      <MiniLineChart
        points={current.points.map((p) => ({ date: p.date, value: p.pace_s }))}
        markers={current.points.filter((p) => p.new_best).map((p) => ({ date: p.date, value: p.pace_s }))}
        markerLabel="New best"
        color={METRIC_COLOR.pace}
        axis="seconds"
        invert
        format={(v) => `${formatSplit(v)} ${unit}`}
        label={`Split progression for ${recordName(current.key)}`}
        height={170}
      />
      {withWatts.length >= 2 && (
        <>
          <p className="mb-1 mt-4 text-xs text-text-tertiary">
            Average power{withWatts.some((p) => p.watts_basis === "derived") ? " (a piece's watts are worked out from its pace)" : ""}.
          </p>
          <MiniLineChart points={withWatts.map((p) => ({ date: p.date, value: p.avg_watts }))} color={METRIC_COLOR.power} format={(v) => `${Math.round(v)} W`} label={`Power progression for ${recordName(current.key)}`} height={150} />
        </>
      )}
      <DataTable label={`${recordName(current.key)} efforts`} className="mt-3">
        <thead>
          <tr>
            <th>Date</th>
            <th>{timed ? "Distance" : "Time"}</th>
            <th>Split</th>
            <th>Power</th>
            <th>What</th>
          </tr>
        </thead>
        <tbody>
          {current.points
            .slice()
            .reverse()
            .map((p, i) => (
              <tr key={i}>
                <td className="whitespace-nowrap">{p.ref ? <Link to={p.ref} className="text-accent underline">{formatShortDate(p.date)}</Link> : formatShortDate(p.date)}</td>
                <td className="font-mono-nums">{timed ? `${Math.round(p.distance_m).toLocaleString()} m` : formatTimeTenths(p.duration_s)}</td>
                <td className="font-mono-nums">{p.pace_s != null ? formatSplit(p.pace_s) : "—"}</td>
                <td className="font-mono-nums">{p.avg_watts != null ? `${Math.round(p.avg_watts)}` : "—"}</td>
                <td className="text-xs text-text-secondary">
                  {LABEL_TEXT[p.label]}
                  {p.new_best ? " · new best" : ""}
                </td>
              </tr>
            ))}
        </tbody>
      </DataTable>
    </Card>
  );
}

function change(v: number | null, unit: string, lowerIs: string, higherIs: string, digits = 0): string {
  if (v == null) return "—";
  if (Math.abs(v) < (digits ? 0.05 : 0.5)) return "about the same";
  return `${Math.abs(v).toFixed(digits)} ${unit} ${v < 0 ? lowerIs : higherIs}`;
}

export function HrAtWorkloadCard({ from, to }: { from: string; to: string }) {
  const q = useQuery({ queryKey: ["lab-hr-workload", from, to], queryFn: () => fetchHrAtWorkload(from, to) });
  if (q.isError) return <ErrorState message="Couldn't load heart rate at comparable power." onRetry={() => q.refetch()} />;
  if (!q.data) return <CardSkeleton lines={4} />;
  const d = q.data;
  const rows = d.bands.filter((b) => b.earlier.sessions + b.recent.sessions > 0);
  return (
    <Card title="Heart rate at the same power" testId="hr-workload-card">
      <p className="text-sm text-text-secondary">
        Continuous erg sessions of 10 minutes or more, grouped by average power, before and after {formatShortDate(d.split_date)}. A figure needs at least {d.min_sessions} sessions in that band and half.
      </p>
      {rows.length === 0 ? (
        <EmptyState message="No continuous erg sessions with both power and heart rate in this period." />
      ) : (
        <DataTable label="Heart rate by power band" className="mt-3">
          <thead>
            <tr>
              <th>Power</th>
              <th>Earlier</th>
              <th>Recent</th>
              <th>Change</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((b) => (
              <tr key={b.band_w[0]}>
                <td className="whitespace-nowrap font-mono-nums">
                  {b.band_w[0]}–{b.band_w[1]} W
                </td>
                <td className="font-mono-nums">{b.earlier.median_hr != null ? `${Math.round(b.earlier.median_hr)} bpm` : "—"} <span className="text-xs text-text-tertiary">({b.earlier.sessions})</span></td>
                <td className="font-mono-nums">{b.recent.median_hr != null ? `${Math.round(b.recent.median_hr)} bpm` : "—"} <span className="text-xs text-text-tertiary">({b.recent.sessions})</span></td>
                <td className="text-xs text-text-secondary">{change(b.hr_change_bpm, "bpm", "lower", "higher")}</td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      )}
      <p className="mt-2 text-xs text-text-tertiary">
        Median heart rate; (n) = sessions. A lower heart rate at the same power usually means better aerobic fitness, but heat, fatigue, caffeine, illness and a different heart-rate sensor all move it too.
      </p>
    </Card>
  );
}

export function SplitByRateCard({ from, to }: { from: string; to: string }) {
  const q = useQuery({ queryKey: ["lab-split-rate", from, to], queryFn: () => fetchSplitByRate(from, to) });
  if (q.isError) return <ErrorState message="Couldn't load split by stroke rate." onRetry={() => q.refetch()} />;
  if (!q.data) return <CardSkeleton lines={4} />;
  const d = q.data;
  return (
    <Card title="Split at the same stroke rate" testId="split-rate-card">
      <p className="text-sm text-text-secondary">
        Every Concept2 rowing stroke in the period, grouped by rate, before and after {formatShortDate(d.split_date)}. A figure needs at least {d.min_strokes} strokes from {d.min_sessions} sessions.
      </p>
      {d.bands.length === 0 ? (
        <EmptyState message="No per-stroke Concept2 data in this period." />
      ) : (
        <DataTable label="Split by stroke rate" className="mt-3">
          <thead>
            <tr>
              <th>Rate</th>
              <th>Earlier</th>
              <th>Recent</th>
              <th>Change</th>
            </tr>
          </thead>
          <tbody>
            {d.bands.map((b) => (
              <tr key={b.band_spm[0]}>
                <td className="whitespace-nowrap font-mono-nums">
                  {b.band_spm[0]}–{b.band_spm[1] - 1} spm
                </td>
                <td className="font-mono-nums">{b.earlier.split_s != null ? formatSplit(b.earlier.split_s) : "—"}</td>
                <td className="font-mono-nums">{b.recent.split_s != null ? formatSplit(b.recent.split_s) : "—"}</td>
                <td className="text-xs text-text-secondary">{change(b.split_change_s, "s", "faster", "slower", 1)}</td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      )}
      <p className="mt-2 text-xs text-text-tertiary">Splits are /500m: the average of each stroke's own split. Drag factor and the session's purpose (steady or hard) aren't accounted for.</p>
    </Card>
  );
}

const EFFORT_TEXT: Record<Predicted2kComponent["effort"], string> = {
  declared: "a confirmed test or piece",
  hr_verified: "hard by heart rate",
  effort_unknown: "effort not known",
};

export function Estimate2kCard() {
  const q = useQuery({ queryKey: ["predict-2k"], queryFn: fetchPredict2k });
  if (q.isError) return <ErrorState message="Couldn't load the 2k estimate." onRetry={() => q.refetch()} />;
  if (!q.data) return <CardSkeleton lines={3} />;
  const p = q.data;
  const comps = (p.components as Predicted2kComponent[]).filter((c) => c && typeof c === "object" && "implied_2k_s" in c);
  return (
    <Card title="Estimated 2k" eyebrow="Estimate" testId="estimate-2k-card">
      {p.predicted_time_s != null ? (
        <>
          <p className="font-mono-nums text-2xl font-semibold text-text-primary">{formatTimeTenths(p.predicted_time_s)}</p>
          {p.range_s && (
            <p className="text-sm text-text-secondary">
              likely {formatTimeTenths(p.range_s[0])}–{formatTimeTenths(p.range_s[1])} · {p.confidence ?? p.band} confidence
            </p>
          )}
        </>
      ) : (
        <p className="text-sm text-text-secondary">Not enough recent hard efforts for an estimate.</p>
      )}
      <p className="mt-2 text-xs text-text-tertiary">{p.explanation}</p>
      {comps.length > 0 && (
        <DataTable label="What the estimate used" className="mt-3">
          <thead>
            <tr>
              <th>Effort</th>
              <th>Implies</th>
              <th>Weight</th>
            </tr>
          </thead>
          <tbody>
            {comps.map((c, i) => (
              <tr key={i}>
                <td>
                  <span className="font-mono-nums">{Math.round(c.distance_m).toLocaleString()} m in {formatTimeTenths(c.duration_s)}</span>
                  <span className="block text-xs text-text-tertiary">
                    {formatShortDate(c.date)} · {EFFORT_TEXT[c.effort]}
                  </span>
                </td>
                <td className="font-mono-nums">{formatTimeTenths(c.implied_2k_s)}</td>
                <td className="font-mono-nums">{Math.round(c.weight * 100)}%</td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      )}
      {p.measured_2k?.latest && (
        <p className="mt-2 text-sm text-text-secondary">
          Measured 2k: <span className="font-mono-nums">{formatTimeTenths(p.measured_2k.latest.time_s)}</span> on {formatShortDate(p.measured_2k.latest.date)} — a result, shown separately.
        </p>
      )}
      <p className="mt-2 text-xs text-text-tertiary">Paul's law turns each effort into an implied 2k; the estimate is their weighted middle. It is an estimate, never a result.</p>
    </Card>
  );
}
