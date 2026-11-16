// Garmin's Personal API exposes no key-expiry field, so the date is a plain reminder the user enters when they connect the key
// (per-user, on the connection — see Connections → Garmin). Shared between the Connections card and GarminKeyBanner.tsx (which
// surfaces it app-wide) so the "14 days" threshold can't drift between the two.
export const GARMIN_KEY_PAGE_URL = "https://connect.garmin.com/app/settings/personalApiToken";

export function daysUntilGarminKeyExpires(iso: string | null): number | null {
  if (!iso) return null;
  const diff = new Date(iso + "T00:00:00").getTime() - Date.now();
  return Math.ceil(diff / 86_400_000);
}
