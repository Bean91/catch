/** Joins class names, skipping falsy parts. No conflict resolution: later utilities don't override earlier ones, so
 * primitives take a `className` only for layout (margins, widths, grid placement), not for restyling. */
export function cn(...parts: (string | false | null | undefined | 0)[]): string {
  return parts.filter(Boolean).join(" ");
}
