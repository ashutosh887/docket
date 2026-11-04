import json
import random
import re
import sys
from datetime import datetime, timezone
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "data" / "raw" / "Auto-check-EGE-math" / "dataset_benchmark"
SEED = 20261104
SEEDED_SIZE = 61
IMAGE_VARIANT = "without_answer"
READER_MODE = "with_true_solution"
SCORE_PATTERN = re.compile(r"estimate_(\d+)")


def page_key(path):
    numbers = re.findall(r"\d+", path.stem)
    return [int(n) for n in numbers], path.name


def scripts(variant=IMAGE_VARIANT):
    found = []
    for task_dir in sorted(p for p in DATASET.iterdir() if p.is_dir() and p.name.isdigit()):
        for example_dir in sorted(p for p in task_dir.iterdir() if p.is_dir()):
            for solution_dir in sorted(p for p in example_dir.iterdir() if p.is_dir()):
                pages = sorted((solution_dir / variant).glob("*.png"), key=page_key)
                if not pages:
                    continue
                scores = {int(SCORE_PATTERN.search(p.name).group(1)) for p in pages if SCORE_PATTERN.search(p.name)}
                if len(scores) != 1:
                    raise ValueError(f"{solution_dir.name}: pages disagree on the official grade {sorted(scores)}")
                found.append({
                    "scriptId": solution_dir.name,
                    "task": task_dir.name,
                    "official": scores.pop(),
                    "pages": [str(p.relative_to(ROOT)) for p in pages],
                })
    return found


def seeded_subset(all_scripts, size=SEEDED_SIZE, seed=SEED):
    by_task = defaultdict(list)
    for s in all_scripts:
        by_task[s["task"]].append(s["scriptId"])
    rng = random.Random(seed)
    total = len(all_scripts)
    chosen = []
    for task in sorted(by_task):
        ids = sorted(by_task[task])
        take = round(size * len(ids) / total)
        chosen.extend(rng.sample(ids, min(take, len(ids))))
    return sorted(chosen, key=lambda i: [int(x) for x in i.split(".")])


def load(name):
    every = scripts()
    if name == "full":
        return every
    if name == "seeded61":
        keep = set(json.loads((Path(__file__).parent / "slice_seeded61.json").read_text())["scriptIds"])
        return [s for s in every if s["scriptId"] in keep]
    raise ValueError(f"unknown slice {name}")


def main():
    every = scripts()
    subset = seeded_subset(every)
    out = {
        "seed": SEED,
        "size": len(subset),
        "variant": IMAGE_VARIANT,
        "mode": READER_MODE,
        "stratifiedBy": "task",
        "scriptIds": subset,
    }
    (Path(__file__).parent / "slice_seeded61.json").write_text(json.dumps(out, indent=2) + "\n")
    tasks = defaultdict(int)
    grades = defaultdict(int)
    for s in every:
        tasks[s["task"]] += 1
        grades[s["official"]] += 1
    summary = {
        "scripts": len(every),
        "pages": sum(len(s["pages"]) for s in every),
        "byTask": dict(sorted(tasks.items())),
        "byOfficialGrade": dict(sorted(grades.items())),
        "seededSubset": len(subset),
        "variant": IMAGE_VARIANT,
        "mode": READER_MODE,
    }
    summary["metric"] = "slice"
    summary["seed"] = SEED
    summary["writtenAt"] = datetime.now(timezone.utc).isoformat()
    (Path(__file__).parent / "results" / "slice.json").write_text(json.dumps(summary, indent=2) + "\n")
    json.dump(summary, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
