import { readFileSync } from "node:fs";
import { importPublicKey, verifySigned } from "../web/src/crypto.ts";

const [pemPath, casesPath] = process.argv.slice(2);
const key = await importPublicKey(readFileSync(pemPath, "utf8"));
const lines = readFileSync(casesPath, "utf8").split("\n").filter(Boolean);
const out = [];
for (const line of lines) {
  const c = JSON.parse(line);
  let ok = false;
  try {
    ok = await verifySigned(key, JSON.parse(c.text));
  } catch {
    ok = false;
  }
  out.push(ok ? "1" : "0");
}
process.stdout.write(out.join(""));
