import json
import math
import re
from fractions import Fraction
from functools import lru_cache
from pathlib import Path

KEYS = Path(__file__).with_name("keys")

EQUATIONS = {
    "13.1": lambda x: math.cos(2 * x) - math.sqrt(2) * math.sin(x + math.pi) - 1,
    "13.2": lambda x: math.sin(x) * math.cos(2 * x) + math.sqrt(2) * math.cos(x) ** 2 + math.sin(x),
    "13.3": lambda x: math.sin(2 * x) + 2 * math.sin(-x) + math.cos(-x) - 1,
    "13.4": lambda x: math.cos(2 * x) + 2 - math.sqrt(3) * math.cos(3 * math.pi / 2 - x),
    "13.5": lambda x: 9 * 81 ** math.cos(x) - 28 * 9 ** math.cos(x) + 3,
    "13.6": lambda x: 2 * math.log(4 * math.sin(x), 4) ** 2 - 5 * math.log(4 * math.sin(x), 4) + 2 if math.sin(x) > 0 else float("nan"),
}

FRACTION = re.compile(r"^\s*([+-]?)\s*(\d+)?\s*(?:/\s*(\d+))?\s*$")


def fraction(text) -> Fraction:
    if isinstance(text, (int, Fraction)):
        return Fraction(text)
    cleaned = str(text).replace("π", "").replace("pi", "").replace(" ", "").replace("−", "-")
    if cleaned in ("", "+"):
        return Fraction(1)
    if cleaned == "-":
        return Fraction(-1)
    if cleaned.startswith("-/") or cleaned.startswith("/"):
        cleaned = cleaned.replace("/", "1/", 1)
    return Fraction(cleaned)


def lcm(a: Fraction, b: Fraction) -> Fraction:
    return Fraction(math.lcm(a.numerator, b.numerator), math.gcd(a.denominator, b.denominator))


def parsed(families: list[dict]) -> list[tuple[Fraction, Fraction]] | None:
    out = []
    for family in families:
        try:
            offset, period = fraction(family["offset"]), abs(fraction(family["period"]))
        except (ValueError, ZeroDivisionError, KeyError, TypeError):
            return None
        if period == 0:
            return None
        out += [(sign * offset, period) for sign in ((1, -1) if family.get("plus_minus") else (1,))]
    return out


def points(items: list[tuple[Fraction, Fraction]], span: Fraction) -> frozenset[Fraction]:
    found = set()
    for offset, period in items:
        for j in range(int(span / period)):
            found.add((offset + j * period) % span)
    return frozenset(found)


def span_of(*groups: list[tuple[Fraction, Fraction]]) -> Fraction:
    span = Fraction(2)
    for group in groups:
        for _, period in group:
            span = lcm(span, period)
    return span


def same_set(families: list[dict], others: list[dict]) -> bool:
    a, b = parsed(families), parsed(others)
    if a is None or b is None:
        return False
    span = span_of(a, b)
    return points(a, span) == points(b, span)


def canonical_families(families: list[dict]) -> str:
    items = parsed(families)
    if items is None:
        return "unparsed"
    span = span_of(items)
    return f"mod {span}pi: " + ", ".join(f"{p}pi" for p in sorted(points(items, span)))


def canonical_roots(roots: list) -> str:
    try:
        return ", ".join(f"{r}pi" for r in sorted({fraction(r) for r in roots}))
    except (ValueError, ZeroDivisionError):
        return "unparsed"


def same_roots(roots: list, others: list) -> bool:
    return canonical_roots(roots) != "unparsed" and canonical_roots(roots) == canonical_roots(others)


@lru_cache(maxsize=None)
def key_for(variant: str) -> dict | None:
    path = KEYS / f"{variant}.json"
    return json.loads(path.read_text()) if path.exists() else None


def variant_of(script_id: str) -> str:
    return ".".join(script_id.split(".")[:2])


