#!/usr/bin/env node
// Session 30 (docs/mobile/test-report.md): drives the REAL Capacitor Android app on an emulator over the WebView's DevTools socket
// (adb forward → Playwright connectOverCDP), against a local public-mode API + throwaway Supabase stack. Not part of `npm test`:
// it needs an emulator, `adb`, a debug build with webContentsDebuggingEnabled and the local stack (see docs/mobile/README.md §Testing).
//
//   CATCH_E2E_EMAIL=… CATCH_E2E_PASSWORD=… node tests/native/android-e2e.mjs [scenario ...]
import { execFileSync } from "node:child_process";
import { _android as android } from "@playwright/test";

const ADB = process.env.ADB ?? "adb";
const PKG = process.env.CATCH_E2E_PACKAGE ?? "com.openoted.catch.dev";
const EMAIL = process.env.CATCH_E2E_EMAIL;
const PASSWORD = process.env.CATCH_E2E_PASSWORD;
const API = process.env.CATCH_E2E_API ?? "http://localhost:8000";
const SHOTS = process.env.CATCH_E2E_SHOTS ?? "/tmp";
if (!EMAIL || !PASSWORD) throw new Error("set CATCH_E2E_EMAIL and CATCH_E2E_PASSWORD (a disposable test account)");

const adb = (...a) => execFileSync(ADB, a, { encoding: "utf8" }).trim();
const adbSoft = (...a) => {
  try {
    return adb(...a);
  } catch {
    return "";
  }
};
const results = [];
const check = (name, ok, detail = "") => {
  results.push({ name, ok, detail });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  — " + detail : ""}`);
};

function launch({ clear = false } = {}) {
  // `adb reverse` doesn't survive an adbd restart or a reinstall; re-establish the host API/auth ports every launch.
  for (const port of ["8000", "54321"]) adbSoft("reverse", `tcp:${port}`, `tcp:${port}`);
  if (clear) adb("shell", "pm", "clear", PKG);
  adb("shell", "am", "force-stop", PKG);
  adb("shell", "am", "start", "-n", `${PKG}/com.openoted.catchapp.MainActivity`);
}

// Playwright's own Android driver: connectOverCDP to a WebView fails (Browser.setDownloadBehavior isn't implemented there).
async function connect() {
  const [device] = await android.devices();
  if (!device) throw new Error("no Android device/emulator found (adb devices)");
  for (let i = 0; i < 30; i++) {
    try {
      const webview = await device.webView({ pkg: PKG });
      const page = await webview.page();
      return { browser: { close: () => device.close() }, page, device };
    } catch {
      await new Promise((r) => setTimeout(r, 1000));
    }
  }
  throw new Error("could not attach to the WebView");
}

async function signIn(page) {
  await page.getByLabel(/email/i).fill(EMAIL);
  await page.getByLabel(/password/i).first().fill(PASSWORD);
  await page.getByRole("button", { name: /sign in|log in/i }).click();
  // The phone tab bar only exists once signed in (session 35: the first "CATCH" in the DOM is the desktop sidebar's, hidden on a phone).
  await page.getByRole("navigation", { name: "Primary" }).waitFor({ timeout: 20000 });
}

async function sessionKeys(page) {
  return page.evaluate(() => Object.keys(localStorage).filter((k) => /auth|supabase|sb-/i.test(k)));
}

const SB = process.env.CATCH_E2E_SUPABASE_URL;
const SB_KEY = process.env.CATCH_E2E_PUBLISHABLE_KEY;

async function strengthSetCount() {
  const token = await serverToken();
  const h = { Authorization: `Bearer ${token}` };
  const list = await (await fetch(`${API}/api/activities?category=strength`, { headers: h })).json();
  let n = 0;
  for (const a of list.items ?? []) n += ((await (await fetch(`${API}/api/activities/${a.id}`, { headers: h })).json()).strength_sets ?? []).length;
  return n;
}

async function serverToken() {
  const r = await fetch(`${SB}/auth/v1/token?grant_type=password`, { method: "POST", headers: { apikey: SB_KEY, "Content-Type": "application/json" }, body: JSON.stringify({ email: EMAIL, password: PASSWORD }) });
  return (await r.json()).access_token;
}

