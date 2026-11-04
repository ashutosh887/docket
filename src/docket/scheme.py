import hashlib
from dataclasses import dataclass, field, replace



@dataclass(frozen=True)
class Criterion:
    id: str
    text: str

    @property
    def definition_hash(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Level:
    points: int
    any_of: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class Scheme:
    task: int
    version: str
    max: int
    criteria: tuple[Criterion, ...]
    levels: tuple[Level, ...]
    official: str
    change: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def scheme_id(self) -> str:
        return f"ege-profile-math-task-{self.task}"

    def criterion(self, criterion_id: str) -> Criterion:
        return next(c for c in self.criteria if c.id == criterion_id)

    def score(self, values: dict[str, int]) -> int:
        for level in self.levels:
            if any(all(values.get(k, 0) == 1 for k in clause) for clause in level.any_of):
                return level.points
        return 0

    def band(self, total: int) -> str:
        if total == self.max:
            return "full"
        return "partial" if total > 0 else "none"

    def rules_text(self) -> str:
        lines = []
        for level in self.levels:
            clauses = " OR ".join(" AND ".join(clause) for clause in level.any_of)
            lines.append(f"{level.points} points if {clauses}")
        lines.append("0 points otherwise")
        return "; ".join(lines)


TWO_PART_PROOF = (
    Criterion("K1", "Part (a): the statement is proved correctly and completely."),
    Criterion("K2", "Part (b): the correct answer is obtained with valid justification, without relying on an unproved part (a)."),
    Criterion("K3", "Part (b): the reasoning is justified but the final answer is wrong only because of an arithmetic error."),
    Criterion("K4", "Part (b): the correct answer is obtained by using the statement of part (a), while part (a) itself is not proved."),
)

TWO_PART_PROOF_LEVELS = (
    Level(3, (("K1", "K2"),)),
    Level(2, (("K2",), ("K1", "K3"))),
    Level(1, (("K1",), ("K3",), ("K4",))),
)

V1 = {
    13: Scheme(
        task=13,
        version="v1",
        max=2,
        criteria=(
            Criterion("K1", "Part (a): the correct answer (all roots of the equation) is obtained with valid justification."),
            Criterion("K2", "Part (b): the correct roots on the given interval are obtained with valid justification."),
            Criterion("K3", "Both parts: every step of the solution sequence is correct, and any wrong answer is caused only by a computational error."),
        ),
        levels=(Level(2, (("K1", "K2"),)), Level(1, (("K1",), ("K3",)))),
        official="2: обоснованно получены верные ответы в обоих пунктах; 1: обоснованно получен верный ответ в пункте а ИЛИ получены неверные ответы из-за вычислительной ошибки, но при этом имеется верная последовательность всех шагов решения обоих пунктов; 0: иначе",
    ),
    14: Scheme(
        task=14,
        version="v1",
        max=3,
        criteria=TWO_PART_PROOF,
        levels=TWO_PART_PROOF_LEVELS,
        official="3: верное доказательство а и обоснованно получен верный ответ б; 2: обоснованно получен верный ответ б ИЛИ доказательство а и арифметическая ошибка в б; 1: доказательство а ИЛИ арифметическая ошибка в б ИЛИ верный ответ б с использованием утверждения а; 0: иначе",
    ),
    15: Scheme(
        task=15,
        version="v1",
        max=2,
        criteria=(
            Criterion("K1", "The correct answer to the inequality is obtained with valid justification."),
            Criterion("K2", "Every step of the solution sequence is correct, and the answer differs from the correct one only because of a computational error."),
        ),
        levels=(Level(2, (("K1",),)), Level(1, (("K2",),))),
        official="2: обоснованно получен верный ответ; 1: ответ отличается из-за вычислительной ошибки при верной последовательности всех шагов; 0: иначе",
    ),
    16: Scheme(
        task=16,
        version="v1",
        max=2,
        criteria=(
            Criterion("K1", "The correct answer is obtained with valid justification."),
            Criterion("K2", "The word problem is correctly reduced to a complete mathematical model (not just a single equation or inequality), and the text shows how the model is built."),
        ),
        levels=(Level(2, (("K1",),)), Level(1, (("K2",),))),
        official="2: обоснованно получен верный ответ; 1: верно построена математическая модель; 0: иначе",
    ),
    17: Scheme(
        task=17,
        version="v1",
        max=3,
        criteria=TWO_PART_PROOF,
        levels=TWO_PART_PROOF_LEVELS,
        official="3: верное доказательство а и обоснованно получен верный ответ б; 2: обоснованно получен верный ответ б ИЛИ доказательство а и арифметическая ошибка в б; 1: доказательство а ИЛИ арифметическая ошибка в б ИЛИ верный ответ б с использованием утверждения а; 0: иначе",
    ),
    18: Scheme(
        task=18,
        version="v1",
        max=4,
        criteria=(
            Criterion("K1", "The correct set of parameter values is obtained with valid justification."),
            Criterion("K2", "Correct reasoning gives a set of parameter values that differs from the correct one only by excluded boundary points or by included points that are not in the answer."),
            Criterion("K3", "Correct reasoning gives an interval of the set of parameter values, possibly with boundary points included."),
            Criterion("K4", "Every step is correct, and the answer is wrong only because of a computational error."),
            Criterion("K5", "The roots are obtained and the problem is correctly reduced to studying those roots under the condition(s)."),
        ),
        levels=(Level(4, (("K1",),)), Level(3, (("K2",),)), Level(2, (("K3",), ("K4",))), Level(1, (("K5",),))),
        official="4: обоснованно получен верный ответ; 3: множество значений отличается только граничными точками; 2: получен промежуток множества значений ИЛИ вычислительная ошибка при верных шагах; 1: получены корни и задача верно сведена к исследованию корней; 0: иначе",
    ),
    19: Scheme(
        task=19,
        version="v1",
        max=4,
        criteria=(
            Criterion("K1", "Part (a): the correct answer is obtained with valid justification."),
            Criterion("K2", "Part (b): the correct answer is obtained with valid justification."),
            Criterion("K3", "Part (c): the correct answer is obtained with valid justification."),
        ),
        levels=(
            Level(4, (("K1", "K2", "K3"),)),
            Level(3, (("K3", "K1"), ("K3", "K2"))),
            Level(2, (("K1", "K2"), ("K3",))),
            Level(1, (("K1",), ("K2",))),
        ),
        official="4: верные ответы в а, б и в; 3: верный ответ в в и в а или б; 2: верные ответы в а и б ИЛИ верный ответ в в; 1: верный ответ в а или б; 0: иначе",
    ),
}

V2_CHANGE = "Demonstration amendment (not an FIPI change): on task 13, 1 point now requires that every step of both parts is correct with any wrong answer caused only by a computational error (K3); a correct part (a) next to a wrong root selection in part (b) no longer earns it."

V2 = {task: replace(scheme, version="v2") for task, scheme in V1.items()}
V2[13] = replace(
    V1[13],
    version="v2",
    levels=(Level(2, (("K1", "K2"),)), Level(1, (("K3",),))),
    change=V2_CHANGE,
)

SCHEMES = {"v1": V1, "v2": V2}


def changed_tasks(old: str, new: str) -> list[int]:
    return [task for task in SCHEMES[new] if SCHEMES[new][task].levels != SCHEMES[old][task].levels or SCHEMES[new][task].criteria != SCHEMES[old][task].criteria]


def scheme_for(task: int, version: str | None = None) -> Scheme:
    return SCHEMES[version or current_version()][task]


def current_version() -> str:
    from docket import store

    state = store.get("scheme.json")
    return state["current"] if state else "v1"


def set_current_version(version: str) -> None:
    if version not in SCHEMES:
        raise ValueError(f"unknown scheme version {version}")
    from docket import store

    store.put("scheme.json", {"current": version, "at": store.now()})
