import { EmptyState } from "../ui/EmptyState";

interface Entry {
  text: string;
  evidence: { label: string; value: unknown; source: string }[];
}

/** Two lists using only --band-green/--band-yellow/--accent — the one-hue/band-color rule
 * DESIGN.md already enforces everywhere else; no new hue is introduced for "strength" vs.
 * "investigate" since those already have a natural home in the existing band palette. */
export function StrengthsWeaknessesCard({ strengths, weaknesses }: { strengths: Entry[]; weaknesses: Entry[] }) {
  if (strengths.length === 0 && weaknesses.length === 0) {
    return <EmptyState message="Not enough performance history yet to call out strengths or areas to investigate." />;
  }
  return (
    <div className="flex flex-col gap-4">
      {strengths.length > 0 && (
        <div>
          <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-[var(--band-green)]">Strengths</p>
          <ul className="flex flex-col gap-1">
            {strengths.map((s, i) => (
              <li key={i} className="text-sm text-text-primary">
                {s.text}
              </li>
            ))}
          </ul>
        </div>
      )}
      {weaknesses.length > 0 && (
        <div>
          <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-[var(--band-yellow)]">Areas to investigate</p>
          <ul className="flex flex-col gap-1">
            {weaknesses.map((w, i) => (
              <li key={i} className="text-sm text-text-primary">
                {w.text}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
