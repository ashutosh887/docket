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

const index = { source: pick.source, generatedAt: new Date().toISOString(), credentials: [], revocations: null, schemes: [], images: {}, readings: {}, pending: [], appeals: [], other: [] };
const files = (existsSync(pick.dir) ? walk(pick.dir) : []).filter((p) => !p.endsWith(".pem") && !basename(p).startsWith("."));
const imageFiles = [];
const placed = files.map((path) => ({ path, rel: publishedPath(relative(pick.dir, path).split("\\").join("/")) })).filter((f) => f.rel);
const taken = new Set(placed.filter((f) => !f.path.includes("/appeals/")).map((f) => f.rel));
const chosen = placed.filter((f) => !f.path.includes("/appeals/") || !taken.has(f.rel) || f.rel === "revocations.json" && newerList(f.path));
const winners = new Map([...chosen.filter((f) => !f.path.includes("/appeals/")), ...chosen.filter((f) => f.path.includes("/appeals/"))].map((f) => [f.rel, f]));

for (const { path, rel } of [...winners.values()]) {
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
  } else if (rel.startsWith("appeals/")) {
    index.appeals.push(rel);
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

const results = join(web, "..", "eval", "results");
const resultsOut = join(web, "public", "results");
rmSync(resultsOut, { recursive: true, force: true });
const single = readJson(join(results, "single_reader_d2_b.json"));
const published = readJson(join(results, "published_baselines.json"));
const headline = single && published ? headlineFrom(single, published) : null;
if (headline) {
  mkdirSync(resultsOut, { recursive: true });
  writeFileSync(join(resultsOut, "headline.json"), JSON.stringify(headline, null, 2));
}
console.log(`headline: ${headline ? `${headline.docket.exact.k}/${headline.docket.exact.n} vs ${headline.baseline?.exact ?? "none"}` : "missing eval results"}`);

function headlineFrom(single, published) {
  const run = [...single.runs].sort((a, b) => b.scripts - a.scripts)[0];
  if (!run) return null;
  const same = (published.task13Rows ?? []).filter((r) => r.scripts === run.scripts && sameSet(r.scriptIds, run.scriptIds));
  const best = same.sort((a, b) => b.exact - a.exact)[0];
  const paired = best && (single.pairedWithPublished ?? []).find((p) => p.model === best.model && p.mode === best.mode && p.scripts === run.scripts);
  return {
    writtenAt: single.writtenAt,
    slice: run.slice,
    docket: { design: single.design, reader: single.reader, model: run.model, scripts: run.scripts, exact: run.exact, withinOne: run.withinOne, aboveOfficial: run.aboveOfficial },
    baseline: best ? { model: best.model, mode: best.mode, scripts: best.scripts, exact: best.exact, exactPct: best.exactPct, withinOnePct: best.withinOnePct, source: published.source } : null,
    mcnemarExactP: paired?.mcnemarExactP ?? null,
    spread: single.spreadExactPct ? { on: single.spreadOn, ...single.spreadExactPct } : null,
    files: ["eval/results/single_reader_d2_b.json", "eval/results/published_baselines.json"],
  };
}

function sameSet(a = [], b = []) {
  return a.length === b.length && a.every((x) => b.includes(x));
}

function publishedPath(rel) {
  if (!rel.startsWith("appeals/")) return rel;
  const rest = rel.slice("appeals/".length);
  if (rest === "index.json") return null;
  if (rest === "revocations.json") return "revocations.json";
  if (rest.startsWith("credentials/")) return rest;
  if (rest.startsWith("records/")) return `appeals/${rest.slice("records/".length)}`;
  return `appeals/${rest}`;
}

function newerList(path) {
  const mine = readJson(path);
  const main = readJson(join(pick.dir, "revocations.json"));
  if (!mine?.entries || !mine.signature) return false;
  if (!main?.entries) return true;
  const ids = new Set(mine.entries.map((e) => e.credentialId));
  return mine.issuedAt > main.issuedAt && main.entries.every((e) => ids.has(e.credentialId));
}
