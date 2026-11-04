import { Component, Suspense, use, type ReactNode } from "react";
import { siteData } from "./data";
import { PAGES, href, useRoute, type Route } from "./route";
import { VerifyPage } from "./pages/Verify";
import { ScriptsPage } from "./pages/Scripts";
import { RemarkPage } from "./pages/Remark";
import { HowPage } from "./pages/How";

function Body({ route }: { route: Route }) {
  const data = use(siteData());
  return (
    <>
      {route.page === "verify" && <VerifyPage data={data} initial={route.params.get("id")} />}
      {route.page === "scripts" && <ScriptsPage data={data} focus={route.params.get("script")} />}
      {route.page === "remark" && <RemarkPage data={data} />}
      {route.page === "how" && <HowPage />}
      <footer className="foot">
        {data.index.source === "fixture"
          ? "Sample scripts, signed with a local test key while the live run is prepared."
          : `Credentials signed by AWS KMS (${[...data.credentials.values()][0]?.doc.signature.keyId ?? "key"}). Public key: /keys/docket-public.pem.`}
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
          {PAGES.map((p) => (
            <a key={p.id} href={href(p.id)} aria-current={route.page === p.id ? "page" : undefined}>
              {p.label}
            </a>
          ))}
        </nav>
      </header>
      <section className="lead">
        <h1>When the exam board corrects its marking scheme, which students' grades are now wrong, and who fixes them?</h1>
        <p>
          Docket marks photos of handwritten exam scripts with two vision readers from different model families. Plain code applies
          the marking scheme, a teacher decides every disagreement, and each grade is a signed credential anyone can check. When the
          scheme changes, Docket re-marks the affected scripts and lists the old grades on a signed revocation list.
        </p>
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
