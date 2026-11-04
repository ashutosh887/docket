function Node({ x, y, w, label, sub, tone }: { x: number; y: number; w: number; label: string; sub?: string; tone?: string }) {
  return (
    <g className={`node ${tone ?? ""}`}>
      <rect x={x} y={y} width={w} height={sub ? 52 : 40} rx={8} />
      <text x={x + w / 2} y={y + (sub ? 22 : 25)} textAnchor="middle" className="label">
        {label}
      </text>
      {sub && (
        <text x={x + w / 2} y={y + 40} textAnchor="middle" className="sub">
          {sub}
        </text>
      )}
    </g>
  );
}

function Edge({ d, label, lx, ly, dashed }: { d: string; label?: string; lx?: number; ly?: number; dashed?: boolean }) {
  return (
    <g className="edge">
      <path d={d} markerEnd="url(#arrow)" strokeDasharray={dashed ? "5 4" : undefined} />
      {label && (
        <text x={lx} y={ly} textAnchor="middle" className="edge-label">
          {label}
        </text>
      )}
    </g>
  );
}

function GraphDiagram() {
  return (
    <svg className="diagram" viewBox="0 0 400 520" role="img" aria-label="Strands Graph: ReaderA and ReaderB feed the Comparator; agreement goes to the Signer, disagreement to the TeacherInterrupt and then the Signer.">
      <defs>
        <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" />
        </marker>
      </defs>
      <Node x={120} y={10} w={160} label="Script photo" sub="S3, SHA-256 kept" tone="io" />
      <Node x={20} y={100} w={160} label="ReaderA" sub="vision model, family 1" />
      <Node x={220} y={100} w={160} label="ReaderB" sub="vision model, family 2" />
      <Node x={120} y={200} w={160} label="Comparator" sub="plain code, per criterion" tone="code" />
      <Node x={220} y={310} w={160} label="TeacherInterrupt" sub="Strands interrupt" tone="human" />
      <Node x={20} y={410} w={160} label="Signer" sub="AWS KMS, ECDSA P-256" tone="code" />
      <Node x={220} y={420} w={160} label="Signed credential" tone="io" />
      <Edge d="M170 62 L110 98" />
      <Edge d="M230 62 L290 98" />
      <Edge d="M100 152 L170 198" />
      <Edge d="M300 152 L230 198" />
      <Edge d="M160 252 L100 408" label="readers agree" lx={92} ly={330} />
      <Edge d="M240 252 L290 308" label="readers differ" lx={300} ly={285} />
      <Edge d="M250 362 L160 408" label="teacher decides" lx={260} ly={395} />
      <Edge d="M180 440 L218 440" />
    </svg>
  );
}

const SERVICES: { name: string; decides: string }[] = [
  { name: "Strands Agents SDK (Graph)", decides: "Routes each script straight to the signer when the readers agree, or stops at the teacher interrupt when they differ." },
  { name: "AWS KMS", decides: "Signs the SHA-256 digest of every credential and of the revocation list. The private key never leaves KMS." },
  { name: "Amazon S3", decides: "Holds the scripts, credentials, scheme versions and revocation list. A new schemes/*.json is the event that starts a re-mark." },
  { name: "Amazon EventBridge", decides: "Sees a new scheme version land and starts the re-mark." },
  { name: "AWS Step Functions (Map)", decides: "Finds the scripts the new version affects and re-marks them in parallel, one branch per script." },
  { name: "AWS Lambda", decides: "Re-marks one script under the new scheme version and re-signs it if the grade changed." },
  { name: "Amazon CloudFront", decides: "Serves this page and the signed data. Verification runs in your browser, not on a server." },
];

export function HowPage() {
  return (
    <section className="page">
      <h2>How it works</h2>
      <p>
        <strong>The model reads, code decides.</strong> The readers return a reading per criterion as structured output. Plain code
        owns the points, the total, the routing, the signing and the re-marking.
      </p>
      <GraphDiagram />
      <h3>When the scheme changes</h3>
      <ol className="flow">
        <li>A new scheme version is written to S3 as schemes/&lt;id&gt;-&lt;version&gt;.json.</li>
        <li>EventBridge matches the object-created event and starts a Step Functions execution.</li>
        <li>The first step lists every current credential issued under the previous version.</li>
        <li>A Map state re-marks each of those scripts in parallel with the new scheme.</li>
        <li>Changed grades get new signed credentials; the old ones go on the signed revocation list as superseded, with the reason.</li>
      </ol>
      <h3>What each service decides</h3>
      <dl className="services">
        {SERVICES.map((s) => (
          <div key={s.name}>
            <dt>{s.name}</dt>
            <dd>{s.decides}</dd>
          </div>
        ))}
      </dl>
      <h3>Check it yourself</h3>
      <p className="small">
        The signed bytes are the credential without its <code>signature</code> field, as canonical JSON (sorted keys, no spaces,
        UTF-8). The signature is ECDSA P-256 over its SHA-256 digest, DER-encoded and base64. The public key is at{" "}
        <a href="keys/docket-public.pem">keys/docket-public.pem</a>.
      </p>
    </section>
  );
}
