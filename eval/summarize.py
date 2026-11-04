import argparse
import math
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

EVAL = Path(__file__).resolve().parent
RUNS = EVAL / "runs"

RESULTS = EVAL / "results"

BAR = {
    "commitsGapPoints": 10,
    "floorGapPoints": 5,
    "commitsWinShare": 40,
    "commitsLossShare": 25,
    "catchWinShare": 80,
    "catchLossShare": 50,
}


def wilson(k, n, z=1.959964):
    if n == 0:
        return None
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return {"k": k, "n": n, "pct": round(100 * p, 1), "low": round(100 * max(0.0, centre - half), 1), "high": round(100 * min(1.0, centre + half), 1)}


def mcnemar(only_first, only_second):
    n = only_first + only_second
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(only_first, only_second) + 1)) / 2 ** n
    return round(min(1.0, 2 * tail), 4)


def paired(records, first, second):
    a = sum(1 for r in records if first(r) and not second(r))
    b = sum(1 for r in records if second(r) and not first(r))
    return {"firstOnlyRight": a, "secondOnlyRight": b, "bothRight": sum(1 for r in records if first(r) and second(r)), "neitherRight": sum(1 for r in records if not first(r) and not second(r)), "mcnemarExactP": mcnemar(a, b)}


def pct(n, d):
    return None if d == 0 else round(100 * n / d, 1)


def load_run(run_id):
    records = []
    for path in sorted((RUNS / run_id).glob("*.json")):
        if path.name.startswith("_"):
            continue
        records.append(json.loads(path.read_text()))
    meta_path = RUNS / run_id / "_meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    return meta, records


def failed_calls(run_id):
    path = RUNS / run_id / "_failures.jsonl"
    if not path.exists():
        return {}
    counts = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        model = entry["label"].split(" ", 1)[-1]
        counts[model] = counts.get(model, 0) + 1
    return counts


def usable(record):
    return not record["readerA"].get("error") and not record["readerB"].get("error")


