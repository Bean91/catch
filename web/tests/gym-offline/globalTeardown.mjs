import fs from "node:fs";

export default async function globalTeardown() {
  const dir = process.env.CATCH_GYM_TEST_SCRATCH_DIR;
  if (dir) fs.rmSync(dir, { recursive: true, force: true });
}
