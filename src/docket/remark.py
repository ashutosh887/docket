import asyncio
import time

from docket import store
from docket.checkmat import script_for_case
from docket.revocations import load_revocations, publish_revocations
from docket.scheme import SCHEMES, changed_tasks, current_version, set_current_version
from docket.service import mark


def carried_decisions(previous: dict, old: str, new: str, task: int) -> dict[str, int]:
    before, after = SCHEMES[old][task], SCHEMES[new][task]
    same = {c.id for c in after.criteria if any(o.id == c.id and o.definition_hash == c.definition_hash for o in before.criteria)}
    return {c["id"]: c["points"] for c in previous["criteria"] if c["decidedBy"] == "teacher" and c["id"] in same}


def affected(old: str, new: str) -> list[dict]:
    tasks = changed_tasks(old, new)
    return [c for c in store.all_cases() if c["task"] in tasks and c.get("credentialId")]


def change_note(old: str, new: str) -> str | None:
    return next((SCHEMES[new][t].change for t in changed_tasks(old, new) if SCHEMES[new][t].change), None)


def revocation_entries(entries: list[dict], outcomes: list[dict], old: str, new: str) -> list[dict]:
    change = change_note(old, new)
    for o in outcomes:
        if o.get("status") == "reissued":
            reason = f"scheme {old} -> {new}: total {o['oldTotal']} -> {o['newTotal']}. {change or ''}".strip()
            entries = [e for e in entries if e["credentialId"] != o["old"]]
            entries.append({"credentialId": o["old"], "status": "superseded", "reason": reason, "replacedBy": o["new"]})
    return entries


async def remark_one(case: dict, old: str, new: str, limit: asyncio.Semaphore) -> dict:
    async with limit:
        previous = store.load_credential(case["credentialId"])
        script = script_for_case(case)
        result = await mark(script, new, supersedes=previous, carried=carried_decisions(previous, old, new, script.task))
        outcome = {"scriptId": script.script_id, "old": previous["credentialId"], "oldTotal": previous["total"]}
        if result.credential:
            outcome.update(status="reissued", new=result.credential["credentialId"], newTotal=result.credential["total"])
        elif result.unchanged:
            outcome.update(status="unchanged", newTotal=previous["total"])
        elif result.interrupt:
            outcome.update(status="needs-teacher", contested=[c["id"] for c in result.interrupt["reason"]["contested"]])
        else:
            outcome.update(status="blocked", reason=result.blocked)
        outcome["seconds"] = result.seconds
        outcome["reread"] = [side for side, record in result.records.items() if record and not record.get("cached")]
        return outcome


async def bump(new: str, concurrency: int = 4) -> dict:
    old = current_version()
    if new == old:
        raise ValueError(f"scheme is already {new}")
    started = time.monotonic()
    set_current_version(new)
    tasks = changed_tasks(old, new)
    limit = asyncio.Semaphore(concurrency)
    outcomes = await asyncio.gather(*[remark_one(c, old, new, limit) for c in affected(old, new)])
    change = change_note(old, new)
    publish_revocations(revocation_entries(load_revocations()["entries"], outcomes, old, new))
    report = {
        "from": old,
        "to": new,
        "change": change,
        "tasksChanged": tasks,
        "remarked": len(outcomes),
        "reissued": sum(o["status"] == "reissued" for o in outcomes),
        "unchanged": sum(o["status"] == "unchanged" for o in outcomes),
        "needsTeacher": sum(o["status"] == "needs-teacher" for o in outcomes),
        "blocked": sum(o["status"] == "blocked" for o in outcomes),
        "modelCalls": sum(len(o["reread"]) for o in outcomes),
        "seconds": round(time.monotonic() - started, 1),
        "at": store.now(),
        "outcomes": outcomes,
    }
    report["key"] = store.put(f"remarks/{old}-to-{new}-{int(time.time())}.json", report)
    return report
