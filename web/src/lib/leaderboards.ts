import type { LbBoardContext, Verification } from "./types";

// Labels and tones only. The browser holds no ranking, eligibility or age maths: the server returns every rank, label and total.

export const VERIFICATION_GLYPH: Record<Verification, string> = { verified: "✓", provider_linked: "◐", unverified: "○" };
export const VERIFICATION_LABEL: Record<Verification, string> = { verified: "Verified", provider_linked: "Provider-linked", unverified: "Unverified" };

export function verificationTone(v: Verification): string {
  return v === "verified" ? "border-band-green/40 text-band-green" : "border-border text-text-secondary";
}

/** One plain sentence on what a state means — shown wherever the badge is explained, never implying more than it can. */
export const VERIFICATION_MEANING: Record<Verification, string> = {
  verified:
    "Fetched through your own Concept2 account and flagged verified by Concept2. Catch can authenticate where this result came from; it does not confirm who rowed it or the conditions.",
  provider_linked: "From a source you connected, but not every verified condition is met (for example Concept2 hasn't flagged it verified).",
  unverified: "Typed or photographed by you. Catch has no way to authenticate it.",
};

export const REPORT_REASONS: { value: string; label: string }[] = [
  { value: "not_a_real_result", label: "This doesn't look like a real result" },
  { value: "wrong_category", label: "It's in the wrong category" },
  { value: "inappropriate_name_or_note", label: "The name or note is inappropriate" },
  { value: "other", label: "Something else" },
];

export const PRECISION_LABEL: Record<string, string> = {
  none: "No date",
  year: "Year only",
  month: "Month and year",
  day: "Exact date",
};

export const STATUS_LABEL: Record<string, string> = {
  active: "Public",
  hidden: "Hidden for review",
  removed: "Removed",
  withdrawn: "Taken down",
};

export const ACTOR_LABEL: Record<string, string> = { user: "You", moderator: "A moderator", system: "Catch (automatic)" };

/** The "what am I looking at" line above a board — spells out every filter that affects the ranking. */
export function contextLine(c: LbBoardContext): string {
  const parts = [c.label, c.verification === "verified" ? "Verified results only" : "Verified ranked first, others listed separately"];
  if (c.age) parts.push(`Age ${c.age}`);
  if (c.weight === "lightweight") parts.push("Lightweight");
  if (c.club) parts.push("Club");
  parts.push(`${c.ranked_athletes} ${c.ranked_athletes === 1 ? "athlete" : "athletes"}`);
  return parts.join(" · ");
}
