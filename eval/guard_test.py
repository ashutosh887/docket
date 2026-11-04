import argparse
import asyncio
import copy
import json
import os
import shutil

from common import ROOT, RUNS, ist, now_iso, slice_scripts, write_result

WORK = RUNS / "guard" / "out"


def isolate():
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)
    (WORK / "cache").symlink_to(ROOT / "out" / "cache", target_is_directory=True)
    os.environ["DOCKET_OUT"] = str(WORK)


isolate()

from docket import config, graph, readers, scheme as schemes
from docket.graph import Case, run_case

SIGNED = []
REAL_READ = readers.read_script


def counting_sign(document):
    SIGNED.append(document.get("scriptId"))
    signed = dict(document)
    signed["signature"] = {"alg": "ECDSA_SHA_256", "keyId": "eval:no-kms", "value": ""}
    return signed


graph.sign = counting_sign


def cached(script, spec, scheme):
    key = readers.cache_key(script, spec, scheme, False)
    return (config.out_dir() / "cache" / f"{key}.json").exists()


def injector(kind):
    async def read(script, spec, scheme, blind=False, attempts=6):
        record = copy.deepcopy(await REAL_READ(script, spec, scheme, blind=blind, attempts=attempts))
        side = "a" if spec == config.reader_a() else "b"
        if kind == "missing-reading" and side == "b":
            raise RuntimeError("injected: reader b returned nothing")
        if kind == "dropped-criterion" and side == "a":
            record["reading"]["criteria"] = record["reading"]["criteria"][1:]
        if kind == "stale-definition" and side == "a":
            first = scheme.criteria[0].id
            record["definitions"][first] = "0" * 16
        if kind == "declined" and side == "a":
            record["reading"]["declined"] = True
            record["reading"]["decline_reason"] = "injected decline"
        return record

    return read


def teacher_answers(reason):
    return {"decisions": {c["id"]: int(c["readerA"] or 0) for c in reason["contested"]}, "note": "eval: official grade stands in"}


async def one(script, kind):
    if kind == "stale-scheme":
        schemes.set_current_version("v2")
    else:
        schemes.set_current_version("v1")
    graph.read_script = injector(kind)
    before = len(SIGNED)
    case = Case(script=script, scheme=schemes.scheme_for(script.task, "v1"))
    error = None
    try:
        await run_case(case, teacher_answers)
    except Exception as e:
        error = f"{type(e).__name__}: {str(e)[:200]}"
    signed = len(SIGNED) > before
    return {
        "scriptId": script.script_id,
        "kind": kind,
        "route": case.route,
        "blocked": case.blocked,
        "signed": signed,
        "error": error,
    }


KINDS = ["missing-reading", "stale-scheme", "dropped-criterion", "stale-definition", "declined"]


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--slice", default="full")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    v1 = {t: schemes.scheme_for(t, "v1") for t in range(13, 20)}
    pool = [s for s in slice_scripts(args.slice) if cached(s, config.reader_a(), v1[s.task]) and cached(s, config.reader_b(), v1[s.task])]
    if args.limit:
        pool = pool[: args.limit]
    print(f"{ist()} guard test on {len(pool)} scripts with both readings cached")
    rows = []
    for script in pool:
        rows.append(await one(script, "control"))
        for kind in KINDS:
            rows.append(await one(script, kind))
    graph.read_script = REAL_READ
    schemes.set_current_version("v1")
    parts = []
    for kind in KINDS:
        hits = [r for r in rows if r["kind"] == kind]
        ok = sum(1 for r in hits if r["blocked"] and not r["signed"])
        parts.append({"label": kind, "total": len(hits), "passed": ok})
    controls = [r for r in rows if r["kind"] == "control"]
    write_result(f"guard_d{os.environ.get('DOCKET_DESIGN', '2')}", {
        "design": os.environ.get("DOCKET_DESIGN", "2"),
        "metric": "guard",
        "slice": args.slice,
        "scripts": len(pool),
        "readers": {"a": config.reader_a(), "b": config.reader_b()},
        "method": "the real Strands graph with the SigningGuard hook runs on cached readings; each case injects one fault into the readings or the live scheme version, a teacher answer is supplied for every contested criterion so only the guard can stop signing, and the KMS sign call is replaced by a counter",
        "writtenAt": now_iso(),
        "total": sum(p["total"] for p in parts),
        "passed": sum(p["passed"] for p in parts),
        "parts": parts,
        "controlsSigned": sum(1 for r in controls if r["signed"]),
        "controls": len(controls),
        "failures": [r for r in rows if r["kind"] != "control" and (r["signed"] or not r["blocked"])],
        "controlFailures": [r for r in controls if not r["signed"]],
        "rows": rows,
    })
    print(json.dumps(parts, indent=1))
    print(f"controls signed {sum(1 for r in controls if r['signed'])} of {len(controls)}")


if __name__ == "__main__":
    asyncio.run(main())
