import { describe, expect, it, vi } from "vitest";
import { createTabBarSync, diffState, tapAction, type TabBarPort, type TabBarState, type TabSelectedEvent, type TapAction } from "./tabBarSync";

const TABS = [
  { id: "today", label: "Today", symbol: "clock.fill" },
  { id: "plan", label: "Plan", symbol: "calendar" },
  { id: "train", label: "Train", symbol: "bolt.fill" },
  { id: "coach", label: "Coach", symbol: "person.fill" },
  { id: "more", label: "More", symbol: "square.grid.2x2.fill", action: true },
];
const ROOTS = { today: "/", plan: "/calendar", train: "/train", coach: "/coach", more: null };
const INITIAL: TabBarState = { selected: "today", visible: true, theme: "dark" };

/** A stand-in for the Swift plugin: records calls, lets a test fire native events and hold `configure` open. */
function fakePort({ holdConfigure = false, rejectConfigure = false, reduceTransparency = false } = {}) {
  const calls: { method: string; options: unknown }[] = [];
  const listeners = new Map<string, Set<(e: never) => void>>();
  let releaseConfigure: () => void = () => {};
  const port: TabBarPort = {
    configure: vi.fn(async (options) => {
      calls.push({ method: "configure", options });
      if (rejectConfigure) throw new Error("not implemented");
      if (holdConfigure) await new Promise<void>((r) => (releaseConfigure = r));
      return { reduceTransparency };
    }),
    setState: vi.fn(async (options) => {
      calls.push({ method: "setState", options });
    }),
    addListener: vi.fn(async (event: string, listener: (e: never) => void) => {
      if (!listeners.has(event)) listeners.set(event, new Set());
      listeners.get(event)!.add(listener);
      return { remove: async () => void listeners.get(event)!.delete(listener) };
    }) as TabBarPort["addListener"],
  };
  return {
    port,
    calls,
    listenerCount: () => [...listeners.values()].reduce((n, s) => n + s.size, 0),
    emit: (event: string, payload: unknown) => listeners.get(event)?.forEach((l) => l(payload as never)),
    release: () => releaseConfigure(),
  };
}

const settle = () => new Promise((r) => setTimeout(r, 0));

function start(port: TabBarPort, overrides: Partial<Parameters<typeof createTabBarSync>[1]> = {}) {
  const actions: TapAction[] = [];
  const transparency: boolean[] = [];
  let pathname = "/";
  const onUnavailable = vi.fn();
  const sync = createTabBarSync(port, {
    tabs: TABS,
    roots: ROOTS,
    initial: INITIAL,
    pathname: () => pathname,
    onAction: (a) => actions.push(a),
    onReduceTransparency: (r) => transparency.push(r),
    onUnavailable,
    ...overrides,
  });
  return { sync, actions, transparency, onUnavailable, setPath: (p: string) => (pathname = p) };
}

describe("tapAction", () => {
  const tap = (id: string, reselected = false): TabSelectedEvent => ({ id, reselected });

  it("goes to a tab's root page", () => {
    expect(tapAction(tap("plan"), "/", ROOTS)).toEqual({ kind: "navigate", to: "/calendar" });
  });

  it("returns to the root when the current tab is tapped deeper in its section", () => {
    expect(tapAction(tap("train", true), "/workouts/12", ROOTS)).toEqual({ kind: "navigate", to: "/train" });
    expect(tapAction(tap("today", true), "/checkin", ROOTS)).toEqual({ kind: "navigate", to: "/" });
  });

  it("scrolls to the top when the current tab is tapped on its root", () => {
    expect(tapAction(tap("coach", true), "/coach", ROOTS)).toEqual({ kind: "scrollTop" });
  });

  it("opens the More sheet, never navigating", () => {
    expect(tapAction(tap("more"), "/", ROOTS)).toEqual({ kind: "more" });
    expect(tapAction(tap("more", true), "/body", ROOTS)).toEqual({ kind: "more" });
  });

  it("ignores an id it doesn't know", () => {
    expect(tapAction(tap("nope"), "/", ROOTS)).toBeNull();
  });
});

describe("diffState", () => {
  it("returns only what changed, or null", () => {
    expect(diffState(INITIAL, INITIAL)).toBeNull();
    expect(diffState(INITIAL, { ...INITIAL, selected: "plan" })).toEqual({ selected: "plan" });
    expect(diffState(INITIAL, { selected: "coach", visible: false, theme: "light" })).toEqual({ selected: "coach", visible: false, theme: "light" });
  });
});

