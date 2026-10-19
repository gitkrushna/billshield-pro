import fs from "node:fs";
import crypto from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const target = path.join(root, ".env.local");
const existing = fs.existsSync(target) ? fs.readFileSync(target, "utf8") : "";
const missing = key => !new RegExp(`^${key}=`, "m").test(existing);
const values = {};
for (const key of ["LOCAL_POSTGRES_PASSWORD", "LOCAL_RUNTIME_DB_PASSWORD", "LOCAL_AUTH_DB_PASSWORD", "LOCAL_S3_SECRET_ACCESS_KEY", "LOCAL_AUTH_JWT_SECRET"]) {
  if (missing(key)) values[key] = crypto.randomBytes(32).toString("hex");
}
if (missing("LOCAL_S3_ACCESS_KEY_ID")) values.LOCAL_S3_ACCESS_KEY_ID = crypto.randomBytes(12).toString("hex");
if (missing("LOCAL_AUTH_JWT_KEYS")) {
  const { privateKey } = crypto.generateKeyPairSync("ec", { namedCurve: "prime256v1" });
  const jwk = { ...privateKey.export({ format: "jwk" }), kid: crypto.randomUUID(), use: "sig", alg: "ES256", key_ops: ["sign", "verify"] };
  values.LOCAL_AUTH_JWT_KEYS = `'${JSON.stringify([jwk])}'`;
}
if (Object.keys(values).length) {
  fs.appendFileSync(target, `${existing.endsWith("\n") || !existing ? "" : "\n"}\n# Local Compose only — generated, never commit\n${Object.entries(values).map(([key, value]) => `${key}=${value}`).join("\n")}\n`, { mode: 0o600 });
}
console.log("Local Compose configuration ready; secret values suppressed. Existing values preserved.");
