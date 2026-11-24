import { useCallback, useState } from "react";

// Session 37 (DESIGN.md "Mobile glass"): the phone/tablet glass materials have three levels, set as `data-glass` on <html>:
// - "off"  — the athlete turned on Reduce transparency (Settings → Appearance). Saved on this device only. Capacitor's iOS web view
//            doesn't pass on the system's reduce-transparency setting, so this switch is the way to get solid surfaces there.
// - "lite" — a low-memory Chromium/Android device: half the blur. Safari has no navigator.deviceMemory, so iPhones are never downgraded.
// - unset  — full glass.
// The CSS does nothing with any of this at desktop widths.

const STORAGE_KEY = "catch:glass";

export type GlassLevel = "full" | "lite" | "off";

function storedOff(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "off";
  } catch {
    return false;
  }
}

export function glassLevel(): GlassLevel {
  if (storedOff()) return "off";
  const memory = (navigator as Navigator & { deviceMemory?: number }).deviceMemory;
  return typeof memory === "number" && memory <= 2 ? "lite" : "full";
}

/** Called once before the first render, so the first paint already uses the right surfaces. */
export function applyGlassPreference(): void {
  const level = glassLevel();
  if (level === "full") document.documentElement.removeAttribute("data-glass");
  else document.documentElement.setAttribute("data-glass", level);
}

/** The Settings switch: `reduced` is true when glass is off. */
export function useReduceTransparency(): [boolean, (reduced: boolean) => void] {
  const [reduced, setReduced] = useState(storedOff);
  const set = useCallback((next: boolean) => {
    try {
      if (next) localStorage.setItem(STORAGE_KEY, "off");
      else localStorage.removeItem(STORAGE_KEY);
    } catch {
      // Storage can be unavailable (private mode); the choice then lasts for this page load only.
    }
    setReduced(next);
    if (next) document.documentElement.setAttribute("data-glass", "off");
    else applyGlassPreference();
  }, []);
  return [reduced, set];
}
