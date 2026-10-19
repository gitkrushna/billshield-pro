import fs from "node:fs";
import path from "node:path";

// Fail closed: absence of a production build is not a successful bundle audit.
const directory = path.resolve(".next/static");
if (!fs.existsSync(directory)) throw new Error("Production browser bundle missing; build first.");
const forbiddenNames = /(?:NEXT_PUBLIC_\w*(?:SECRET|PASSWORD|PRIVATE|SERVICE_ROLE|DEEPSEEK|DATABASE)|SUPABASE_SERVICE_ROLE_KEY|S3_SECRET_ACCESS_KEY|DEEPSEEK_API_KEY|BEGIN (?:RSA |EC )?PRIVATE KEY)/i;
const secretValues = Object.entries(process.env)
  .filter(([key, value]) => value && value.length >= 12 && /(?:PASSWORD|SECRET|PRIVATE_KEY|JWT_KEYS|DEEPSEEK_API_KEY|DATABASE_URL|S3_ACCESS_KEY_ID)/i.test(key))
  .map(([, value]) => value);
let scanned = 0;
function scan(folder) {
  for (const entry of fs.readdirSync(folder, { withFileTypes: true })) {
    const file = path.join(folder, entry.name);
    if (entry.isDirectory()) scan(file);
    else if (/\.(?:js|json|map|css)$/.test(file)) {
      const text = fs.readFileSync(file, "utf8");
      scanned++;
      if (forbiddenNames.test(text) || secretValues.some(value => text.includes(value))) {
        throw new Error("Private configuration detected in browser bundle (content suppressed).");
      }
    }
  }
}
scan(directory);
if (!scanned) throw new Error("No browser assets were scanned.");
console.log(`Browser secret check passed (${scanned} assets).`);
