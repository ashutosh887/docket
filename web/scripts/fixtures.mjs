import { createHash, generateKeyPairSync, sign } from "node:crypto";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { canonical } from "./canonical.mjs";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "fixtures");
rmSync(root, { recursive: true, force: true });
for (const dir of ["credentials", "scripts", "schemes"]) mkdirSync(join(root, dir), { recursive: true });

const { privateKey, publicKey } = generateKeyPairSync("ec", { namedCurve: "P-256" });
writeFileSync(join(root, "docket-public.pem"), publicKey.export({ type: "spki", format: "pem" }));
const keyId = "fixture:local-test-key";
const schemeId = "ege-profile-math-task-13";

const schemes = {
  v1: {
    schemeId,
    schemeVersion: "v1",
    previousVersion: null,
    changedCriteria: [],
    criteria: [
      { id: "K1", max: 1, text: "Part (a): the equation is solved and every root is stated." },
      { id: "K2", max: 1, text: "Part (b): the roots in the interval are selected, with part (a) correct." },
    ],
  },
  v2: {
    schemeId,
    schemeVersion: "v2",
    previousVersion: "v1",
    changedCriteria: ["K2"],
    note: "K2 now credits a correct selection method carried forward from a part (a) slip.",
    criteria: [
      { id: "K1", max: 1, text: "Part (a): the equation is solved and every root is stated." },
      { id: "K2", max: 1, text: "Part (b): the roots in the interval are selected by a correct method, carrying forward part (a)." },
    ],
  },
};
for (const s of Object.values(schemes)) writeFileSync(join(root, "schemes", `${schemeId}-${s.schemeVersion}.json`), JSON.stringify(s, null, 2));

function signed(doc) {
  const value = sign("sha256", Buffer.from(canonical(doc), "utf8"), { key: privateKey, dsaEncoding: "der" }).toString("base64");
  return { ...doc, signature: { alg: "ECDSA_SHA_256", keyId, value } };
}

function scan(scriptId, lines) {
  const body = lines.map((l, i) => `<text x="40" y="${90 + i * 46}" font-family="Georgia, serif" font-style="italic" font-size="26" fill="#1f2a5a">${l}</text>`).join("");
  const rules = Array.from({ length: 14 }, (_, i) => `<line x1="20" x2="780" y1="${100 + i * 46}" y2="${100 + i * 46}" stroke="#c9d3e8" stroke-width="1"/>`).join("");
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="800" height="760" viewBox="0 0 800 760"><rect width="800" height="760" fill="#fbfaf5"/>${rules}<text x="40" y="50" font-family="monospace" font-size="18" fill="#9a3b1b">FIXTURE ${scriptId}: stand-in for a scanned script</text>${body}</svg>`;
  const file = join(root, "scripts", `${scriptId}.svg`);
  writeFileSync(file, svg);
  return createHash("sha256").update(svg).digest("hex");
}

const scripts = [
  {
    scriptId: "fx-01",
    lines: ["a) 2cos²x − cos x − 1 = 0", "cos x = 1 or cos x = −1/2", "x = 2πk, x = ±2π/3 + 2πk", "b) on [−3π; −3π/2]:", "x = −8π/3"],
    v1: [{ id: "K1", a: 1, b: 1 }, { id: "K2", a: 0, b: 0 }],
    v2: [{ id: "K1", a: 1, b: 1 }, { id: "K2", a: 0, b: 0 }],
  },
  {
    scriptId: "fx-02",
    lines: ["a) 2cos²x − cos x − 1 = 0", "cos x = 1 or cos x = 1/2", "x = 2πk, x = ±π/3 + 2πk", "b) on [−3π; −3π/2]:", "x = −7π/3, x = −2π, x = −5π/3"],
    v1: [{ id: "K1", a: 0, b: 0 }, { id: "K2", a: 0, b: 1, teacher: 0 }],
    v2: [{ id: "K1", a: 0, b: 0 }, { id: "K2", a: 1, b: 1 }],
    note: "Part (a) is wrong, so K2 cannot be awarded under v1.",
  },
  {
    scriptId: "fx-03",
    lines: ["a) t = cos x, 2t² − t − 1 = 0", "t = 1, t = −1/2", "x = 2πk, x = ±2π/3 + 2πk", "b) unit circle: x = −8π/3, x = −2π", "answer: b) −8π/3; −2π"],
    v1: [{ id: "K1", a: 1, b: 1 }, { id: "K2", a: 1, b: 1 }],
    v2: [{ id: "K1", a: 1, b: 1 }, { id: "K2", a: 1, b: 1 }],
  },
];

const readers = { a: "groq:qwen/qwen3.8-27b", b: "cohere:command-a-vision-07-2025" };
const t0 = Date.parse("2026-11-04T06:00:00Z");
const entries = [];

function credential(s, version, rows, n, supersedes, when, note) {
  const criteria = rows.map((r) => {
    const decidedBy = r.teacher === undefined ? "code" : "teacher";
    const points = decidedBy === "teacher" ? r.teacher : r.a;
    return { id: r.id, points, max: 1, readerA: r.a, readerB: r.b, margin: Math.abs(r.a - r.b), decidedBy };
  });
  const teacherDecided = criteria.filter((c) => c.decidedBy === "teacher").map((c) => c.id);
  return signed({
    credentialId: `dkt_${s.scriptId}_${version}_${n}`,
    scriptId: s.scriptId,
    imageSha256: s.sha,
    schemeId,
    schemeVersion: version,
    criteria,
    total: criteria.reduce((t, c) => t + c.points, 0),
    max: criteria.reduce((t, c) => t + c.max, 0),
    readers,
    teacher: { decided: teacherDecided, note: teacherDecided.length ? note ?? null : null },
    issuedAt: new Date(when).toISOString(),
    supersedes,
  });
}

scripts.forEach((s, i) => {
  s.sha = scan(s.scriptId, s.lines);
  const first = credential(s, "v1", s.v1, 1, null, t0 + i * 60000, s.note);
  writeFileSync(join(root, "credentials", `${first.credentialId}.json`), JSON.stringify(first, null, 2));
  const changed = s.v1.some((r, k) => (r.teacher ?? r.a) !== s.v2[k].a);
  if (!changed) return;
  const next = credential(s, "v2", s.v2, 1, first.credentialId, t0 + 3600000 + i * 60000);
  writeFileSync(join(root, "credentials", `${next.credentialId}.json`), JSON.stringify(next, null, 2));
  entries.push({
    credentialId: first.credentialId,
    status: "superseded",
    reason: `Scheme ${schemeId} v1 → v2 changed K2; total ${first.total}/${first.max} → ${next.total}/${next.max}.`,
    replacedBy: next.credentialId,
  });
});

const revocations = signed({ issuedAt: new Date(t0 + 3700000).toISOString(), entries });
writeFileSync(join(root, "revocations.json"), JSON.stringify(revocations, null, 2));
console.log(`fixtures: ${scripts.length} scripts, ${entries.length} superseded, key ${keyId}`);
