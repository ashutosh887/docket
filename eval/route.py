from docket import config
from docket.comparator import as_dicts, compare, route


def route_script(record_a, record_b, scheme):
    calls = compare(scheme, record_a, record_b, config.min_confidence(), config.margin_threshold())
    core_route = route(calls)
    agreed = {c.id: c.readerA for c in calls if c.status == "agreed"}
    routed = [c.id for c in calls if c.status != "agreed"]
    floor = dict(agreed)
    for c in calls:
        if c.status != "agreed":
            values = [v for v in (c.readerA, c.readerB) if v is not None]
            floor[c.id] = min(values) if values else 0
    signed = core_route == "signer"
    return {
        "route": "signed" if signed else "teacher",
        "coreRoute": core_route,
        "teacherCriteria": routed,
        "criteriaCount": len(calls),
        "total": scheme.score(agreed) if signed else None,
        "floorTotal": scheme.score(floor),
        "calls": as_dicts(calls),
    }
