import type { Load } from "../../lib/types";
import { bandLabel } from "../../lib/format";
import { BandBadge } from "../ui/Badge";
import { Card } from "../ui/Card";
import { EmptyState } from "../ui/EmptyState";

export function LoadCard({ load }: { load: Load | null }) {
  if (!load || load.value == null) {
    return (
      <Card title="Training load">
        <EmptyState message="Not enough history yet to compute acute:chronic load." />
      </Card>
    );
  }

  const [component] = load.components;
  const highRisk = load.band === "high_risk";

  return (
    <Card title="Training load" action={<BandBadge band={load.band} label={bandLabel(load.band)} />}>
      <div className="flex items-baseline gap-2">
        <span className="font-mono-nums text-3xl font-semibold text-text-primary">{load.value.toFixed(2)}</span>
        <span className="text-sm text-text-tertiary">acute : chronic</span>
      </div>
      {component && (
        <dl className="mt-3 grid grid-cols-3 gap-2 text-sm">
          <div>
            <dt className="text-xs text-text-tertiary">Acute (7d)</dt>
            <dd className="font-mono-nums text-text-primary">{component.acute_7d.toFixed(0)}</dd>
          </div>
          <div>
            <dt className="text-xs text-text-tertiary">Chronic (42d)</dt>
            <dd className="font-mono-nums text-text-primary">{component.chronic_42d.toFixed(0)}</dd>
          </div>
          <div>
            <dt className="text-xs text-text-tertiary">Form</dt>
            <dd className="font-mono-nums text-text-primary">
              {component.form > 0 ? "+" : ""}
              {component.form.toFixed(0)}
            </dd>
          </div>
        </dl>
      )}
      {highRisk && (
        <p className="mt-3 rounded-md border border-band-red/30 bg-band-red/10 px-3 py-2 text-xs text-band-red">
          Acute:chronic ratio is in the high-risk band — add load cautiously.
        </p>
      )}
    </Card>
  );
}
