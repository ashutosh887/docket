import { appealsOf, dataUrl, entryFor, type Appeal } from "../data";
import { href } from "../route";
import type { SiteData } from "../types";

const grade = (total: number | undefined, max: number | undefined) => (total === undefined ? "not published" : `${total}${max !== undefined ? `/${max}` : ""}`);

function Calls({ appeal }: { appeal: Appeal }) {
  const calls = appeal.record?.calls ?? [];
  if (!calls.length) return null;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Criterion</th>
            <th title="Reader A after the swap">A</th>
            <th title="Reader B after the swap">B</th>
            <th>Routed because</th>
            <th>Points</th>
          </tr>
        </thead>
        <tbody>
          {calls.map((c) => {
            const moved = typeof c.before === "number" && c.before !== c.points;
            return (
              <tr key={c.id} className={moved ? "moved" : undefined}>
                <td>
                  <strong>{c.id}</strong>
                </td>
                <td>{c.readerA}</td>
                <td>{c.readerB}</td>
                <td>{c.decidedBy === "teacher" ? c.why ?? "teacher" : "readers agreed"}</td>
                <td>
                  {moved && <s>{c.before}</s>} {c.points}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function AppealCard({ data, appeal }: { data: SiteData; appeal: Appeal }) {
  const status = appeal.entry?.status ?? entryFor(data, appeal.oldId)?.status;
  const r = appeal.record;
  const changed = appeal.oldTotal !== appeal.newTotal;
  return (
    <article className="card">
      <header>
        <h3>Script {appeal.scriptId}</h3>
        {appeal.outcome && <span className={`tag ${appeal.outcome === "upheld" ? "over" : ""}`}>{appeal.outcome === "upheld" ? "appeal upheld" : appeal.outcome}</span>}
      </header>
      {appeal.reason && (
        <p>
          <span className="muted">Reason: </span>
          {appeal.reason}
        </p>
      )}
      <div className="stats two">
        <div>
          <b>{grade(appeal.oldTotal, appeal.max)}</b>
          <span>old grade</span>
        </div>
        <div>
          <b>{grade(appeal.newTotal, appeal.max)}</b>
          <span>{changed ? "new grade" : "grade stands"}</span>
        </div>
      </div>
      <Calls appeal={appeal} />
      {r?.readers?.a && (
        <p className="small">
          Readers swapped: A is now <code>{r.readers.a}</code>, B is <code>{r.readers.b}</code>.
          {r.swapCheck && <> Swapping changed {r.swapCheck.sameCalls ? "no reading" : `${r.swapCheck.differences?.length ?? "some"} readings`}.</>}
          {typeof r.modelCalls === "number" && <> Model calls: {r.modelCalls} (cached readings).</>}
        </p>
      )}
      {r?.teacher?.note && <p className="small muted">Teacher note: {r.teacher.note}</p>}
      <p className="small">
        Old <a href={href("verify", { id: appeal.oldId })}>{appeal.oldId}</a>: {status ? <b>{status}</b> : "still valid"}
        {appeal.entry && <> ({appeal.entry.reason})</>}
        {appeal.newId && (
          <>
            {" "}
            · new {data.credentials.has(appeal.newId) ? <a href={href("verify", { id: appeal.newId })}>{appeal.newId}</a> : <code>{appeal.newId}</code>}
          </>
        )}
        {r && (
          <>
            {" "}
            · <a href={dataUrl(r.file)}>appeal record</a>
            {r.signed !== null && <>, signature {r.signed ? "checked" : "does not verify"}</>}
          </>
        )}
      </p>
    </article>
  );
}

export function AppealsPage({ data }: { data: SiteData }) {
  const all = appealsOf(data);
  const upheld = all.filter((a) => a.newId).length;
  return (
    <section className="page">
      <h2>Appeals</h2>
      <p className="muted">
        A student appeals a grade. Docket marks the script again from the cached readings with the two readers swapped, and a teacher
        reviews every appealed criterion. If the grade changes, Docket signs a new credential and lists the old one on the signed
        revocation list, so the old credential still verifies but reads superseded.
      </p>
      <p className="small">
        {all.length} {all.length === 1 ? "appeal" : "appeals"}: {upheld} upheld with a new signed credential, {all.length - upheld} with the grade unchanged.
      </p>
      {all.map((a) => (
        <AppealCard key={a.oldId} data={data} appeal={a} />
      ))}
    </section>
  );
}
