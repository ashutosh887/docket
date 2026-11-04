import { callFor, criterionText, firstMarking, officialFor, scriptIds } from "../data";
import { href } from "../route";
import type { Credential, Criterion, SiteData } from "../types";

interface Row {
  id: string;
  credential: Credential;
  official: number | undefined;
}

function rows(data: SiteData): Row[] {
  return scriptIds(data)
    .map((id) => ({ id, credential: firstMarking(data, id)!, official: officialFor(data, id) }))
    .filter((r) => r.credential);
}

const met = (v: number) => (v === 1 ? "met" : "not met");

function Readings({ data, scriptId, k }: { data: SiteData; scriptId: string; k: Criterion }) {
  const seen = data.evidence[scriptId];
  return (
    <p className="small readings">
      {(["a", "b"] as const).map((side) => {
        const value = side === "a" ? k.readerA : k.readerB;
        const quote = seen?.[side][k.id]?.evidence;
        const confidence = seen?.[side][k.id]?.confidence;
        return (
          <span key={side}>
            <b>{side.toUpperCase()}</b> {met(value)}
            {typeof confidence === "number" && <span className="muted"> ({confidence})</span>}
            {quote && <span className="quote">: {quote}</span>}
          </span>
        );
      })}
    </p>
  );
}

function Differs({ data, row }: { data: SiteData; row: Row }) {
  const c = row.credential;
  const teacher = c.criteria.filter((k) => k.decidedBy === "teacher");
  const agreed = c.criteria.filter((k) => k.decidedBy === "code");
  const official = row.official as number;
  return (
    <article className="card mod-card">
      <header>
        <h3>Script {row.id}</h3>
        <span className={c.total > official ? "tag over" : "tag under"}>
          Docket {c.total}/{c.max} · official {official}/{c.max}
        </span>
      </header>
      <p className="small">
        {teacher.length === 0
          ? `Both readers agreed on all ${agreed.length} criteria, so code signed the grade and no teacher saw it.`
          : `The readers agreed on ${agreed.length} of ${c.criteria.length} criteria; a teacher decided ${teacher.map((k) => k.id).join(", ")}.`}{" "}
        The grade is {c.total > official ? `${c.total - official} above` : `${official - c.total} below`} the official one.
      </p>
      <ul className="crit-list">
        {c.criteria.map((k) => (
          <li key={k.id}>
            <p className="small">
              <strong>{k.id}</strong> {k.points}/{k.max}, {k.decidedBy === "teacher" ? <span className="tag teacher">teacher</span> : <span className="tag">readers agreed</span>}
              {criterionText(data, c.schemeId, c.schemeVersion, k.id) && <span className="muted"> {criterionText(data, c.schemeId, c.schemeVersion, k.id)}</span>}
            </p>
            <Readings data={data} scriptId={row.id} k={k} />
          </li>
        ))}
      </ul>
      <p className="small">
        <a href={href("scripts", { script: row.id })}>Scan and full marking</a> · <a href={href("verify", { id: c.credentialId })}>{c.credentialId}</a>
      </p>
    </article>
  );
}

export function ModerationPage({ data }: { data: SiteData }) {
  const all = rows(data);
  const criteria = all.flatMap((r) => r.credential.criteria.map((k) => ({ row: r, k })));
  const routed = criteria.filter(({ k }) => k.decidedBy === "teacher");
  const graded = all.filter((r) => r.official !== undefined);
  const differ = graded.filter((r) => r.official !== r.credential.total);
  const above = differ.filter((r) => r.credential.total > (r.official as number)).length;
  const straightWrong = differ.filter((r) => r.credential.criteria.every((k) => k.decidedBy === "code")).length;
  const versions = [...new Set(all.map((r) => r.credential.schemeVersion))].join(", ");

  return (
    <section className="page">
      <h2>Moderation</h2>
      <p className="muted">
        An exam board's moderators sample marked scripts and compare them with a senior examiner's grade. This page does that for
        every script in the class set: each script's first signed grade (scheme {versions}) against the official CHECK-MAT expert
        grade, and every criterion the graph sent to a teacher.
      </p>
      <div className="stats">
        <div>
          <b>
            {routed.length} of {criteria.length}
          </b>
          <span>criteria routed to a teacher</span>
        </div>
        <div>
          <b>
            {differ.length} of {graded.length}
          </b>
          <span>signed grades differ from the official grade</span>
        </div>
        <div>
          <b>{above}</b>
          <span>of those are above the official grade</span>
        </div>
        <div>
          <b>{straightWrong}</b>
          <span>of those had no teacher: both readers agreed</span>
        </div>
      </div>
      <p className="small">
        {routed.length} of {criteria.length} criteria routed to a teacher; {differ.length} signed {differ.length === 1 ? "grade differs" : "grades differ"} from the
        official grade.
        {straightWrong > 0 &&
          ` ${straightWrong === differ.length ? "Every one" : `${straightWrong} of them`} went straight to the signer because both readers agreed, which is why a moderator still samples agreed scripts.`}
      </p>

      <h3>Grades that differ from the official grade</h3>
      {differ.length ? differ.map((r) => <Differs key={r.id} data={data} row={r} />) : <p>Every signed grade matches the official grade.</p>}

      <h3>Criteria a teacher decided</h3>
      {routed.length ? (
        <div className="card">
          <ul className="crit-list">
            {routed.map(({ row, k }) => {
              const call = callFor(data, row.id, k.id);
              return (
                <li key={`${row.id}-${k.id}`}>
                  <p className="small">
                    <a href={href("scripts", { script: row.id })}>Script {row.id}</a> <strong>{k.id}</strong>: stopped because{" "}
                    <b>{call?.reason ?? (k.readerA !== k.readerB ? "readers disagree" : "the comparator flagged it")}</b> (A {k.readerA}, B {k.readerB}, margin{" "}
                    {k.margin}). Teacher gave {k.points}/{k.max}.
                    {row.official !== undefined && (
                      <span className="muted">
                        {" "}
                        Script grade {row.credential.total}/{row.credential.max}, official {row.official}.
                      </span>
                    )}
                  </p>
                  <Readings data={data} scriptId={row.id} k={k} />
                  {row.credential.teacher.note && <p className="small muted">Teacher note: {row.credential.teacher.note}</p>}
                </li>
              );
            })}
          </ul>
        </div>
      ) : (
        <p>No criterion was routed to a teacher.</p>
      )}
    </section>
  );
}
