/// <reference types="vite/client" />

// Substituted at build time by vite.config.ts's `define` — the same value sw.js's own VERSION
// uses, so Settings.tsx showing this is a direct way to confirm which build a device is really
// running (see PLAN.md's session 9 notes on why that matters for the real-iPhone checklist).
declare const __BUILD_ID__: string;
