import itertools
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
    if key and key.get("task") in CHECKERS:
        return CHECKERS[key["task"]](variant, key)
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
    if script.task in DERIVERS:
        return DERIVERS[script.task](transcript, script, scheme)
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


INFINITE = {"inf", "+inf", "∞", "+∞", "infinity", "+infinity"}
UNIT_SCALES = (("млн", 1_000_000), ("million", 1_000_000), ("тыс", 1000), ("thousand", 1000))


def number(text) -> Fraction | float:
    if isinstance(text, (int, Fraction)):
        return Fraction(text)
    cleaned = str(text).strip().lower().replace(" ", "").replace(" ", "").replace("−", "-").replace("–", "-").replace(",", ".")
    for prefix in ("a=", "x=", "r="):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
    if cleaned in INFINITE:
        return math.inf
    if cleaned.startswith("-") and cleaned[1:] in INFINITE:
        return -math.inf
    return Fraction(cleaned)


def normal(pieces) -> tuple:
    kept = sorted((p for p in pieces if p[0] < p[1] or (p[0] == p[1] and p[2] and p[3])), key=lambda p: (p[0], not p[2]))
    out: list = []
    for low, high, low_closed, high_closed in kept:
        if out:
            p_low, p_high, p_low_closed, p_high_closed = out[-1]
            if low < p_high or (low == p_high and (p_high_closed or low_closed)):
                if high > p_high:
                    out[-1] = (p_low, high, p_low_closed, high_closed)
                elif high == p_high:
                    out[-1] = (p_low, p_high, p_low_closed, p_high_closed or high_closed)
                continue
        out.append((low, high, low_closed, high_closed))
    return tuple(out)


def interval_set(answer: dict) -> tuple | None:
    pieces = []
    try:
        for item in answer.get("intervals") or []:
            low, high = number(item["low"]), number(item["high"])
            pieces.append((low, high, bool(item.get("low_closed")) and math.isfinite(low), bool(item.get("high_closed")) and math.isfinite(high)))
        for point in answer.get("points") or []:
            value = number(point)
            if not math.isfinite(value):
                return None
            pieces.append((value, value, True, True))
    except (ValueError, ZeroDivisionError, KeyError, TypeError):
        return None
    return normal(pieces)


def contains(pieces: tuple, x) -> bool:
    return any(low < x < high or (x == low and low_closed) or (x == high and high_closed) for low, high, low_closed, high_closed in pieces)


def with_points(pieces: tuple, points) -> tuple:
    return normal(list(pieces) + [(p, p, True, True) for p in points])


def without_points(pieces: tuple, points) -> tuple:
    current = list(pieces)
    for p in points:
        split = []
        for low, high, low_closed, high_closed in current:
            if low < p < high:
                split += [(low, p, low_closed, False), (p, high, False, high_closed)]
            elif p == low and low_closed:
                split.append((low, high, False, high_closed))
            elif p == high and high_closed:
                split.append((low, high, low_closed, False))
            else:
                split.append((low, high, low_closed, high_closed))
        current = split
    return normal(current)


def within_points(student: tuple | None, base: tuple, include, exclude) -> bool:
    if student is None:
        return False
    include, exclude = [number(p) for p in include], [number(p) for p in exclude]
    for i in range(len(include) + 1):
        for added in itertools.combinations(include, i):
            for j in range(len(exclude) + 1):
                for removed in itertools.combinations(exclude, j):
                    if without_points(with_points(base, added), removed) == student:
                        return True
    return False


def set_text(pieces: tuple | None) -> str:
    if pieces is None:
        return "unparsed"
    if not pieces:
        return "empty"
    shown = lambda v: "inf" if v == math.inf else "-inf" if v == -math.inf else str(v)
    return " U ".join(
        f"{{{shown(low)}}}" if low == high else f"{'[' if low_closed else '('}{shown(low)}, {shown(high)}{']' if high_closed else ')'}"
        for low, high, low_closed, high_closed in pieces
    )


def answer_state(answer: dict, right: bool) -> str:
    if not answer.get("legible", True):
        return "illegible"
    if not answer.get("present"):
        return "absent"
    return f"{'right' if right else 'wrong'}, work {'shown' if answer.get('work_shown') else 'missing'}"


def finish(transcript: dict, key: dict, scheme, rows) -> dict:
    declined = bool(transcript.get("declined")) or not transcript.get("student_work_visible", True)
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


def set_reading(transcript: dict, key: dict):
    answer = transcript.get("answer") or {}
    student = interval_set(answer) if answer.get("present") else None
    expected = interval_set(key["answer"])
    right = student is not None and student == expected
    return answer, student, expected, right, bool(answer.get("work_shown")) and bool(answer.get("present"))


def derive_inequality(transcript: dict, script, scheme) -> dict:
    key = key_for(variant_of(script.script_id))
    answer, student, expected, right, worked = set_reading(transcript, key)
    near = not right and within_points(student, expected, key["near"]["include"], key["near"]["exclude"])
    slip = bool(transcript.get("computational_slip_only")) and not right
    text, state = set_text(student), answer_state(answer, right)
    rows = [
        ("K1", right and worked, f"answer: {text} ({state})", f"answer={text}|{state}"),
        ("K2", worked and (near or slip), f"answer: {text} ({state}); differs only by the key's boundary point={near}; slip_only={slip}", f"answer={text}|{state}|near={near}|slip={slip}"),
    ]
    return finish(transcript, key, scheme, rows)


