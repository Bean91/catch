// Session 32: the password rules, the same ones Supabase Auth enforces on the public deployment (minimum 8; lowercase, uppercase,
// digits and symbols — docs/supabase-setup.md). Kept identical to tests/fixtures/auth/password_policy.json, which a vitest compares
// against, so the checklist can never pass a password the server then rejects (or reject one it would accept).

export type PasswordRule = "length" | "lowercase" | "uppercase" | "digit" | "symbol";

export const MIN_PASSWORD_LENGTH = 8;
// Supabase's "symbols" set (GoTrue's lower_upper_letters_digits_symbols): a space or an accented letter does not count.
export const PASSWORD_SYMBOLS = "!@#$%^&*()_+-=[]{};'\\:\"|<>?,./`~";

export const PASSWORD_RULES: { id: PasswordRule; label: string; test: (p: string) => boolean }[] = [
  { id: "length", label: `At least ${MIN_PASSWORD_LENGTH} characters`, test: (p) => [...p].length >= MIN_PASSWORD_LENGTH },
  { id: "lowercase", label: "A lowercase letter (a–z)", test: (p) => /[a-z]/.test(p) },
  { id: "uppercase", label: "An uppercase letter (A–Z)", test: (p) => /[A-Z]/.test(p) },
  { id: "digit", label: "A number (0–9)", test: (p) => /[0-9]/.test(p) },
  { id: "symbol", label: "A symbol, such as ! ? # $ % or *", test: (p) => [...p].some((c) => PASSWORD_SYMBOLS.includes(c)) },
];

export function unmetRules(password: string): PasswordRule[] {
  return PASSWORD_RULES.filter((r) => !r.test(password)).map((r) => r.id);
}

export const POLICY_SENTENCE = `at least ${MIN_PASSWORD_LENGTH} characters with a lowercase and an uppercase letter, a number and a symbol`;