def run_metrics(records):
    kept = [r for r in records if usable(r)]
    n = len(kept)
    a_exact = sum(r["readerA"]["total"] == r["official"] for r in kept)
    b_exact = sum(r["readerB"]["total"] == r["official"] for r in kept)
    a_one = sum(abs(r["readerA"]["total"] - r["official"]) <= 1 for r in kept)
    b_one = sum(abs(r["readerB"]["total"] - r["official"]) <= 1 for r in kept)
    signed = [r for r in kept if r["docket"]["route"] == "signed"]
    routed = [r for r in kept if r["docket"]["route"] == "teacher"]
    signed_exact = sum(r["docket"]["total"] == r["official"] for r in signed)
    signed_one = sum(abs(r["docket"]["total"] - r["official"]) <= 1 for r in signed)
    floor_exact = sum(r["docket"]["floorTotal"] == r["official"] for r in kept)
    floor_one = sum(abs(r["docket"]["floorTotal"] - r["official"]) <= 1 for r in kept)
    teacher_exact = signed_exact + len(routed)
    teacher_one = signed_one + len(routed)
    criteria = sum(r["docket"]["criteriaCount"] for r in kept)
    routed_criteria = sum(len(r["docket"]["teacherCriteria"]) for r in kept)
    diff_a = sum(r["readerA"]["total"] != r["official"] for r in routed)
    diff_b = sum(r["readerB"]["total"] != r["official"] for r in routed)
    diff_any = sum(r["readerA"]["total"] != r["official"] or r["readerB"]["total"] != r["official"] for r in routed)
    diff_both = sum(r["readerA"]["total"] != r["official"] and r["readerB"]["total"] != r["official"] for r in routed)
    exact = lambda key: (lambda r: r[key]["total"] == r["official"])
    floor_right = lambda r: r["docket"]["floorTotal"] == r["official"]
    intervals = {
        "readerAExact": wilson(a_exact, n),
        "readerAWithinOne": wilson(a_one, n),
        "readerBExact": wilson(b_exact, n),
        "readerBWithinOne": wilson(b_one, n),
        "commits": wilson(len(signed), n),
        "exactWhenCommits": wilson(signed_exact, len(signed)),
        "withinOneWhenCommits": wilson(signed_one, len(signed)),
        "floorExact": wilson(floor_exact, n),
        "floorWithinOne": wilson(floor_one, n),
    }
    pairs = {
        "floorVsReaderA": paired(kept, floor_right, exact("readerA")),
        "floorVsReaderB": paired(kept, floor_right, exact("readerB")),
        "readerAVsReaderB": paired(kept, exact("readerA"), exact("readerB")),
    }
    return {
        "scripts": n,
        "dropped": len(records) - n,
        "wilson95": intervals,
        "paired": pairs,
        "readerA": {"exactPct": pct(a_exact, n), "withinOnePct": pct(a_one, n)},
        "readerB": {"exactPct": pct(b_exact, n), "withinOnePct": pct(b_one, n)},
        "docket": {
            "commitsPct": pct(len(signed), n),
            "committedScripts": len(signed),
            "exactWhenCommitsPct": pct(signed_exact, len(signed)),
            "withinOneWhenCommitsPct": pct(signed_one, len(signed)),
            "floorExactPct": pct(floor_exact, n),
            "floorWithinOnePct": pct(floor_one, n),
            "teacherStandInExactPct": pct(teacher_exact, n),
            "teacherStandInWithinOnePct": pct(teacher_one, n),
        },
        "teacher": {
            "criteriaRoutedPct": pct(routed_criteria, criteria),
            "criteriaRouted": routed_criteria,
            "criteria": criteria,
            "scriptsRoutedPct": pct(len(routed), n),
            "scriptsRouted": len(routed),
            "scriptsUnreadByAReader": sum(1 for r in routed if r["docket"].get("coreRoute") == "unread"),
            "officialDiffersFromAPct": pct(diff_a, len(routed)),
            "officialDiffersFromBPct": pct(diff_b, len(routed)),
            "officialDiffersFromAtLeastOnePct": pct(diff_any, len(routed)),
            "officialDiffersFromBothPct": pct(diff_both, len(routed)),
        },
    }


def spread(values):
    values = [v for v in values if v is not None]
    if not values:
        return None
    return {
        "mean": round(statistics.mean(values), 1),
        "min": min(values),
        "max": max(values),
        "spread": round(max(values) - min(values), 1),
        "runs": values,
    }


def across(per_run, group, key):
    return spread([m[group][key] for m in per_run])


def verdict_gap(docket, baseline, gap_points):
    if docket is None or baseline is None:
        return "not measured"
    gap = docket["mean"] - baseline["mean"]
    noise = max(docket["spread"], baseline["spread"])
    if abs(gap) <= noise:
        return "within noise"
    if gap >= gap_points:
        return "win"
    if docket["mean"] <= baseline["mean"]:
        return "loss"
    return "no clear result"


def verdict_share(value, win, loss):
    if value is None:
        return "not measured"
    if value["mean"] >= win:
        return "win"
    if value["mean"] < loss:
        return "loss"
    return "no clear result"


