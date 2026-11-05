import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ExerciseBlock, type EquipmentConfig } from "../components/gym/ExerciseBlock";
import { ExercisePicker } from "../components/gym/ExercisePicker";
import { RestTimer, DEFAULT_REST_S } from "../components/gym/RestTimer";
import { SyncStatusBadge } from "../components/gym/SyncStatusBadge";
import { Card } from "../components/ui/Card";
import { CardSkeleton } from "../components/ui/Skeleton";
import { fetchBody, fetchExercises, fetchGyms, fetchRepeatLastWorkout, fetchStations, fetchTemplates } from "../lib/api";
import * as gymDb from "../lib/gymDb";
import { logSetLocally, deleteSetLocally } from "../lib/gymSync";
import { useGymSync } from "../lib/useGymSync";
import type { EquipmentType, Exercise, GymStation, SetType } from "../lib/types";

function newSessionId(): string {
  return crypto.randomUUID();
}

function defaultConfig(exercise: Exercise): EquipmentConfig {
  return {
    equipmentType: exercise.default_equipment_type,
    barWeightKg: exercise.default_equipment_type === "barbell" ? 20 : null,
    pulleyMultiplier: 1,
    gymStationId: null,
    bandTag: "medium",
  };
}

export function GymPage() {
  const syncStatus = useGymSync();
  const queryClient = useQueryClient();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [checkedResume, setCheckedResume] = useState(false);
  const [sessionExercises, setSessionExercises] = useState<{ exercise: Exercise; config: EquipmentConfig }[]>([]);
  const [localSets, setLocalSets] = useState<gymDb.LocalSet[]>([]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [restEndAt, setRestEndAt] = useState<number | null>(null);

  const exercisesQuery = useQuery({ queryKey: ["gym-exercises"], queryFn: () => fetchExercises() });
  const gymsQuery = useQuery({ queryKey: ["gym-gyms"], queryFn: fetchGyms });
  const templatesQuery = useQuery({ queryKey: ["gym-templates"], queryFn: fetchTemplates });
  const bodyQuery = useQuery({ queryKey: ["gym-body"], queryFn: () => fetchBody() });
  const stationsQuery = useQuery({
    queryKey: ["gym-stations", gymsQuery.data?.map((g) => g.id)],
    queryFn: async () => {
      const gyms = gymsQuery.data ?? [];
      const all: GymStation[] = [];
      for (const g of gyms) all.push(...(await fetchStations(g.id)));
      return all;
    },
    enabled: (gymsQuery.data?.length ?? 0) > 0,
  });

  const bodyweightKg = useMemo(() => {
    const readings = bodyQuery.data ?? [];
    const withWeight = [...readings].reverse().find((r) => r.weight != null);
    return withWeight?.weight ?? null;
  }, [bodyQuery.data]);

  // Resume today's session on first load, offline-first — IndexedDB, not a network call.
  useEffect(() => {
    gymDb.getTodaysSessionId().then((id) => {
      setSessionId(id);
      setCheckedResume(true);
    });
  }, []);

  useEffect(() => {
    if (!sessionId) {
      setLocalSets([]);
      return;
    }
    gymDb.getSetsForSession(sessionId).then((sets) => {
      setLocalSets(sets);
      if (exercisesQuery.data) {
        setSessionExercises((prev) => {
          const existingIds = new Set(prev.map((e) => e.exercise.id));
          const toAdd = [...new Set(sets.map((s) => s.exercise_id))].filter((id) => !existingIds.has(id));
          const added = toAdd
            .map((id) => exercisesQuery.data!.find((e) => e.id === id))
            .filter((e): e is Exercise => !!e)
            .map((exercise) => ({ exercise, config: defaultConfig(exercise) }));
          return [...prev, ...added];
        });
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, exercisesQuery.data]);

  function startSession() {
    setSessionId(newSessionId());
    setSessionExercises([]);
  }

  async function startFromPlan(items: { exercise_id: number; equipment_type: EquipmentType; gym_station_id: number | null }[]) {
    const exercises = exercisesQuery.data ?? [];
    const picked = items
      .map((item) => {
        const exercise = exercises.find((e) => e.id === item.exercise_id);
        if (!exercise) return null;
        return { exercise, config: { ...defaultConfig(exercise), equipmentType: item.equipment_type, gymStationId: item.gym_station_id } };
      })
      .filter((x): x is { exercise: Exercise; config: EquipmentConfig } => !!x);
    setSessionId(newSessionId());
    setSessionExercises(picked);
  }

  function addExercise(exercise: Exercise) {
    setSessionExercises((prev) => (prev.some((e) => e.exercise.id === exercise.id) ? prev : [...prev, { exercise, config: defaultConfig(exercise) }]));
    setPickerOpen(false);
  }

  function removeExercise(exerciseId: number) {
    setSessionExercises((prev) => prev.filter((e) => e.exercise.id !== exerciseId));
  }

  function updateConfig(exerciseId: number, config: EquipmentConfig) {
    setSessionExercises((prev) => prev.map((e) => (e.exercise.id === exerciseId ? { ...e, config } : e)));
  }

  async function logSet(
    exercise: Exercise,
    config: EquipmentConfig,
    input: {
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
    },
  ) {
    const sid = sessionId ?? newSessionId();
    if (!sessionId) setSessionId(sid);
    const seq = localSets.length;
    const stationConfig = (stationsQuery.data ?? []).find((s) => s.id === config.gymStationId)?.config ?? null;
    const local = await logSetLocally(
      sid,
      {
        client_id: crypto.randomUUID(),
        exercise_id: exercise.id,
        gym_station_id: input.gym_station_id,
        seq,
        set_type: input.set_type,
        reps: input.reps,
        rir: input.rir,
        equipment_type: input.equipment_type,
        load_kg: input.load_kg,
        bar_weight_kg: input.bar_weight_kg,
        pulley_multiplier: input.pulley_multiplier,
        added_weight_kg: input.added_weight_kg,
        assistance_kg: input.assistance_kg,
        band_tag: input.band_tag,
      },
      { exerciseName: exercise.name, bodyweightKg, stationConfig },
    );
    setLocalSets((prev) => [...prev, local]);
    if (input.set_type !== "warmup") setRestEndAt(Date.now() + DEFAULT_REST_S * 1000);
    void queryClient;
  }

  async function removeSet(clientId: string) {
    await deleteSetLocally(clientId);
    setLocalSets((prev) => prev.filter((s) => s.client_id !== clientId));
  }

  if (!checkedResume || exercisesQuery.isLoading) {
    return (
      <div className="flex flex-col gap-4">
        <CardSkeleton lines={2} />
        <CardSkeleton lines={4} />
      </div>
    );
  }

  const inSession = sessionId != null;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-text-primary">Gym</h1>
        <SyncStatusBadge status={syncStatus} />
      </div>

      {!inSession ? (
        <>
          <Card title="Start a workout">
            <div className="flex flex-col gap-2">
              <button type="button" onClick={startSession} className="min-h-11 rounded-md bg-accent text-sm font-semibold text-bg">
                Start blank workout
              </button>
              <button
                type="button"
                onClick={async () => {
                  const plan = await fetchRepeatLastWorkout();
                  if (plan.length > 0) await startFromPlan(plan);
                }}
                className="min-h-11 rounded-md border border-border text-sm font-medium text-text-primary"
              >
                Repeat last workout
              </button>
            </div>
          </Card>
          {templatesQuery.data && templatesQuery.data.length > 0 && (
            <Card title="Templates">
              <ul className="flex flex-col gap-2">
                {templatesQuery.data.map((t) => (
                  <li key={t.id}>
                    <button
                      type="button"
                      onClick={() =>
                        startFromPlan(
                          t.items.map((i) => ({
                            exercise_id: i.exercise_id,
                            equipment_type: exercisesQuery.data?.find((e) => e.id === i.exercise_id)?.default_equipment_type ?? "other",
                            gym_station_id: i.gym_station_id ?? null,
                          })),
                        )
                      }
                      className="flex min-h-11 w-full items-center justify-between rounded-md px-2.5 text-left text-sm text-text-primary transition-colors hover:bg-surface-2"
                    >
                      <span>{t.name}</span>
                      <span className="text-xs text-text-tertiary">{t.items.length} exercises</span>
                    </button>
                  </li>
                ))}
              </ul>
            </Card>
          )}
          <Card title="Muscle readiness">
            <p className="text-sm text-text-secondary">See which muscle groups are still loaded from recent sessions.</p>
            <Link to="/gym/readiness" className="mt-2 inline-block text-sm font-medium text-accent">
              View readiness →
            </Link>
          </Card>
        </>
      ) : (
        <>
          <RestTimer endAt={restEndAt} onDismiss={() => setRestEndAt(null)} onExtend={(s) => setRestEndAt((prev) => (prev ?? Date.now()) + s * 1000)} />

          {sessionExercises.map(({ exercise, config }) => (
            <ExerciseBlock
              key={exercise.id}
              exercise={exercise}
              stations={stationsQuery.data ?? []}
              bodyweightKg={bodyweightKg}
              config={config}
              onConfigChange={(c) => updateConfig(exercise.id, c)}
              loggedSets={localSets.filter((s) => s.exercise_id === exercise.id)}
              onLogSet={(input) => logSet(exercise, config, input)}
              onDeleteSet={removeSet}
              onRemoveExercise={() => removeExercise(exercise.id)}
            />
          ))}

          <button
            type="button"
            onClick={() => setPickerOpen(true)}
            className="min-h-11 rounded-md border border-dashed border-border text-sm font-medium text-text-secondary transition-colors hover:border-accent hover:text-accent"
          >
            + Add exercise
          </button>

          <button type="button" onClick={() => setSessionId(null)} className="min-h-11 rounded-md border border-border text-sm font-medium text-text-primary">
            Done for now
          </button>

          <ExercisePicker
            open={pickerOpen}
            onOpenChange={setPickerOpen}
            exercises={exercisesQuery.data ?? []}
            onPick={addExercise}
            onCreated={(exercise) => {
              queryClient.setQueryData<Exercise[]>(["gym-exercises"], (prev) => [...(prev ?? []), exercise]);
              addExercise(exercise);
            }}
          />
        </>
      )}
    </div>
  );
}
