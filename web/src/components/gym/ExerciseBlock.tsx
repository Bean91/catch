import { useEffect, useMemo, useState } from "react";
import { fetchLastSetsForExercise } from "../../lib/api";
import type { LocalSet } from "../../lib/gymDb";
import type { EquipmentType, Exercise, GymStation, SetType } from "../../lib/types";
import { Card } from "../ui/Card";
import { PlateCalculatorDialog } from "./PlateCalculatorDialog";
import { Stepper } from "./Stepper";

export interface EquipmentConfig {
  equipmentType: EquipmentType;
  barWeightKg: number | null;
  pulleyMultiplier: number | null;
  gymStationId: number | null;
  bandTag: string | null;
}

const EQUIPMENT_LABELS: Record<EquipmentType, string> = {
  barbell: "Barbell",
  dumbbell: "Dumbbell",
  kettlebell: "Kettlebell",
  machine_plate: "Plate machine",
  machine_selectorized: "Selectorized machine",
  smith: "Smith machine",
  cable: "Cable",
  bodyweight: "Bodyweight",
  weighted: "Weighted",
  assisted: "Assisted",
  band: "Band",
  other: "Other",
};

// Plate-sensible load increments per equipment (task Part A.4) — not a universal physical
// constant, just a reasonable default per equipment family; the input still accepts any typed
// value for a gym with different plates/increments.
const LOAD_STEP: Record<EquipmentType, number> = {
  barbell: 2.5,
  smith: 2.5,
  dumbbell: 2,
  kettlebell: 2,
  machine_plate: 5,
  machine_selectorized: 5,
  cable: 1,
  bodyweight: 0,
  weighted: 2.5,
  assisted: 2.5,
  band: 0,
  other: 2.5,
};

const SET_TYPES: SetType[] = ["working", "warmup", "drop", "failure", "amrap"];
const BAND_TAGS = ["light", "medium", "heavy"];

function summarizeLoad(set: { load_kg?: number | null; equipment_type: EquipmentType }): string {
  if (set.equipment_type === "band") return "band";
  if (set.load_kg == null) return "—";
  return `${set.load_kg}kg`;
}

