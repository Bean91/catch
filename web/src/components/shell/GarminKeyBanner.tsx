import { useQuery } from "@tanstack/react-query";
import { fetchSettings } from "../../lib/api";
import { daysUntilGarminKeyExpires, GARMIN_KEY_PAGE_URL } from "../../lib/garminKey";
import { useAuth } from "../../lib/auth";

export function GarminKeyBanner() {
  const { status } = useAuth();
  const { data } = useQuery({
    queryKey: ["settings"],
    queryFn: fetchSettings,
    enabled: status === "authed",
    staleTime: 60 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const daysLeft = daysUntilGarminKeyExpires(data?.garmin_key_expires_on ?? null);
  if (daysLeft === null || daysLeft > 14) return null;

  const message =
    daysLeft <= 0
      ? "Your Garmin key has expired — Garmin syncs will fail until you create a new one."
      : `Your Garmin key expires in ${daysLeft} day${daysLeft === 1 ? "" : "s"} — create a new one before syncs start failing.`;

  return (
    <div className="border-b border-border bg-band-red/10 px-4 py-2 text-center text-sm text-band-red-text sm:px-6 lg:px-8">
      {message}{" "}
      <a href={GARMIN_KEY_PAGE_URL} target="_blank" rel="noreferrer" className="font-semibold underline underline-offset-2">
        Create a new key
      </a>
    </div>
  );
}
