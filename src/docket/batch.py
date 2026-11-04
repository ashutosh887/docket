import asyncio
import json
import shutil
import time
from pathlib import Path

from docket import store
from docket.checkmat import Script, all_scripts
from docket.service import mark


def class_set(task: int | None = 13, n: int = 10, ids: list[str] | None = None) -> list[Script]:
    scripts = all_scripts()
    if ids:
        wanted = set(ids)
        return [s for s in scripts if s.script_id in wanted]
    if task is not None:
        scripts = [s for s in scripts if s.task == task]
    return scripts[:n]


STAND_IN_NOTE = "official expert grade (stand-in for the teacher)"


def official_stand_in(script: Script, version: str | None):
    from itertools import product

    from docket.scheme import scheme_for

    scheme = scheme_for(script.task, version)

    def answer(reason: dict) -> dict:
        contested = [c["id"] for c in reason["contested"]]
        best, gap = None, None
        for bits in product((0, 1), repeat=len(contested)):
            values = {**reason.get("agreed", {}), **dict(zip(contested, bits))}
            distance = abs(scheme.score(values) - (script.official_score or 0))
            if gap is None or distance < gap:
                best, gap = dict(zip(contested, bits)), distance
        return {"decisions": best, "note": STAND_IN_NOTE}

    return answer


async def mark_batch(scripts: list[Script], concurrency: int = 3, version: str | None = None, stand_in: bool = False) -> dict:
    limit = asyncio.Semaphore(concurrency)
    started = time.monotonic()

    async def one(script: Script) -> dict:
        async with limit:
            try:
                answer = official_stand_in(script, version) if stand_in and script.official_score is not None else None
                case = await mark(script, version, answer=answer)
            except Exception as error:
                return {"scriptId": script.script_id, "status": "error", "error": str(error)[:300]}
            status = "signed" if case.credential else ("needs-teacher" if case.interrupt else ("blocked" if case.blocked else "unsigned"))
            return {
                "scriptId": script.script_id,
                "status": status,
                "route": case.route,
                "credentialId": case.credential["credentialId"] if case.credential else None,
                "total": case.credential["total"] if case.credential else None,
                "officialScore": script.official_score,
                "contested": [c.id for c in case.contested()],
                "blocked": case.blocked,
                "seconds": case.seconds,
                "cached": {side: bool(r and r.get("cached")) for side, r in case.records.items()},
            }

    outcomes = await asyncio.gather(*[one(s) for s in scripts])
    report = {
        "at": store.now(),
        "scripts": len(scripts),
        "signed": sum(o["status"] == "signed" for o in outcomes),
        "needsTeacher": sum(o["status"] == "needs-teacher" for o in outcomes),
        "blocked": sum(o["status"] == "blocked" for o in outcomes),
        "errors": sum(o["status"] == "error" for o in outcomes),
        "seconds": round(time.monotonic() - started, 1),
        "outcomes": outcomes,
    }
    report["key"] = store.put(f"batches/batch-{int(time.time())}.json", report)
    return report


async def blind_check(scripts: list[Script], concurrency: int = 3) -> dict:
    limit = asyncio.Semaphore(concurrency)
    started = time.monotonic()

    async def one(script: Script) -> dict:
        async with limit:
            try:
                case = await mark(script, blind=True)
            except Exception as error:
                return {"scriptId": script.script_id, "error": str(error)[:300]}
            declined = {side: bool(r and r["reading"]["declined"]) for side, r in case.records.items()}
            return {"scriptId": script.script_id, "declined": declined, "signed": bool(case.credential), "blocked": case.blocked, "errors": case.errors}

    outcomes = await asyncio.gather(*[one(s) for s in scripts])
    answered = [o for o in outcomes if "declined" in o]
    report = {
        "at": store.now(),
        "scripts": len(scripts),
        "declinedByA": sum(o["declined"]["a"] for o in answered),
        "declinedByB": sum(o["declined"]["b"] for o in answered),
        "readsByA": sum(1 for o in answered if "a" not in o["errors"]),
        "readsByB": sum(1 for o in answered if "b" not in o["errors"]),
        "signed": sum(o["signed"] for o in answered),
        "seconds": round(time.monotonic() - started, 1),
        "outcomes": outcomes,
    }
    report["key"] = store.put(f"blind/blind-{int(time.time())}.json", report)
    return report


DATASET = {
    "name": "CHECK-MAT (Khrulev, 2025)",
    "repository": "https://github.com/Karifannaa/Auto-check-EGE-math",
    "paper": "https://arxiv.org/abs/2507.22958",
    "licence": "CHECK-MAT, research and educational use. The repository README states MIT; the Hugging Face card says research and educational purposes. Scans are not committed; fetch them with scripts/fetch_checkmat.py.",
}


def export_site(script_ids: list[str], target) -> list[str]:
    target = Path(target)
    (target / "credentials").mkdir(parents=True, exist_ok=True)
    (target / "scripts").mkdir(parents=True, exist_ok=True)
    written = []
    index = []
    for script_id in script_ids:
        case = store.load_case(script_id)
        if not case:
            continue
        credentials = store.credentials_for(script_id)
        for credential in credentials:
            path = target / "credentials" / f"{credential['credentialId']}.json"
            path.write_text(json.dumps(credential, ensure_ascii=False, indent=2))
            written.append(str(path))
        readings = {}
        for side, ref in (case.get("readings") or {}).items():
            record = ref and store.get(f"cache/{ref['key']}.json")
            if record:
                readings[side] = {"reader": record["reader"], "criteria": record["reading"]["criteria"], "declined": record["reading"]["declined"], "seconds": record.get("seconds")}
        pages = []
        for image in case.get("images", []):
            source = Path(image)
            if source.exists():
                name = f"{script_id}-{len(pages) + 1}.png"
                shutil.copyfile(source, target / "scripts" / name)
                pages.append(f"scripts/{name}")
        detail = {"scriptId": script_id, "task": case["task"], "officialScore": case.get("officialScore"), "pages": pages, "calls": case.get("calls"), "readings": readings, "credentials": [c["credentialId"] for c in credentials]}
        path = target / "scripts" / f"{script_id}.json"
        path.write_text(json.dumps(detail, ensure_ascii=False, indent=2))
        written.append(str(path))
        index.append({"scriptId": script_id, "credentials": detail["credentials"], "latest": case.get("credentialId")})
    revocations = store.get(store.REVOCATIONS)
    if revocations:
        (target / "revocations.json").write_text(json.dumps(revocations, ensure_ascii=False, indent=2))
        written.append(str(target / "revocations.json"))
    shutil.copyfile(Path(__file__).with_name("docket-public.pem"), target / "docket-public.pem")
    (target / "index.json").write_text(json.dumps({"generatedAt": store.now(), "dataset": DATASET, "scripts": index}, ensure_ascii=False, indent=2))
    return written