export function ExerciseBlock({
  exercise,
  stations,
  bodyweightKg,
  config,
  onConfigChange,
  loggedSets,
  onLogSet,
  onDeleteSet,
  onRemoveExercise,
}: {
  exercise: Exercise;
  stations: GymStation[];
  bodyweightKg: number | null;
  config: EquipmentConfig;
  onConfigChange: (config: EquipmentConfig) => void;
  loggedSets: LocalSet[];
  onLogSet: (input: {
    equipment_type: EquipmentType;
    load_kg: number | null;
    bar_weight_kg: number | null;
    pulley_multiplier: number | null;
    added_weight_kg: number | null;
    assistance_kg: number | null;
    band_tag: string | null;
    gym_station_id: number | null;
    reps: number;
    rir: number | null;
    set_type: SetType;
  }) => void;
  onDeleteSet: (clientId: string) => void;
  onRemoveExercise: () => void;
}) {
  const [reps, setReps] = useState(8);
  const [loadKg, setLoadKg] = useState(0);
  const [rir, setRir] = useState<number | null>(2);
  const [setType, setSetType] = useState<SetType>("working");
  const [plateCalcOpen, setPlateCalcOpen] = useState(false);
  const [lastSession, setLastSession] = useState<{ reps: number; load_kg: number | null; effective_load_kg: number | null }[]>([]);

  useEffect(() => {
    let cancelled = false;
    fetchLastSetsForExercise(exercise.id).then((sets) => {
      if (!cancelled) setLastSession(sets.map((s) => ({ reps: s.reps, load_kg: s.load_kg ?? null, effective_load_kg: s.effective_load_kg })));
    });
    return () => {
      cancelled = true;
    };
  }, [exercise.id]);

  const stationsForEquipment = stations.filter((s) => s.equipment_type === config.equipmentType);
  const step = LOAD_STEP[config.equipmentType];

  const lastLoggedThisSession = loggedSets[loggedSets.length - 1];

  function sameAsLast() {
    if (lastLoggedThisSession) {
      setReps(lastLoggedThisSession.reps);
      setLoadKg(lastLoggedThisSession.load_kg ?? 0);
      setRir(lastLoggedThisSession.rir ?? null);
    } else if (lastSession.length > 0) {
      const l = lastSession[0];
      setReps(l.reps);
      setLoadKg(l.load_kg ?? 0);
    }
  }

  function submit() {
    const needsBodyweight = config.equipmentType === "bodyweight" || config.equipmentType === "assisted";
    onLogSet({
      equipment_type: config.equipmentType,
      load_kg: config.equipmentType === "bodyweight" ? null : config.equipmentType === "band" ? null : loadKg,
      bar_weight_kg: config.equipmentType === "barbell" || config.equipmentType === "smith" ? config.barWeightKg : null,
      pulley_multiplier: config.equipmentType === "cable" ? config.pulleyMultiplier : null,
      added_weight_kg: config.equipmentType === "weighted" ? loadKg : null,
      assistance_kg: config.equipmentType === "assisted" ? loadKg : null,
      band_tag: config.equipmentType === "band" ? config.bandTag : null,
      gym_station_id: config.gymStationId,
      reps,
      rir,
      set_type: setType,
    });
    void needsBodyweight;
  }

  const lastSessionLine = useMemo(() => {
    if (lastSession.length === 0) return null;
    return lastSession.map((s) => `${s.load_kg ?? "—"}kg×${s.reps}`).join(", ");
  }, [lastSession]);

  return (
    <Card className="flex flex-col gap-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-sm font-semibold text-text-primary">{exercise.name}</div>
          {lastSessionLine && <div className="text-xs text-text-tertiary">Last time: {lastSessionLine}</div>}
        </div>
        <button type="button" onClick={onRemoveExercise} aria-label={`Remove ${exercise.name}`} className="min-h-11 min-w-11 text-xs text-text-tertiary hover:text-band-red-text">
          Remove
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <select
          value={config.equipmentType}
          onChange={(e) => onConfigChange({ ...config, equipmentType: e.target.value as EquipmentType })}
          className="min-h-11 rounded-md border border-border bg-bg px-2 text-sm text-text-primary"
        >
          {Object.entries(EQUIPMENT_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>

        {(config.equipmentType === "barbell" || config.equipmentType === "smith") && (
          <>
            <input
              type="number"
              inputMode="decimal"
              value={config.barWeightKg ?? ""}
              placeholder={config.equipmentType === "barbell" ? "20 (bar kg)" : "Bar kg — unknown"}
              onChange={(e) => onConfigChange({ ...config, barWeightKg: e.target.value === "" ? null : Number(e.target.value) })}
              className="min-h-11 w-32 rounded-md border border-border bg-bg px-2 text-sm text-text-primary"
            />
            <button type="button" onClick={() => setPlateCalcOpen(true)} className="min-h-11 rounded-md border border-border px-3 text-xs font-medium text-text-secondary">
              Plate calc
            </button>
          </>
        )}

        {config.equipmentType === "cable" && (
          <>
            {stationsForEquipment.length > 0 && (
              <select
                value={config.gymStationId ?? ""}
                onChange={(e) => onConfigChange({ ...config, gymStationId: e.target.value ? Number(e.target.value) : null })}
                className="min-h-11 rounded-md border border-border bg-bg px-2 text-sm text-text-primary"
              >
                <option value="">No saved station</option>
                {stationsForEquipment.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            )}
            <select
              value={config.pulleyMultiplier ?? 1}
              onChange={(e) => onConfigChange({ ...config, pulleyMultiplier: Number(e.target.value) })}
              className="min-h-11 rounded-md border border-border bg-bg px-2 text-sm text-text-primary"
            >
              <option value={1}>1:1 pulley</option>
              <option value={0.5}>2:1 pulley</option>
              <option value={0.25}>4:1 pulley</option>
            </select>
          </>
        )}

        {config.equipmentType === "band" && (
          <select
            value={config.bandTag ?? "medium"}
            onChange={(e) => onConfigChange({ ...config, bandTag: e.target.value })}
            className="min-h-11 rounded-md border border-border bg-bg px-2 text-sm text-text-primary"
          >
            {BAND_TAGS.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        )}

        {(config.equipmentType === "bodyweight" || config.equipmentType === "weighted" || config.equipmentType === "assisted") &&
          bodyweightKg == null && <span className="text-xs text-band-yellow">No bodyweight on file — log one in Body for an accurate load.</span>}
      </div>

      {loggedSets.length > 0 && (
        <ul className="flex flex-col gap-1">
          {loggedSets.map((s, i) => (
            <li key={s.client_id} className="flex items-center justify-between rounded-md bg-surface-2 px-3 py-2 text-sm">
              <span className="text-text-secondary">
                Set {i + 1} · {s.reps} reps{s.set_type !== "working" ? ` (${s.set_type})` : ""}
              </span>
              <span className="flex items-center gap-2 font-mono-nums text-text-primary">
                {s.effectiveLoadKg != null ? `${Math.round(s.effectiveLoadKg * 10) / 10}kg` : summarizeLoad(s)}
                {s.isRepPr && <span className="rounded-full bg-accent/20 px-2 py-0.5 text-xs font-semibold text-accent">PR</span>}
                <button type="button" onClick={() => onDeleteSet(s.client_id)} aria-label="Delete set" className="min-h-11 min-w-11 text-text-tertiary hover:text-band-red-text">
                  ×
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stepper label="Reps" value={reps} onChange={setReps} step={1} min={0} />
        {config.equipmentType !== "bodyweight" && config.equipmentType !== "band" && (
          <Stepper
            label={config.equipmentType === "weighted" ? "Added kg" : config.equipmentType === "assisted" ? "Assist kg" : config.equipmentType === "cable" ? "Stack #" : "Load kg"}
            value={loadKg}
            onChange={setLoadKg}
            step={step}
          />
        )}
        <label className="flex flex-col gap-1">
          <span className="text-xs text-text-tertiary">Set type</span>
          <select value={setType} onChange={(e) => setSetType(e.target.value as SetType)} className="min-h-11 rounded-md border border-border bg-bg px-2 text-sm text-text-primary">
            {SET_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-text-tertiary">RIR</span>
          <input
            type="number"
            inputMode="numeric"
            value={rir ?? ""}
            onChange={(e) => setRir(e.target.value === "" ? null : Number(e.target.value))}
            className="min-h-11 rounded-md border border-border bg-bg px-2 text-center font-mono-nums text-sm text-text-primary"
          />
        </label>
      </div>

      <div className="flex gap-2">
        <button
          type="button"
          onClick={sameAsLast}
          disabled={!lastLoggedThisSession && lastSession.length === 0}
          className="min-h-11 flex-1 rounded-md border border-border text-sm font-medium text-text-secondary disabled:opacity-40"
        >
          Same as last set
        </button>
        <button type="button" onClick={submit} className="min-h-11 flex-[2] rounded-md bg-accent text-sm font-semibold text-bg">
          Log set
        </button>
      </div>

      <PlateCalculatorDialog open={plateCalcOpen} onOpenChange={setPlateCalcOpen} initialPlateLoadKg={loadKg} />
    </Card>
  );
}
