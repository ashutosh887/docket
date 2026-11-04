import { criterionText, entryFor } from "../data";
import { href } from "../route";
import type { Credential, SiteData } from "../types";
import { CriteriaTable } from "./Scripts";

interface Step {
  schemeId: string;
  from: string;
  to: string;
}

function steps(data: SiteData): Step[] {
  const fromSchemes = data.schemes
    .filter((s) => s.previousVersion)
    .map((s) => ({ schemeId: s.schemeId, from: s.previousVersion as string, to: s.schemeVersion }));
  if (fromSchemes.length) return fromSchemes;
  const all = [...data.credentials.values()].map((c) => c.doc);
  const out: Step[] = [];
  for (const schemeId of new Set(all.map((c) => c.schemeId))) {
    const versions = [...new Set(all.filter((c) => c.schemeId === schemeId).map((c) => c.schemeVersion))].sort();
    for (let i = 1; i < versions.length; i++) out.push({ schemeId, from: versions[i - 1], to: versions[i] });
  }
  return out;
}

function changedCriteria(data: SiteData, step: Step): string[] {
  const to = data.schemes.find((s) => s.schemeId === step.schemeId && s.schemeVersion === step.to);
  if (to?.changedCriteria?.length) return to.changedCriteria;
  const from = data.schemes.find((s) => s.schemeId === step.schemeId && s.schemeVersion === step.from);
  if (!to || !from) return [];
  return to.criteria
    .filter((k) => {
      const old = from.criteria.find((o) => o.id === k.id);
      return !old || JSON.stringify(old) !== JSON.stringify(k);
    })
    .map((k) => k.id);
}

function latest(list: Credential[]) {
  return [...list].sort((a, b) => a.issuedAt.localeCompare(b.issuedAt)).at(-1);
}

function StepView({ data, step }: { data: SiteData; step: Step }) {
  const all = [...data.credentials.values()].map((c) => c.doc).filter((c) => c.schemeId === step.schemeId);
  const declared = changedCriteria(data, step);
  const note = data.schemes.find((s) => s.schemeId === step.schemeId && s.schemeVersion === step.to)?.note;
  const scripts = [...new Set(all.filter((c) => c.schemeVersion === step.from).map((c) => c.scriptId))].sort();
  const rows = scripts.map((id) => {
    const old = latest(all.filter((c) => c.scriptId === id && c.schemeVersion === step.from))!;
    const next = all.find((c) => c.supersedes === old.credentialId) ?? latest(all.filter((c) => c.scriptId === id && c.schemeVersion === step.to));
    return { id, old, next, entry: entryFor(data, old.credentialId) };
  });
  const regraded = rows.filter((r) => r.next && r.next.total !== r.old.total);
  const moved = [
    ...new Set(
      rows.flatMap((r) => (r.next ? r.next.criteria.filter((k) => r.old.criteria.find((o) => o.id === k.id)?.points !== k.points).map((k) => k.id) : [])),
    ),
  ].sort();
  const changed = declared.length ? declared : moved;
  const reason = rows.find((r) => r.entry)?.entry?.reason;
  const added = rows.filter((r) => r.entry).length;
  const listSize = data.revocations.list?.entries.length ?? 0;

  return (
    <article className="card">
      <header>
        <h3>
          {step.schemeId}: {step.from} → {step.to}
        </h3>
      </header>
      <div className="stats">
        <div>
          <b>{changed.length}</b>
          <span>{declared.length ? "criteria changed" : "criteria moved a grade"}</span>
        </div>
        <div>
          <b>{rows.length}</b>
          <span>scripts re-marked</span>
        </div>
        <div>
          <b>{regraded.length}</b>
          <span>grades changed</span>
        </div>
        <div>
          <b>
            {listSize - added} → {listSize}
          </b>
          <span>revocation list entries</span>
        </div>
      </div>
      {note && <p>{note}</p>}
      {!note && reason && <p className="small">{reason}</p>}
      {declared.map((id) => (
        <div key={id} className="diff">
          <strong>{id}</strong>
          <p>
            <span className="was">{criterionText(data, step.schemeId, step.from, id) ?? `${step.from} wording not published`}</span>
            <span className="now">{criterionText(data, step.schemeId, step.to, id) ?? `${step.to} wording not published`}</span>
          </p>
        </div>
      ))}
      <h4>Every script under {step.from}</h4>
      {rows.map(({ id, old, next, entry }) => (
        <div key={id} className={`remark-row ${next && next.total !== old.total ? "changed" : ""}`}>
          <p>
            <strong>Script {id}</strong>:{" "}
            {next ? (
              next.total !== old.total ? (
                <>
                  grade {old.total}/{old.max} → <b>{next.total}/{next.max}</b>
                </>
              ) : (
                <>
                  re-issued, grade unchanged at {next.total}/{next.max}
                </>
              )
            ) : (
              <>unchanged at {old.total}/{old.max}; its credential stays valid</>
            )}
          </p>
          {next && next.total !== old.total && <CriteriaTable data={data} credential={next} compare={old} />}
          <p className="small">
            Old <a href={href("verify", { id: old.credentialId })}>{old.credentialId}</a>: {entry ? <b>{entry.status}</b> : "valid"}
            {entry && <> — {entry.reason}</>}
            {next && (
              <>
                {" "}
                · new <a href={href("verify", { id: next.credentialId })}>{next.credentialId}</a>
              </>
            )}
          </p>
        </div>
      ))}
    </article>
  );
}

export function RemarkPage({ data }: { data: SiteData }) {
  const all = steps(data);
  return (
    <section className="page">
      <h2>Re-mark after a scheme change</h2>
      <p className="muted">
        A new scheme version written to S3 starts the re-mark. Code finds every script marked under the old version, marks it
        again, re-signs the grades that changed and adds the old credentials to the signed revocation list.
      </p>
      {all.length ? all.map((s) => <StepView key={`${s.schemeId}-${s.from}-${s.to}`} data={data} step={s} />) : <p>No scheme change is published yet.</p>}
    </section>
  );
}
