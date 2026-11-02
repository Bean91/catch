// Builds two real production bundles with distinct, deterministic BUILD_IDs (vite.config.ts's
// CATCH_BUILD_ID override) into scratch dirs outside catch/api/static — the actual deploy
// target must never be touched by a test run. update.spec.ts serves one, then the other, from
// the same origin/port to simulate `./deploy.sh` shipping a new build to an already-open tab.
import { execSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const webDir = path.resolve(__dirname, "../../");

export const DIST_A = path.join(__dirname, ".dist-a");
export const DIST_B = path.join(__dirname, ".dist-b");

function build(buildId, outDir) {
  execSync(`npx vite build --outDir ${JSON.stringify(outDir)} --emptyOutDir`, {
    cwd: webDir,
    env: { ...process.env, CATCH_BUILD_ID: buildId },
    stdio: "inherit",
  });
}

export default async function globalSetup() {
  build("build-a", DIST_A);
  build("build-b", DIST_B);
}
