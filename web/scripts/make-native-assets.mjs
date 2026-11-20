#!/usr/bin/env node
// Session 30 (docs/mobile/store-assets.md): derives the native icon/splash SOURCE images from the PWA's existing icon
// (public/icons/icon-512.png — the purple oar blade on near-black) so the store icon is the same mark, then
// `npm run native:assets` (capacitor-assets) fans them out into every iOS/Android size.
//   - icon-only.png        1024², full-bleed square (iOS rounds it itself; the App Store marketing icon must have no transparency)
//   - icon-foreground.png  the oar alone on transparency, inside the Android adaptive-icon safe zone (the 66 % centre of the canvas)
//   - icon-background.png  the flat background colour
//   - splash.png / splash-dark.png  2732², the mark centred on the app's dark surface
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import sharp from "sharp";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const out = join(root, "assets");
mkdirSync(out, { recursive: true });

const SRC = join(root, "public/icons/icon-512.png");
const base = sharp(SRC).resize(1024, 1024, { kernel: "lanczos3" });
const { data, info } = await base.clone().raw().toBuffer({ resolveWithObject: true });
const px = (x, y) => [0, 1, 2].map((c) => data[(y * info.width + x) * info.channels + c]);
const bg = px(130, 130); // inside the rounded square, clear of the oar: the field colour
const bgHex = "#" + bg.map((v) => v.toString(16).padStart(2, "0")).join("");
console.log("background", bgHex);

await base.clone().flatten({ background: bgHex }).png().toFile(join(out, "icon-only.png"));
await sharp({ create: { width: 1024, height: 1024, channels: 3, background: bgHex } }).png().toFile(join(out, "icon-background.png"));

// Foreground: alpha from how far each pixel is from the background colour (the oar is saturated purple, the field is near black).
const rgba = Buffer.alloc(info.width * info.height * 4);
for (let i = 0; i < info.width * info.height; i++) {
  const r = data[i * info.channels], g = data[i * info.channels + 1], b = data[i * info.channels + 2];
  const dist = Math.max(Math.abs(r - bg[0]), Math.abs(g - bg[1]), Math.abs(b - bg[2]));
  const a = Math.max(0, Math.min(255, Math.round(((dist - 10) / 50) * 255)));
  rgba[i * 4] = r; rgba[i * 4 + 1] = g; rgba[i * 4 + 2] = b; rgba[i * 4 + 3] = a;
}
const oar = await sharp(rgba, { raw: { width: 1024, height: 1024, channels: 4 } }).trim({ threshold: 1 }).png().toBuffer({ resolveWithObject: true });
const target = Math.round(1024 * 0.56); // inside the 66 % safe zone with room for the launcher's mask shapes
const fit = await sharp(oar.data).resize(target, target, { fit: "inside" }).png().toBuffer();
await sharp({ create: { width: 1024, height: 1024, channels: 4, background: { r: 0, g: 0, b: 0, alpha: 0 } } })
  .composite([{ input: fit, gravity: "center" }])
  .png()
  .toFile(join(out, "icon-foreground.png"));

const mark = await sharp(rgba, { raw: { width: 1024, height: 1024, channels: 4 } }).trim({ threshold: 1 }).resize(700, 700, { fit: "inside" }).png().toBuffer();
for (const name of ["splash.png", "splash-dark.png"]) {
  await sharp({ create: { width: 2732, height: 2732, channels: 3, background: bgHex } }).composite([{ input: mark, gravity: "center" }]).png().toFile(join(out, name));
}
console.log("assets written to", out);
