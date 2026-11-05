// A schematic, not anatomical, front/back body map (task Part C.3) — simple rounded shapes
// per muscle group, shaded by load the same way zoneColors.ts ramps training zones: one
// accent hue, lightest at low load, never a second hue (DESIGN.md's "no other component
// introduces a new hue" rule). Each region is front- or back-only based on which side it's
// actually visible on, so every one of the 17 muscles in catch/seed/exercises.json's
// vocabulary gets exactly one home, never both.
const FRONT_MUSCLES = ["neck", "shoulders", "chest", "biceps", "forearms", "abdominals", "quadriceps", "adductors", "abductors"] as const;
const BACK_MUSCLES = ["traps", "lats", "middle back", "lower back", "glutes", "hamstrings", "calves", "triceps"] as const;

function loadColor(value: number, max: number): string {
  if (max <= 0 || value <= 0) return "var(--surface-2)";
  const opacity = 0.15 + 0.85 * Math.min(1, value / max);
  return `color-mix(in oklab, var(--accent) ${Math.round(opacity * 100)}%, var(--surface-2))`;
}

interface Region {
  muscle: string;
  shape: "rect" | "ellipse";
  x: number;
  y: number;
  w: number;
  h: number;
  rx?: number;
}

const FRONT_REGIONS: Region[] = [
  { muscle: "neck", shape: "rect", x: 44, y: 8, w: 12, h: 10, rx: 3 },
  { muscle: "shoulders", shape: "ellipse", x: 25, y: 20, w: 14, h: 10 },
  { muscle: "shoulders", shape: "ellipse", x: 75, y: 20, w: 14, h: 10 },
  { muscle: "chest", shape: "rect", x: 32, y: 24, w: 36, h: 20, rx: 6 },
  { muscle: "biceps", shape: "rect", x: 18, y: 32, w: 10, h: 22, rx: 4 },
  { muscle: "biceps", shape: "rect", x: 72, y: 32, w: 10, h: 22, rx: 4 },
  { muscle: "forearms", shape: "rect", x: 16, y: 56, w: 9, h: 20, rx: 4 },
  { muscle: "forearms", shape: "rect", x: 75, y: 56, w: 9, h: 20, rx: 4 },
  { muscle: "abdominals", shape: "rect", x: 36, y: 46, w: 28, h: 22, rx: 5 },
  { muscle: "adductors", shape: "rect", x: 44, y: 70, w: 12, h: 14, rx: 4 },
  { muscle: "abductors", shape: "rect", x: 32, y: 70, w: 10, h: 18, rx: 4 },
  { muscle: "abductors", shape: "rect", x: 58, y: 70, w: 10, h: 18, rx: 4 },
  { muscle: "quadriceps", shape: "rect", x: 33, y: 86, w: 15, h: 34, rx: 6 },
  { muscle: "quadriceps", shape: "rect", x: 52, y: 86, w: 15, h: 34, rx: 6 },
];

const BACK_REGIONS: Region[] = [
  { muscle: "traps", shape: "rect", x: 36, y: 16, w: 28, h: 16, rx: 6 },
  { muscle: "lats", shape: "rect", x: 26, y: 30, w: 16, h: 26, rx: 6 },
  { muscle: "lats", shape: "rect", x: 58, y: 30, w: 16, h: 26, rx: 6 },
  { muscle: "middle back", shape: "rect", x: 40, y: 32, w: 20, h: 18, rx: 5 },
  { muscle: "triceps", shape: "rect", x: 18, y: 32, w: 10, h: 22, rx: 4 },
  { muscle: "triceps", shape: "rect", x: 72, y: 32, w: 10, h: 22, rx: 4 },
  { muscle: "lower back", shape: "rect", x: 38, y: 50, w: 24, h: 18, rx: 5 },
  { muscle: "glutes", shape: "rect", x: 33, y: 68, w: 34, h: 16, rx: 7 },
  { muscle: "hamstrings", shape: "rect", x: 33, y: 86, w: 15, h: 28, rx: 6 },
  { muscle: "hamstrings", shape: "rect", x: 52, y: 86, w: 15, h: 28, rx: 6 },
  { muscle: "calves", shape: "rect", x: 33, y: 116, w: 15, h: 20, rx: 5 },
  { muscle: "calves", shape: "rect", x: 52, y: 116, w: 15, h: 20, rx: 5 },
];

function Figure({ regions, byMuscle, max }: { regions: Region[]; byMuscle: Record<string, number>; max: number }) {
  return (
    <svg viewBox="0 0 100 140" className="h-full w-full" role="img" aria-hidden>
      <circle cx={50} cy={6} r={6} fill="var(--surface-2)" stroke="var(--border)" strokeWidth={0.6} />
      {regions.map((r, i) => {
        const value = byMuscle[r.muscle] ?? 0;
        const fill = loadColor(value, max);
        return r.shape === "rect" ? (
          <rect key={i} x={r.x} y={r.y} width={r.w} height={r.h} rx={r.rx ?? 4} fill={fill} stroke="var(--border)" strokeWidth={0.6}>
            <title>{`${r.muscle}: ${Math.round(value)} AU`}</title>
          </rect>
        ) : (
          <ellipse key={i} cx={r.x} cy={r.y} rx={r.w / 2} ry={r.h / 2} fill={fill} stroke="var(--border)" strokeWidth={0.6}>
            <title>{`${r.muscle}: ${Math.round(value)} AU`}</title>
          </ellipse>
        );
      })}
    </svg>
  );
}

export function MuscleBodyMap({ byMuscle }: { byMuscle: Record<string, number> }) {
  const max = Math.max(1, ...Object.values(byMuscle));
  return (
    <div className="flex gap-4">
      <div className="flex flex-1 flex-col items-center gap-1">
        <Figure regions={FRONT_REGIONS} byMuscle={byMuscle} max={max} />
        <span className="text-xs text-text-tertiary">Front</span>
      </div>
      <div className="flex flex-1 flex-col items-center gap-1">
        <Figure regions={BACK_REGIONS} byMuscle={byMuscle} max={max} />
        <span className="text-xs text-text-tertiary">Back</span>
      </div>
    </div>
  );
}

export { FRONT_MUSCLES, BACK_MUSCLES };
