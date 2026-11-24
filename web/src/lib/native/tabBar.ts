// Session 38 (DESIGN.md "Native tab bar", docs/mobile/README.md): the iOS app's bottom navigation is the system tab bar
// (UITabBarController — Liquid Glass on iOS 26), not the web BottomNav. This file is the ONLY place the web app talks to it:
// AppShell calls useNativeTabBar(), the dialog primitives mount <NativeModalMarker />, and the rules live in tabBarSync.ts.
// Everywhere else — a browser, the PWA, Android — nothing here does anything and the web tab bar renders as before.
import { registerPlugin } from "@capacitor/core";
import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { setSystemReduceTransparency } from "../glass";
import { PRIMARY_TABS, tabFor, type TabId } from "../navigation";
import { useTheme } from "../theme";
import { nativeTabBarAvailable, useAnyModalOpen } from "./nativeModal";
import { createTabBarSync, type NativeTabSpec, type TabBarPort, type TabBarState, type TabBarSync, type TapAction } from "./tabBarSync";
import { APP_RESUMED_EVENT } from "./useNativeShell";

export { nativeTabBarAvailable } from "./nativeModal";

const NativeTabBar = registerPlugin<TabBarPort>("NativeTabBar");

// SF Symbols chosen to read like the web icons (clock-face Today, calendar, bolt, person, grid), filled as iOS tab bars are.
// Each also exists on iOS 15, the app's minimum; the fallback covers a symbol a future rename drops.
const SYMBOLS: Record<TabId, { symbol: string; fallbackSymbol?: string }> = {
  today: { symbol: "clock.fill", fallbackSymbol: "clock" },
  plan: { symbol: "calendar" },
  train: { symbol: "bolt.fill", fallbackSymbol: "bolt" },
  coach: { symbol: "person.fill", fallbackSymbol: "person" },
  more: { symbol: "square.grid.2x2.fill", fallbackSymbol: "square.grid.2x2" },
};

export const NATIVE_TABS: NativeTabSpec[] = [
  ...PRIMARY_TABS.map(({ id, label }) => ({ id, label, ...SYMBOLS[id] })),
  { id: "more", label: "More", ...SYMBOLS.more, action: true },
];

const ROOTS: Record<string, string | null> = {
  ...Object.fromEntries(PRIMARY_TABS.map(({ id, to }) => [id, to])),
  more: null,
};

// ---- The hook ----------------------------------------------------------------------------------------------------------------

const DESKTOP_QUERY = "(min-width: 64rem)"; // AppShell's lg: split; min-width rather than a range so iOS 15's WebKit parses it

function useDesktopLayout(enabled: boolean): boolean {
  return useSyncExternalStore(
    (onChange) => {
      if (!enabled) return () => {};
      const mq = window.matchMedia(DESKTOP_QUERY);
      mq.addEventListener("change", onChange);
      return () => mq.removeEventListener("change", onChange);
    },
    () => enabled && window.matchMedia(DESKTOP_QUERY).matches,
  );
}

function scrollToTop(): void {
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  window.scrollTo({ top: 0, behavior: reduce ? "auto" : "smooth" });
}

/**
 * Drives the native tab bar from the router while AppShell is mounted (that is, only when signed in: the login, legal and
 * pre-auth screens have no bar). Returns true while the native bar is in charge, so AppShell renders no web tab bar.
 */
export function useNativeTabBar(openMore: () => void): boolean {
  const [active, setActive] = useState(nativeTabBarAvailable);
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const { theme } = useTheme();
  const modalOpen = useAnyModalOpen();
  const desktop = useDesktopLayout(active);

  const state: TabBarState = { selected: tabFor(pathname), visible: !modalOpen && !desktop, theme };
  const latest = useRef({ state, pathname, navigate, openMore });
  latest.current = { state, pathname, navigate, openMore };
  const sync = useRef<TabBarSync | null>(null);

  // Layout effect: the attribute zeroes --shell-bottom (the bar's footprint arrives through the safe area instead) before the
  // first paint, so the page never pads for both.
  useLayoutEffect(() => {
    if (!active) return;
    const root = document.documentElement;
    root.setAttribute("data-native-tabbar", "");
    const onAction = (action: TapAction) => {
      if (action.kind === "more") latest.current.openMore();
      else if (action.kind === "scrollTop") scrollToTop();
      else latest.current.navigate(action.to);
    };
    const s = createTabBarSync(NativeTabBar, {
      tabs: NATIVE_TABS,
      roots: ROOTS,
      initial: latest.current.state,
      pathname: () => latest.current.pathname,
      onAction,
      onReduceTransparency: setSystemReduceTransparency,
      onUnavailable: (error) => {
        console.warn("native tab bar unavailable; using the web tab bar", error);
        setActive(false);
      },
    });
    sync.current = s;
    const onResume = () => s.resend();
    window.addEventListener(APP_RESUMED_EVENT, onResume);
    return () => {
      window.removeEventListener(APP_RESUMED_EVENT, onResume);
      s.dispose();
      sync.current = null;
      root.removeAttribute("data-native-tabbar");
    };
  }, [active]);

  useEffect(() => {
    sync.current?.update(state);
  }, [state.selected, state.visible, state.theme]); // eslint-disable-line react-hooks/exhaustive-deps

  return active;
}
