import { importPublicKey, verifySigned } from "./crypto";
import type { Credential, Pending, RevocationList, Scheme, SiteData, SiteIndex } from "./types";

const base = import.meta.env.BASE_URL;
export const dataUrl = (file: string) => `${base}data/${file}`;

async function text(path: string): Promise<string> {
  const res = await fetch(path, { cache: "no-cache" });
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.text();
}

async function load(): Promise<SiteData> {
  const [index, pem] = await Promise.all([
    text(dataUrl("index.json")).then((t) => JSON.parse(t) as SiteIndex),
    text(`${base}keys/docket-public.pem`),
  ]);
  const key = await importPublicKey(pem);
  const credentials = new Map<string, { file: string; raw: string; doc: Credential }>();
  await Promise.all(
    index.credentials.map(async (c) => {
      const raw = await text(dataUrl(c.file));
      credentials.set(c.credentialId, { file: c.file, raw, doc: JSON.parse(raw) as Credential });
    }),
  );
  let revocations: SiteData["revocations"] = { list: null, valid: false };
  if (index.revocations) {
    const list = JSON.parse(await text(dataUrl(index.revocations))) as RevocationList;
    revocations = { list, valid: await verifySigned(key, list as unknown as Record<string, unknown>) };
  }
  const schemes = await Promise.all(index.schemes.map(async (s) => JSON.parse(await text(dataUrl(s.file))) as Scheme));
  const readings: Record<string, unknown[]> = {};
  await Promise.all(
    Object.entries(index.readings).map(async ([id, files]) => {
      readings[id] = await Promise.all(files.map(async (f) => JSON.parse(await text(dataUrl(f)))));
    }),
  );
  const pending = (
    await Promise.all((index.pending ?? []).map((f) => text(dataUrl(f)).then((t) => JSON.parse(t) as Pending).catch(() => null)))
  ).filter((p): p is Pending => !!p?.interrupt);
  const evidence: SiteData["evidence"] = {};
  await Promise.all(
    Object.entries(readings).map(async ([id, docs]) => {
      const refs = (docs as { readings?: Record<string, { key?: string }> }[]).map((d) => d.readings).find((r) => r?.a?.key || r?.b?.key);
      if (!refs) return;
      const sides: Record<"a" | "b", Record<string, { evidence?: string; confidence?: number; met?: boolean }>> = { a: {}, b: {} };
      await Promise.all(
        (["a", "b"] as const).map(async (side) => {
          const cacheKey = refs[side]?.key;
          if (!cacheKey) return;
          try {
            const doc = JSON.parse(await text(dataUrl(`cache/${cacheKey}.json`)));
            for (const c of doc.reading?.criteria ?? []) sides[side][c.id] = c;
          } catch {
            return;
          }
        }),
      );
      evidence[id] = sides;
    }),
  );
  return { index, key, credentials, revocations, schemes, readings, pending, evidence };
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
