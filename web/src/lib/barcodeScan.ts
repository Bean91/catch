// Native BarcodeDetector covers Chrome/Android; iOS Safari (and older Chromium) has none, so
// this self-hosted ZXing-wasm ponyfill (ref: DESIGN.md has no prior art for this — see
// PLAN.md's session 13 notes) is the fallback. Both paths expose the same detect() shape, so
// BarcodeScanner.tsx never branches on which one it got.
import { BarcodeDetector as ZXingBarcodeDetector, type BarcodeFormat, prepareZXingModule } from "barcode-detector/pure";
// `?url` makes Vite emit this into /assets with a hashed name (and the service worker caches
// it like any other build asset) instead of the package's default jsDelivr-CDN fetch — the
// Pi serves everything itself, with no outbound dependency for a feature used offline-first.
import zxingReaderWasmUrl from "zxing-wasm/reader/zxing_reader.wasm?url";

const FORMATS: BarcodeFormat[] = ["ean_13", "ean_8", "upc_a", "upc_e", "code_128"];

let wasmConfigured = false;

function configureSelfHostedWasm() {
  if (wasmConfigured) return;
  wasmConfigured = true;
  prepareZXingModule({
    overrides: { locateFile: (path: string) => (path.endsWith(".wasm") ? zxingReaderWasmUrl : path) },
    fireImmediately: false,
  });
}

export interface BarcodeDetectorLike {
  detect(source: CanvasImageSource): Promise<{ rawValue: string }[]>;
}

export async function createBarcodeDetector(): Promise<BarcodeDetectorLike> {
  const native = (window as unknown as { BarcodeDetector?: new (opts: { formats: string[] }) => BarcodeDetectorLike }).BarcodeDetector;
  if (native) return new native({ formats: FORMATS });
  configureSelfHostedWasm();
  return new ZXingBarcodeDetector({ formats: FORMATS }) as unknown as BarcodeDetectorLike;
}