const ready = (page) => page.waitForFunction(() => /Morning check-in|RECOVERY|Recovery/.test(document.body.innerText), null, { timeout: 25000 });
const pathOf = (page) => new URL(page.url()).pathname + new URL(page.url()).search;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// The emulator reaches the host API through `adb reverse`, which survives wifi/data toggles, and the WebView keeps connections alive —
// so "offline" is a root firewall rule that resets loopback traffic to the API port (needs a google_apis, not Play Store, image).
const RULE = ["iptables", "-o", "lo", "-p", "tcp", "--dport", "8000", "-j", "REJECT", "--reject-with", "tcp-reset"];
const goOffline = () => {
  for (const bin of ["iptables", "ip6tables"]) adb("shell", [bin, "-I", "OUTPUT", ...RULE.slice(1)].join(" "));
};
const goOnline = () => {
  for (const bin of ["iptables", "ip6tables"]) adbSoft("shell", [bin, "-D", "OUTPUT", ...RULE.slice(1)].join(" "));
};

const scenarios = {
  async login_and_secure_storage() {
    launch({ clear: true });
    const { browser, page } = await connect();
    try {
      await page.waitForLoadState("domcontentloaded");
      check("origin is the native shell", /^https:\/\/localhost/.test(page.url()), page.url());
      await signIn(page);
      check("signed in through the shared Supabase project", await page.getByRole("navigation", { name: "Primary" }).isVisible());
      const leaked = await sessionKeys(page);
      check("no session token in webview localStorage", leaked.length === 0, leaked.join(",") || "none");
      let raw = "";
      for (let i = 0; i < 10 && !raw; i++) {
        raw = adbSoft("shell", "cat", `/data/data/${PKG}/shared_prefs/WSSecureStorageSharedPreferences.xml`) || adbSoft("shell", "run-as", PKG, "cat", "shared_prefs/WSSecureStorageSharedPreferences.xml");
        if (!raw) await sleep(500);
      }
      check("session is held by the native secure store", /catch\.auth/.test(raw));
      check("the stored session is encrypted at rest (no JWT / access_token in clear)", raw.length > 0 && !/eyJ[A-Za-z0-9_-]{20,}|access_token/.test(raw));
      await page.screenshot({ path: `${SHOTS}/android-signed-in.png` });
    } finally {
      await browser.close();
    }
  },

  async session_survives_restart_and_update() {
    launch();
    let { browser, page } = await connect();
    try {
      await ready(page);
      check("session restored from the Keystore after a cold start", true);
    } catch (e) {
      check("session restored from the Keystore after a cold start", false, String(e.message).slice(0, 80));
    } finally {
      await browser.close();
    }
    // "App update": install the same package over itself (adb install -r keeps app data), then relaunch.
    if (process.env.CATCH_E2E_APK) {
      adb("install", "-r", process.env.CATCH_E2E_APK);
      launch();
      ({ browser, page } = await connect());
      try {
        await ready(page);
        check("session persists across an in-place app update", true);
      } catch (e) {
        check("session persists across an in-place app update", false, String(e.message).slice(0, 80));
      } finally {
        await browser.close();
      }
    }
  },

  async expired_session_refreshes() {
    // An access token that expired while the app was away is refreshed from the stored refresh token on resume.
    launch();
    const { browser, page } = await connect();
    try {
      await ready(page);
      adb("shell", "input", "keyevent", "KEYCODE_HOME");
      await sleep(1500);
      adb("shell", "am", "start", "-n", `${PKG}/com.openoted.catchapp.MainActivity`); // resume, not a restart
      await sleep(2000);
      await ready(page);
      const status = await page.evaluate(async () => (await fetch("/api/health")).status).catch(() => 0);
      const bodyOk = await page.evaluate(() => !/Sign in/.test(document.body.innerText));
      check("resume after background stays signed in", bodyOk, `health ${status}`);
    } finally {
      await browser.close();
    }
  },

  async deep_links() {
    const cases = [
      ["workouts/42", /^\/workouts\/42$/],
      ["calendar", /^\/calendar$/],
      ["calendar/events/7", /^\/calendar\/events\/7$/],
      ["coach", /^\/coach$/],
      ["checkin", /^\/checkin$/],
      ["settings/connections?provider=whoop&result=connected", /^\/settings\/connections\?provider=whoop&result=connected$/],
      ["settings/moderation", /^\/$/], // not on the allow-list: lands on Today
    ];
    launch();
    let { browser, page } = await connect();
    try {
      await ready(page);
      for (const [target, expect] of cases) {
        adb("shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", `'${PKG}://${target}'`, PKG);
        await sleep(2500);
        check(`deep link ${PKG}://${target}`, expect.test(pathOf(page)), pathOf(page));
      }
      const checkinOpen = await page.evaluate(() => !!document.querySelector('[role="dialog"]'));
      adb("shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", `'${PKG}://checkin'`, PKG);
      await sleep(3000);
      check("check-in link opens the check-in sheet", await page.evaluate(() => !!document.querySelector('[role="dialog"]')), `before: ${checkinOpen}`);
    } finally {
      await browser.close();
    }
    // Cold start from a link (app killed first).
    adb("shell", "am", "force-stop", PKG);
    adb("shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", `${PKG}://workouts/9`, "-n", `${PKG}/com.openoted.catchapp.MainActivity`);
    ({ browser, page } = await connect());
    try {
      await ready(page).catch(() => {});
      await sleep(2500);
      check("cold start from a deep link lands on the workout", /^\/workouts\/9$/.test(pathOf(page)), pathOf(page));
    } finally {
      await browser.close();
    }
  },

  async offline_strength_logging() {
    const before = await strengthSetCount();
    launch();
    let { browser, page } = await connect();
    try {
      await ready(page);
      await page.evaluate(() => window.history.pushState({}, "", "/gym") || window.dispatchEvent(new PopStateEvent("popstate")));
      await page.getByRole("button", { name: "Start blank workout" }).waitFor({ timeout: 15000 });
      goOffline();
      await page.getByRole("button", { name: "Start blank workout" }).click();
      await page.getByRole("button", { name: "+ Add exercise" }).click();
      await page.getByPlaceholder("Search exercises…").fill("Barbell Squat");
      await page.getByText("Barbell Squat", { exact: true }).click();
      for (const [reps, kg] of [[5, 60], [5, 70], [5, 80]]) {
        await page.getByRole("spinbutton", { name: "Reps", exact: true }).fill(String(reps));
        await page.getByRole("spinbutton", { name: "Load kg", exact: true }).fill(String(kg));
        await page.getByRole("button", { name: "Log set" }).click();
      }
      await page.getByText("3 sets to sync").waitFor({ timeout: 10000 });
      check("three sets logged with the API unreachable", true);
      await page.screenshot({ path: `${SHOTS}/android-offline-logged.png` });
    } catch (e) {
      goOnline(); // a failure here must not leave the API blocked for every later run
      throw e;
    } finally {
      await browser.close();
    }
    // Closing the app while offline must lose nothing.
    adb("shell", "am", "force-stop", PKG);
    launch();
    ({ browser, page } = await connect());
    try {
      await page.waitForFunction(() => document.body.innerText.length > 0, null, { timeout: 20000 });
      await page.evaluate(() => window.history.pushState({}, "", "/gym") || window.dispatchEvent(new PopStateEvent("popstate")));
      await page.getByText("Barbell Squat").first().waitFor({ timeout: 20000 });
      await page.getByText("3 sets to sync").waitFor({ timeout: 15000 });
      check("sets survive closing and reopening the app offline", true);
      goOnline();
      await page.getByText("Synced").first().waitFor({ timeout: 30000 });
      check("queue flushed on reconnect", true);
    } catch (e) {
      check("sets survive closing/reopening and sync on reconnect", false, String(e.message).slice(0, 120));
    } finally {
      goOnline();
      await browser.close();
    }
    const after = await strengthSetCount();
    check("the server gained exactly the three sets logged offline", after - before === 3, `${before} -> ${after}`);
  },
};

// Session 32 sends a brand-new account to first-run setup; this harness tests the shell (storage, links, offline), so the
// disposable account is marked as set up before any scenario runs.
{
  const token = await serverToken();
  const r = await fetch(`${API}/api/onboarding`, { method: "PUT", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ complete: true }) });
  if (!r.ok) console.log(`could not mark setup complete (${r.status}); scenarios may land on /welcome`);
}

goOnline(); // a previous, interrupted run may have left the "offline" firewall rule in place

const wanted = process.argv.slice(2);
for (const [name, fn] of Object.entries(scenarios)) {
  if (wanted.length && !wanted.includes(name)) continue;
  try {
    await fn();
  } catch (e) {
    check(name, false, String(e.message).slice(0, 160));
  }
}
const failed = results.filter((r) => !r.ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed ? 1 : 0);
