import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { fetchMe, reportDeviceZone } from "./api";
import { deviceZone, setActiveZone } from "./localTime";

const REPORT_KEY = "catch:zone-report";
const REPORT_EVERY_MS = 60 * 60 * 1000;

function lastReport(): { zone: string; at: number } | null {
  try {
    const raw = window.localStorage.getItem(REPORT_KEY);
    return raw ? (JSON.parse(raw) as { zone: string; at: number }) : null;
  } catch {
    return null;
  }
}

function remember(zone: string): void {
  try {
    window.localStorage.setItem(REPORT_KEY, JSON.stringify({ zone, at: Date.now() }));
  } catch {
    // storage blocked: we just report again next time
  }
}

/** Session 32 (docs/time.md): runs once inside the signed-in app.
 * - Adopts the account's current zone from /api/me, so every "today" and every time shown is the athlete's, not this device's.
 * - Tells the server which zone this phone/computer is in when the app opens or comes back to the foreground (at most hourly unless
 *   the zone changed). That is how "today" follows a traveller with nothing to do; the server ignores a report that contradicts a
 *   watch abroad, and does nothing when the athlete has switched following off.
 * - Sends a brand-new public account to setup once, from the landing page only — every other page stays reachable. */
export function useAccountTime(): void {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const me = useQuery({ queryKey: ["me"], queryFn: fetchMe, staleTime: 5 * 60_000, retry: false });

  useEffect(() => {
    if (me.data) setActiveZone(me.data.current_zone);
  }, [me.data]);

  useEffect(() => {
    if (me.data?.onboarding.show && pathname === "/") navigate("/welcome", { replace: true });
  }, [me.data, pathname, navigate]);

  useEffect(() => {
    const report = () => {
      if (document.visibilityState !== "visible") return;
      const zone = deviceZone();
      if (!zone) return;
      const last = lastReport();
      if (last && last.zone === zone && Date.now() - last.at < REPORT_EVERY_MS) return;
      reportDeviceZone(zone)
        .then((out) => {
          remember(zone);
          if (out.changed) {
            setActiveZone(out.current_zone);
            void qc.invalidateQueries();
          }
        })
        .catch(() => undefined);
    };
    report();
    document.addEventListener("visibilitychange", report);
    return () => document.removeEventListener("visibilitychange", report);
  }, [qc]);
}
