import { describe, expect, it, vi } from "vitest";

const { getPhoto } = vi.hoisted(() => ({ getPhoto: vi.fn() }));
vi.mock("./platform", () => ({ isNative: () => true }));
vi.mock("@capacitor/camera", () => ({ Camera: { getPhoto }, CameraResultType: { Uri: "uri" }, CameraSource: { Prompt: "PROMPT" } }));

describe("pickNativePhoto errors", () => {

  it("a configuration error reaches the person as a plain sentence, never the developer message", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    getPhoto.mockImplementation(() => Promise.reject(new Error("You are missing NSPhotoLibraryAddUsageDescription in your Info.plist file. Camera will not function without it.")));
    const { pickNativePhoto, CameraUnavailableError } = await import("./camera");
    const err = await pickNativePhoto().catch((e) => e);
    expect(err).toBeInstanceOf(CameraUnavailableError);
    expect(err.message).not.toMatch(/Info\.plist|NSPhoto/);
  });

  it("cancelling returns nothing and a denial explains where to allow it", async () => {
    const { pickNativePhoto, CameraPermissionError } = await import("./camera");
    getPhoto.mockImplementation(() => Promise.reject(new Error("User cancelled photos app")));
    await expect(pickNativePhoto()).resolves.toBeNull();
    getPhoto.mockImplementation(() => Promise.reject(new Error("User denied access to camera")));
    await expect(pickNativePhoto()).rejects.toBeInstanceOf(CameraPermissionError);
  });
});