def speed_cost(records_by_run, prices):
    seconds = []
    tokens = {"readerA": {"in": [], "out": []}, "readerB": {"in": [], "out": []}}
    models = {}
    for records in records_by_run.values():
        for r in records:
            if not usable(r):
                continue
            seconds.append(max(r["readerA"].get("seconds") or 0, r["readerB"].get("seconds") or 0))
            for side in ("readerA", "readerB"):
                models[side] = r[side]["model"]
                t = r[side].get("tokens") or {}
                if t.get("in") is not None:
                    tokens[side]["in"].append(t["in"])
                if t.get("out") is not None:
                    tokens[side]["out"].append(t["out"])
    out = {"secondsPerScript": None, "secondsMeaning": "the slower reader's call time per script, from each reading's own log; the two readers run in parallel and code takes milliseconds", "readers": {}}
    if seconds:
        out["secondsPerScript"] = {
            "median": round(statistics.median(seconds), 1),
            "mean": round(statistics.mean(seconds), 1),
            "max": round(max(seconds), 1),
            "scriptsTimed": len(seconds),
        }
    total_estimate = 0.0
    priced = True
    for side, t in tokens.items():
        model = models.get(side)
        mean_in = round(statistics.mean(t["in"]), 0) if t["in"] else None
        mean_out = round(statistics.mean(t["out"]), 0) if t["out"] else None
        price = prices.get(model) if model else None
        estimate = None
        if price and mean_in is not None and mean_out is not None:
            estimate = round((mean_in * price["inPerMillion"] + mean_out * price["outPerMillion"]) / 1e6, 6)
            total_estimate += estimate
        else:
            priced = False
        out["readers"][side] = {
            "model": model,
            "meanInputTokensPerScript": mean_in,
            "meanOutputTokensPerScript": mean_out,
            "freeTierCostUsd": 0,
            "priceSheetEstimateUsdPerScript": estimate,
            "priceSheet": price,
        }
    out["priceSheetEstimateUsdPerScript"] = round(total_estimate, 6) if priced else None
    side_seconds = {"readerA": [], "readerB": []}
    retries = {"readerA": 0, "readerB": 0}
    slower = {"readerA": 0, "readerB": 0}
    for records in records_by_run.values():
        for r in records:
            if not usable(r):
                continue
            a, b = r["readerA"].get("seconds") or 0, r["readerB"].get("seconds") or 0
            side_seconds["readerA"].append(a)
            side_seconds["readerB"].append(b)
            slower["readerA" if a >= b else "readerB"] += 1
            for side in retries:
                retries[side] += max(0, (r[side].get("attempts") or 1) - 1)
    if side_seconds["readerA"]:
        med = {k: round(statistics.median(v), 1) for k, v in side_seconds.items()}
        n = len(side_seconds["readerA"])
        top = max(slower, key=slower.get)
        out["bound"] = (
            f"the slower call is {models.get(top)} on {slower[top]} of {n} scripts; median call seconds: "
            f"{models.get('readerA')} {med['readerA']}, {models.get('readerB')} {med['readerB']}; "
            f"retries after a provider error: {retries['readerA']} and {retries['readerB']}"
        )
        out["medianCallSeconds"] = med
        out["retries"] = retries
    return out


def build(run_ids, score_on):
    per_run, metas, records_by_run = [], {}, {}
    keep = None
    if score_on != "all":
        keep = set(json.loads((EVAL / f"slice_{score_on}.json").read_text())["scriptIds"])
    for run_id in run_ids:
        meta, records = load_run(run_id)
        if keep is not None:
            records = [r for r in records if r["scriptId"] in keep]
            meta = {**meta, "slice": score_on}
        if not records:
            continue
        metas[run_id] = meta
        records_by_run[run_id] = records
        m = run_metrics(records)
        m["runId"] = run_id
        per_run.append(m)
    if not per_run:
        raise SystemExit(f"no records for {run_ids} on {score_on}")
    common = {
        "runIds": [m["runId"] for m in per_run],
        "slice": sorted({meta.get("slice") for meta in metas.values() if meta.get("slice")}),
        "models": {run_id: meta.get("models") for run_id, meta in metas.items()},
        "readerSettings": {run_id: meta.get("readerSettings") for run_id, meta in metas.items()},
        "startedAt": {run_id: meta.get("startedAt") for run_id, meta in metas.items()},
        "finishedAt": {run_id: meta.get("finishedAt") for run_id, meta in metas.items()},
        "variant": sorted({meta.get("variant") for meta in metas.values() if meta.get("variant")}),
        "mode": sorted({meta.get("mode") for meta in metas.values() if meta.get("mode")}),
        "writtenAt": datetime.now(timezone.utc).isoformat(),
    }
    agreement = {
        "metric": "agreement",
        **common,
        "scriptsPerRun": [m["scripts"] for m in per_run],
        "failedCallsRetriedPerRun": [failed_calls(m["runId"]) for m in per_run],
        "droppedPerRun": [m["dropped"] for m in per_run],
        "readerA": {"exactPct": across(per_run, "readerA", "exactPct"), "withinOnePct": across(per_run, "readerA", "withinOnePct")},
        "readerB": {"exactPct": across(per_run, "readerB", "exactPct"), "withinOnePct": across(per_run, "readerB", "withinOnePct")},
        "docket": {k: across(per_run, "docket", k) for k in per_run[0]["docket"]},
        "perRun": per_run,
        "wilson95": per_run[0]["wilson95"] if len(per_run) == 1 else None,
        "paired": per_run[0]["paired"] if len(per_run) == 1 else None,
    }
    teacher = {k: across(per_run, "teacher", k) for k in per_run[0]["teacher"]}
    return agreement, teacher, common, records_by_run