describe("createTabBarSync", () => {
  it("subscribes before it configures, with the full state", async () => {
    const f = fakePort();
    start(f.port);
    await settle();
    expect(f.port.addListener).toHaveBeenCalledTimes(2);
    const addOrder = (f.port.addListener as ReturnType<typeof vi.fn>).mock.invocationCallOrder.at(-1)!;
    const configureOrder = (f.port.configure as ReturnType<typeof vi.fn>).mock.invocationCallOrder[0];
    expect(addOrder).toBeLessThan(configureOrder);
    expect(f.calls).toEqual([{ method: "configure", options: { tabs: TABS, ...INITIAL } }]);
  });

  it("sends one setState with only the change when the route moves to another tab", async () => {
    const f = fakePort();
    const { sync } = start(f.port);
    await settle();
    sync.update({ ...INITIAL, selected: "plan" });
    sync.update({ ...INITIAL, selected: "plan" });
    expect(f.calls.slice(1)).toEqual([{ method: "setState", options: { selected: "plan" } }]);
  });

  it("holds updates until configure lands, then sends the difference", async () => {
    const f = fakePort({ holdConfigure: true });
    const { sync } = start(f.port);
    await settle();
    sync.update({ ...INITIAL, selected: "coach", visible: false });
    expect(f.calls.map((c) => c.method)).toEqual(["configure"]);
    f.release();
    await settle();
    expect(f.calls.slice(1)).toEqual([{ method: "setState", options: { selected: "coach", visible: false } }]);
  });

  it("turns a native tap into a router action without echoing the selection back", async () => {
    const f = fakePort();
    const { sync, actions } = start(f.port);
    await settle();
    f.emit("tabSelected", { id: "plan", reselected: false });
    expect(actions).toEqual([{ kind: "navigate", to: "/calendar" }]);
    sync.update({ ...INITIAL, selected: "plan" }); // the route change the tap caused
    expect(f.calls.filter((c) => c.method === "setState")).toEqual([]);
  });

  it("corrects native when the tap lands on another tab (a redirect)", async () => {
    const f = fakePort();
    const { sync } = start(f.port);
    await settle();
    f.emit("tabSelected", { id: "coach", reselected: false });
    sync.update({ ...INITIAL, selected: "today" });
    expect(f.calls.at(-1)).toEqual({ method: "setState", options: { selected: "today" } });
  });

  it("opens More without changing what native shows as selected", async () => {
    const f = fakePort();
    const { sync, actions } = start(f.port);
    await settle();
    f.emit("tabSelected", { id: "more", reselected: false });
    expect(actions).toEqual([{ kind: "more" }]);
    // The sheet opens: the bar steps aside; then a destination from it is chosen.
    sync.update({ ...INITIAL, visible: false });
    sync.update({ ...INITIAL, selected: "more", visible: true });
    expect(f.calls.slice(1)).toEqual([
      { method: "setState", options: { visible: false } },
      { method: "setState", options: { selected: "more", visible: true } },
    ]);
  });

  it("uses the pathname at the moment of the tap", async () => {
    const f = fakePort();
    const { actions, setPath } = start(f.port);
    await settle();
    setPath("/workouts/3");
    f.emit("tabSelected", { id: "train", reselected: true });
    setPath("/train");
    f.emit("tabSelected", { id: "train", reselected: true });
    expect(actions).toEqual([{ kind: "navigate", to: "/train" }, { kind: "scrollTop" }]);
  });

  it("re-sends the full state on resume", async () => {
    const f = fakePort();
    const { sync } = start(f.port);
    await settle();
    sync.update({ ...INITIAL, theme: "light" });
    sync.resend();
    await settle();
    expect(f.calls.at(-1)).toEqual({ method: "configure", options: { tabs: TABS, ...INITIAL, theme: "light" } });
  });

  it("reports iOS Reduce Transparency from configure and from later changes", async () => {
    const f = fakePort({ reduceTransparency: true });
    const { transparency } = start(f.port);
    await settle();
    f.emit("accessibility", { reduceTransparency: false });
    expect(transparency).toEqual([true, false]);
  });

  it("hides the bar and removes every listener on dispose, then ignores late events", async () => {
    const f = fakePort();
    const { sync, actions } = start(f.port);
    await settle();
    expect(f.listenerCount()).toBe(2);
    sync.dispose();
    await settle();
    expect(f.listenerCount()).toBe(0);
    expect(f.calls.at(-1)).toEqual({ method: "setState", options: { visible: false } });
    f.emit("tabSelected", { id: "plan", reselected: false });
    sync.update({ ...INITIAL, selected: "plan" });
    expect(actions).toEqual([]);
    expect(f.calls.filter((c) => c.method === "setState")).toHaveLength(1);
  });

  it("hides the bar if it was unmounted while configure was in flight (sign-out during start-up)", async () => {
    const f = fakePort({ holdConfigure: true });
    const { sync } = start(f.port);
    await settle();
    sync.dispose();
    f.release();
    await settle();
    expect(f.calls.at(-1)).toEqual({ method: "setState", options: { visible: false } });
    expect(f.listenerCount()).toBe(0);
  });

  it("removes listeners that resolve after dispose (StrictMode's mount-unmount-mount)", async () => {
    const f = fakePort();
    const { sync } = start(f.port);
    sync.dispose();
    await settle();
    expect(f.listenerCount()).toBe(0);
    expect(f.port.configure).not.toHaveBeenCalled();
  });

  it("falls back when the plugin refuses configure", async () => {
    const f = fakePort({ rejectConfigure: true });
    const { onUnavailable } = start(f.port);
    await settle();
    expect(onUnavailable).toHaveBeenCalledOnce();
  });

  it("ignores taps before configure has landed (a reload in progress)", async () => {
    const f = fakePort({ holdConfigure: true });
    const { actions } = start(f.port);
    await settle();
    f.emit("tabSelected", { id: "plan", reselected: false });
    expect(actions).toEqual([]);
  });
});
