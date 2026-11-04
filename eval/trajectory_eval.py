import asyncio
import os
import json
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from strands.hooks import BeforeNodeCallEvent, HookProvider, HookRegistry
from strands_evals import Case as EvalCase
from strands_evals import Experiment
from strands_evals.evaluators import StateEquals
from strands_evals.evaluators.evaluator import Evaluator
from strands_evals.tools.evaluation_tools import exact_match_scorer
from strands_evals.types.evaluation import EnvironmentState, EvaluationData, EvaluationOutput

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

os.environ["GROQ_API_KEY"] = "replay-no-model-calls"
os.environ["GOOGLE_API_KEY"] = "replay-no-model-calls"

from docket import comparator, graph
from docket.batch import official_stand_in
from docket.checkmat import find_script
from docket.config import margin_threshold, min_confidence
from docket.graph import Case, run_case
from docket.readers import with_reading
from docket.scheme import scheme_for

CACHES = [ROOT / "out" / "cache", *sorted(p for p in (ROOT / "eval" / "runs").glob("*/out/cache") if p.parent.parent.name not in ("appeals", "trajectory"))]
WORK = ROOT / "eval" / "runs" / "trajectory"
RESULT = ROOT / "eval" / "results" / "trajectory.json"
READERS = ("reader_a", "reader_b")


def replay_sign(document: dict) -> dict:
    return {**{k: v for k, v in document.items() if k != "signature"}, "signature": {"alg": "replay-unsigned"}}


graph.sign = replay_sign


class NodeTrail(HookProvider):
    def __init__(self) -> None:
        self.nodes: list[str] = []

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeNodeCallEvent, self.record)

    def record(self, event: BeforeNodeCallEvent) -> None:
        paused = event.node_id == "teacher" and not event.invocation_state["case"].teacher
        self.nodes.append("interrupt:teacher" if paused else event.node_id)


def pairs() -> list[dict]:
    groups: dict[tuple, dict[str, tuple[Path, dict]]] = defaultdict(dict)
    for folder in CACHES:
        for path in sorted(folder.glob("*.json")):
            record = json.loads(path.read_text())
            group = (str(folder.relative_to(ROOT)), record["scriptId"], record.get("promptVersion"), record.get("design", 1), bool(record.get("blind")))
            groups[group].setdefault(record["reader"], (path, record))
    found, seen = [], set()
    for (folder, script_id, version, design, blind), by_reader in groups.items():
        first = [spec for spec in by_reader if spec.startswith("groq:")]
        for a in first:
            for b in sorted(spec for spec in by_reader if not spec.startswith("groq:")):
                pair = (by_reader[a][0].name, by_reader[b][0].name)
                if pair in seen:
                    continue
                seen.add(pair)
                found.append({"readers": f"{a} + {b}", "cache": folder, "scriptId": script_id, "promptVersion": version, "design": design, "blind": blind, "a": str(by_reader[a][0].relative_to(ROOT)), "b": str(by_reader[b][0].relative_to(ROOT))})
    return found


def load(path: str, script, scheme) -> dict:
    record = json.loads((ROOT / path).read_text())
    record["cached"] = True
    return with_reading(record, script, scheme)


def expected_for(source: dict) -> tuple[list[str], dict[str, str], str]:
    script = find_script(source["scriptId"])
    scheme = scheme_for(script.task, "v1")
    calls = comparator.compare(scheme, load(source["a"], script, scheme), load(source["b"], script, scheme), min_confidence(), margin_threshold())
    route = comparator.route(calls)
    nodes = [*READERS, "comparator", *(["interrupt:teacher", "teacher"] if route == "teacher" else []), "signer"]
    decided = {} if route == "unread" else {c.id: "code" if c.status == "agreed" else "teacher" for c in calls}
    return nodes, decided, route


def readers_first(nodes: list[str]) -> list[str]:
    head = sorted(nodes[:2]) if set(nodes[:2]) == set(READERS) else nodes[:2]
    return [*head, *nodes[2:]]


class FollowsRoutingRule(Evaluator[dict, dict]):
    def evaluate(self, evaluation_case: EvaluationData[dict, dict]) -> list[EvaluationOutput]:
        actual = readers_first(list(evaluation_case.actual_trajectory or []))
        expected = list(evaluation_case.expected_trajectory or [])
        score = exact_match_scorer(actual_trajectory=actual, expected_trajectory=expected) if len(actual) == len(expected) else 0.0
        passed = score == 1.0
        return [EvaluationOutput(score=score, test_pass=passed, reason=f"{' -> '.join(actual)}" + ("" if passed else f" (expected {' -> '.join(expected)})"))]

    async def evaluate_async(self, evaluation_case: EvaluationData[dict, dict]) -> list[EvaluationOutput]:
        return self.evaluate(evaluation_case)