def derive_parameter(transcript: dict, script, scheme) -> dict:
    key = key_for(variant_of(script.script_id))
    answer, student, expected, right, worked = set_reading(transcript, key)
    near = not right and within_points(student, expected, key["near"]["include"], key["near"]["exclude"])
    part = any(within_points(student, expected if entry["base"] == "key" else interval_set(entry["base"]), entry["include"], entry["exclude"]) for entry in key["two_point_sets"])
    slip = bool(transcript.get("computational_slip_only")) and not right
    reduced = bool(transcript.get("reduced_to_study"))
    text, state = set_text(student), answer_state(answer, right)
    rows = [
        ("K1", right and worked, f"a: {text} ({state})", f"a={text}|{state}"),
        ("K2", worked and near, f"a: {text} ({state}); differs only by the key's boundary points={near}", f"a={text}|{state}|near={near}"),
        ("K3", worked and part, f"a: {text} ({state}); the 2-point set of the official criteria={part}", f"a={text}|{state}|part={part}"),
        ("K4", worked and slip, f"slip_only={slip}", f"a={text}|{state}|slip={slip}"),
        ("K5", reduced, f"reduced_to_study={reduced}", f"reduced={reduced}"),
    ]
    return finish(transcript, key, scheme, rows)


def number_matches(answer: dict, key: dict) -> tuple[bool, str]:
    try:
        value = number(answer.get("value") or "")
    except (ValueError, ZeroDivisionError, TypeError):
        return False, "unparsed"
    unit = str(answer.get("unit") or "").lower()
    scale = next((factor for word, factor in UNIT_SCALES if word in unit), 1)
    accepted = {number(v) for v in key["accepted"]}
    shown = f"{value} x{scale}" if scale != 1 else f"{value}"
    return value * scale in accepted or (scale == 1 and value in accepted), shown


def derive_number(transcript: dict, script, scheme) -> dict:
    key = key_for(variant_of(script.script_id))
    answer = transcript.get("answer") or {}
    right, text = number_matches(answer, key) if answer.get("present") else (False, "absent")
    worked = bool(answer.get("work_shown")) and bool(answer.get("present"))
    model = bool(transcript.get("model_built"))
    state = answer_state(answer, right)
    rows = [
        ("K1", right and worked, f"answer: {text} ({state})", f"answer={text}|{state}"),
        ("K2", model, f"model_built={model}", f"model={model}"),
    ]
    return finish(transcript, key, scheme, rows)


def safely(f):
    def run(x):
        try:
            return f(x)
        except (ValueError, ZeroDivisionError, OverflowError):
            return math.nan
    return run


INEQUALITIES = {
    "15.1": safely(lambda x: (3**x + 9) / (3**x - 9) + (3**x - 9) / (3**x + 9) - (4 * 3 ** (x + 1) + 144) / (9**x - 81)),
    "15.2": safely(lambda x: math.log2(x**3 - 3 * x**2 + 3 * x - 1) / 3 - (math.log2(x**2 - 1) - 5)),
    "15.3": safely(lambda x: 4 / (3**x - 27) - 1 / (3**x - 9)),
    "15.5": safely(lambda x: (math.log2(64 * x) / 2) / (math.log2(x) / 2 - 3) + (math.log2(x) / 2 - 3) / (math.log2(64 * x) / 2) - (math.log2(x**4) / 2 + 16) / ((math.log2(x) / 2) ** 2 - 9)),
}
INEQUALITY_RANGES = {"15.5": (1e-6, 300.0)}


def boundaries(pieces: tuple) -> set:
    return {v for low, high, _, _ in pieces for v in (low, high) if math.isfinite(v)}


def check_inequality(variant: str, key: dict) -> list[str]:
    f = INEQUALITIES.get(variant)
    if f is None:
        return [f"{variant}: no inequality to check against"]
    expected = interval_set(key["answer"])
    edges = boundaries(expected)
    low, high = INEQUALITY_RANGES.get(variant, (-20.0, 40.0))
    problems = []
    steps = 40000
    for i in range(steps + 1):
        x = low + (high - low) * i / steps
        if any(abs(x - float(e)) < 1e-6 for e in edges):
            continue
        value = f(x)
        holds = math.isfinite(value) and value >= 0
        if holds != contains(expected, Fraction(x)):
            problems.append(f"{variant}: at x={x:.6f} the inequality {'holds' if holds else 'fails'} but the key says {'in' if contains(expected, Fraction(x)) else 'out'}")
            if len(problems) > 5:
                break
    for e in edges:
        value = f(float(e))
        if contains(expected, e) and not (math.isfinite(value) and value >= -1e-9):
            problems.append(f"{variant}: the key includes {e} but the inequality gives {value} there")
        if not contains(expected, e) and math.isfinite(value) and value >= -1e-9:
            problems.append(f"{variant}: the key leaves out {e} but the inequality holds there ({value})")
    for p in key["near"]["include"] + key["near"]["exclude"]:
        if number(p) not in edges:
            problems.append(f"{variant}: the criteria's boundary point {p} is not a boundary of the key")
    return problems


