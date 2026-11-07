import { Card } from "../ui/Card";
import type { TrainingProfile } from "../../lib/types";

const PHASE_LABELS: Record<string, string> = { base: "Base", build: "Build", taper: "Taper" };

/** Confidence is rendered as plain text, not a colored BandBadge — it's a trust axis (how
 * much data backs this), not a status judgment, so giving it a traffic-light color would
 * misread as "good/bad" the way a recovery or overload band legitimately is. See DESIGN.md's
 * note on this (session 18). */
export function TrainingProfileCard({ profile }: { profile: TrainingProfile }) {
  const phaseLabel = profile.phase.value ? (PHASE_LABELS[profile.phase.value] ?? profile.phase.value) : "Not yet known";
  return (
    <Card title="Training profile">
      <p className="text-lg font-semibold text-text-primary">
        {phaseLabel}
        {profile.phase.inferred && profile.phase.value && <span className="ml-2 text-xs font-normal text-text-tertiary">(inferred)</span>}
      </p>
      <p className="mt-1 text-sm text-text-secondary">{profile.phase.explanation}</p>
      <p className="mt-3 text-xs text-text-tertiary">Confidence: {profile.confidence.replace("_", " ")}</p>
      {profile.consistency_summary && <p className="mt-1 text-xs text-text-tertiary">{profile.consistency_summary.explanation}</p>}
      {(profile.nutrition.logged || profile.daily_activity.logged || profile.recent_note) && (
        <div className="mt-3 flex flex-col gap-1 border-t border-border pt-3 text-xs text-text-tertiary">
          {profile.nutrition.logged && (
            <p>
              Nutrition: {profile.nutrition.logged_days} day(s) logged this week{profile.nutrition.under_fuelling ? ", under-fuelling flagged" : ""}.
            </p>
          )}
          {profile.daily_activity.logged && (
            <p>
              Today's activity: {profile.daily_activity.steps.toLocaleString()} steps
              {profile.daily_activity.active_kcal != null && `, ${profile.daily_activity.active_kcal} active kcal`}.
            </p>
          )}
          {profile.recent_note && <p>Recent note: "{profile.recent_note}"</p>}
        </div>
      )}
    </Card>
  );
}
