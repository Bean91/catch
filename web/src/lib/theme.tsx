import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { isNative } from "./native/platform";

export type Theme = "dark" | "light";

interface ThemeContextValue {
  theme: Theme;
  toggle: () => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);
const STORAGE_KEY = "catch:theme";
// Must match --bg in styles/tokens.css.
const THEME_COLOR: Record<Theme, string> = { dark: "#0B1120", light: "#F4F6FB" };

function readInitialTheme(): Theme {
  const attr = document.documentElement.getAttribute("data-theme");
  return attr === "light" ? "light" : "dark";
}

function storedChoice(): Theme | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === "light" || v === "dark" ? v : null;
  } catch {
    return null;
  }
}

// Session 30: only an explicit tap on the theme button is stored. Before, the effect below wrote the *current* theme on every
// load, so the system's light/dark preference was frozen the first time the app opened and could never be followed again.
// With no stored choice the app follows the phone's appearance live (including while it is open).
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(readInitialTheme);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    // The browser chrome (address bar, PWA title bar) follows the app's theme, not just the system's.
    for (const meta of document.querySelectorAll('meta[name="theme-color"]')) meta.setAttribute("content", THEME_COLOR[theme]);
    if (!isNative()) return;
    // The status bar's text colour follows the app theme, and its background stays transparent (the web layer pads for it).
    void import("@capacitor/status-bar").then(({ StatusBar, Style }) => {
      void StatusBar.setStyle({ style: theme === "dark" ? Style.Dark : Style.Light }).catch(() => {});
    });
  }, [theme]);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: light)");
    const onChange = () => {
      if (storedChoice() === null) setTheme(mq.matches ? "light" : "dark");
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  function toggle() {
    setTheme((t) => {
      const next: Theme = t === "dark" ? "light" : "dark";
      try {
        localStorage.setItem(STORAGE_KEY, next);
      } catch {
        // Private-browsing / blocked storage — theme still applies for this load.
      }
      return next;
    });
  }

  return <ThemeContext.Provider value={{ theme, toggle }}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within ThemeProvider");
  return ctx;
}
