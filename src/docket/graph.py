import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from strands.agent.agent_result import AgentResult
from strands.hooks import BeforeNodeCallEvent, HookProvider, HookRegistry
from strands.multiagent import GraphBuilder
from strands.multiagent.base import MultiAgentBase, MultiAgentResult, NodeResult, Status
from strands.telemetry.metrics import EventLoopMetrics

from docket import comparator, store
from docket.checkmat import Script
from docket.config import margin_threshold, min_confidence, reader_a, reader_b
from docket.readers import read_script
from docket.scheme import Scheme, current_version
from docket.signing import sign

log = logging.getLogger("docket.graph")


@dataclass
class Case:
    script: Script
    scheme: Scheme
    readers: dict[str, str] = field(default_factory=lambda: {"a": reader_a(), "b": reader_b()})
    blind: bool = False
    records: dict[str, dict | None] = field(default_factory=lambda: {"a": None, "b": None})
    errors: dict[str, str] = field(default_factory=dict)
    calls: list[comparator.CriterionCall] = field(default_factory=list)
    route: str | None = None
    teacher: dict[str, int] = field(default_factory=dict)
    carried: dict[str, int] = field(default_factory=dict)
    note: str | None = None
    supersedes: dict | None = None
    credential: dict | None = None
    unchanged: bool = False
    blocked: str | None = None
    interrupt: Any = None
    seconds: float = 0.0
    requests: dict = field(default_factory=dict)
    appeal: dict | None = None

    def contested(self) -> list[comparator.CriterionCall]:
        return [c for c in self.calls if c.status == "contested"]

    def evidence(self, criterion_id: str) -> dict:
        out = {}
        for side, record in self.records.items():
            if record:
                match = next((c for c in record["reading"]["criteria"] if c["id"] == criterion_id), None)
                if match:
                    out[side] = {"met": match["met"], "confidence": match["confidence"], "evidence": match["evidence"]}
        return out


def _result(name: str, text: str, started: float) -> MultiAgentResult:
    elapsed = round((time.monotonic() - started) * 1000)
    message = {"role": "assistant", "content": [{"text": text}]}
    agent_result = AgentResult(stop_reason="end_turn", message=message, metrics=EventLoopMetrics(), state={})
    node = NodeResult(result=agent_result, execution_time=elapsed, status=Status.COMPLETED, execution_count=1)
    return MultiAgentResult(status=Status.COMPLETED, results={name: node}, execution_count=1, execution_time=elapsed)


class Step(MultiAgentBase):
    def __init__(self, name: str, run: Callable[[Case], Awaitable[str]]):
        super().__init__()
        self.id = name
        self.name = name
        self.run = run

    async def invoke_async(self, task: Any, invocation_state: dict[str, Any] | None = None, **kwargs: Any) -> MultiAgentResult:
        started = time.monotonic()
        text = await self.run(invocation_state["case"])
        return _result(self.name, text, started)


def reader(side: str) -> Callable[[Case], Awaitable[str]]:
    async def run(case: Case) -> str:
        if case.records.get(side) is not None:
            reading = case.records[side]["reading"]
            return f"reader {side} replayed {len(reading['criteria'])} cached criteria, declined={reading['declined']}"
        try:
            case.records[side] = await read_script(case.script, case.readers[side], case.scheme, blind=case.blind)
        except Exception as error:
            case.errors[side] = str(error)[:500]
            return f"reader {side} failed: {str(error)[:200]}"
        reading = case.records[side]["reading"]
        return f"reader {side} read {len(reading['criteria'])} criteria, declined={reading['declined']}"

    return run


async def compare_step(case: Case) -> str:
    case.calls = comparator.compare(case.scheme, case.records["a"], case.records["b"], min_confidence(), margin_threshold())
    if case.appeal:
        for call in case.calls:
            if call.status == "agreed" and call.id in case.appeal["criteria"]:
                call.status, call.reason = "contested", "under appeal"
    case.route = comparator.route(case.calls)
    return f"route={case.route}"


async def teacher_step(case: Case) -> str:
    return f"teacher decided {sorted(case.teacher)}"