def with_spread(stat, spread_stat):
    if stat is None:
        return None
    return {**stat, "spread": spread_stat["spread"] if spread_stat else stat["spread"]}


def single_reader(run_ids, side, headline_on, spread_on, design):
    key = "readerA" if side == "a" else "readerB"
    out = {"metric": "single_reader", "design": design, "reader": side, "writtenAt": datetime.now(timezone.utc).isoformat(), "runs": []}
    for run_id in run_ids:
        meta, records = load_run(run_id)
        records = [r for r in records if not r[key].get("error") and not r[key].get("notRun") and "total" in r[key]]
        if not records:
            continue
        model = records[0][key]["model"]
        n = len(records)
        exact = sum(r[key]["total"] == r["official"] for r in records)
        one = sum(abs(r[key]["total"] - r["official"]) <= 1 for r in records)
        above = sum(r[key]["total"] > r["official"] for r in records)
        out["runs"].append({
            "runId": run_id, "slice": meta.get("slice"), "model": model, "scripts": n,
            "scriptIds": sorted(r["scriptId"] for r in records),
            "exact": wilson(exact, n), "withinOne": wilson(one, n), "aboveOfficial": above,
            "failedCallsRetried": failed_calls(run_id),
        })
    keep = set(json.loads((EVAL / f"slice_{spread_on}.json").read_text())["scriptIds"])
    per = []
    for run_id in run_ids:
        records = [r for r in load_run(run_id)[1] if r["scriptId"] in keep and "total" in r[key] and not r[key].get("notRun")]
        if records:
            per.append(round(100 * sum(r[key]["total"] == r["official"] for r in records) / len(records), 1))
    first = {r["scriptId"]: r for r in load_run(run_ids[0])[1] if "total" in r[key] and not r[key].get("notRun")}
    d1 = {r["scriptId"]: r for r in load_run("r1")[1] if usable(r)}
    common_ids = sorted(set(first) & set(d1))
    right = lambda r: r[key]["total"] == r["official"]
    pairs = {}
    for name, other in (("vsDesign1ReaderB", lambda r: r["readerB"]["total"] == r["official"]), ("vsDesign1ReaderA", lambda r: r["readerA"]["total"] == r["official"]), ("vsDesign1Floor", lambda r: r["docket"]["floorTotal"] == r["official"])):
        a = sum(1 for i in common_ids if right(first[i]) and not other(d1[i]))
        b = sum(1 for i in common_ids if other(d1[i]) and not right(first[i]))
        pairs[name] = {"scripts": len(common_ids), "firstOnlyRight": a, "secondOnlyRight": b,
                       "bothRight": sum(1 for i in common_ids if right(first[i]) and other(d1[i])),
                       "neitherRight": sum(1 for i in common_ids if not right(first[i]) and not other(d1[i])),
                       "mcnemarExactP": mcnemar(a, b)}
    published = json.loads((RESULTS / "published_baselines.json").read_text()).get("task13Rows", []) if (RESULTS / "published_baselines.json").exists() else []
    vs_published = []
    for row in published[:3]:
        ids = sorted(set(row.get("scriptIds", [])) & set(first))
        good = set(row.get("rightScriptIds", []))
        a = sum(1 for i in ids if right(first[i]) and i not in good)
        b = sum(1 for i in ids if i in good and not right(first[i]))
        vs_published.append({"model": row["model"], "mode": row["mode"], "scripts": len(ids), "firstOnlyRight": a, "secondOnlyRight": b,
                             "bothRight": sum(1 for i in ids if right(first[i]) and i in good),
                             "neitherRight": sum(1 for i in ids if not right(first[i]) and i not in good),
                             "mcnemarExactP": mcnemar(a, b), "source": row["file"]})
    out["pairedWithPublished"] = vs_published
    out["pairedOnCommonScripts"] = pairs
    out["spreadOn"] = spread_on
    out["spreadExactPct"] = spread(per)
    return out


