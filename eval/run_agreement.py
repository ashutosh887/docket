import argparse
import asyncio
import json
import os
import time

from common import RUNS, ist, now_iso, slice_scripts, tokens_of, use_cache_for, with_outer_retry
from docket import config
from docket import readers as readers_module
from docket.readers import read_script
from docket.scheme import scheme_for
from route import route_script

TPM_DEFAULT = 8000


def met_values(record):
    return {c["id"]: 1 if c["met"] else 0 for c in record["reading"]["criteria"]}


def reader_entry(record, scheme, spec):
    values = met_values(record)
    return {
        "model": spec,
        "criteria": values,
        "confidence": {c["id"]: c["confidence"] for c in record["reading"]["criteria"]},
        "declined": record["reading"].get("declined"),
        "total": scheme.score(values),
        "seconds": record.get("seconds"),
        "tokens": tokens_of(record),
        "cached": record.get("cached"),
        "attempts": record.get("attempts"),
        "cacheKey": record.get("key"),
    }


async def mark(script, scheme, readers, failures=None):
    t0 = time.monotonic()
    calls = [with_outer_retry(lambda spec=spec: read_script(script, spec, scheme), log_path=failures, label=f"{script.script_id} {spec}") for spec in readers.values()]
    results = await asyncio.gather(*calls, return_exceptions=True)
    entry = {
        "scriptId": script.script_id,
        "task": script.task,
        "official": script.official_score,
        "max": scheme.max,
        "schemeVersion": scheme.version,
    }
    records = {}
    for (side, spec), result in zip(readers.items(), results):
        key = "readerA" if side == "a" else "readerB"
        if isinstance(result, Exception):
            entry[key] = {"model": spec, "error": str(result)[:400]}
        else:
            records[side] = result
            entry[key] = reader_entry(result, scheme, spec)
    if len(records) == 2:
        entry["docket"] = route_script(records["a"], records["b"], scheme)
    else:
        entry["docket"] = {"route": "error"}
    entry["seconds"] = round(time.monotonic() - t0, 1)
    return entry


def estimate(scripts, tpm, tokens_per_call, runs):
    calls_per_reader = len(scripts) * runs
    minutes = calls_per_reader * tokens_per_call / tpm
    return round(minutes / 60, 1)


async def run(run_id, scripts, version, slice_name, resume, concurrency):
    cache = use_cache_for(run_id)
    readers = {"a": config.reader_a(), "b": config.reader_b()}
    folder = RUNS / run_id
    folder.mkdir(parents=True, exist_ok=True)
    meta_path = folder / "_meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() and resume else {}
    meta.update({
        "runId": run_id,
        "slice": slice_name,
        "variant": "without_answer",
        "mode": "with_true_solution",
        "schemeVersion": version,
        "models": readers,
        "readerSettings": {side: spec + readers_module.settings_tag(spec) for side, spec in readers.items()},
        "promptVersion": readers_module.PROMPT_VERSION,
        "design": os.environ.get("DOCKET_DESIGN", "1"),
        "providerLimits": {k: os.environ.get(k) for k in ("DOCKET_LIMIT_GROQ", "DOCKET_LIMIT_GEMINI")},
        "thresholds": {"marginThreshold": config.margin_threshold(), "minConfidence": config.min_confidence()},
        "cacheDir": str(cache),
        "scripts": len(scripts),
        "concurrency": concurrency,
    })
    meta.setdefault("startedAt", now_iso())
    meta_path.write_text(json.dumps(meta, indent=2))
    t_start = time.monotonic()
    gate = asyncio.Semaphore(concurrency)
    progress = {"done": 0, "seen": 0}
    todo = []
    for script in scripts:
        out = folder / f"{script.script_id}.json"
        if resume and out.exists():
            previous = json.loads(out.read_text())
            if previous.get("docket", {}).get("route") != "error":
                continue
        todo.append(script)

    async def one(script):
        async with gate:
            scheme = scheme_for(script.task, version)
            entry = await mark(script, scheme, readers, failures=folder / "_failures.jsonl")
        entry["runId"] = run_id
        entry["markedAt"] = now_iso()
        (folder / f"{script.script_id}.json").write_text(json.dumps(entry, indent=1, ensure_ascii=False))
        progress["done"] += 1
        elapsed = time.monotonic() - t_start
        left = (len(todo) - progress["done"]) * elapsed / progress["done"]
        a = entry["readerA"].get("total", "err")
        b = entry["readerB"].get("total", "err")
        print(f"{ist()} {run_id} {progress['done']}/{len(todo)} {script.script_id} official={script.official_score} a={a} b={b} route={entry['docket']['route']} {entry['seconds']}s, about {left / 60:.0f} min left", flush=True)

    await asyncio.gather(*(one(s) for s in todo))
    meta["finishedAt"] = now_iso()
    meta_path.write_text(json.dumps(meta, indent=2))


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--slice", default="full", choices=["full", "seeded61", "seeded21", "task13", "task13s61"])
    parser.add_argument("--runs", nargs="+", default=["r1", "r2", "r3"])
    parser.add_argument("--version", default="v1")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--tokens-per-call", type=int, default=5000)
    parser.add_argument("--tpm", type=int, default=int(os.environ.get("GROQ_TPM", TPM_DEFAULT)))
    parser.add_argument("--estimate-only", action="store_true")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--only", nargs="*", default=[])
    parser.add_argument("--fresh", action="store_true")
    args = parser.parse_args()
    scripts = slice_scripts(args.slice, args.limit)
    if args.only:
        scripts = [s for s in scripts if s.script_id in set(args.only)]
    hours = estimate(scripts, args.tpm, args.tokens_per_call, len(args.runs))
    print(f"{ist()} slice={args.slice} scripts={len(scripts)} runs={args.runs} readers A={config.reader_a()} B={config.reader_b()}")
    print(f"{ist()} estimate: {len(scripts) * len(args.runs)} calls per reader at about {args.tokens_per_call} tokens each under {args.tpm} tokens/min = about {hours} h of reader A time (uncached)")
    if args.estimate_only:
        return
    for run_id in args.runs:
        await run(run_id, scripts, args.version, args.slice, resume=not args.fresh, concurrency=args.concurrency)


if __name__ == "__main__":
    asyncio.run(main())
