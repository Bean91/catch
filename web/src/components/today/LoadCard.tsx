import type { Load } from "../../lib/types";
import { bandLabel } from "../../lib/format";
import { BandBadge } from "../ui/Badge";
import { Card } from "../ui/Card";
import { EmptyState } from "../ui/EmptyState";
import { InfoTip } from "../ui/InfoTip";

export function LoadCard({ load, rowingLoad }: { load: Load | null; rowingLoad?: Load | null }) {
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
    <Card className="h-full" title="Training load" action={<BandBadge band={load.band} label={bandLabel(load.band)} />}>
      <div className="flex items-baseline gap-2">
        <span className="font-mono-nums text-[2rem] font-semibold leading-none tracking-tight text-text-primary">{load.value.toFixed(2)}</span>
        <span className="text-sm text-text-tertiary">acute : chronic</span>
        <InfoTip label="acute : chronic load">
          The last 7 days' training load divided by your 42-day average. Around 0.8–1.3 means this week is in line with what you're used to;
          well above it means load is rising faster than you've adapted to.
        </InfoTip>
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
        <p className="mt-3 rounded-md border border-band-red/30 bg-band-red/10 px-3 py-2 text-xs text-band-red-text">
          Acute:chronic ratio is in the high-risk band — add load cautiously.
        </p>
      )}
      {rowingLoad?.value != null && (
        <div className="mt-3 flex items-center justify-between border-t border-border pt-3 text-sm">
          <span className="text-text-tertiary">Rowing only</span>
          <span className="font-mono-nums text-text-primary">
            {rowingLoad.value.toFixed(2)} <BandBadge band={rowingLoad.band} label={bandLabel(rowingLoad.band)} />
          </span>
        </div>
      )}
    </Card>
  );
}
