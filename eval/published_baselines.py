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
    task13 = []
    keyed = {"15": [], "16": [], "18": []}
    for path in sorted(RESULTS.glob("*/*.json")):
        if path.name.endswith("_analysis.json"):
            continue
        data = json.loads(path.read_text())
        if not isinstance(data, list):
            continue
        groups = {}
        for row in data:
            if str(row.get("task_id")) not in ("13", *keyed) or row.get("score") is None or row.get("expected_score") is None:
                continue
            mode = "with_true_solution" if row.get("use_true_solution") else ("with_answer" if row.get("use_answer") else "without_answer")
            groups.setdefault((str(row.get("task_id")), row.get("model_id"), mode), []).append(row)
        for (task, model, mode), rows_ in groups.items():
            n = len(rows_)
            (task13 if task == "13" else keyed[task]).append({
                "model": model, "mode": mode, "scripts": n,
                "exactPct": round(100 * sum(r["score"] == r["expected_score"] for r in rows_) / n, 1),
                "exact": sum(r["score"] == r["expected_score"] for r in rows_),
                "withinOnePct": round(100 * sum(abs(r["score"] - r["expected_score"]) <= 1 for r in rows_) / n, 1),
                "file": str(path.relative_to(RESULTS.parent)),
                "rightScriptIds": sorted(r["solution_id"] for r in rows_ if r["score"] == r["expected_score"]),
                "scriptIds": sorted(r["solution_id"] for r in rows_),
            })
    best13 = {}
    for r in task13:
        k = (r["model"], r["mode"])
        if k not in best13 or r["exactPct"] > best13[k]["exactPct"]:
            best13[k] = r
    out = {
        "metric": "published_baselines",
        "source": REPO,
        "note": "Numbers read from the CHECK-MAT repo's own model_results files; not run by Docket.",
        "readAt": datetime.now(timezone.utc).isoformat(),
        "rows": sorted(best.values(), key=lambda r: (-r["exactPct"], r["model"], r["mode"])),
        "task13Rows": sorted(best13.values(), key=lambda r: (-r["exactPct"], r["model"], r["mode"])),
        "keyedTaskRows": {task: rows_ for task, rows_ in keyed.items()},
    }
    (Path(__file__).parent / "results" / "published_baselines.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    for r in out["rows"][:8]:
        print(r["model"], r["mode"], r["scripts"], r["exactPct"], r["withinOnePct"])


if __name__ == "__main__":
    main()
