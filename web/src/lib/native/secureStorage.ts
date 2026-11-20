// Session 30 (docs/mobile/security.md): the Supabase session (access + refresh token) lives in the iOS Keychain /
// Android Keystore-backed store, never in the webview's localStorage. auth-js accepts any async {getItem,setItem,removeItem}.
import { Preferences } from "@capacitor/preferences";
import { KeychainAccess, SecureStorage } from "@aparajita/capacitor-secure-storage";

const INSTALL_MARKER = "catch.install-marker";
let ready: Promise<void> | null = null;

/** Keychain items outlive an uninstall on iOS; Preferences (UserDefaults) do not. A missing marker therefore means "fresh
 * install": a session left in the Keychain by a previous install is wiped so a deleted app can't resurrect a login. */
async function prepare(): Promise<void> {
  await SecureStorage.setKeyPrefix("catch.");
  // No iCloud sync, no migration to another device: a refresh token belongs to this device only.
  await SecureStorage.setSynchronize(false);
  await SecureStorage.setDefaultKeychainAccess(KeychainAccess.afterFirstUnlockThisDeviceOnly);
  const { value } = await Preferences.get({ key: INSTALL_MARKER });
  if (!value) {
    await SecureStorage.clear();
    await Preferences.set({ key: INSTALL_MARKER, value: "1" });
  }
}

function init(): Promise<void> {
  ready ??= prepare().catch((e) => {
    ready = null;
    throw e;
  });
  return ready;
}

export const secureSessionStorage = {
  async getItem(key: string): Promise<string | null> {
    await init();
    return SecureStorage.getItem(key);
  },
  async setItem(key: string, value: string): Promise<void> {
    await init();
    await SecureStorage.setItem(key, value);
  },
  async removeItem(key: string): Promise<void> {
    await init();
    await SecureStorage.removeItem(key);
  },
};

export async function clearSecureStorage(): Promise<void> {
  await init();
  await SecureStorage.clear();
}
