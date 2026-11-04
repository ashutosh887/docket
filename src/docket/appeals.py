import json
import shutil
from itertools import product
from pathlib import Path

from docket import comparator, store
from docket.checkmat import Script, script_for_case
from docket.config import margin_threshold, min_confidence
from docket.graph import Case, run_case
from docket.readers import with_reading
from docket.revocations import revoke
from docket.scheme import Scheme, scheme_for
from docket.signing import PUBLIC_PEM, sign

REVIEW_NOTE = "official expert grade (stand-in for the teacher), changing as few appealed marks as reach it"
UNCHANGED = "appeal reviewed, grade unchanged"


def upheld(reason: str) -> str:
    return f"appeal upheld: {reason}"


def appeal_key(appeal_id: str) -> str:
    return f"appeals/{appeal_id}.json"


def next_appeal_id(script_id: str) -> str:
    return f"apl_{script_id}_{len(store.keys(f'appeals/apl_{script_id}_')) + 1}"


def cached_records(case: dict, script: Script, scheme: Scheme) -> dict[str, dict]:
    records = {}
    for side, ref in (case.get("readings") or {}).items():
        record = ref and store.get(f"cache/{ref['key']}.json")
        if not record:
            raise ValueError(f"no cached reading from reader {side} for {case['scriptId']}; an appeal never calls a model")
        record["cached"] = True
        records[side] = with_reading(record, script, scheme)
    if set(records) != {"a", "b"}:
        raise ValueError(f"{case['scriptId']} needs cached readings from both readers")
    return records


def swap_check(scheme: Scheme, records: dict[str, dict]) -> dict:
    straight = comparator.compare(scheme, records["a"], records["b"], min_confidence(), margin_threshold())
    swapped = comparator.compare(scheme, records["b"], records["a"], min_confidence(), margin_threshold())
    differences = [
        {"id": s.id, "original": s.status, "swapped": w.status}
        for s, w in zip(straight, swapped)
        if (s.status, s.margin, s.readerA, s.readerB) != (w.status, w.margin, w.readerB, w.readerA)
    ]
    return {"sameCalls": not differences, "differences": differences, "originalRoute": comparator.route(straight), "swappedRoute": comparator.route(swapped)}


def reviewing_teacher(script: Script, scheme: Scheme, previous: dict):
    if script.official_score is None:
        raise ValueError(f"{script.script_id} has no official grade to stand in for the teacher")
    before = {c["id"]: c["points"] for c in previous["criteria"]}

    def answer(reason: dict) -> dict:
        contested = [c["id"] for c in reason["contested"]]
        agreed = reason.get("agreed", {})
        options = []
        for bits in product((0, 1), repeat=len(contested)):
            decisions = dict(zip(contested, bits))
            distance = abs(scheme.score({**agreed, **decisions}) - script.official_score)
            changes = sum(before.get(k) != v for k, v in decisions.items())
            options.append((distance, changes, bits))
        bits = min(options)[2]
        return {"decisions": dict(zip(contested, bits)), "note": REVIEW_NOTE}

    return answer


def marks_of(case: Case) -> dict[str, int]:
    return {c.id: (c.readerA if c.status == "agreed" else case.teacher[c.id]) for c in case.calls}


async def appeal(script_id: str, reason: str, criteria: list[str] | None = None) -> dict:
    record = store.load_case(script_id)
    if not record or not record.get("credentialId"):
        raise ValueError(f"{script_id} has no signed credential to appeal")
    previous = store.load_credential(record["credentialId"])
    script = script_for_case(record)
    scheme = scheme_for(script.task)
    criteria = list(criteria or [c.id for c in scheme.criteria])
    unknown = set(criteria) - {c.id for c in scheme.criteria}
    if unknown:
        raise ValueError(f"{sorted(unknown)} are not criteria of task {script.task}")
    originals = cached_records(record, script, scheme)
    swapped = {"a": originals["b"], "b": originals["a"]}
    appeal_id = next_appeal_id(script_id)
    filed = store.now()
    case = Case(
        script=script,
        scheme=scheme,
        readers={"a": swapped["a"]["reader"], "b": swapped["b"]["reader"]},
        records=swapped,
        supersedes=previous,
        appeal={"appealId": appeal_id, "reason": reason, "criteria": criteria},
    )
    await run_case(case, reviewing_teacher(script, scheme, previous))
    if case.credential:
        outcome, decision, standing = "upheld", upheld(reason), case.credential["credentialId"]
        revoke(previous["credentialId"], decision, "superseded", standing)
        record.update(credentialId=standing, total=case.credential["total"])
    elif case.unchanged:
        outcome, decision, standing = "unchanged", UNCHANGED, previous["credentialId"]
    else:
        return {"appealId": appeal_id, "scriptId": script_id, "outcome": "not decided", "blocked": case.blocked, "interrupt": case.interrupt}
    marks = marks_of(case)
    document = sign({
        "appealId": appeal_id,
        "scriptId": script_id,
        "imageSha256": script.image_sha256,
        "appealed": previous["credentialId"],
        "schemeId": scheme.scheme_id,
        "schemeVersion": scheme.version,
        "reason": reason,
        "criteria": criteria,
        "readers": dict(case.readers),
        "swapCheck": swap_check(scheme, originals),
        "calls": [{"id": c.id, "readerA": c.readerA, "readerB": c.readerB, "status": c.status, "why": c.reason, "points": marks[c.id], "before": next((p["points"] for p in previous["criteria"] if p["id"] == c.id), None), "decidedBy": "code" if c.status == "agreed" else "teacher"} for c in case.calls],
        "teacher": {"decisions": dict(case.teacher), "note": case.note},
        "oldTotal": previous["total"],
        "newTotal": scheme.score(marks),
        "max": scheme.max,
        "outcome": outcome,
        "decision": decision,
        "standingCredential": standing,
        "modelCalls": 0,
        "filedAt": filed,
        "decidedAt": store.now(),
    })
    store.put(appeal_key(appeal_id), document)
    record["appeals"] = [*record.get("appeals", []), appeal_id]
    store.save_case(record)
    return {"key": store.where(appeal_key(appeal_id)), "seconds": case.seconds, **document}


def export_appeals(target) -> list[str]:
    target = Path(target)
    for folder in ("credentials", "records"):
        (target / folder).mkdir(parents=True, exist_ok=True)
    written, index = [], []
    for key in store.keys("appeals/"):
        document = store.get(key)
        path = target / "records" / f"{document['appealId']}.json"
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2))
        written.append(str(path))
        for credential_id in dict.fromkeys((document["appealed"], document["standingCredential"])):
            credential = store.load_credential(credential_id)
            path = target / "credentials" / f"{credential_id}.json"
            path.write_text(json.dumps(credential, ensure_ascii=False, indent=2))
            written.append(str(path))
        index.append({k: document[k] for k in ("appealId", "scriptId", "appealed", "standingCredential", "outcome", "decision", "oldTotal", "newTotal", "max")})
    revocations = store.get(store.REVOCATIONS)
    if revocations:
        (target / "revocations.json").write_text(json.dumps(revocations, ensure_ascii=False, indent=2))
        written.append(str(target / "revocations.json"))
    shutil.copyfile(PUBLIC_PEM, target / "docket-public.pem")
    (target / "index.json").write_text(json.dumps({"generatedAt": store.now(), "appeals": index}, ensure_ascii=False, indent=2))
    written.append(str(target / "index.json"))
    return written
