import { useEffect, useRef, useState } from "react";

const DEFAULT_REST_S = 90;

function beep() {
  // Web Audio, not an <audio> element — no asset to ship, and this app is deliberately
  // dependency-light (DESIGN.md's hand-rolled-over-library precedent). iOS Safari has no
  // navigator.vibrate at all (confirmed: WebKit has never implemented the Vibration API), so
  // this is the primary alert there, not just a fallback for a muted phone.
  try {
    const ctx = new (window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.frequency.value = 880;
    osc.connect(gain);
    gain.connect(ctx.destination);
    gain.gain.setValueAtTime(0.15, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.4);
    osc.start();
    osc.stop(ctx.currentTime + 0.4);
  } catch {
    // Audio can fail (autoplay policy, no user gesture yet) — the visual countdown hitting
    // 0:00 is still a correct, if silent, signal.
  }
}

/** Rest auto-starts when `endAt` changes to a real timestamp (task Part A.4: "a rest timer
 * that auto-starts and vibrates"). Computed from that stored end timestamp on every tick,
 * never accumulated via setInterval ticks — a backgrounded PWA suspends JS timers, so an
 * accumulate-based countdown would be wrong by however long it was backgrounded; recomputing
 * from a real `Date.now()` vs. a fixed target is correct regardless. */
export function RestTimer({ endAt, onDismiss, onExtend }: { endAt: number | null; onDismiss: () => void; onExtend: (seconds: number) => void }) {
  const [now, setNow] = useState(() => Date.now());
  const alerted = useRef(false);

  useEffect(() => {
    if (!endAt) return;
    alerted.current = false;
    const id = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(id);
  }, [endAt]);

  const remainingMs = endAt ? endAt - now : 0;

  useEffect(() => {
    if (endAt && remainingMs <= 0 && !alerted.current) {
      alerted.current = true;
      beep();
      if ("vibrate" in navigator) navigator.vibrate([200, 100, 200]);
    }
  }, [endAt, remainingMs]);

  if (!endAt) return null;

  const remainingS = Math.max(0, Math.ceil(remainingMs / 1000));
  const minutes = Math.floor(remainingS / 60);
  const seconds = remainingS % 60;
  const done = remainingMs <= 0;

  return (
    <div
      className={`flex items-center justify-between gap-3 rounded-md border px-4 py-3 ${
        done ? "border-band-green/50 bg-band-green/10" : "border-border bg-surface-2"
      }`}
      role="timer"
      aria-live="polite"
    >
      <div>
        <div className="text-xs text-text-tertiary">{done ? "Rest done" : "Resting"}</div>
        <div className="font-mono-nums text-2xl font-semibold text-text-primary tabular-nums">
          {done ? "0:00" : `${minutes}:${seconds.toString().padStart(2, "0")}`}
        </div>
      </div>
      <div className="flex gap-2">
        {!done && (
          <button
            type="button"
            onClick={() => onExtend(30)}
            className="min-h-11 min-w-11 rounded-md border border-border px-3 text-xs font-medium text-text-secondary"
          >
            +30s
          </button>
        )}
        <button
          type="button"
          onClick={onDismiss}
          className="min-h-11 min-w-11 rounded-md border border-border px-3 text-xs font-medium text-text-secondary"
        >
          Skip
        </button>
      </div>
    </div>
  );
}

export { DEFAULT_REST_S };
