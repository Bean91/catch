import { VERIFICATION_GLYPH, VERIFICATION_LABEL, verificationTone } from "../../lib/leaderboards";
import type { Verification } from "../../lib/types";

/** A glyph and a word, never colour alone. */
export function VerificationBadge({ state }: { state: Verification }) {
  return (
    <span
      data-testid={`verification-${state}`}
      className={`inline-flex items-center gap-1 rounded-full border bg-surface-2 px-2 py-0.5 text-xs font-medium ${verificationTone(state)}`}
    >
      <span aria-hidden="true">{VERIFICATION_GLYPH[state]}</span>
      {VERIFICATION_LABEL[state]}
    </span>
  );
}
