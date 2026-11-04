import { importPublicKey, verifySigned } from "./crypto";
import type { AppealRecord, Credential, Pending, ReadCriterion, ReadingDoc, RevocationEntry, RevocationList, Scheme, SiteData, SiteIndex } from "./types";

const base = import.meta.env.BASE_URL;
export const dataUrl = (file: string) => `${base}data/${file}`;

async function text(path: string): Promise<string> {
  const res = await fetch(path, { cache: "no-cache" });
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.text();
}

const isAppeal = (file: string) => file.startsWith("appeals/");

async function json<T>(file: string): Promise<T> {
  return JSON.parse(await text(dataUrl(file))) as T;
}

async function loadEvidence(docs: ReadingDoc[]): Promise<SiteData["evidence"][string] | undefined> {
  const sides: SiteData["evidence"][string] = { a: {}, b: {} };
  let found = false;
  await Promise.all(
    (["a", "b"] as const).map(async (side) => {
      const inline = docs.map((d) => d.readings?.[side]?.criteria).find((c) => c?.length);
      const cacheKey = docs.map((d) => d.readings?.[side]?.key).find(Boolean);
      let criteria = inline;
      if (!criteria && cacheKey) {
        try {
          criteria = (await json<{ reading?: { criteria?: ReadCriterion[] } }>(`cache/${cacheKey}.json`)).reading?.criteria;
        } catch {
          criteria = undefined;
        }
      }
      for (const c of criteria ?? []) {
        sides[side][c.id] = c;
        found = true;
      }
    }),
  );
  return found ? sides : undefined;
}

async function load(): Promise<SiteData> {
  const [index, pem] = await Promise.all([
    text(dataUrl("index.json")).then((t) => JSON.parse(t) as SiteIndex),
    text(`${base}keys/docket-public.pem`),
  ]);
  const keyPromise = importPublicKey(pem);
  const credentials = new Map<string, { file: string; raw: string; doc: Credential }>();
  const appealFiles = [
    ...new Set([...(index.appeals ?? []), ...(index.other ?? []).filter(isAppeal), ...Object.values(index.readings).flat().filter(isAppeal)]),
  ];
  const readingEntries = Object.entries(index.readings).map(([id, files]) => [id, files.filter((f) => !isAppeal(f))] as const);
  const [, revocations, schemes, readingPairs, pending, appeals] = await Promise.all([
    Promise.all(
      index.credentials.map(async (c) => {
        const raw = await text(dataUrl(c.file));
        credentials.set(c.credentialId, { file: c.file, raw, doc: JSON.parse(raw) as Credential });
      }),
    ),
    (async (): Promise<SiteData["revocations"]> => {
      if (!index.revocations) return { list: null, valid: false };
      const list = await json<RevocationList>(index.revocations);
      return { list, valid: await verifySigned(await keyPromise, list as unknown as Record<string, unknown>) };
    })(),
    Promise.all(index.schemes.map((s) => json<Scheme>(s.file))),
    Promise.all(
      readingEntries.map(async ([id, files]) => {
        const docs = await Promise.all(files.map((f) => json<ReadingDoc>(f)));
        return [id, docs, await loadEvidence(docs)] as const;
      }),
    ),
    Promise.all((index.pending ?? []).map((f) => json<Pending>(f).catch(() => null))).then((all) => all.filter((p): p is Pending => !!p?.interrupt)),
    Promise.all(
      appealFiles.map((f) =>
        json<Record<string, unknown>>(f)
          .then(async (doc) => ({ ...doc, file: f, signed: "signature" in doc ? await verifySigned(await keyPromise, doc) : null }) as AppealRecord)
          .catch(() => null),
      ),
    ).then((all) => all.filter((a): a is AppealRecord => !!a && !("credentialId" in a && !("appealId" in a)))),
  ]);
  const readings: Record<string, unknown[]> = {};
  const evidence: SiteData["evidence"] = {};
  for (const [id, docs, seen] of readingPairs) {
    readings[id] = docs;
    if (seen) evidence[id] = seen;
  }
  return { index, key: await keyPromise, credentials, revocations, schemes, readings, pending, evidence, appeals };
}

let pending: Promise<SiteData> | null = null;
export const siteData = () => (pending ??= load());

export function entryFor(data: SiteData, credentialId: string) {
  return data.revocations.valid ? data.revocations.list?.entries.find((e) => e.credentialId === credentialId) : undefined;
}

export function currentFor(data: SiteData, scriptId: string): Credential | undefined {
  const all = [...data.credentials.values()].map((c) => c.doc).filter((c) => c.scriptId === scriptId);
  const live = all.filter((c) => !entryFor(data, c.credentialId));
  const pool = live.length ? live : all;
  return pool.sort((a, b) => a.issuedAt.localeCompare(b.issuedAt)).at(-1);
}

