import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { EventSheet } from "../components/calendar/EventSheet";
import { eventTypeLabel, phaseKindLabel } from "../components/calendar/labels";
import { Card } from "../components/ui/Card";
import { ErrorState } from "../components/ui/EmptyState";
import { CardSkeleton } from "../components/ui/Skeleton";
import { fetchEventOverview, fetchEventProjection } from "../lib/api";
import { formatShortDate } from "../lib/format";
import type { EventProjection } from "../lib/types";

function fmtTime(s: number | null | undefined): string {
  if (s == null) return "—";
  const m = Math.floor(s / 60);
  return `${m}:${(s - m * 60).toFixed(1).padStart(4, "0")}`;
}

function ProjectionCard({ p }: { p: EventProjection }) {
  return (
    <Card title="Race projection">
      <div className="flex flex-col gap-3 text-sm" data-testid="projection">
        {p.available && p.value_s != null ? (
          <>
            <p className="text-text-primary">
              <span className="font-mono-nums text-2xl">{fmtTime(p.value_s)}</span>
              {p.range_s && (
                <span className="ml-2 text-text-secondary">
                  likely range {fmtTime(p.range_s[0])} – {fmtTime(p.range_s[1])}
                </span>
              )}
            </p>
            {p.goal_time_s != null && p.gap_to_goal_s != null && (
              <p className="text-text-secondary">
                Goal {fmtTime(p.goal_time_s)} — projection is {Math.abs(p.gap_to_goal_s).toFixed(1)} s {p.gap_to_goal_s > 0 ? "slower than" : "faster than"} the goal.
              </p>
            )}
          </>
        ) : (
          <p className="text-text-secondary" data-testid="projection-unavailable">
            No projection yet. {p.reason}
          </p>
        )}
        {p.history.length > 0 && (
          <div>
            <p className="mb-1 font-medium text-text-primary">Based on</p>
            <ul className="grid gap-0.5 text-text-secondary">
              {p.history.map((h) => (
                <li key={h.date} className="flex justify-between">
                  <span>{formatShortDate(h.date)}</span>
                  <span className="font-mono-nums">{fmtTime(h.duration_s)}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {p.assumptions.length > 0 && (
          <div>
            <p className="mb-1 font-medium text-text-primary">Assumptions</p>
            <ul className="list-disc pl-5 text-text-secondary">
              {p.assumptions.map((a) => (
                <li key={a}>{a}</li>
              ))}
            </ul>
          </div>
        )}
        {p.uncertainty && (
          <p className="text-text-tertiary">
            <span className="font-medium text-text-secondary">Uncertainty: </span>
            {p.uncertainty}
          </p>
        )}
      </div>
    </Card>
  );
}

export function EventDetailPage() {
  const { id } = useParams();
  const eventId = Number(id);
  const navigate = useNavigate();
  const [editing, setEditing] = useState(false);
  const overview = useQuery({ queryKey: ["event", eventId], queryFn: () => fetchEventOverview(eventId), enabled: Number.isFinite(eventId) });
  const projection = useQuery({ queryKey: ["event", eventId, "projection"], queryFn: () => fetchEventProjection(eventId), enabled: Number.isFinite(eventId) });

  if (overview.isError) return <ErrorState message="Couldn't find that event." onRetry={() => overview.refetch()} />;
  if (!overview.data) return <CardSkeleton lines={4} />;
  const o = overview.data;
  const e = o.event;

  return (
    <div className="flex flex-col gap-4">
      <Link to="/calendar" className="inline-flex min-h-11 items-center text-sm text-text-secondary">
        ← Calendar
      </Link>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h1 className="text-lg font-semibold text-text-primary">{e.name}</h1>
          <p className="text-sm text-text-secondary">
            {eventTypeLabel(e.type)}
            {e.priority ? ` · ${e.priority} race` : ""} · {formatShortDate(e.date)}
            {e.location ? ` · ${e.location}` : ""}
          </p>
        </div>
        <button type="button" onClick={() => setEditing(true)} className="min-h-11 rounded-md border border-border px-4 text-sm text-text-secondary">
          Edit
        </button>
      </div>

      <Card>
        <div className="flex items-baseline gap-3" data-testid="countdown">
          <span className="font-mono-nums text-4xl text-text-primary">{e.days_to_go >= 0 ? e.days_to_go : Math.abs(e.days_to_go)}</span>
          <span className="text-text-secondary">
            {e.days_to_go > 0 ? "days to go" : e.days_to_go === 0 ? "— it's today" : "days ago"}
            {e.days_to_go > 7 ? ` (${o.weeks_to_go} weeks)` : ""}
          </span>
          {e.taper && <span className="rounded-full border border-accent/30 bg-accent/10 px-2 py-0.5 text-xs text-accent">Taper window</span>}
        </div>
        <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
          {e.distance && (
            <>
              <dt className="text-text-tertiary">Distance</dt>
              <dd className="text-text-primary">{e.distance}</dd>
            </>
          )}
          {e.goal_time && (
            <>
              <dt className="text-text-tertiary">Goal time</dt>
              <dd className="font-mono-nums text-text-primary">{e.goal_time}</dd>
            </>
          )}
          {e.result && (
            <>
              <dt className="text-text-tertiary">Result</dt>
              <dd className="font-mono-nums text-text-primary">{e.result}</dd>
            </>
          )}
          <dt className="text-text-tertiary">Planned sessions before</dt>
          <dd className="text-text-primary">{o.planned_sessions_before_event}</dd>
        </dl>
        {e.goals && <p className="mt-3 text-sm text-text-secondary">Goals: {e.goals}</p>}
        {e.notes && <p className="mt-1 text-sm text-text-secondary">Notes: {e.notes}</p>}
      </Card>

      <Card title="Preparation">
        {o.phase ? (
          <p className="text-sm text-text-secondary" data-testid="event-phase">
            Currently in <span className="text-text-primary">{o.phase.name}</span> ({phaseKindLabel(o.phase.kind)}), until {formatShortDate(o.phase.end_date)}.
            {o.phase.coach_approved ? " Coach-approved." : ""}
          </p>
        ) : (
          <p className="text-sm text-text-tertiary">No training phase covers today.</p>
        )}
        <div className="mt-3 flex flex-wrap gap-2">
          <Link to={`/calendar?view=week&date=${e.date}`} className="flex min-h-11 items-center rounded-full border border-border px-4 text-sm text-text-secondary">
            See the week
          </Link>
          <Link to="/calendar/plan" className="flex min-h-11 items-center rounded-full border border-border px-4 text-sm text-text-secondary">
            Training plan
          </Link>
          <Link to="/tests" className="flex min-h-11 items-center rounded-full border border-border px-4 text-sm text-text-secondary">
            {e.has_pacing_plan ? "Pacing plan & tests" : "Build a pacing plan"}
          </Link>
        </div>
      </Card>

      {projection.data ? <ProjectionCard p={projection.data} /> : <CardSkeleton lines={3} />}

      {o.pacing_plan?.splits && (
        <Card title="Pacing plan">
          <p className="text-sm text-text-secondary">
            Goal {fmtTime(o.pacing_plan.goal_time_s)} · {o.pacing_plan.style?.replace(/_/g, " ")}
          </p>
          <ol className="mt-2 grid gap-0.5 text-sm text-text-secondary">
            {o.pacing_plan.splits.map((s) => (
              <li key={s.split_index} className="flex justify-between">
                <span>Split {s.split_index + 1}</span>
                <span className="font-mono-nums">{fmtTime(s.target_split_s)}</span>
              </li>
            ))}
          </ol>
        </Card>
      )}

      <Card title="Test history">
        {o.tests.length === 0 ? (
          <p className="text-sm text-text-tertiary">No confirmed tests at this distance yet.</p>
        ) : (
          <ul className="grid gap-1 text-sm">
            {o.tests.map((t) => (
              <li key={`${t.kind}-${t.canonical_id ?? t.piece_id}`}>
                <Link
                  to={t.kind === "piece" ? `/tests/piece/${t.piece_id}` : `/tests/${t.canonical_id}`}
                  className="flex min-h-11 items-center justify-between rounded-md px-1 text-text-secondary hover:text-text-primary"
                >
                  <span>{t.date ? formatShortDate(t.date) : "—"}</span>
                  <span className="font-mono-nums">{fmtTime(t.duration_s)}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <EventSheet open={editing} onOpenChange={setEditing} existing={e} defaultDate={e.date} onDeleted={() => navigate("/calendar", { replace: true })} />
    </div>
  );
}
