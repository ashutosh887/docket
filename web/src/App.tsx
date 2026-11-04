import { Component, Suspense, use, type ReactNode } from "react";
import { appealsOf, entryFor, isAppealEntry, siteData } from "./data";
import { headline } from "./results";
import { PAGES, href, useRoute, type Page, type Route } from "./route";
import { VerifyPage } from "./pages/Verify";
import { ScriptsPage } from "./pages/Scripts";
import { RemarkPage } from "./pages/Remark";
import { HowPage } from "./pages/How";
import { ModerationPage } from "./pages/Moderation";
import { AppealsPage } from "./pages/Appeals";

function Result() {
  const h = use(headline());
  if (!h) return <h1>When the exam board corrects its marking scheme, which students' grades are now wrong, and who fixes them?</h1>;
  const d = h.docket;
  const significant = h.mcnemarExactP !== null && h.mcnemarExactP < 0.05;
  return (
    <>
      <p className="kicker">When the exam board corrects its marking scheme, which students' grades are now wrong, and who fixes them?</p>
      <h1>
        {d.exact.k} of {d.exact.n} handwritten exam scripts got the official examiners' exact grade.
      </h1>
      <p className="result">
        {d.exact.pct}% exact (95% CI {d.exact.low} to {d.exact.high}), {d.withinOne.k} of {d.withinOne.n} within one point, on the{" "}
        {d.scripts} task-13 scripts of CHECK-MAT with one vision reader and a code answer key.
        {h.baseline && (
          <>
            {" "}
            The dataset authors' best published result on the same {h.baseline.scripts} scripts is {h.baseline.exact} of {h.baseline.scripts}.
            {h.mcnemarExactP !== null && (significant ? ` The gap is significant (McNemar p = ${h.mcnemarExactP.toFixed(2)}).` : ` At n = ${d.scripts} the gap is not statistically significant (McNemar p = ${h.mcnemarExactP.toFixed(2)}).`)}
          </>
        )}
      </p>
      <p className="small muted">
        Read from {h.files.map((f, i) => (
          <span key={f}>
            {i > 0 && " and "}
            <code>{f}</code>
          </span>
        ))}
        .
      </p>
    </>
  );
}

function TryIt() {
  const data = use(siteData());
  const ids = [...data.credentials.keys()].sort();
  const valid = ids.find((id) => !entryFor(data, id));
  const superseded = ids.find((id) => isAppealEntry(entryFor(data, id))) ?? ids.find((id) => entryFor(data, id));
  return (
    <ol className="try">
      <li>
        <b>Pick a credential.</b> <a href={href("verify", valid ? { id: valid } : undefined)}>Open {valid ?? "one"} in Verify</a>.
      </li>
      <li>
        <b>Verify.</b> Your browser checks the AWS KMS signature and the signed revocation list. The verdict reads Valid.
      </li>
      <li>
        <b>Tamper.</b> Press "Tamper: flip one byte". The verdict turns to Signature invalid.
      </li>
      {superseded && (
        <li>
          <b>See a replaced grade.</b> <a href={href("verify", { id: superseded })}>Open {superseded}</a>: still signed, but listed as superseded.
        </li>
      )}
    </ol>
  );
}

function AppealsLink({ current }: { current: Page }) {
  const data = use(siteData());
  if (!appealsOf(data).length) return null;
  return (
    <a href={href("appeals")} aria-current={current === "appeals" ? "page" : undefined}>
      Appeals
    </a>
  );
}

function Body({ route }: { route: Route }) {
  const data = use(siteData());
  return (
    <>
      {route.page === "verify" && <VerifyPage data={data} initial={route.params.get("id")} />}
      {route.page === "scripts" && <ScriptsPage data={data} focus={route.params.get("script")} />}
      {route.page === "moderation" && <ModerationPage data={data} />}
      {route.page === "remark" && <RemarkPage data={data} />}
      {route.page === "appeals" && (appealsOf(data).length ? <AppealsPage data={data} /> : <p>No appeal is published yet.</p>)}
      {route.page === "how" && <HowPage />}
      <footer className="foot">
        {data.index.source === "fixture"
          ? "Sample scripts, signed with a local test key while the live run is prepared."
          : `Credentials signed by AWS KMS (${[...data.credentials.values()][0]?.doc.signature.keyId ?? "key"}). Public key: /keys/docket-public.pem.`}{" "}
        <a href="https://github.com/ashutosh887/docket">Code on GitHub</a> · <a href="https://youtu.be/ILI1JPPAMmU">Demo video</a>
      </footer>
    </>
  );
}

class Failure extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  render() {
    return this.state.error ? <p className="verdict v-invalid">Could not load the published data: {this.state.error.message}</p> : this.props.children;
  }
}

export function App() {
  const route = useRoute();
  return (
    <div className="shell">
      <header className="top">
        <a className="mark" href={href("verify")}>
          Docket
        </a>
        <nav>
          {PAGES.map((p) =>
            p.id === "appeals" ? (
              <Suspense key={p.id} fallback={null}>
                <AppealsLink current={route.page} />
              </Suspense>
            ) : (
              <a key={p.id} href={href(p.id)} aria-current={route.page === p.id ? "page" : undefined}>
                {p.label}
              </a>
            ),
          )}
        </nav>
      </header>
      <section className={route.page === "verify" ? "lead" : "lead compact"}>
        <Suspense fallback={<h1>When the exam board corrects its marking scheme, which students' grades are now wrong, and who fixes them?</h1>}>
          <Result />
        </Suspense>
        <p>
          Docket marks photos of handwritten exam scripts with two vision readers from different model families. Plain code applies
          the marking scheme, a teacher decides every disagreement, and each grade is a signed credential anyone can check. When the
          scheme changes, Docket re-marks the affected scripts and lists the old grades on a signed revocation list.
        </p>
        {route.page === "verify" && (
          <Failure>
            <Suspense fallback={null}>
              <h2 className="try-title">Try it</h2>
              <TryIt />
            </Suspense>
          </Failure>
        )}
      </section>
      <main>
        <Failure>
          <Suspense fallback={<p className="muted">Loading credentials…</p>}>
            <Body route={route} />
          </Suspense>
        </Failure>
      </main>
    </div>
  );
}
