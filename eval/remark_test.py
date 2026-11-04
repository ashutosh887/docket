import argparse
import asyncio
import itertools
import json
import os
import shutil
import time

from common import ROOT, RUNS, ist, now_iso, slice_scripts, write_result

WORK = RUNS / "remark" / "out"


def isolate():
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)
    (WORK / "cache").symlink_to(ROOT / "out" / "cache", target_is_directory=True)
    os.environ["DOCKET_OUT"] = str(WORK)


isolate()

from docket import config, readers, store
from docket import scheme as schemes
from docket.remark import bump
from docket.revocations import load_revocations, status_of
from docket.service import mark
from docket.signing import verify


def cached(script, scheme):
    return all((config.out_dir() / "cache" / f"{readers.cache_key(script, spec, scheme, False)}.json").exists() for spec in (config.reader_a(), config.reader_b()))


def official_stand_in(script, scheme):
    def answer(reason):
        contested = [c["id"] for c in reason["contested"]]
        case = store.load_case(script.script_id) or {}
        agreed = {c["id"]: c["readerA"] for c in case.get("calls", []) if c["status"] == "agreed"}
        best, best_gap = None, None
        for bits in itertools.product((0, 1), repeat=len(contested)):
            values = {**agreed, **dict(zip(contested, bits))}
            gap = abs(scheme.score(values) - (script.official_score or 0))
            if best_gap is None or gap < best_gap:
                best, best_gap = dict(zip(contested, bits)), gap
        return {"decisions": best, "note": "eval: the official expert grade stands in for the teacher"}

    return answer


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--slice", default="full")
    parser.add_argument("--to", default="v2")
    args = parser.parse_args()
    schemes.set_current_version("v1")
    changed = schemes.changed_tasks("v1", args.to)
    pool = [s for s in slice_scripts(args.slice) if s.task in changed and cached(s, schemes.scheme_for(s.task, "v1"))]
    print(f"{ist()} re-mark test: {len(pool)} scripts on changed tasks {changed} with cached readings")
    t0 = time.monotonic()
    first = []
    for script in pool:
        case = await mark(script, "v1")
        if case.interrupt:
            scheme = schemes.scheme_for(script.task, "v1")
            case = await mark(script, "v1", answer=official_stand_in(script, scheme))
        first.append({"scriptId": script.script_id, "credentialId": case.credential and case.credential["credentialId"], "total": case.credential and case.credential["total"], "official": script.official_score, "blocked": case.blocked})
    issue_seconds = round(time.monotonic() - t0, 1)
    report = await bump(args.to)
    revocations = load_revocations()
    by_old = {e["credentialId"]: e for e in revocations["entries"]}
    checks = []
    for o in report["outcomes"]:
        old = store.load_credential(o["old"])
        status = status_of(old)
        row = {"scriptId": o["scriptId"], "status": o["status"], "oldTotal": o["oldTotal"], "newTotal": o.get("newTotal")}
        if o["status"] == "reissued":
            new = store.load_credential(o["new"])
            row["newVerifies"] = verify(new)
            row["newSupersedesOld"] = new.get("supersedes") == o["old"]
            row["oldListed"] = by_old.get(o["old"], {}).get("replacedBy") == o["new"]
            row["oldStatus"] = status["status"]
            row["ok"] = row["newVerifies"] and row["newSupersedesOld"] and row["oldListed"] and status["status"] == "superseded"
        elif o["status"] == "unchanged":
            row["oldStatus"] = status["status"]
            row["ok"] = status["status"] == "valid" and o["old"] not in by_old
        else:
            row["ok"] = False
        checks.append(row)
    result = {
        "metric": "remark",
        "slice": args.slice,
        "from": report["from"],
        "to": report["to"],
        "change": report["change"],
        "tasksChanged": report["tasksChanged"],
        "readers": {"a": config.reader_a(), "b": config.reader_b()},
        "keyId": (revocations.get("signature") or {}).get("keyId"),
        "issuedUnderV1": sum(1 for f in first if f["credentialId"]),
        "issueSeconds": issue_seconds,
        "remarked": report["remarked"],
        "reissued": report["reissued"],
        "revoked": sum(1 for e in revocations["entries"] if e["status"] in ("superseded", "revoked")),
        "unchanged": report["unchanged"],
        "needsTeacher": report["needsTeacher"],
        "blocked": report["blocked"],
        "modelCalls": report["modelCalls"],
        "seconds": report["seconds"],
        "revocationListVerifies": verify(revocations),
        "checksPassed": sum(1 for c in checks if c["ok"]),
        "checks": len(checks),
        "teacherStandIn": "contested criteria decided by the 0/1 assignment whose scheme total is nearest the official grade",
        "writtenAt": now_iso(),
        "rows": checks,
        "firstIssue": first,
        "outDir": str(WORK.relative_to(ROOT)),
    }
    result["design"] = os.environ.get("DOCKET_DESIGN", "2")
    write_result(f"remark_d{result['design']}", result)
    print(json.dumps({k: v for k, v in result.items() if k not in ("rows", "firstIssue")}, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
