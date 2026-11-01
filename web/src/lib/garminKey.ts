// Garmin's personal-API-key swagger spec exposes no key-expiry field (see
// catch/analytics/defaults.py), so there's nothing to sync from Garmin — the expiry date is
// a plain user-editable reminder stored in Settings (garmin_key_expires_on), not read from
// any API response. Shared between Settings.tsx (where it's set) and GarminKeyBanner.tsx
// (which surfaces it app-wide) so the "14 days" threshold can't drift between the two.
export const GARMIN_KEY_PAGE_URL = "https://developer.garmin.com/gc-developer-program/personal";

export function daysUntilGarminKeyExpires(iso: string | null): number | null {
  if (!iso) return null;
  const diff = new Date(iso + "T00:00:00").getTime() - Date.now();
  return Math.ceil(diff / 86_400_000);
}
