import { copyFileSync, existsSync, mkdirSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { basename, dirname, extname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const web = join(dirname(fileURLToPath(import.meta.url)), "..");
const examples = join(web, "..", "examples");
const real = { dir: process.env.DOCKET_SITE_DIR ?? join(examples, "site-data"), key: join(examples, "docket-public.pem"), source: "examples" };
const fixture = { dir: join(web, "fixtures"), key: join(web, "fixtures", "docket-public.pem"), source: "fixture" };
const out = join(web, "public", "data");
const keyOut = join(web, "public", "keys", "docket-public.pem");
const images = new Set([".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif"]);

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });
}

function readJson(path) {
  try {
    return JSON.parse(readFileSync(path, "utf8"));
  } catch {
    return undefined;
  }
}

const pick = process.env.DOCKET_DATA === "fixture" ? fixture : real;
if (!existsSync(pick.key)) throw new Error(`public key missing: ${pick.key}`);

rmSync(out, { recursive: true, force: true });
mkdirSync(out, { recursive: true });
mkdirSync(dirname(keyOut), { recursive: true });
copyFileSync(pick.key, keyOut);

const index = { source: pick.source, generatedAt: new Date().toISOString(), credentials: [], revocations: null, schemes: [], images: {}, readings: {}, pending: [], other: [] };
const files = (existsSync(pick.dir) ? walk(pick.dir) : []).filter((p) => !p.endsWith(".pem") && !basename(p).startsWith("."));
const imageFiles = [];

for (const path of files) {
  const rel = relative(pick.dir, path).split("\\").join("/");
  mkdirSync(dirname(join(out, rel)), { recursive: true });
  copyFileSync(path, join(out, rel));
  if (images.has(extname(path).toLowerCase())) {
    if (!rel.includes("/reference/") && !rel.includes("solve_true")) imageFiles.push(rel);
    continue;
  }
  if (rel.startsWith("pending/") && rel.endsWith(".json")) index.pending.push(rel);
  if (extname(path) !== ".json" || /^(cache|blocks|remarks|batches|pending)\//.test(rel)) continue;
  const doc = readJson(path);
  if (!doc || typeof doc !== "object") continue;
  if (doc.credentialId && doc.signature && doc.scriptId) {
    index.credentials.push({ file: rel, credentialId: doc.credentialId, scriptId: doc.scriptId, schemeVersion: doc.schemeVersion });
  } else if (Array.isArray(doc.entries) && doc.signature) {
    if (!index.revocations || basename(rel) === "revocations.json") index.revocations = rel;
  } else if (doc.schemeVersion && Array.isArray(doc.criteria) && !doc.signature) {
    index.schemes.push({ file: rel, schemeId: doc.schemeId, schemeVersion: doc.schemeVersion });
  } else if (doc.scriptId) {
    (index.readings[doc.scriptId] ??= []).push(rel);
  } else {
    index.other.push(rel);
  }
}

const scriptIds = [...new Set([...index.credentials.map((c) => c.scriptId), ...index.pending.map((p) => basename(p, ".json"))])];
for (const id of scriptIds) {
  const exact = imageFiles.find((f) => basename(f, extname(f)) === id);
  const near = imageFiles.filter((f) => basename(f).includes(id)).sort((a, b) => a.length - b.length)[0];
  const folder = imageFiles.filter((f) => f.split("/").slice(0, -1).includes(id)).sort()[0];
  const found = exact ?? near ?? folder;
  if (found) index.images[id] = found;
}
index.credentials.sort((a, b) => a.credentialId.localeCompare(b.credentialId));
index.schemes.sort((a, b) => String(a.schemeVersion).localeCompare(String(b.schemeVersion)));

writeFileSync(join(out, "index.json"), JSON.stringify(index, null, 2));
console.log(`site data: ${pick.source}, ${index.credentials.length} credentials, ${scriptIds.length} scripts, revocations ${index.revocations ?? "none"}, ${index.schemes.length} schemes`);