async def replay(case: EvalCase) -> dict:
    source = case.input
    folder = WORK / "out" / case.name.replace("/", "_")
    shutil.rmtree(folder, ignore_errors=True)
    os.environ["DOCKET_OUT"] = str(folder)
    script = find_script(source["scriptId"])
    scheme = scheme_for(script.task, "v1")
    records = {"a": load(source["a"], script, scheme), "b": load(source["b"], script, scheme)}
    marked = Case(script=script, scheme=scheme, readers={"a": records["a"]["reader"], "b": records["b"]["reader"]}, records=records, blind=source["blind"])
    trail = NodeTrail()
    await run_case(marked, official_stand_in(script, "v1") if script.official_score is not None else None, hooks=(trail,))
    decided = {c["id"]: c["decidedBy"] for c in marked.credential["criteria"]} if marked.credential else {}
    output = {"route": marked.route, "signed": bool(marked.credential), "blocked": marked.blocked, "teacher": marked.teacher, "interrupted": "interruptedIn" in marked.requests}
    state = [EnvironmentState(name="decidedBy", state=decided), EnvironmentState(name="interrupted", state=output["interrupted"])]
    return {"output": output, "trajectory": trail.nodes, "environment_state": state}


def main() -> None:
    shutil.rmtree(WORK, ignore_errors=True)
    sources = pairs()
    cases = []
    for source in sources:
        nodes, decided, route = expected_for(source)
        name = f"{source['cache']}:{source['scriptId']}:{source['promptVersion']}:{source['b'].rsplit('/', 1)[-1][:8]}"
        cases.append(EvalCase[dict, dict](
            name=name,
            input=source,
            expected_trajectory=nodes,
            expected_environment_state=[EnvironmentState(name="decidedBy", state=decided), EnvironmentState(name="interrupted", state=route == "teacher")],
            metadata={"expectedRoute": route},
        ))
    experiment = Experiment[dict, dict](cases=cases, evaluators=[FollowsRoutingRule(name="routing-rule"), StateEquals(name="decidedBy"), StateEquals(name="interrupted")])
    report = asyncio.run(experiment.run_evaluations_async(replay, max_workers=1))
    rows = defaultdict(dict)
    for row, passed, reason in zip(report.cases, report.test_passes, report.reasons):
        entry = rows[row["name"]]
        entry.setdefault("scriptId", row["input"]["scriptId"])
        entry.setdefault("cache", row["input"]["cache"])
        entry.setdefault("design", row["input"]["design"])
        entry.setdefault("readers", row["input"]["readers"])
        entry.setdefault("expectedRoute", (row.get("metadata") or {}).get("expectedRoute"))
        entry.setdefault("output", row.get("actual_output"))
        entry[row["evaluator"]] = {"pass": passed, "reason": reason}
    evaluators = ["routing-rule", "decidedBy", "interrupted"]
    cases_out = [{"name": name, **entry, "pass": all(entry[e]["pass"] for e in evaluators)} for name, entry in rows.items()]
    by_route = defaultdict(lambda: {"cases": 0, "pass": 0})
    for entry in cases_out:
        by_route[entry["expectedRoute"]]["cases"] += 1
        by_route[entry["expectedRoute"]]["pass"] += entry["pass"]
    summary = {
        "what": "Replays the Strands Graph on cached reader pairs (no model calls, signing stubbed) and checks the routing rule: agreed criteria go reader_a/reader_b -> comparator -> signer and are decided by code; any contested criterion pauses the Graph on a Strands interrupt at the teacher node (interrupt:teacher), resumes with the teacher's decision, then reaches the signer, and is decided by the teacher; an unread criterion goes to the signer, where the guard blocks it.",
        "library": "strands-agents-evals 1.8.0: Case, Experiment, EvaluationReport, StateEquals and exact_match_scorer. Its TrajectoryEvaluator needs an LLM judge (default Bedrock), so the trajectory check is a deterministic Evaluator subclass that applies the library's exact_match_scorer to the node trail.",
        "trajectorySource": "BeforeNodeCallEvent hook on the Graph, one entry per node call; the two readers run in parallel, so their order is normalised.",
        "teacher": "official CHECK-MAT expert grade stands in for the teacher, as in the rest of the repo",
        "caches": sorted({c["cache"] for c in cases_out}),
        "cases": len(cases_out),
        "scripts": len({c["scriptId"] for c in cases_out}),
        "distinctReadingPairs": "each case is a distinct pair of cached reading files; copies of the same cache in other run folders are counted once",
        "readerPairs": dict(Counter(c["readers"] for c in cases_out)),
        "pass": sum(c["pass"] for c in cases_out),
        "byExpectedRoute": dict(by_route),
        "byEvaluator": {e: sum(rows[n][e]["pass"] for n in rows) for e in evaluators},
        "modelCalls": 0,
        "results": cases_out,
    }
    RESULT.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, indent=2))


if __name__ == "__main__":
    main()
