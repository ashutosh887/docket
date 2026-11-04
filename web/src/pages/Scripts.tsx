import { Fragment, useEffect } from "react";
import { criterionText, currentFor, dataUrl, entryFor, scriptIds } from "../data";
import { href } from "../route";
import type { Credential, Pending, SiteData } from "../types";

export function CriteriaTable({ data, credential, compare }: { data: SiteData; credential: Credential; compare?: Credential }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Criterion</th>
            <th title="Reader A">A</th>
            <th title="Reader B">B</th>
            <th>Margin</th>
            <th>Points</th>
            <th>Decided</th>
          </tr>
        </thead>
        <tbody>
          {credential.criteria.map((k) => {
            const before = compare?.criteria.find((c) => c.id === k.id);
            const moved = before && before.points !== k.points;
            const text = criterionText(data, credential.schemeId, credential.schemeVersion, k.id);
            const seen = data.evidence[credential.scriptId];
            return (
              <Fragment key={k.id}>
              <tr className={`${moved ? "moved" : ""} ${text || seen?.a[k.id]?.evidence || seen?.b[k.id]?.evidence ? "has-text" : ""}`}>
                <td>
                  <strong>{k.id}</strong>
                </td>
                <td>{k.readerA}</td>
                <td>{k.readerB}</td>
                <td className={k.readerA !== k.readerB ? "warn" : undefined}>{k.margin}</td>
                <td>
                  {moved && <s>{before.points}</s>} {k.points}/{k.max}
                </td>
                <td>{k.decidedBy === "teacher" ? <span className="tag teacher">teacher</span> : <span className="tag">code</span>}</td>
              </tr>
              {text && (
                <tr className={`crit-row ${moved ? "moved" : ""}`}>
                  <td colSpan={6}>{text}</td>
                </tr>
              )}
              {(seen?.a[k.id]?.evidence || seen?.b[k.id]?.evidence) && (
                <tr className={`crit-row evidence ${moved ? "moved" : ""}`}>
                  <td colSpan={6}>
                    {(["a", "b"] as const).map((side) =>
                      seen?.[side][k.id]?.evidence ? (
                        <span key={side}>
                          <b>{side.toUpperCase()}</b> {seen[side][k.id].evidence}
                        </span>
                      ) : null,
                    )}
                  </td>
                </tr>
              )}
              </Fragment>
            );
          })}
        </tbody>
        <tfoot>
          <tr>
            <td colSpan={4}>Total</td>
            <td colSpan={2}>
              {compare && compare.total !== credential.total && <s>{compare.total}</s>} {credential.total}/{credential.max}
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

function ScriptCard({ data, id }: { data: SiteData; id: string }) {
  const current = currentFor(data, id);
  if (!current) return null;
  const history = [...data.credentials.values()].map((c) => c.doc).filter((c) => c.scriptId === id && c.credentialId !== current.credentialId);
  const image = data.index.images[id];
  const official = (data.readings[id] as { officialScore?: number }[] | undefined)?.find((d) => typeof d.officialScore === "number")?.officialScore;
  return (
    <article className="card" id={`script-${id}`}>
      <header>
        <h3>Script {id}</h3>
        <span className="muted">
          {current.schemeId} · scheme {current.schemeVersion}
        </span>
      </header>
      <div className="split">
        {image ? (
          <a className="scan" href={dataUrl(image)}>
            <img src={dataUrl(image)} alt={`Scan of script ${id}`} />
          </a>
        ) : (
          <div className="scan none">No scan published</div>
        )}
        <div>
          <CriteriaTable data={data} credential={current} />
          {current.teacher.decided.length > 0 && (
            <p className="small">
              The readers disagreed on {current.teacher.decided.join(", ")}, so the graph stopped and a teacher decided.
              {current.teacher.note && <> Note: “{current.teacher.note}”</>}
            </p>
          )}
          {official !== undefined && (
            <p className="small">
              Official expert grade (CHECK-MAT): <strong>{official}/{current.max}</strong>
              {official !== current.total && <span className="warn-text"> · differs from Docket's {current.total}</span>}
            </p>
          )}
          {current.route && (
            <p className="small">
              Graph route: <strong>{current.route === "teacher" ? "stopped at the teacher interrupt, then signed" : "straight to the signer"}</strong>
            </p>
          )}
          <p className="small muted">
            Reader A: <code>{current.readers.a}</code> · Reader B: <code>{current.readers.b}</code>
          </p>
          <p className="small">
            <span className="muted">Image SHA-256 </span>
            <code>{current.imageSha256.slice(0, 16)}…</code>
          </p>
          <p className="small">
            Credential <a href={href("verify", { id: current.credentialId })}>{current.credentialId}</a>
            {history.map((h) => (
              <span key={h.credentialId} className="history">
                {" "}
                · earlier <a href={href("verify", { id: h.credentialId })}>{h.credentialId}</a> ({entryFor(data, h.credentialId)?.status ?? "valid"})
              </span>
            ))}
          </p>
        </div>
      </div>
    </article>
  );
}

function PendingCard({ data, pending }: { data: SiteData; pending: Pending }) {
  const image = data.index.images[pending.scriptId];
  const contested = pending.interrupt?.reason?.contested ?? [];
  return (
    <article className="card pending" id={`script-${pending.scriptId}`}>
      <header>
        <h3>Script {pending.scriptId}</h3>
        <span className="tag teacher">waiting for a teacher</span>
      </header>
      <div className="split">
        {image ? (
          <a className="scan" href={dataUrl(image)}>
            <img src={dataUrl(image)} alt={`Scan of script ${pending.scriptId}`} />
          </a>
        ) : (
          <div className="scan none">No scan published</div>
        )}
        <div>
          <p className="small">
            The readers disagreed, so the Strands graph stopped at the teacher interrupt before signing. No credential exists until a
            teacher decides {contested.map((c) => c.id).join(", ")}.
          </p>
          {contested.map((c) => (
            <div key={c.id} className="diff">
              <strong>{c.id}</strong>
              {c.criterion && <p className="small muted">{c.criterion}</p>}
              <p className="small">
                <span>
                  <b>A</b> {c.readings?.a?.met ? "met" : "not met"} ({c.readerA}): {c.readings?.a?.evidence}
                </span>
                <span>
                  <b>B</b> {c.readings?.b?.met ? "met" : "not met"} ({c.readerB}): {c.readings?.b?.evidence}
                </span>
              </p>
            </div>
          ))}
        </div>
      </div>
    </article>
  );
}

export function ScriptsPage({ data, focus }: { data: SiteData; focus: string | null }) {
  useEffect(() => {
    if (focus) document.getElementById(`script-${focus}`)?.scrollIntoView();
  }, [focus]);
  return (
    <section className="page">
      <h2>Scripts</h2>
      <p className="muted">
        Each criterion shows both readings (1 = met) and what each reader quoted from the page. When they agree, code awards the
        points. When they differ, the teacher decides. The margin is how far apart the readers' confidence was.
      </p>
      {scriptIds(data).map((id) => (
        <ScriptCard key={id} data={data} id={id} />
      ))}
      {data.pending
        .filter((p) => !currentFor(data, p.scriptId) || p.schemeVersion !== currentFor(data, p.scriptId)?.schemeVersion)
        .map((p) => (
          <PendingCard key={p.scriptId} data={data} pending={p} />
        ))}
    </section>
  );
}
