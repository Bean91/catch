// Session 30: inside the app shell a link to another site must not replace the app's own page (there is no back button to
// return with). External http(s) links and target=_blank open in the system's in-app browser sheet instead.
import { webBase } from "./apiBase";
import { isNative } from "./platform";

function isExternal(a: HTMLAnchorElement): boolean {
  if (!/^https?:$/.test(a.protocol)) return false;
  if (a.target === "_blank") return true;
  const own = [window.location.origin, webBase].filter(Boolean);
  return !own.includes(a.origin);
}

export function openExternal(url: string): void {
  void import("@capacitor/browser").then(({ Browser }) => Browser.open({ url }));
}

/** One delegated listener; returns its disposer. */
export function installExternalLinkHandler(): () => void {
  if (!isNative()) return () => {};
  const onClick = (e: MouseEvent) => {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey) return;
    const a = (e.target as Element | null)?.closest?.("a[href]") as HTMLAnchorElement | null;
    if (!a || !isExternal(a)) return;
    e.preventDefault();
    openExternal(a.href);
  };
  document.addEventListener("click", onClick);
  return () => document.removeEventListener("click", onClick);
}