def keyed_tasks(run_ids, headline_on, spread_on):
    key = "readerB"
    graded = lambda records: [r for r in records if "total" in r[key] and not r[key].get("notRun") and not r[key].get("error")]
    meta, first_records = load_run(run_ids[0])
    wanted = json.loads((EVAL / f"slice_{headline_on}.json").read_text())["scriptIds"]
    first = {r["scriptId"]: r for r in graded(first_records) if r["scriptId"] in set(wanted)}
    right = lambda r: r[key]["total"] == r["official"]
    published = json.loads((RESULTS / "published_baselines.json").read_text()).get("keyedTaskRows", {})
    out = {"metric": "single_reader_keyed", "design": "2", "reader": "b", "writtenAt": datetime.now(timezone.utc).isoformat(),
           "runId": run_ids[0], "slice": headline_on, "model": next((r[key]["model"] for r in first.values()), None),
           "scriptsInSlice": len(wanted), "scriptsGraded": len(first), "notRun": sorted(set(wanted) - set(first)),
           "failedCallsRetried": failed_calls(run_ids[0]), "dailyCap": meta.get("dailyCap"), "tasks": {}}
    groups = {}
    for r in first.values():
        groups.setdefault(str(r["task"]), []).append(r)
    groups["pooled"] = list(first.values())
    for task, records in groups.items():
        n = len(records)
        row = {"scripts": n, "scriptIds": sorted(r["scriptId"] for r in records),
               "exact": wilson(sum(right(r) for r in records), n),
               "withinOne": wilson(sum(abs(r[key]["total"] - r["official"]) <= 1 for r in records), n),
               "aboveOfficial": sum(r[key]["total"] > r["official"] for r in records),
               "belowOfficial": sum(r[key]["total"] < r["official"] for r in records)}
        tasks = [task] if task != "pooled" else sorted(t for t in groups if t != "pooled")
        candidates = {}
        for t in tasks:
            for prow in published.get(t, []):
                if prow["mode"] != "with_true_solution":
                    continue
                entry = candidates.setdefault(prow["model"], {"scriptIds": set(), "right": set(), "files": set()})
                entry["scriptIds"] |= set(prow["scriptIds"])
                entry["right"] |= set(prow["rightScriptIds"])
                entry["files"].add(prow["file"])
        best = None
        for model, entry in candidates.items():
            ids = sorted(set(entry["scriptIds"]) & {r["scriptId"] for r in records})
            if len(ids) != n:
                continue
            good = entry["right"]
            score = sum(1 for i in ids if i in good)
            if best is None or score > best["publishedExact"]:
                a = sum(1 for i in ids if right(first[i]) and i not in good)
                b = sum(1 for i in ids if i in good and not right(first[i]))
                best = {"model": model, "mode": "with_true_solution", "scripts": len(ids), "publishedExact": score,
                        "firstOnlyRight": a, "secondOnlyRight": b,
                        "bothRight": sum(1 for i in ids if right(first[i]) and i in good),
                        "neitherRight": sum(1 for i in ids if not right(first[i]) and i not in good),
                        "mcnemarExactP": mcnemar(a, b), "source": sorted(entry["files"])}
        row["bestPublishedOnSameScripts"] = best
        out["tasks"][task] = row
    keep = set(json.loads((EVAL / f"slice_{spread_on}.json").read_text())["scriptIds"])
    per = []
    counts = []
    for run_id in run_ids:
        records = [r for r in graded(load_run(run_id)[1]) if r["scriptId"] in keep]
        if records:
            per.append(round(100 * sum(right(r) for r in records) / len(records), 1))
            counts.append({"runId": run_id, "exact": sum(right(r) for r in records), "scripts": len(records)})
    out["spreadOn"] = spread_on
    out["spreadExactPct"] = spread(per)
    out["spreadCounts"] = counts
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--headline", nargs="+", default=["r1"])
    parser.add_argument("--headline-on", default="seeded61")
    parser.add_argument("--spread", nargs="+", default=["r1", "r2", "r3"])
    parser.add_argument("--spread-on", default="seeded21")
    parser.add_argument("--runs-dir", type=Path, default=None)
    parser.add_argument("--results-dir", type=Path, default=None)
    parser.add_argument("--design", default="1")
    parser.add_argument("--pair-with", default=None)
    parser.add_argument("--single-reader", choices=["a", "b"], default=None)
    parser.add_argument("--keyed", action="store_true")
    args = parser.parse_args()
    global RUNS, RESULTS
    RUNS = args.runs_dir or RUNS
    RESULTS = args.results_dir or RESULTS
    if args.keyed:
        result = keyed_tasks(args.spread, args.headline_on, args.spread_on)
        (RESULTS / "single_reader_d2_b_keyed.json").write_text(json.dumps(result, indent=2) + "\n")
        for task, row in result["tasks"].items():
            print(task, row["exact"], row["withinOne"], row["bestPublishedOnSameScripts"] and {k: row["bestPublishedOnSameScripts"][k] for k in ("model", "publishedExact", "mcnemarExactP")})
        print("spread", result["spreadExactPct"], result["spreadCounts"])
        return
    if args.single_reader:
        result = single_reader(args.spread, args.single_reader, args.headline_on, args.spread_on, args.design)
        (RESULTS / f"single_reader_d{args.design}_{args.single_reader}.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps({k: v for k, v in result.items() if k != "runs"}, indent=1))
        for r in result["runs"]:
            print(r["runId"], r["scripts"], r["exact"], r["withinOne"])
        return
    agreement, teacher, common, records_by_run = build(args.headline, args.headline_on)
    common["design"] = args.design
    agreement["design"] = args.design
    if args.pair_with and agreement.get("paired") is not None:
        own = {r["scriptId"]: r for recs in records_by_run.values() for r in recs if usable(r)}
        other = {r["scriptId"]: r for r in load_run(args.pair_with)[1] if usable(r)}
        both = sorted(set(own) & set(other))
        floor_right = lambda table: (lambda sid: table[sid]["docket"]["floorTotal"] == table[sid]["official"])
        mine, theirs = floor_right(own), floor_right(other)
        a = sum(1 for i in both if mine(i) and not theirs(i))
        b = sum(1 for i in both if theirs(i) and not mine(i))
        agreement["paired"]["design2VsDesign1"] = {
            "scripts": len(both), "pairedWith": args.pair_with,
            "firstOnlyRight": a, "secondOnlyRight": b,
            "bothRight": sum(1 for i in both if mine(i) and theirs(i)),
            "neitherRight": sum(1 for i in both if not mine(i) and not theirs(i)),
            "mcnemarExactP": mcnemar(a, b),
        }
    spread_agreement = spread_teacher = None
    present = [r for r in args.spread if (RUNS / r).exists() and any((RUNS / r).glob("[0-9]*.json"))]
    if len(present) > 1:
        spread_agreement, spread_teacher, _, _ = build(present, args.spread_on)
    sa = spread_agreement or agreement
    a = with_spread(agreement["readerA"]["exactPct"], sa["readerA"]["exactPct"])
    b = with_spread(agreement["readerB"]["exactPct"], sa["readerB"]["exactPct"])
    best_side = "readerA" if a["mean"] >= b["mean"] else "readerB"
    best = a if best_side == "readerA" else b
    d = agreement["docket"]
    sd = sa["docket"]
    verdicts = {
        "metric": "verdicts",
        "design": args.design,
        **common,
        "bar": BAR,
        "meansFrom": {"runs": agreement["runIds"], "slice": agreement["slice"]},
        "spreadsFrom": {"runs": sa["runIds"], "slice": sa["slice"]},
        "bestSingleReader": best_side,
        "exactWhenCommitsVsReaderA": verdict_gap(with_spread(d["exactWhenCommitsPct"], sd["exactWhenCommitsPct"]), a, BAR["commitsGapPoints"]),
        "exactWhenCommitsVsReaderB": verdict_gap(with_spread(d["exactWhenCommitsPct"], sd["exactWhenCommitsPct"]), b, BAR["commitsGapPoints"]),
        "floorVsBest": verdict_gap(with_spread(d["floorExactPct"], sd["floorExactPct"]), best, BAR["floorGapPoints"]),
        "commitsShare": verdict_share(d["commitsPct"], BAR["commitsWinShare"], BAR["commitsLossShare"]),
        "interruptCatches": verdict_share(teacher["officialDiffersFromAtLeastOnePct"], BAR["catchWinShare"], BAR["catchLossShare"]),
    }
    if len(sa["runIds"]) < 3:
        for key in ("exactWhenCommitsVsReaderA", "exactWhenCommitsVsReaderB", "floorVsBest"):
            verdicts[key] = f"{verdicts[key]} on {len(sa['runIds'])} run(s); the bar needs three runs for the spread, so this is not a preregistered result"
    all_records = dict(records_by_run)
    for run_id in present:
        if run_id not in all_records:
            all_records[run_id] = load_run(run_id)[1]
    prices_path = EVAL / "prices.json"
    prices = json.loads(prices_path.read_text()) if prices_path.exists() else {}
    cost = {"metric": "speed_cost", **common, "runIds": sorted(all_records), "priceSource": prices.get("_source"), **speed_cost(all_records, prices)}
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"agreement_d{args.design}.json").write_text(json.dumps(agreement, indent=2) + "\n")
    (RESULTS / f"teacher_load_d{args.design}.json").write_text(json.dumps({"metric": "teacher_load", **common, **teacher}, indent=2) + "\n")
    if spread_agreement:
        (RESULTS / f"agreement_spread_d{args.design}.json").write_text(json.dumps(spread_agreement, indent=2) + "\n")
        (RESULTS / f"teacher_load_spread_d{args.design}.json").write_text(json.dumps({"metric": "teacher_load_spread", **spread_teacher}, indent=2) + "\n")
    (RESULTS / f"verdicts_d{args.design}.json").write_text(json.dumps(verdicts, indent=2) + "\n")
    (RESULTS / f"speed_cost_d{args.design}.json").write_text(json.dumps(cost, indent=2) + "\n")
    print(json.dumps({k: v for k, v in verdicts.items() if k not in common and k != "bar"}, indent=2))


if __name__ == "__main__":
    main()