export function scriptIds(data: SiteData): string[] {
  return [...new Set([...data.credentials.values()].map((c) => c.doc.scriptId))].sort();
}

export function criterionText(data: SiteData, schemeId: string, version: string, id: string): string | undefined {
  const scheme = data.schemes.find((s) => s.schemeId === schemeId && s.schemeVersion === version);
  const c = scheme?.criteria.find((k) => k.id === id);
  return c?.text ?? c?.description ?? c?.title;
}

export function readingDocs(data: SiteData, scriptId: string): ReadingDoc[] {
  return (data.readings[scriptId] ?? []) as ReadingDoc[];
}

export function officialFor(data: SiteData, scriptId: string): number | undefined {
  return readingDocs(data, scriptId).find((d) => typeof d.officialScore === "number")?.officialScore;
}

export function callFor(data: SiteData, scriptId: string, criterionId: string) {
  return readingDocs(data, scriptId)
    .flatMap((d) => d.calls ?? [])
    .find((c) => c.id === criterionId);
}

export function firstMarking(data: SiteData, scriptId: string): Credential | undefined {
  const all = [...data.credentials.values()].map((c) => c.doc).filter((c) => c.scriptId === scriptId);
  const originals = all.filter((c) => !c.supersedes);
  return (originals.length ? originals : all).sort((a, b) => a.issuedAt.localeCompare(b.issuedAt))[0];
}

const APPEAL = /appeal/i;

export const isAppealEntry = (entry: RevocationEntry | undefined) => !!entry && APPEAL.test(entry.reason);

function field(record: AppealRecord | undefined, keys: string[]): string | undefined {
  for (const k of keys) {
    const v = record?.[k];
    if (typeof v === "string" && v.trim()) return v;
  }
  return undefined;
}

function number(record: AppealRecord | undefined, keys: string[]): number | undefined {
  for (const k of keys) {
    const v = record?.[k];
    if (typeof v === "number") return v;
  }
  return undefined;
}

export interface Appeal {
  scriptId: string;
  oldId: string;
  newId: string | null;
  old?: Credential;
  next?: Credential;
  oldTotal?: number;
  newTotal?: number;
  max?: number;
  reason: string;
  outcome?: string;
  decision?: string;
  entry?: RevocationEntry;
  record?: AppealRecord;
}

const OLD_KEYS = ["appealed", "oldCredentialId", "supersededCredentialId", "originalCredentialId", "appealedCredentialId", "from", "old"];
const NEW_KEYS = ["standingCredential", "newCredentialId", "replacementCredentialId", "replacedBy", "to", "new"];
const REASON_KEYS = ["reason", "grounds", "appealReason", "claim", "request"];

export function appealsOf(data: SiteData): Appeal[] {
  const doc = (id: string | null | undefined) => (id ? data.credentials.get(id)?.doc : undefined);
  const out = new Map<string, Appeal>();
  const entries = data.revocations.valid ? data.revocations.list?.entries ?? [] : [];
  for (const record of data.appeals) {
    const oldId = field(record, OLD_KEYS) ?? (record.credentialId as string | undefined);
    if (!oldId) continue;
    const entry = entries.find((e) => e.credentialId === oldId);
    const named = field(record, NEW_KEYS) ?? entry?.replacedBy ?? [...data.credentials.values()].find((c) => c.doc.supersedes === oldId)?.doc.credentialId ?? null;
    const newId = named === oldId ? null : named;
    const old = doc(oldId);
    const next = doc(newId);
    out.set(oldId, {
      scriptId: field(record, ["scriptId"]) ?? old?.scriptId ?? next?.scriptId ?? oldId,
      oldId,
      newId,
      old,
      next,
      oldTotal: number(record, ["oldTotal", "oldGrade", "fromTotal"]) ?? old?.total,
      newTotal: number(record, ["newTotal", "newGrade", "toTotal"]) ?? next?.total ?? (newId ? undefined : old?.total),
      max: next?.max ?? old?.max ?? number(record, ["max"]),
      reason: field(record, REASON_KEYS) ?? entry?.reason ?? "",
      outcome: field(record, ["outcome", "status", "result"]),
      decision: field(record, ["decision"]),
      entry,
      record,
    });
  }
  for (const entry of entries) {
    if (!isAppealEntry(entry) || out.has(entry.credentialId)) continue;
    const old = doc(entry.credentialId);
    const next = doc(entry.replacedBy);
    out.set(entry.credentialId, {
      scriptId: old?.scriptId ?? next?.scriptId ?? entry.credentialId,
      oldId: entry.credentialId,
      newId: entry.replacedBy,
      old,
      next,
      oldTotal: old?.total,
      newTotal: next?.total,
      max: next?.max ?? old?.max,
      reason: entry.reason,
      entry,
    });
  }
  return [...out.values()].sort((a, b) => a.scriptId.localeCompare(b.scriptId));
}
