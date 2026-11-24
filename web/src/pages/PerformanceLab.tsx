import { useState } from "react";
import { Estimate2kCard, HrAtWorkloadCard, PowerCurveCard, ProgressionCard, RecordsCard, SplitByRateCard, type Modality } from "../components/lab/LabCards";
import { PageHeader, SectionHeader } from "../components/ui/PageHeader";
import { PillNav } from "../components/ui/PillNav";
import { Segmented } from "../components/ui/Segmented";
import { addDays, todayISO } from "../lib/dates";

const RANGES = [
  { value: "90", label: "3 mo" },
  { value: "182", label: "6 mo" },
  { value: "365", label: "1 yr" },
  { value: "1095", label: "3 yr" },
] as const;
type RangeValue = (typeof RANGES)[number]["value"];

/** Session 36: investigate performance rather than read a list of metrics — records, how each standard effort has moved, and two
 * like-for-like comparisons (heart rate at the same power, split at the same rate). Every figure is the server's; the page only
 * chooses the window. */
export function PerformanceLabPage() {
  const [modality, setModality] = useState<Modality>("rowing_erg");
  const [range, setRange] = useState<RangeValue>("365");
  const to = todayISO();
  const from = addDays(to, -Number(range));
  return (
    <div className="flex flex-col gap-4 lg:gap-5">
      <PageHeader eyebrow="Training" title="Performance lab" subtitle="Records, progression and like-for-like comparisons from your own sessions." />
      <PillNav
        label="Related"
        items={[
          { to: "/tests", label: "Tests" },
          { to: "/trends", label: "Trends" },
          { to: "/trends/intelligence", label: "Training intelligence" },
          { to: "/goals", label: "Goals" },
        ]}
      />
      <div className="flex flex-wrap items-center gap-2">
        <Segmented label="Machine" size="sm" value={modality} onChange={setModality} options={[{ value: "rowing_erg", label: "Rowing erg" }, { value: "bike", label: "Bike" }]} />
        <Segmented label="Period" size="sm" value={range} onChange={setRange} options={RANGES.map((r) => ({ value: r.value, label: r.label }))} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2 lg:items-start lg:gap-5">
        <RecordsCard modality={modality} />
        <ProgressionCard modality={modality} from={from} to={to} />
      </div>

      {modality === "rowing_erg" && (
        <>
          <SectionHeader title="Like for like" description="The earlier half of the period beside the recent half, only where both have enough data." />
          <div className="grid gap-4 lg:grid-cols-2 lg:items-start lg:gap-5">
            <HrAtWorkloadCard from={from} to={to} />
            <SplitByRateCard from={from} to={to} />
          </div>
          <div className="grid gap-4 lg:grid-cols-2 lg:items-start lg:gap-5">
            <PowerCurveCard from={from} to={to} />
            <Estimate2kCard />
          </div>
        </>
      )}
      <p className="text-xs text-text-tertiary">Records are all-time; progression and the comparisons follow the period chosen above.</p>
    </div>
  );
}
