import asyncio
import os

from docket import store
from docket.inputs import resolve_keys, script_from_s3, script_id_from_key


def _bucket(event: dict) -> str:
    bucket = event.get("bucket") or os.environ.get("DOCKET_INPUT_BUCKET")
    if not bucket:
        raise ValueError("no input bucket: pass 'bucket' or set DOCKET_INPUT_BUCKET")
    return bucket


def outcome(case) -> dict:
    result = {
        "scriptId": case.script.script_id,
        "schemeVersion": case.scheme.version,
        "route": None,
        "credentialId": None,
        "credentialKey": None,
        "total": None,
        "max": case.scheme.max,
        "contested": [c.id for c in case.contested()],
        "blocked": case.blocked,
        "seconds": case.seconds,
        "session": case.requests,
    }
    if case.credential:
        result.update(route="signed", credentialId=case.credential["credentialId"], credentialKey=store.where(store.credential_key(case.credential["credentialId"])), total=case.credential["total"], path=case.credential["route"])
    elif case.interrupt:
        result.update(route="teacher", interruptKey=store.where(store.pending_key(case.script.script_id)), interrupt=case.interrupt)
    elif case.unchanged:
        result.update(route="unchanged")
    else:
        result.update(route="blocked")
    return result


def _mark(event: dict) -> dict:
    from docket.service import mark

    bucket = _bucket(event)
    script_key = event["scriptKey"]
    keys, reference = resolve_keys(bucket, script_key)
    if not keys:
        raise ValueError(f"no PNG pages under s3://{bucket}/{script_key}")
    reference = event.get("referenceKey") or reference
    script_id = event.get("scriptId") or script_id_from_key(script_key)
    task = int(event.get("task") or script_id.split(".")[0])
    script = script_from_s3(bucket, keys, reference, script_id, task)
    return outcome(asyncio.run(mark(script, event.get("schemeVersion"), blind=bool(event.get("blind")))))


def _teacher(event: dict) -> dict:
    from docket.service import teacher

    case, pending = asyncio.run(teacher(event["scriptId"], event["decisions"], event.get("note")))
    if case is None:
        contested = [c["id"] for c in pending["interrupt"]["reason"]["contested"]]
        return {"scriptId": event["scriptId"], "route": "teacher", "decided": pending["decisions"], "waitingFor": [c for c in contested if c not in pending["decisions"]]}
    return outcome(case)


def _bump(event: dict) -> dict:
    from docket.remark import affected
    from docket.scheme import changed_tasks, current_version, set_current_version

    old, new = current_version(), event["schemeVersion"]
    set_current_version(new)
    items = [{"action": "remark", "scriptId": c["scriptId"], "from": old, "to": new} for c in affected(old, new)]
    return {"from": old, "to": new, "tasksChanged": changed_tasks(old, new), "items": items}


def _remark(event: dict) -> dict:
    from docket.remark import remark_one

    case = store.load_case(event["scriptId"])

    async def run():
        return await remark_one(case, event["from"], event["to"], asyncio.Semaphore(1))

    return asyncio.run(run())


def _publish(event: dict) -> dict:
    from docket.remark import revocation_entries
    from docket.revocations import load_revocations, publish_revocations

    entries = revocation_entries(load_revocations()["entries"], event["outcomes"], event["from"], event["to"])
    document = publish_revocations(entries)
    return {"revocationsKey": store.where(store.REVOCATIONS), "entries": len(document["entries"]), "reissued": sum(o.get("status") == "reissued" for o in event["outcomes"])}


def _verify(event: dict) -> dict:
    from docket.revocations import status_of

    credential = event.get("credential") or store.load_credential(event["credentialId"])
    if credential is None:
        return {"status": "unknown", "reason": "no such credential"}
    return {"credentialId": credential.get("credentialId"), **status_of(credential)}


ACTIONS = {"mark": _mark, "teacher": _teacher, "bump": _bump, "remark": _remark, "publish-revocations": _publish, "verify": _verify}


def handler(event: dict, context=None) -> dict:
    request = getattr(context, "aws_request_id", None)
    if request:
        os.environ["DOCKET_REQUEST_ID"] = f"lambda-{request}"
    action = event.get("action") or ("mark" if "scriptKey" in event else None)
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action}; one of {sorted(ACTIONS)}")
    return ACTIONS[action](event)
