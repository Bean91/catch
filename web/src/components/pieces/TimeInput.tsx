import { useEffect, useState } from "react";

// Task Part C.3: iOS Safari's numeric keyboard has no colon, so a plain `inputMode="numeric"`
// field can't type "1:38.2" directly. Typing raw digits right-to-left instead — "1382" reads
// as 1 minute, 38 seconds, 2 tenths — and reformatting as they're typed is the same pattern a
// stopwatch/timer UI uses; see DESIGN.md if this needs documenting there too.
function secondsToDigits(seconds: number): string {
  const totalTenths = Math.round(seconds * 10);
  const minutes = Math.floor(totalTenths / 600);
  const secs = Math.floor((totalTenths % 600) / 10);
  const tenths = totalTenths % 10;
  return `${minutes}${String(secs).padStart(2, "0")}${tenths}`;
}

function digitsToSeconds(digits: string): number | null {
  if (!digits) return null;
  const padded = digits.padStart(3, "0");
  const tenths = Number(padded.slice(-1));
  const secs = Number(padded.slice(-3, -1));
  const minutes = Number(padded.slice(0, -3) || "0");
  return minutes * 60 + secs + tenths / 10;
}

function digitsToDisplay(digits: string): string {
  if (!digits) return "";
  const padded = digits.padStart(3, "0");
  const tenths = padded.slice(-1);
  const secs = padded.slice(-3, -1);
  const minutes = padded.slice(0, -3) || "0";
  return `${minutes}:${secs}.${tenths}`;
}

export function TimeInput({
  valueS,
  onChange,
  ariaLabel,
  className,
}: {
  valueS: number | null;
  onChange: (seconds: number | null) => void;
  ariaLabel?: string;
  className?: string;
}) {
  const [digits, setDigits] = useState(() => (valueS != null ? secondsToDigits(valueS) : ""));

  // Re-sync from an external reset/overwrite (a paste, a different row's value after a
  // delete, a realign) — but only when `valueS` actually differs numerically from what's
  // currently displayed, so this never fights the user's own in-progress typing (each
  // keystroke already updates `digits` locally, which also changes what this comparison
  // reads). Comparing only `valueS == null` (an earlier version) missed every case where
  // `valueS` changed to a different *non-null* number — a pasted-over row, or a row shifted
  // up after an earlier row's deletion, kept showing a stale value. A real bug an advisor
  // review caught.
  useEffect(() => {
    const current = digitsToSeconds(digits);
    const inSync = valueS == null ? current == null : current != null && Math.abs(current - valueS) < 0.05;
    if (!inSync) setDigits(valueS != null ? secondsToDigits(valueS) : "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [valueS]);

  return (
    <input
      type="text"
      inputMode="numeric"
      autoComplete="off"
      value={digitsToDisplay(digits)}
      placeholder="m:ss.t"
      aria-label={ariaLabel}
      onChange={(e) => {
        const raw = e.target.value.replace(/\D/g, "").slice(-6);
        setDigits(raw);
        onChange(digitsToSeconds(raw));
      }}
      className={className ?? "min-h-9 w-full rounded-md border border-border bg-bg px-2 text-base text-text-primary font-mono-nums"}
    />
  );
}
