import argparse
import os
import asyncio
import time

from common import ist, now_iso, slice_scripts, tokens_of, use_cache_for, with_outer_retry, write_result
from docket import config
from docket.readers import read_script
from docket.scheme import scheme_for


def gave_a_grade(record, scheme):
    reading = record["reading"]
    met = {c["id"]: 1 if c["met"] else 0 for c in reading["criteria"]}
    points = scheme.score(met)
    declined = reading.get("declined") is True or reading.get("student_work_visible") is False
    return {
        "declined": declined,
        "anyMet": any(met.values()),
        "points": points,
        "gradeGiven": not declined or points > 0,
    }


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--slice", default="full")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--version", default="v1")
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--only-reader", choices=["a", "b"], default=None)
    args = parser.parse_args()
    use_cache_for("core")
    scripts = slice_scripts(args.slice, args.limit)
    readers = {"a": config.reader_a(), "b": config.reader_b()}
    if args.only_reader:
        readers = {args.only_reader: readers[args.only_reader]}
    started = now_iso()
    gate = asyncio.Semaphore(args.concurrency)
    done = {"n": 0}

    async def side_call(script, scheme, side, spec):
        t0 = time.monotonic()
        try:
            record = await with_outer_retry(lambda: read_script(script, spec, scheme, blind=True))
            out = {**gave_a_grade(record, scheme), "cached": record.get("cached"), "tokens": tokens_of(record), "reason": record["reading"].get("decline_reason")}
        except Exception as error:
            out = {"error": str(error)[:300]}
        out["seconds"] = round(time.monotonic() - t0, 1)
        return side, out

    async def one(script):
        async with gate:
            scheme = scheme_for(script.task, args.version)
            row = {"scriptId": script.script_id, "task": script.task}
            for side, out in await asyncio.gather(*(side_call(script, scheme, side, spec) for side, spec in readers.items())):
                row[side] = out
        done["n"] += 1
        print(f"{ist()} blind {done['n']}/{len(scripts)} {script.script_id} " + " ".join(f"{k}={row[k].get('declined', 'err')}" for k in readers), flush=True)
        return row

    rows = await asyncio.gather(*(one(s) for s in scripts))
    parts = []
    passed = total = 0
    for side, spec in readers.items():
        answered = [r[side] for r in rows if "error" not in r[side]]
        ok = sum(1 for r in answered if not r["gradeGiven"])
        parts.append({"label": f"reader {side.upper()} `{spec}`", "reader": spec, "total": len(answered), "passed": ok,
                      "declinedFlag": sum(r["declined"] for r in answered), "anyCriterionMet": sum(r["anyMet"] for r in answered),
                      "errors": sum(1 for r in rows if "error" in r[side])})
        passed += ok
        total += len(answered)
    write_result("blind", {
        "metric": "blind",
        "slice": args.slice,
        "scripts": len(scripts),
        "schemeVersion": args.version,
        "method": "each reader gets the grading request with the student's pages removed (the reference statement and solution stay); a pass is a reading that declines (declined true or student_work_visible false) and scores 0 points by the scheme",
        "readers": readers,
        "design": os.environ.get("DOCKET_DESIGN", "2"),
        "startedAt": started,
        "finishedAt": now_iso(),
        "total": total,
        "passed": passed,
        "parts": parts,
        "gradesGiven": [{"scriptId": r["scriptId"], "reader": s} for r in rows for s in readers if "error" not in r[s] and r[s]["gradeGiven"]],
        "rows": rows,
    })
    print(parts)


if __name__ == "__main__":
    asyncio.run(main())
