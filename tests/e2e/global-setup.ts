import { execFileSync } from "node:child_process";
import path from "node:path";

export default function globalSetup() {
  const root = path.resolve(__dirname, "../..");
  // Build every fixture with known content (same generator the API tests use).
  execFileSync(path.join(root, "services/api/.venv/bin/python"), [path.join(root, "tests/fixtures/generate.py")], { stdio: "ignore" });
}
