import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "data" / "raw" / "Auto-check-EGE-math" / "model_results"
REPO = "https://github.com/Karifannaa/Auto-check-EGE-math/tree/main/model_results"


def main():
    rows = []
    for path in sorted(RESULTS.glob("*/*_analysis.json")):
        data = json.loads(path.read_text())
        for model, modes in data.get("models", {}).items():
            for mode, m in modes.items():
                if not isinstance(m, dict) or "accuracy" not in m:
                    continue
                rows.append({
                    "model": model,
                    "mode": mode,
                    "scripts": m.get("evaluations"),
                    "exactPct": round(m["accuracy"], 1),
                    "withinOnePct": round(m["close_accuracy"], 1),
                    "file": str(path.relative_to(RESULTS.parent)),
                })
    best = {}
    for r in rows:
        key = (r["model"], r["mode"])
        if key not in best or r["exactPct"] > best[key]["exactPct"]:
            best[key] = r
    out = {
        "metric": "published_baselines",
        "source": REPO,
        "note": "Numbers read from the CHECK-MAT repo's own model_results files; not run by Docket.",
        "readAt": datetime.now(timezone.utc).isoformat(),
        "rows": sorted(best.values(), key=lambda r: (-r["exactPct"], r["model"], r["mode"])),
    }
    (Path(__file__).parent / "results" / "published_baselines.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    for r in out["rows"][:8]:
        print(r["model"], r["mode"], r["scripts"], r["exactPct"], r["withinOnePct"])


if __name__ == "__main__":
    main()
