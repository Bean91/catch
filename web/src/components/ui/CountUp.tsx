import { animate } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { useReducedMotion } from "../../lib/useReducedMotion";

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
    if (reduced) {
      setDisplay(value);
      return;
    }
    if (didRun.current) {
      setDisplay(value);
      return;
    }
    didRun.current = true;
    const controls = animate(0, value, {
      duration: durationS,
      ease: [0.16, 1, 0.3, 1],
      onUpdate: (v) => setDisplay(v),
    });
    return () => controls.stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  return (
    <span className={`font-mono-nums ${className}`}>
      {display.toFixed(decimals)}
      {suffix}
    </span>
  );
}
