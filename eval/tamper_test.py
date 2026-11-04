import argparse
import base64
import json
import string
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

ROOT = Path(__file__).resolve().parent.parent
EVAL = ROOT / "eval"
WORK = EVAL / "runs" / "tamper"

DIGITS = string.digits
HEX = "0123456789abcdef"
LETTERS = string.ascii_letters
PUNCT = '{}[]:,"'


def canonical(doc, ascii_only):
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=ascii_only)


def python_verify(public_key, doc):
    sig = (doc.get("signature") or {}).get("value") if isinstance(doc, dict) else None
    if not sig:
        return False
    try:
        der = base64.b64decode(sig, validate=True)
    except Exception:
        return False
    body = {k: v for k, v in doc.items() if k != "signature"}
    for ascii_only in (False, True):
        try:
            public_key.verify(der, canonical(body, ascii_only).encode("utf-8"), ec.ECDSA(hashes.SHA256()))
            return True
        except (InvalidSignature, ValueError):
            continue
    return False


def hex_spans(payload):
    spans = set()
    marker = '"imageSha256":"'
    start = payload.find(marker)
    if start != -1:
        start += len(marker)
        end = payload.find('"', start)
        spans.update(range(start, end))
    return spans


def replacement(ch, klass):
    pool = {"hash": HEX, "digit": DIGITS, "letter": LETTERS, "punctuation": PUNCT}.get(klass, DIGITS + LETTERS)
    for candidate in pool:
        if candidate != ch:
            return candidate
    return "x"


def classify(ch, index, hex_positions):
    if index in hex_positions:
        return "hash"
    if ch in DIGITS:
        return "digit"
    if ch in LETTERS:
        return "letter"
    if ch in PUNCT:
        return "punctuation"
    return "other"


def cases_for(name, doc):
    body = {k: v for k, v in doc.items() if k != "signature"}
    payload = canonical(body, False)
    hex_positions = hex_spans(payload)
    cases = []
    for i, ch in enumerate(payload):
        klass = classify(ch, i, hex_positions)
        tampered = payload[:i] + replacement(ch, klass) + payload[i + 1:]
        try:
            parsed = json.loads(tampered)
        except json.JSONDecodeError:
            cases.append({"doc": name, "class": klass, "position": i, "parses": False, "text": None})
            continue
        if not isinstance(parsed, dict):
            cases.append({"doc": name, "class": klass, "position": i, "parses": False, "text": None})
            continue
        parsed["signature"] = doc["signature"]
        cases.append({"doc": name, "class": klass, "position": i, "parses": True, "text": json.dumps(parsed, ensure_ascii=False)})
    sig = doc["signature"]["value"]
    for i, ch in enumerate(sig):
        if ch == "=":
            continue
        swapped = "A" if ch != "A" else "B"
        mutated = json.loads(json.dumps(doc))
        mutated["signature"]["value"] = sig[:i] + swapped + sig[i + 1:]
        cases.append({"doc": name, "class": "signature", "position": i, "parses": True, "text": json.dumps(mutated, ensure_ascii=False)})
    return cases


def web_verify(pem_path, cases):
    WORK.mkdir(parents=True, exist_ok=True)
    path = WORK / "cases.jsonl"
    path.write_text("\n".join(json.dumps({"text": c["text"]}, ensure_ascii=False) for c in cases) + "\n")
    out = subprocess.run(["node", str(EVAL / "web_verify.mjs"), str(pem_path), str(path)], capture_output=True, text=True, check=True)
    return [ch == "1" for ch in out.stdout.strip()]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--revocations", type=Path, required=True)
    parser.add_argument("--pem", type=Path, required=True)
    parser.add_argument("--label", default="")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    public_key = serialization.load_pem_public_key(args.pem.read_bytes())
    docs = {}
    paths = sorted(args.credentials.glob("*.json"))
    if args.limit:
        paths = paths[: args.limit]
    for path in paths:
        docs[f"credential:{path.name}"] = json.loads(path.read_text())
    docs[f"revocations:{args.revocations.name}"] = json.loads(args.revocations.read_text())
    controls = {name: python_verify(public_key, doc) for name, doc in docs.items()}
    control_web = web_verify(args.pem, [{"text": json.dumps(d, ensure_ascii=False)} for d in docs.values()])
    unsigned = [n for n, ok in controls.items() if not ok]
    all_cases = []
    for name, doc in docs.items():
        if controls[name]:
            all_cases.extend(cases_for(name, doc))
    parsed_cases = [c for c in all_cases if c["parses"]]
    web_results = web_verify(args.pem, parsed_cases) if parsed_cases else []
    for c, ok in zip(parsed_cases, web_results):
        c["webVerified"] = ok
    for c in parsed_cases:
        c["pythonVerified"] = python_verify(public_key, json.loads(c["text"]))
    by_class = Counter()
    rejected = Counter()
    accepted = []
    for c in all_cases:
        by_class[c["class"]] += 1
        ok = c["parses"] and (c.get("webVerified") or c.get("pythonVerified"))
        if not ok:
            rejected[c["class"]] += 1
        else:
            accepted.append({**{k: c[k] for k in ("doc", "class", "position")}, "web": bool(c.get("webVerified")), "python": bool(c.get("pythonVerified"))})
    key_ids = sorted({(d.get("signature") or {}).get("keyId") for d in docs.values()})
    result = {
        "metric": "tamper",
        "label": args.label,
        "keyIds": key_ids,
        "pem": str(args.pem.relative_to(ROOT)) if args.pem.is_relative_to(ROOT) else str(args.pem),
        "credentials": len(docs) - 1,
        "revocationLists": 1,
        "controlsVerifiedPython": sum(controls.values()),
        "controlsVerifiedWeb": sum(control_web),
        "controlsTotal": len(docs),
        "controlsNotVerifying": unsigned,
        "method": "one character changed at every position of each signed payload, and one base64 character of each signature; verified with the published public key by the page's own verifySigned (web/src/crypto.ts in Node WebCrypto) and by Python cryptography",
        "total": len(all_cases),
        "passed": sum(rejected.values()),
        "rejectedBeforeSignatureCheck": sum(1 for c in all_cases if not c["parses"]),
        "parts": [
            {"label": f"{klass} characters", "class": klass, "total": by_class[klass], "passed": rejected[klass]}
            for klass in sorted(by_class)
        ],
        "acceptedTampered": accepted,
        "acceptedByWeb": sum(a["web"] for a in accepted),
        "acceptedByPython": sum(a["python"] for a in accepted),
        "writtenAt": datetime.now(timezone.utc).isoformat(),
    }
    (EVAL / "results" / "tamper.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("label", "keyIds", "controlsVerifiedPython", "controlsVerifiedWeb", "controlsTotal", "total", "passed", "rejectedBeforeSignatureCheck", "acceptedByWeb", "acceptedByPython")}, indent=2))
    print(json.dumps(result["parts"], indent=2))
    if accepted:
        print("ACCEPTED TAMPERED:", json.dumps(accepted[:20]))


if __name__ == "__main__":
    main()
