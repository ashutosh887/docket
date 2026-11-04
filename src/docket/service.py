from dataclasses import asdict

from docket import store
from docket.checkmat import Script, script_for_case
from docket.graph import Case, run_case, session_id
from docket.revocations import revoke
from docket.scheme import current_version, scheme_for


def summary(case: Case) -> dict:
    return {
        "scriptId": case.script.script_id,
        "task": case.script.task,
        "images": [str(p) for p in case.script.images],
        "source": case.script.source,
        "imageSha256": case.script.image_sha256,
        "officialScore": case.script.official_score,
        "schemeVersion": case.scheme.version,
        "readers": case.readers,
        "readings": {side: (record and {"key": record["key"], "seconds": record.get("seconds"), "cached": record.get("cached")}) for side, record in case.records.items()},
        "errors": case.errors,
        "calls": [asdict(c) for c in case.calls],
        "route": case.route,
        "teacher": case.teacher,
        "note": case.note,
        "credentialId": case.credential["credentialId"] if case.credential else None,
        "total": case.credential["total"] if case.credential else None,
        "unchanged": case.unchanged,
        "blocked": case.blocked,
        "pending": case.interrupt,
        "seconds": case.seconds,
        "session": {"sessionId": session_id(case), **case.requests},
        "updatedAt": store.now(),
    }


def persist(case: Case) -> dict:
    record = summary(case)
    previous = store.load_case(case.script.script_id) or {}
    if not case.credential and previous.get("credentialId") and not case.blind:
        record["credentialId"] = previous["credentialId"]
        record["total"] = previous.get("total")
    if not case.blind:
        store.save_case(record)
    pending = store.pending_key(case.script.script_id)
    if case.interrupt and not case.blind:
        store.put(pending, {"scriptId": case.script.script_id, "schemeVersion": case.scheme.version, "interrupt": case.interrupt, "decisions": dict(case.carried), "note": None, "supersedes": case.supersedes["credentialId"] if case.supersedes else None})
    elif case.credential or case.unchanged:
        store.delete(pending)
    return record


def prior_teacher_decisions(script: Script, version: str) -> dict[str, int]:
    prior = [c for c in store.credentials_for(script.script_id) if c["schemeVersion"] == version and c["imageSha256"] == script.image_sha256]
    if not prior:
        return {}
    latest = max(prior, key=lambda c: c["issuedAt"])
    return {c["id"]: c["points"] for c in latest["criteria"] if c["decidedBy"] == "teacher"}


async def mark(script: Script, version: str | None = None, blind: bool = False, supersedes: dict | None = None, carried: dict | None = None, answer=None) -> Case:
    if carried is None and not blind:
        carried = prior_teacher_decisions(script, version or current_version())
    case = Case(script=script, scheme=scheme_for(script.task, version), blind=blind, supersedes=supersedes, carried=carried or {})
    await run_case(case, answer)
    persist(case)
    return case


async def teacher(script_id: str, decisions: dict[str, int], note: str | None = None) -> tuple[Case | None, dict]:
    path = store.pending_key(script_id)
    pending = store.get(path)
    if not pending:
        raise ValueError(f"no teacher decision is pending for {script_id}")
    pending["decisions"].update({k: int(v) for k, v in decisions.items()})
    if note:
        pending["note"] = note
    contested = [c["id"] for c in pending["interrupt"]["reason"]["contested"]]
    unknown = set(decisions) - set(contested)
    if unknown:
        raise ValueError(f"{sorted(unknown)} not contested on {script_id}; contested: {contested}")
    store.put(path, pending)
    if not set(contested) <= set(pending["decisions"]):
        return None, pending
    response = {"decisions": {k: v for k, v in pending["decisions"].items() if k in contested}, "note": pending["note"]}
    previous = store.load_credential(pending["supersedes"]) if pending.get("supersedes") else None
    case = await mark(script_for_case(store.load_case(script_id)), pending["schemeVersion"], supersedes=previous, answer=lambda reason: response)
    if previous and case.credential:
        reason = f"re-marked under scheme {case.scheme.version} with a teacher decision: total {previous['total']} -> {case.credential['total']}"
        revoke(previous["credentialId"], reason, "superseded", case.credential["credentialId"])
    return case, pending
