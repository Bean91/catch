// Session 36: the coach cites the workouts and pages behind a claim by writing their in-app path ("/workouts/123"). The model's
// text is untrusted, so only this short allow-list of exact shapes ever becomes a link — numeric ids only, no query, no hash, no
// host — and anything else stays plain text.

const PATTERNS = [/^\/workouts\/\d{1,10}$/, /^\/tests\/\d{1,10}$/, /^\/tests\/piece\/\d{1,10}$/, /^\/calendar\/events\/\d{1,10}$/, /^\/lab$/, /^\/goals$/, /^\/trends$/];
const CANDIDATE = /(^|[\s(\[])(\/(?:workouts|tests|calendar|lab|goals|trends)(?:\/[a-z0-9]+){0,2})(?=$|[\s).,;:!?\]])/g;

export type TextPart = { text: string; to?: string };

export function isCoachRef(path: string): boolean {
  return PATTERNS.some((p) => p.test(path));
}

/** Splits a message into plain text and allowed in-app links, keeping every character of the original. */
export function splitRefs(text: string): TextPart[] {
  const out: TextPart[] = [];
  let last = 0;
  for (const m of text.matchAll(CANDIDATE)) {
    const path = m[2];
    const start = (m.index ?? 0) + m[1].length;
    if (!isCoachRef(path)) continue;
    if (start > last) out.push({ text: text.slice(last, start) });
    out.push({ text: path, to: path });
    last = start + path.length;
  }
  if (last < text.length) out.push({ text: text.slice(last) });
  return out;
}