def loan_16_2() -> Fraction:
    def total(b):
        debts = [Fraction(1300)] + [1300 - (1300 - b) * i / 5 for i in range(1, 6)] + [b - b * i / 5 for i in range(1, 6)]
        return sum(Fraction(6, 5) * debts[i - 1] - debts[i] for i in range(1, 11))
    t0, t1 = total(Fraction(0)), total(Fraction(1))
    return (2580 - t0) / (t1 - t0)


def loan_16_3() -> Fraction:
    def total(x):
        d1 = Fraction(6, 5) * 800 - x
        d2 = Fraction(6, 5) * d1 - x
        return 2 * x + Fraction(6, 5) * d2
    t0, t1 = total(Fraction(0)), total(Fraction(1))
    return (Fraction(12544, 10) - t0) / (t1 - t0)


def loan_16_4() -> Fraction:
    debts = [Fraction(10 - i, 10) for i in range(6)] + [Fraction(0)]
    for r in range(0, 101):
        k = 1 + Fraction(r, 100)
        if sum(k * debts[i - 1] - debts[i] for i in range(1, 7)) > Fraction(6, 5):
            return Fraction(r)
    return Fraction(-1)


def loan_16_5() -> Fraction:
    debts = [Fraction(39 - i, 39) for i in range(40)]
    total = lambda k: sum(k * debts[i - 1] - debts[i] for i in range(1, 40))
    t0, t1 = total(Fraction(0)), total(Fraction(1))
    k = (Fraction(6, 5) - t0) / (t1 - t0)
    return (k - 1) * 100


LOANS = {"16.2": loan_16_2, "16.3": loan_16_3, "16.4": loan_16_4, "16.5": loan_16_5}


def check_loan(variant: str, key: dict) -> list[str]:
    solve = LOANS.get(variant)
    if solve is None:
        return [f"{variant}: no loan model to check against"]
    derived = solve()
    if derived != number(key["answer"]):
        return [f"{variant}: the key says {key['answer']} but the loan model gives {derived}"]
    return []


def solutions_18(variant: str, a) -> int:
    import sympy

    x = sympy.Symbol("x", real=True)
    a = sympy.Rational(a.numerator, a.denominator)
    found = []

    def keep(expr, conditions, nonzero=()):
        poly = sympy.Poly(sympy.expand(expr), x)
        if poly.is_zero:
            raise ValueError(f"{variant}: identity at a={a}")
        for root in sympy.real_roots(poly):
            if all(sympy.simplify(c.subs(x, root)) >= 0 for c in conditions) and all(sympy.simplify(n.subs(x, root)) != 0 for n in nonzero):
                if not any(abs(float(root - other)) < 1e-12 for other in found):
                    found.append(root)

    if variant == "18.1":
        for s1 in (1, -1):
            for s2 in (1, -1):
                inner = s1 * (x - a) - 4
                keep(4 * s2 * inner + x**2 + 8 * x, [s1 * (x - a), s2 * inner])
    elif variant == "18.2":
        y = 3 * x + a
        keep(x - y + 3, [])
        keep(x**2 - 5 * x - y + 3, [x - y + 3])
    elif variant == "18.3":
        keep((x**2 + a * x + 1) ** 2 - (3 * x**2 + 2 * a * x + 1), [x**2 + a * x + 1, 3 * x**2 + 2 * a * x + 1])
    elif variant == "18.4":
        y = 2 + a * (x - 5)
        for s in (1, -1):
            inner = x - 5 * y + 5
            keep(x**2 + 5 * x + y**2 - y - s * inner - 52, [s * inner])
    elif variant == "18.5":
        for s in (1, -1):
            keep(s * 3 * x - 2 * x - 2 - a, [s * x], [x**2 - 2 * x - a])
    else:
        raise KeyError(variant)
    return len(found)


def check_parameter(variant: str, key: dict) -> list[str]:
    expected = interval_set(key["answer"])
    edges = boundaries(expected) | {number(p) for p in key["near"]["include"] + key["near"]["exclude"]}
    for entry in key["two_point_sets"]:
        edges |= {number(p) for p in entry["include"] + entry["exclude"]}
    grid = [Fraction(-20) + Fraction(i, 4) + shift for i in range(161) for shift in (Fraction(0), Fraction(1, 97))]
    grid += [e + d for e in edges for d in (Fraction(-1, 1000), Fraction(0), Fraction(1, 1000))]
    problems = []
    for a in sorted(set(grid)):
        count = solutions_18(variant, a)
        if (count == key["solutions_wanted"]) != contains(expected, a):
            problems.append(f"{variant}: at a={a} the system has {count} solutions but the key says {'in' if contains(expected, a) else 'out'}")
    return problems


CHECKERS = {15: check_inequality, 16: check_loan, 18: check_parameter}
DERIVERS = {15: derive_inequality, 16: derive_number, 18: derive_parameter}
