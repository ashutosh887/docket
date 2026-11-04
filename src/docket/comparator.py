from dataclasses import asdict, dataclass

from docket.scheme import Scheme


@dataclass
class CriterionCall:
    id: str
    readerA: int | None
    readerB: int | None
    margin: float | int | None
    status: str
    reason: str | None


def tidy(value: float) -> float | int:
    value = round(value, 2)
    return int(value) if value == int(value) else value


def belief(reading: dict) -> float:
    return reading["confidence"] if reading["met"] else 1 - reading["confidence"]


def _criteria(record: dict | None) -> dict:
    if not record or record["reading"]["declined"]:
        return {}
    return {c["id"]: c for c in record["reading"]["criteria"]}


def compare(scheme: Scheme, record_a: dict | None, record_b: dict | None, min_confidence: float, threshold: float) -> list[CriterionCall]:
    a, b = _criteria(record_a), _criteria(record_b)
    calls = []
    for criterion in scheme.criteria:
        ra, rb = a.get(criterion.id), b.get(criterion.id)
        if ra is None or rb is None:
            missing = " and ".join(name for name, r in (("reader a", ra), ("reader b", rb)) if r is None)
            calls.append(CriterionCall(criterion.id, ra and int(ra["met"]), rb and int(rb["met"]), None, "unread", f"no reading from {missing}"))
            continue
        if "transcript" in ra or "transcript" in rb:
            same = ra.get("transcript") == rb.get("transcript")
            unreadable = "illegible" in (ra.get("transcript") or "") or "illegible" in (rb.get("transcript") or "")
            if unreadable:
                status, reason = "contested", "a reader could not read the student's answer"
            elif not same:
                status, reason = "contested", "transcriptions differ"
            else:
                status, reason = "agreed", None
            calls.append(CriterionCall(criterion.id, int(ra["met"]), int(rb["met"]), 0 if same and not unreadable else 1, status, reason))
            continue
        margin = tidy(abs(belief(ra) - belief(rb)))
        if ra["met"] != rb["met"]:
            status, reason = "contested", "readers disagree"
        elif margin > threshold:
            status, reason = "contested", f"margin {margin} above {threshold}"
        elif min(ra["confidence"], rb["confidence"]) < min_confidence:
            status, reason = "contested", f"a reader's confidence is below {min_confidence}"
        else:
            status, reason = "agreed", None
        calls.append(CriterionCall(criterion.id, int(ra["met"]), int(rb["met"]), margin, status, reason))
    return calls


def route(calls: list[CriterionCall]) -> str:
    if any(c.status == "unread" for c in calls):
        return "unread"
    if any(c.status == "contested" for c in calls):
        return "teacher"
    return "signer"


def as_dicts(calls: list[CriterionCall]) -> list[dict]:
    return [asdict(c) for c in calls]
