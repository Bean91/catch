import { useEffect, useRef, useState } from "react";
import { createBarcodeDetector, type BarcodeDetectorLike } from "../../lib/barcodeScan";

export function BarcodeScanner({ onDetect, onClose }: { onDetect: (barcode: string) => void; onClose: () => void }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const detectorRef = useRef<BarcodeDetectorLike | null>(null);
  const loopRef = useRef<number | null>(null);
  const detectedRef = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const [torchOn, setTorchOn] = useState(false);
  const [torchAvailable, setTorchAvailable] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function start() {
      try {
        const detector = await createBarcodeDetector();
        if (cancelled) return;
        detectorRef.current = detector;

        const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" } } });
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        const track = stream.getVideoTracks()[0];
        // iOS Safari's track capabilities don't expose `torch` at all — feature-detect rather
        // than assume it's there just because it's a rear camera.
        const caps = track.getCapabilities?.();
        setTorchAvailable(Boolean(caps && "torch" in caps));

        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play();
        }

        const tick = async () => {
          if (cancelled || detectedRef.current || !videoRef.current) return;
          try {
            const results = await detector.detect(videoRef.current);
            if (results.length > 0 && !detectedRef.current) {
              detectedRef.current = true;
              onDetect(results[0].rawValue);
              return;
            }
          } catch {
            // A transient decode failure on one frame — just try the next one.
          }
          loopRef.current = window.setTimeout(tick, 300);
        };
        tick();
      } catch {
        if (!cancelled) setError("Couldn't access the camera — check camera permissions and try again.");
      }
    }

    start();
    return () => {
      cancelled = true;
      if (loopRef.current != null) clearTimeout(loopRef.current);
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const toggleTorch = async () => {
    const track = streamRef.current?.getVideoTracks()[0];
    if (!track) return;
    const next = !torchOn;
    try {
      await track.applyConstraints({ advanced: [{ torch: next } as unknown as MediaTrackConstraintSet] });
      setTorchOn(next);
    } catch {
      // Some browsers report `torch` in getCapabilities() but still reject applyConstraints —
      // leave the toggle state as it was rather than show a flipped UI that didn't take.
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="relative aspect-[3/4] w-full overflow-hidden rounded-lg bg-black">
        <video ref={videoRef} playsInline muted autoPlay className="h-full w-full object-cover" />
        <div className="pointer-events-none absolute inset-6 rounded-lg border-2 border-white/70" />
        {error && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/80 p-4 text-center text-sm text-white">{error}</div>
        )}
      </div>
      <p className="text-center text-xs text-text-tertiary">Point the camera at a barcode</p>
      <div className="flex gap-2">
        {torchAvailable && (
          <button
            type="button"
            onClick={toggleTorch}
            className={`min-h-11 flex-1 rounded-md border text-sm font-medium transition-colors ${
              torchOn ? "border-accent text-accent" : "border-border text-text-primary hover:border-accent"
            }`}
          >
            {torchOn ? "Torch on" : "Torch"}
          </button>
        )}
        <button type="button" onClick={onClose} className="min-h-11 flex-1 rounded-md border border-border text-sm font-medium text-text-primary transition-colors hover:border-accent">
          Cancel
        </button>
      </div>
    </div>
  );
}
