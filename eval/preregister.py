import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = ["docs/proof.md", "eval/slice.py", "eval/slice_seeded61.json", "eval/summarize.py", "eval/run_agreement.py", "eval/route.py"]


def git(*args):
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else None


def main():
    path = ROOT / "eval" / "results" / "preregistration.json"
    if path.exists():
        print(path.read_text())
        return
    record = {
        "metric": "preregistration",
        "recordedAt": datetime.now(timezone.utc).isoformat(),
        "sha256": {f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest() for f in FILES},
        "proofCommit": git("log", "-1", "--format=%H %cI", "--", "docs/proof.md"),
    }
    path.write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
