import { useId, useState } from "react";
import { PASSWORD_RULES } from "../../lib/passwordPolicy";

const INPUT =
  "min-h-11 w-full rounded-md border border-border bg-surface-2 py-2 pl-3 pr-20 text-text-primary outline-none focus-visible:border-accent";

/** A password input with its own show/hide button (each field independent) and, when `checklist` is set, the requirements listed
 * before anything is submitted and ticked off live as they're met — a glyph and a word for each, never colour alone. */
export function PasswordField({
  id,
  label,
  value,
  onChange,
  autoComplete,
  autoFocus,
  checklist = false,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  autoComplete?: string;
  autoFocus?: boolean;
  checklist?: boolean;
}) {
  const [shown, setShown] = useState(false);
  const listId = useId();
  return (
    <>
      <label htmlFor={id} className="mb-1.5 mt-3 block text-sm font-medium text-text-secondary first:mt-0">
        {label}
      </label>
      <div className="relative">
        <input
          id={id}
          type={shown ? "text" : "password"}
          autoFocus={autoFocus}
          autoComplete={autoComplete}
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck={false}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-describedby={checklist ? listId : undefined}
          className={INPUT}
        />
        <button
          type="button"
          onClick={() => setShown((s) => !s)}
          aria-pressed={shown}
          aria-controls={id}
          aria-label={shown ? `Hide ${label.toLowerCase()}` : `Show ${label.toLowerCase()}`}
          className="absolute inset-y-0 right-0 min-h-11 min-w-16 rounded-r-md px-3 text-xs font-medium text-text-secondary hover:text-text-primary"
        >
          {shown ? "Hide" : "Show"}
        </button>
      </div>
      {checklist && (
        <ul id={listId} aria-live="polite" className="mt-2 flex flex-col gap-1 text-xs" data-testid={`${id}-rules`}>
          {PASSWORD_RULES.map((r) => {
            const met = r.test(value);
            return (
              <li key={r.id} data-met={met} className={met ? "text-text-primary" : "text-text-tertiary"}>
                <span aria-hidden className="mr-1.5 inline-block w-3 font-mono-nums">{met ? "✓" : "○"}</span>
                {r.label}
                <span className="sr-only">{met ? " — done" : " — not yet"}</span>
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}
