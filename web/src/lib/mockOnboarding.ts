// Session 32 mock: /api/me, time-zone preferences and first-run setup, answered with state at response time like the other mocks.
// `?mock=1&onboarding=pending` starts as a brand-new public account (setup shown); otherwise setup is already complete, so every
// existing mock page and Playwright spec behaves exactly as before.

import type { Me, OnboardingState, ProviderId, TimeZonePrefs } from "./types";
import { deviceZone } from "./localTime";

const params = typeof window !== "undefined" ? new URLSearchParams(window.location.search) : new URLSearchParams();
const pending = params.get("onboarding") === "pending";

let onboarding: OnboardingState = {
  state: pending ? "pending" : "completed",
  step: 0,
  steps: ["welcome", "connections", "preferences", "privacy", "sync", "done"],
  skipped: [],
  completed_at: pending ? null : "2026-11-01T09:00:00+00:00",
  show: pending,
};

let zone: TimeZonePrefs = {
  timezone: pending ? null : "Europe/London",
  follow_device_zone: true,
  current_zone: pending ? deviceZone() ?? "UTC" : "Europe/London",
  fallback_zone: "UTC",
  today: new Date().toISOString().slice(0, 10),
};

export function mockOnboarding(): OnboardingState {
  return { ...onboarding };
}

export function mockPutOnboarding(patch: { step?: number; skipped?: ProviderId[]; complete?: boolean; restart?: boolean }): OnboardingState {
  if (patch.restart) onboarding = { ...onboarding, state: "pending", step: 0, completed_at: null, show: true };
  if (patch.step != null) onboarding = { ...onboarding, step: patch.step };
  if (patch.skipped) onboarding = { ...onboarding, skipped: [...new Set(patch.skipped)].sort() };
  if (patch.complete) onboarding = { ...onboarding, state: "completed", step: 5, completed_at: new Date().toISOString(), show: false };
  return mockOnboarding();
}

export function mockStartOnboardingSync(): { started: ProviderId[] } {
  return { started: [] };
}

export function mockTimeZone(): TimeZonePrefs {
  return { ...zone };
}

export function mockPutTimeZone(patch: { timezone?: string | null; follow_device_zone?: boolean }): TimeZonePrefs {
  zone = { ...zone, ...patch } as TimeZonePrefs;
  if (patch.timezone) zone.current_zone = patch.timezone;
  return mockTimeZone();
}

export function mockReportDeviceZone(timezone: string): { changed: boolean; current_zone: string; today: string } {
  return { changed: false, current_zone: zone.current_zone || timezone, today: zone.today };
}

export function mockMe(): Me {
  return {
    id: "owner",
    email: null,
    display_name: "You",
    deployment: "public",
    timezone: zone.timezone,
    follow_device_zone: zone.follow_device_zone,
    current_zone: zone.current_zone,
    today: zone.today,
    onboarding: { state: onboarding.state, show: onboarding.show },
  };
}
