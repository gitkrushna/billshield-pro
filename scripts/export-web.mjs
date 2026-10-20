import { cpSync, existsSync } from "node:fs";
import { resolve } from "node:path";

const source = resolve("web/out");
if (!existsSync(resolve(source, "index.html"))) throw new Error("Static web build missing");
cpSync(source, resolve("public"), { recursive: true });
console.log("Exported web assets to the Vercel public folder.");
