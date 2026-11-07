// Shared by PhotoEstimateDialog (nutrition, session 13) and AddPieceDialog (pieces, session
// 17) — the only two photo-upload flows in this app. Resizes to `maxEdge` on the long edge
// before upload: a phone photo straight off the camera is several MB and 3000px+, and
// neither vision call needs more detail than this, so every byte uploaded costs the athlete
// directly (this app is bring-your-own-key).
export async function resizeImage(file: File, maxEdge = 1500): Promise<Blob> {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, maxEdge / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Canvas not supported");
  ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve, reject) => canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("Couldn't encode image"))), "image/jpeg", 0.85));
}
