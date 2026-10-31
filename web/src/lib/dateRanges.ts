export type TrendRange = "4w" | "12w" | "season" | "all";

// "Season" has no single universal definition for rowing — picked the most recent past
// September 1st (Northern-hemisphere indoor/winter-training-block convention) rather than
// adding a backend setting for something purely a trends-view display choice.
const SEASON_START_MONTH = 8; // September, 0-indexed

export function rangeToFromTo(range: TrendRange): { from?: string; to?: string } {
  const today = new Date();
  if (range === "all") return {};
  if (range === "season") {
    const year = today.getMonth() >= SEASON_START_MONTH ? today.getFullYear() : today.getFullYear() - 1;
    return { from: `${year}-${String(SEASON_START_MONTH + 1).padStart(2, "0")}-01` };
  }
  const weeks = range === "4w" ? 4 : 12;
  const from = new Date(today);
  from.setDate(today.getDate() - weeks * 7);
  return { from: from.toISOString().slice(0, 10) };
}

export function rangeToWeeks(range: TrendRange): number {
  if (range === "4w") return 4;
  if (range === "12w") return 12;
  if (range === "season") {
    const { from } = rangeToFromTo("season");
    const days = (Date.now() - new Date(from as string).getTime()) / 86_400_000;
    return Math.min(52, Math.max(1, Math.ceil(days / 7)));
  }
  return 52; // "all" — capped at the API's max
}