def check_key(variant: str) -> list[str]:
    key = key_for(variant)
    problems = []
    equation = EQUATIONS.get(variant)
    if equation is None:
        return [f"{variant}: no equation to check against"]
    for family in key["partA"]:
        offset, period = fraction(family["offset"]), fraction(family["period"])
        for j in range(-3, 4):
            x = float(offset + j * period) * math.pi
            value = equation(x)
            if not math.isfinite(value) or abs(value) > 1e-9:
                problems.append(f"{variant}: {offset}pi + {period}pi*{j} gives {value}")
    low, high = (fraction(v) for v in key["interval"])
    derived = set()
    for family in key["partA"]:
        offset, period = fraction(family["offset"]), fraction(family["period"])
        j = math.floor((low - offset) / period) - 1
        while offset + j * period <= high:
            if offset + j * period >= low:
                derived.add(offset + j * period)
            j += 1
    if derived != {fraction(r) for r in key["partB"]}:
        problems.append(f"{variant}: part (b) key {sorted(fraction(r) for r in key['partB'])} but part (a) gives {sorted(derived)} on the interval")
    grid = [low + (high - low) * Fraction(i, 20000) for i in range(20001)]
    for left, right in zip(grid, grid[1:]):
        a, b = equation(float(left) * math.pi), equation(float(right) * math.pi)
        if math.isfinite(a) and math.isfinite(b) and a * b < 0 and not any(left <= r <= right for r in derived):
            problems.append(f"{variant}: a sign change between {left}pi and {right}pi that the key does not list")
    return problems


def _part_state(part: dict, matches: bool) -> str:
    if not part.get("legible", True):
        return "illegible"
    if not part.get("present"):
        return "absent"
    return f"{'right' if matches else 'wrong'}, work {'shown' if part.get('work_shown') else 'missing'}"


def derive(transcript: dict, script, scheme) -> dict:
    declined = bool(transcript.get("declined")) or not transcript.get("student_work_visible", True)
    key = key_for(variant_of(script.script_id))
    part_a, part_b = transcript.get("part_a") or {}, transcript.get("part_b") or {}
    a_text = canonical_families(part_a.get("families") or [])
    b_text = canonical_roots(part_b.get("roots") or [])
    a_right = bool(part_a.get("present")) and same_set(part_a.get("families") or [], key["partA"])
    b_right = bool(part_b.get("present")) and same_roots(part_b.get("roots") or [], key["partB"])
    a_state, b_state = _part_state(part_a, a_right), _part_state(part_b, b_right)
    k1 = a_right and bool(part_a.get("work_shown"))
    k2 = b_right and bool(part_b.get("work_shown"))
    both_worked = bool(part_a.get("work_shown")) and bool(part_b.get("work_shown")) and bool(part_a.get("present")) and bool(part_b.get("present"))
    k3 = both_worked and ((a_right and b_right) or bool(transcript.get("computational_slip_only")))
    rows = [
        ("K1", k1, f"a: {a_text} ({a_state})", f"a={a_text}|{a_state}"),
        ("K2", k2, f"b: {b_text} ({b_state})", f"b={b_text}|{b_state}"),
        ("K3", k3, f"a {a_state}; b {b_state}; slip_only={bool(transcript.get('computational_slip_only'))}", f"a={a_text}|{a_state}|b={b_text}|{b_state}|slip={bool(transcript.get('computational_slip_only')) and not (a_right and b_right)}"),
    ]
    wanted = {c.id for c in scheme.criteria}
    criteria = [] if declined else [{"id": cid, "met": met, "confidence": 1.0, "evidence": evidence[:200], "transcript": token} for cid, met, evidence, token in rows if cid in wanted]
    return {
        "student_work_visible": transcript.get("student_work_visible", True),
        "declined": declined,
        "decline_reason": transcript.get("decline_reason"),
        "criteria": criteria,
        "design": 2,
        "key": key["source"],
    }