def build_credential(case: Case) -> dict:
    values, criteria = {}, []
    for call in case.calls:
        if call.status == "agreed":
            points, decided_by = call.readerA, "code"
        else:
            points, decided_by = case.teacher[call.id], "teacher"
        values[call.id] = points
        criteria.append({"id": call.id, "points": points, "max": 1, "readerA": call.readerA, "readerB": call.readerB, "margin": call.margin, "decidedBy": decided_by})
    version = case.scheme.version
    sequence = len([c for c in store.credentials_for(case.script.script_id) if c["schemeVersion"] == version]) + 1
    decided = [c["id"] for c in criteria if c["decidedBy"] == "teacher"]
    return {
        "credentialId": f"dkt_{case.script.script_id}_{version}_{sequence}",
        "scriptId": case.script.script_id,
        "imageSha256": case.script.image_sha256,
        "schemeId": case.scheme.scheme_id,
        "schemeVersion": version,
        "criteria": criteria,
        "total": case.scheme.score(values),
        "max": case.scheme.max,
        "readers": dict(case.readers),
        "teacher": {"decided": decided, "note": case.note if decided else None},
        "route": "teacher" if decided else "straight",
        "design": 2 if any((r or {}).get("design") == 2 for r in case.records.values()) else 1,
        "issuedAt": store.now(),
        "supersedes": case.supersedes["credentialId"] if case.supersedes else None,
        **({"appeal": {"appealId": case.appeal["appealId"], "reason": case.appeal["reason"]}} if case.appeal else {}),
    }


def same_marks(old: dict, new: dict) -> bool:
    return old["total"] == new["total"] and [(c["id"], c["points"]) for c in old["criteria"]] == [(c["id"], c["points"]) for c in new["criteria"]]


async def signer_step(case: Case) -> str:
    draft = build_credential(case)
    if case.appeal:
        if draft["total"] == case.supersedes["total"]:
            case.unchanged = True
            return f"appeal reviewed, grade unchanged: {draft['total']}/{draft['max']}"
        case.credential = sign(draft)
        store.save_credential(case.credential)
        return f"appeal upheld: signed {case.credential['credentialId']} total={draft['total']}/{draft['max']}"
    if not case.supersedes:
        same = [c for c in store.credentials_for(case.script.script_id) if c["schemeVersion"] == draft["schemeVersion"] and c["imageSha256"] == draft["imageSha256"] and c["readers"] == draft["readers"] and same_marks(c, draft)]
        if same:
            case.credential = same[-1]
            return f"already signed as {case.credential['credentialId']}"
    if case.supersedes and case.supersedes["schemeId"] == draft["schemeId"] and same_marks(case.supersedes, draft) and case.supersedes["schemeVersion"] != draft["schemeVersion"]:
        case.unchanged = True
        return f"unchanged under {draft['schemeVersion']}: {draft['total']}/{draft['max']}"
    case.credential = sign(draft)
    store.save_credential(case.credential)
    return f"signed {case.credential['credentialId']} total={draft['total']}/{draft['max']}"


class TeacherInterrupt(HookProvider):
    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeNodeCallEvent, self.ask)

    def ask(self, event: BeforeNodeCallEvent) -> None:
        if event.node_id != "teacher":
            return
        case: Case = event.invocation_state["case"]
        contested = [c.id for c in case.contested()]
        preset = {k: v for k, v in case.carried.items() if k in contested}
        reason = {
            "scriptId": case.script.script_id,
            "schemeVersion": case.scheme.version,
            "agreed": {c.id: c.readerA for c in case.calls if c.status == "agreed"},
            "contested": [{"id": c.id, "criterion": case.scheme.criterion(c.id).text, "readerA": c.readerA, "readerB": c.readerB, "margin": c.margin, "why": c.reason, "readings": case.evidence(c.id)} for c in case.contested()],
        }
        response = event.interrupt("teacher", reason=reason, response=preset if set(preset) == set(contested) else None)
        decisions = response.get("decisions", response) if isinstance(response, dict) else {}
        case.teacher = {k: int(v) for k, v in decisions.items() if k in contested}
        if isinstance(response, dict) and response.get("note"):
            case.note = response["note"]


class SigningGuard(HookProvider):
    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeNodeCallEvent, self.check)

    def problems(self, case: Case) -> list[str]:
        found = []
        live = current_version()
        if case.scheme.version != live:
            found.append(f"case is on scheme {case.scheme.version} but the current scheme is {live}")
        for side in ("a", "b"):
            record = case.records.get(side)
            if record is None:
                found.append(f"no reading from reader {side}" + (f" ({case.errors[side][:120]})" if side in case.errors else ""))
                continue
            if record["reading"]["declined"]:
                found.append(f"reader {side} declined: {record['reading'].get('decline_reason')}")
            read_ids = {c["id"] for c in record["reading"]["criteria"]}
            for criterion in case.scheme.criteria:
                if criterion.id not in read_ids:
                    found.append(f"{criterion.id} has no reading from reader {side}")
                elif record["definitions"].get(criterion.id) != criterion.definition_hash:
                    found.append(f"reader {side} read {criterion.id} against another definition than scheme {case.scheme.version}")
        for call in case.contested():
            if call.id not in case.teacher:
                found.append(f"{call.id} is contested and has no teacher decision")
        return found

    def check(self, event: BeforeNodeCallEvent) -> None:
        if event.node_id != "signer":
            return
        case: Case = event.invocation_state["case"]
        found = self.problems(case)
        if found:
            case.blocked = "; ".join(found)
            store.log_block({"scriptId": case.script.script_id, "schemeVersion": case.scheme.version, "blind": case.blind, "reasons": found})
            event.cancel_node = f"signing blocked: {case.blocked}"


