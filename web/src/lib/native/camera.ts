// Session 30 (docs/mobile/camera.md): the store apps take the PM5/meal photo through the system camera sheet (which also offers
// the photo library) instead of a hidden <input capture>. The OS permission prompt appears only when the person taps the button,
// and the photo still goes through the same resizeImage() → same endpoints as on the web.
import { isNative } from "./platform";

export class CameraPermissionError extends Error {
  constructor() {
    super("Catch doesn't have permission to use the camera or photos. You can allow it in your phone's Settings → Catch.");
  }
}

/** The picked photo, or null when the person cancelled. Native shells only; callers keep their <input> for the web. */
export async function pickNativePhoto(): Promise<File | null> {
  if (!isNative()) return null;
  const { Camera, CameraResultType, CameraSource } = await import("@capacitor/camera");
  try {
    const photo = await Camera.getPhoto({
      source: CameraSource.Prompt, // camera or library; the sheet is the system's
      resultType: CameraResultType.Uri,
      quality: 90,
      correctOrientation: true,
      width: 2000, // the downscale to 1500 px happens in resizeImage(); this just stops a 48 MP original being loaded at all
      promptLabelHeader: "Add a photo",
      promptLabelPhoto: "Choose from library",
      promptLabelPicture: "Take photo",
    });
    if (!photo.webPath) return null;
    const blob = await (await fetch(photo.webPath)).blob();
    return new File([blob], "photo.jpg", { type: blob.type || "image/jpeg" });
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    if (/cancel/i.test(msg)) return null;
    if (/denied|permission/i.test(msg)) throw new CameraPermissionError();
    throw e;
  }
}
