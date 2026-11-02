import type { CDPSession, Page } from "@playwright/test";

// Real multi-touch synthesis via CDP's Input.dispatchTouchEvent — Playwright's own `page.touchscreen`
// only offers a single-point `tap()`, with no move and no second finger, so pan/pinch/hold
// gestures need this instead (Chromium only; see playwright.config.ts's project comment).

export async function newTouchSession(page: Page): Promise<CDPSession> {
  return page.context().newCDPSession(page);
}

async function dispatch(
  cdp: CDPSession,
  type: "touchStart" | "touchMove" | "touchEnd" | "touchCancel",
  points: { x: number; y: number; id: number }[],
) {
  await cdp.send("Input.dispatchTouchEvent", {
    type,
    touchPoints: points.map((p) => ({ x: p.x, y: p.y, id: p.id })),
  });
}

/** A single-finger press, optionally held before any movement, then dragged to `to`, then
 * released — or cancelled instead of released, if `cancel` is set. */
export async function touchDrag(
  cdp: CDPSession,
  from: { x: number; y: number },
  to: { x: number; y: number },
  opts: { holdMs?: number; steps?: number; stepDelayMs?: number; cancel?: boolean } = {},
): Promise<void> {
  const { holdMs = 0, steps = 10, stepDelayMs = 16, cancel = false } = opts;
  await dispatch(cdp, "touchStart", [{ ...from, id: 0 }]);
  if (holdMs > 0) await new Promise((r) => setTimeout(r, holdMs));
  for (let i = 1; i <= steps; i++) {
    const x = from.x + ((to.x - from.x) * i) / steps;
    const y = from.y + ((to.y - from.y) * i) / steps;
    await dispatch(cdp, "touchMove", [{ x, y, id: 0 }]);
    await new Promise((r) => setTimeout(r, stepDelayMs));
  }
  await dispatch(cdp, cancel ? "touchCancel" : "touchEnd", []);
}

/** A stationary single-finger press held for `holdMs`, then released without moving. */
export async function touchHold(cdp: CDPSession, at: { x: number; y: number }, holdMs: number): Promise<void> {
  await dispatch(cdp, "touchStart", [{ ...at, id: 0 }]);
  await new Promise((r) => setTimeout(r, holdMs));
  await dispatch(cdp, "touchEnd", []);
}

/** A quick single-finger tap (down, immediate up, no movement). */
export async function touchTap(cdp: CDPSession, at: { x: number; y: number }): Promise<void> {
  await dispatch(cdp, "touchStart", [{ ...at, id: 0 }]);
  await dispatch(cdp, "touchEnd", []);
}

/** Two fingers moving apart (zoom in) or together (zoom out) around `center`, along the x axis. */
export async function touchPinch(
  cdp: CDPSession,
  center: { x: number; y: number },
  startHalfSpan: number,
  endHalfSpan: number,
  steps = 10,
): Promise<void> {
  const left = (half: number) => ({ x: center.x - half, y: center.y, id: 0 });
  const right = (half: number) => ({ x: center.x + half, y: center.y, id: 1 });
  await dispatch(cdp, "touchStart", [left(startHalfSpan), right(startHalfSpan)]);
  for (let i = 1; i <= steps; i++) {
    const half = startHalfSpan + ((endHalfSpan - startHalfSpan) * i) / steps;
    await dispatch(cdp, "touchMove", [left(half), right(half)]);
    await new Promise((r) => setTimeout(r, 16));
  }
  await dispatch(cdp, "touchEnd", []);
}