def both_read(state) -> bool:
    done = {node.node_id for node in state.completed_nodes}
    return {"reader_a", "reader_b"} <= done


def routed(*routes: str) -> Callable[..., bool]:
    def condition(state, invocation_state=None) -> bool:
        return invocation_state["case"].route in routes

    return condition


def session_id(case: Case) -> str:
    suffix = f"-{case.appeal['appealId']}" if case.appeal else ""
    return f"docket-{case.script.script_id}-{case.scheme.version}{suffix}".replace(".", "_")


def session_for(case: Case):
    if store.on_s3():
        from strands.session.s3_session_manager import S3SessionManager

        from docket.config import aws_session

        bucket, prefix = store._bucket_prefix()
        return S3SessionManager(session_id=session_id(case), bucket=bucket, prefix=f"{prefix}/sessions" if prefix else "sessions", boto_session=aws_session())
    from strands.session.file_session_manager import FileSessionManager

    from docket.config import out_dir

    return FileSessionManager(session_id=session_id(case), storage_dir=str(out_dir() / "sessions"))


def invocation_id() -> str:
    import os

    return os.environ.get("DOCKET_REQUEST_ID") or f"pid-{os.getpid()}"


def build_graph(session_manager=None, hooks: tuple[HookProvider, ...] = ()):
    builder = GraphBuilder()
    builder.add_node(Step("reader_a", reader("a")), "reader_a")
    builder.add_node(Step("reader_b", reader("b")), "reader_b")
    builder.add_node(Step("comparator", compare_step), "comparator")
    builder.add_node(Step("teacher", teacher_step), "teacher")
    builder.add_node(Step("signer", signer_step), "signer")
    builder.set_entry_point("reader_a")
    builder.set_entry_point("reader_b")
    builder.add_edge("reader_a", "comparator", condition=both_read)
    builder.add_edge("reader_b", "comparator", condition=both_read)
    builder.add_edge("comparator", "signer", condition=routed("signer", "unread"))
    builder.add_edge("comparator", "teacher", condition=routed("teacher"))
    builder.add_edge("teacher", "signer")
    builder.set_hook_providers([TeacherInterrupt(), SigningGuard(), *hooks])
    builder.set_max_node_executions(10)
    builder.set_graph_id("docket")
    if session_manager is not None:
        builder.set_session_manager(session_manager)
    return builder.build()


async def run_case(case: Case, answer: Callable[[dict], dict | None] | None = None, hooks: tuple[HookProvider, ...] = ()) -> Case:
    started = time.monotonic()
    graph = build_graph(session_for(case), hooks)
    state = {"case": case}
    case.requests = {"started": invocation_id()}
    try:
        if graph._interrupt_state.activated:
            await reader("a")(case)
            await reader("b")(case)
            await compare_step(case)
            pending = next(iter(graph._interrupt_state.interrupts.values()))
            case.requests["interruptedIn"] = (store.get(f"sessions-meta/{session_id(case)}.json") or {}).get("interruptedIn")
            case.interrupt = {"id": pending.id, "name": pending.name, "reason": pending.reason}
            response = answer(pending.reason) if answer else None
            if response is None:
                case.seconds = round(time.monotonic() - started, 1)
                return case
            case.interrupt = None
            case.requests["resumedIn"] = invocation_id()
            result = await graph.invoke_async([{"interruptResponse": {"interruptId": pending.id, "response": response}}], state)
        else:
            result = await graph.invoke_async(f"Mark script {case.script.script_id} under scheme {case.scheme.version}", state)
        while result.status == Status.INTERRUPTED:
            pending = result.interrupts[0]
            case.interrupt = {"id": pending.id, "name": pending.name, "reason": pending.reason}
            case.requests["interruptedIn"] = invocation_id()
            store.put(f"sessions-meta/{session_id(case)}.json", {"sessionId": session_id(case), "interruptedIn": invocation_id(), "at": store.now()})
            response = answer(pending.reason) if answer else None
            if response is None:
                break
            case.interrupt = None
            case.requests["resumedIn"] = invocation_id()
            result = await graph.invoke_async([{"interruptResponse": {"interruptId": pending.id, "response": response}}], state)
    except Exception as error:
        if not case.blocked:
            raise
        log.info("signing blocked for %s: %s", case.script.script_id, error)
    case.seconds = round(time.monotonic() - started, 1)
    return case
