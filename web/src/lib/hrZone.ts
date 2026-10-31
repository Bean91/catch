// Small TS port of catch/analytics/zones.py's zone_for_hr / _zone_for_pct — duplicated
// intentionally so the erg chart can color thousands of stroke points client-side without a
// round trip per point. Keep in sync by hand if the zone thresholds/order ever change.
const ZONE_ORDER = ["UT2", "UT1", "AT", "TR", "AN"] as const;

export function hrZoneForHr(hr: number | null, maxHr: number | null, hrPct: Record<string, number>): string | null {
  if (hr == null || !maxHr) return null;
  const pct = (hr / maxHr) * 100;
  let zone: string = ZONE_ORDER[0];
  for (const name of ZONE_ORDER) {
    if (pct >= hrPct[name]) zone = name;
  }
  return zone;
}
