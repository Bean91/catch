import { useEffect, useRef, useState } from "react";
import { useReducedMotion } from "../../lib/useReducedMotion";

/** Counts up to `value` once on first mount (an ease-out over `durationS`); later changes, and reduced motion, show the value at once. */
export function CountUp({
  value,
  decimals = 0,
  suffix = "",
  durationS = 1.1,
  className = "",
}: {
  value: number;
  decimals?: number;
  suffix?: string;
  durationS?: number;
  className?: string;
}) {
  const reduced = useReducedMotion();
  const [display, setDisplay] = useState(reduced ? value : 0);
  const didRun = useRef(false);

  useEffect(() => {
    if (reduced || didRun.current) {
      setDisplay(value);
      return;
    }
    didRun.current = true;
    const start = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const t = Math.min((now - start) / (durationS * 1000), 1);
      setDisplay(value * (1 - Math.pow(1 - t, 4)));
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  return (
    <span className={`font-mono-nums ${className}`}>
      {display.toFixed(decimals)}
      {suffix}
    </span>
  );
}
