import { useEffect, useState } from "react";
import { verifySigned } from "../crypto";
import { dataUrl } from "../data";
import { href } from "../route";
import type { Credential, RevocationEntry, SiteData } from "../types";

type Verdict =
  | { kind: "empty" }
  | { kind: "unreadable"; message: string }
  | { kind: "invalid"; doc: Record<string, unknown> }
  | { kind: "valid"; doc: Credential }
  | { kind: "superseded" | "revoked"; doc: Credential; entry: RevocationEntry };

async function judge(data: SiteData, text: string): Promise<Verdict> {
  if (!text.trim()) return { kind: "empty" };
  let doc: Record<string, unknown>;
  try {
    doc = JSON.parse(text);
  } catch {
    return { kind: "unreadable", message: "This is not valid JSON." };
  }
  if (!doc || typeof doc !== "object" || !("signature" in doc)) return { kind: "unreadable", message: "This JSON has no signature field." };
  if (!(await verifySigned(data.key, doc))) return { kind: "invalid", doc };
  const credential = doc as unknown as Credential;
  const entry = data.revocations.valid ? data.revocations.list?.entries.find((e) => e.credentialId === credential.credentialId) : undefined;
  if (entry) return { kind: entry.status, doc: credential, entry };
  return { kind: "valid", doc: credential };
}

function tamper(text: string): { text: string; note: string } | null {
  const total = /("total"\s*:\s*)(\d)/.exec(text);
  if (total) {
    const digit = total[2] === "9" ? "8" : String(Number(total[2]) + 1);
    const at = total.index + total[1].length;
    return { text: text.slice(0, at) + digit + text.slice(at + 1), note: `Changed one byte: total ${total[2]} → ${digit}.` };
  }
  const any = /\d/.exec(text);
  if (!any) return null;
  const digit = any[0] === "9" ? "8" : String(Number(any[0]) + 1);
  return { text: text.slice(0, any.index) + digit + text.slice(any.index + 1), note: `Changed one byte: ${any[0]} → ${digit}.` };
}

const LABEL: Record<Verdict["kind"], string> = {
  empty: "Paste a credential",
  unreadable: "Cannot read",
  invalid: "Signature invalid",
  valid: "Valid",
  superseded: "Superseded",
  revoked: "Revoked",
};

export function VerifyPage({ data, initial }: { data: SiteData; initial: string | null }) {
  const ids = [...data.credentials.keys()].sort();
  const startId = initial && data.credentials.has(initial) ? initial : ids.find((id) => !data.revocations.list?.entries.some((e) => e.credentialId === id)) ?? ids[0];
  const [picked, setPicked] = useState(startId ?? "");
  const [text, setText] = useState(startId ? data.credentials.get(startId)!.raw : "");
  const [note, setNote] = useState<string | null>(null);
  const [verdict, setVerdict] = useState<Verdict>({ kind: "empty" });

  useEffect(() => {
    if (initial && data.credentials.has(initial)) {
      setPicked(initial);
      setText(data.credentials.get(initial)!.raw);
      setNote(null);
    }
  }, [initial, data]);

  useEffect(() => {
    let live = true;
    judge(data, text).then((v) => live && setVerdict(v));
    return () => {
      live = false;
    };
  }, [data, text]);

  const pick = (id: string) => {
    setPicked(id);
    setText(data.credentials.get(id)?.raw ?? "");
    setNote(null);
  };

  const flip = () => {
    const out = tamper(text);
    if (out) {
      setText(out.text);
      setNote(out.note);
    }
  };

  const listLine = data.revocations.list
    ? data.revocations.valid
      ? `Revocation list signature checked: ${data.revocations.list.entries.length} ${data.revocations.list.entries.length === 1 ? "entry" : "entries"}, issued ${new Date(data.revocations.list.issuedAt).toLocaleString()}.`
      : "The revocation list signature does not verify, so it is ignored."
    : "No revocation list is published yet.";

  return (
    <section className="page">
      <h2>Verify a grade</h2>
      <p className="muted">
        Your browser checks the ECDSA P-256 signature against Docket's public key, then looks the credential up on the signed
        revocation list. Nothing you paste leaves your browser.
      </p>
      <div className="controls">
        <label>
          <span>Credential</span>
          <select value={picked} onChange={(e) => pick(e.target.value)}>
            {ids.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
        </label>
        <button type="button" onClick={flip}>
          Tamper: flip one byte
        </button>
        <button type="button" className="quiet" onClick={() => pick(picked)}>
          Reset
        </button>
      </div>
      <textarea
        aria-label="Credential JSON"
        spellCheck={false}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setNote(null);
        }}
      />
      {note && <p className="note">{note}</p>}
      <div className={`verdict v-${verdict.kind}`} role="status">
        <strong>{LABEL[verdict.kind]}</strong>
        <VerdictDetail verdict={verdict} data={data} />
      </div>
      <p className="muted small">{listLine}</p>
    </section>
  );
}

function VerdictDetail({ verdict, data }: { verdict: Verdict; data: SiteData }) {
  if (verdict.kind === "empty") return <span>Pick one above or paste its JSON.</span>;
  if (verdict.kind === "unreadable") return <span>{verdict.message}</span>;
  if (verdict.kind === "invalid") return <span>The signed bytes no longer match the signature. Someone changed this credential after it was signed.</span>;
  const c = verdict.doc;
  const summary = (
    <span>
      Script <code>{c.scriptId}</code>, {c.total}/{c.max} under {c.schemeId} {c.schemeVersion}, issued {new Date(c.issuedAt).toLocaleString()}.{" "}
      <a href={href("scripts", { script: c.scriptId })}>See the marking</a> · <a href={dataUrl(data.credentials.get(c.credentialId)?.file ?? "")}>JSON</a>
    </span>
  );
  if (verdict.kind === "valid") return summary;
  const replacement = verdict.entry.replacedBy;
  return (
    <>
      {summary}
      <span className="reason">{verdict.entry.reason}</span>
      {replacement && (
        <span>
          Replaced by{" "}
          {data.credentials.has(replacement) ? <a href={href("verify", { id: replacement })}>{replacement}</a> : <code>{replacement}</code>}.
        </span>
      )}
    </>
  );
}
