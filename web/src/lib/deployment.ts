// Session 24 (docs/public-architecture.md): which build this is. Vite replaces `import.meta.env.*` with literals at
// build time, so in a personal build `isPublic` is the constant `false` and everything gated on it — including the
// Supabase auth client's dynamic import — is dropped from the bundle (the Pi's budget is unchanged).
export const isPublic = import.meta.env.VITE_CATCH_DEPLOYMENT === "public";

// Only the project URL and the *publishable* key ever reach the browser. The secret/service-role key and the database
// credentials live on the server alone (docs/public-setup.md).
export const supabaseUrl: string = (import.meta.env.VITE_SUPABASE_URL ?? "").replace(/\/$/, "");
export const supabasePublishableKey: string = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY ?? "";
