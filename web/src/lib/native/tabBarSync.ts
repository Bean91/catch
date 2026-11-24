// Session 38 (DESIGN.md "Native tab bar"): the pure half of the iOS app's native tab bar. React Router stays the source of
// truth for where the person is; this keeps the native UITabBarController showing that state and turns its taps into router
// actions. No DOM, no Capacitor import: the plugin is passed in, so every rule here is unit-tested with a fake.

export type TabBarTheme = "dark" | "light";

/** One native tab: an SF Symbol name (and one for older iOS), and whether the tab runs an action instead of being selected. */
export type NativeTabSpec = { id: string; label: string; symbol: string; fallbackSymbol?: string; action?: boolean };

export type TabBarState = { selected: string; visible: boolean; theme: TabBarTheme };

export type TabSelectedEvent = { id: string; reselected: boolean };

type Handle = { remove: () => Promise<void> };

/** The plugin's shape (ios/App/App/NativeTabBarPlugin.swift). */
export interface TabBarPort {
  configure(options: { tabs: NativeTabSpec[] } & TabBarState): Promise<{ reduceTransparency?: boolean } | void>;
  setState(options: Partial<TabBarState>): Promise<void>;
  addListener(event: "tabSelected", listener: (e: TabSelectedEvent) => void): Promise<Handle>;
  addListener(event: "accessibility", listener: (e: { reduceTransparency: boolean }) => void): Promise<Handle>;
}

export type TapAction = { kind: "navigate"; to: string } | { kind: "scrollTop" } | { kind: "more" };

/**
 * What a tap on a native tab means, given where the app is. iOS conventions: a tab goes to its root page; tapping the current tab
 * from deeper in its section goes back to that root; tapping it again on the root scrolls to the top. `roots[id] === null` marks
 * the More tab, which opens the web app's own sheet.
 */
export function tapAction(event: TabSelectedEvent, pathname: string, roots: Record<string, string | null>): TapAction | null {
  if (!(event.id in roots)) return null;
  const root = roots[event.id];
  if (root === null) return { kind: "more" };
  if (event.reselected && pathname === root) return { kind: "scrollTop" };
  return { kind: "navigate", to: root };
}

/** Only what changed, or null when nothing did. */
export function diffState(sent: TabBarState, desired: TabBarState): Partial<TabBarState> | null {
  const out: Partial<TabBarState> = {};
  if (sent.selected !== desired.selected) out.selected = desired.selected;
  if (sent.visible !== desired.visible) out.visible = desired.visible;
  if (sent.theme !== desired.theme) out.theme = desired.theme;
  return Object.keys(out).length ? out : null;
}

export type TabBarSyncOptions = {
  tabs: NativeTabSpec[];
  roots: Record<string, string | null>;
  initial: TabBarState;
  /** The router's current pathname at the moment of a tap. */
  pathname: () => string;
  onAction: (action: TapAction) => void;
  onReduceTransparency: (reduced: boolean) => void;
  /** The plugin refused `configure`: the caller falls back to the web tab bar so the app is never left without navigation. */
  onUnavailable: (error: unknown) => void;
};

export type TabBarSync = {
  /** The desired state after a render; sends only the difference, and nothing until `configure` has landed. */
  update: (state: TabBarState) => void;
  /** Sends the full state again (after the app returns from the background). */
  resend: () => void;
  /** Hides the bar and removes the listeners. */
  dispose: () => void;
};

/**
 * Starts the handshake: listeners first, then `configure` with the full state. The native side keeps the bar hidden and ignores
 * taps from the start of every page load until this `configure` arrives, so cold start, a web view reload and a sign-in all go
 * through the same path. Programmatic selection never raises `tabSelected`, and a tap marks its tab as already shown, so a
 * route change caused by a tap is not echoed back.
 */
export function createTabBarSync(port: TabBarPort, options: TabBarSyncOptions): TabBarSync {
  let desired = options.initial;
  let sent: TabBarState | null = null;
  let disposed = false;
  const handles: Handle[] = [];

  const keep = (handle: Handle) => {
    if (disposed) void handle.remove();
    else handles.push(handle);
  };

  const flush = () => {
    if (disposed || !sent) return;
    const diff = diffState(sent, desired);
    if (!diff) return;
    sent = desired;
    void port.setState(diff).catch(() => {});
  };

  const configure = async () => {
    const state = desired;
    const result = await port.configure({ tabs: options.tabs, ...state });
    if (disposed) {
      // Unmounted while configure was in flight (sign-out during start-up): don't leave a bar showing.
      void port.setState({ visible: false }).catch(() => {});
      return;
    }
    sent = state;
    if (result && typeof result.reduceTransparency === "boolean") options.onReduceTransparency(result.reduceTransparency);
    flush();
  };

  void (async () => {
    try {
      keep(
        await port.addListener("tabSelected", (event) => {
          if (disposed || !sent) return;
          const action = tapAction(event, options.pathname(), options.roots);
          if (!action) return;
          // Native has already shown this tab as selected (More is never selected by a tap).
          if (action.kind !== "more") sent = { ...sent, selected: event.id };
          options.onAction(action);
        }),
      );
      keep(await port.addListener("accessibility", (e) => !disposed && options.onReduceTransparency(e.reduceTransparency)));
      if (disposed) return;
      await configure();
    } catch (error) {
      if (!disposed) options.onUnavailable(error);
    }
  })();

  return {
    update(state) {
      desired = state;
      flush();
    },
    resend() {
      if (disposed || !sent) return;
      void configure().catch(() => {});
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      for (const h of handles.splice(0)) void h.remove();
      if (sent) void port.setState({ visible: false }).catch(() => {});
    },
  };
}
