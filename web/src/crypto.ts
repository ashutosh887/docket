import type { Signature } from "./types";

function encode(value: unknown): string {
  if (Array.isArray(value)) return "[" + value.map(encode).join(",") + "]";
  if (value && typeof value === "object") {
    const obj = value as Record<string, unknown>;
    return "{" + Object.keys(obj).sort().map((k) => JSON.stringify(k) + ":" + encode(obj[k])).join(",") + "}";
  }
  return JSON.stringify(value);
}

export function canonical(value: unknown, asciiOnly = false): string {
  const text = encode(value);
  return asciiOnly ? text.replace(/[\u007f-￿]/g, (c) => "\\u" + c.charCodeAt(0).toString(16).padStart(4, "0")) : text;
}

function base64Bytes(b64: string): Uint8Array<ArrayBuffer> {
  const bin = atob(b64.replace(/\s+/g, ""));
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
}

export async function importPublicKey(pem: string): Promise<CryptoKey> {
  const body = pem.replace(/-----(BEGIN|END) PUBLIC KEY-----/g, "");
  return crypto.subtle.importKey("spki", base64Bytes(body), { name: "ECDSA", namedCurve: "P-256" }, false, ["verify"]);
}

export function derToRaw(der: Uint8Array, size = 32): Uint8Array {
  let at = 0;
  const take = () => der[at++];
  const length = () => {
    const first = take();
    if (first < 0x80) return first;
    if (first !== 0x81) throw new Error("signature length not DER");
    const n = take();
    if (n < 0x80) throw new Error("signature length not minimal");
    return n;
  };
  if (take() !== 0x30) throw new Error("signature is not a DER sequence");
  const seqLen = length();
  if (at + seqLen !== der.length) throw new Error("signature sequence length mismatch");
  const out = new Uint8Array(size * 2);
  for (let part = 0; part < 2; part++) {
    if (take() !== 0x02) throw new Error("signature integer missing");
    let len = length();
    let start = at;
    at += len;
    if (at > der.length || len === 0) throw new Error("signature integer overruns");
    if (der[start] & 0x80) throw new Error("signature integer negative");
    if (len > 1 && der[start] === 0 && !(der[start + 1] & 0x80)) throw new Error("signature integer not minimal");
    while (len > size && der[start] === 0) {
      start++;
      len--;
    }
    if (len > size) throw new Error("signature integer too long");
    out.set(der.subarray(start, start + len), part * size + (size - len));
  }
  if (at !== der.length) throw new Error("signature has trailing bytes");
  return out;
}

export async function verifySigned(key: CryptoKey, doc: Record<string, unknown>): Promise<boolean> {
  const signature = doc.signature as Signature | undefined;
  if (!signature?.value) return false;
  let raw: Uint8Array;
  try {
    raw = derToRaw(base64Bytes(signature.value));
  } catch {
    return false;
  }
  const { signature: _omit, ...body } = doc;
  for (const ascii of [false, true]) {
    const bytes = new TextEncoder().encode(canonical(body, ascii));
    const ok = await crypto.subtle.verify({ name: "ECDSA", hash: "SHA-256" }, key, raw as BufferSource, bytes as BufferSource);
    if (ok) return true;
  }
  return false;
}
