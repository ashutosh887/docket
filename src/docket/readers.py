import asyncio
import hashlib
import json
import logging
import os
import random
import time
from pathlib import Path

from pydantic import BaseModel, Field
from strands import Agent

from docket.checkmat import Script
from docket import store
from docket.scheme import Scheme

PROMPT_VERSION = "r3"

log = logging.getLogger("docket.readers")

SYSTEM_PROMPT = """You are one of two independent readers of a handwritten exam script. You read; you never grade.
The script is a Russian Unified State Exam (EGE) profile mathematics answer. The first image(s) are the student's handwritten work, in order. The last image, when present and labelled REFERENCE, is the official task statement with the official solution and criteria table; it is not the student's work.
For each criterion you are given, decide only whether the student's own handwritten work shows it (met true or false), how sure you are (confidence 0 to 1), and quote or transcribe the student's lines that support your call (evidence, under 200 characters).
If no student handwriting is visible, or you were given only the reference or only the question, set student_work_visible to false and declined to true, give the reason, and mark every criterion met false with confidence 0. Never infer a student's work from the reference.
Return every criterion id you were given, exactly once."""


class CriterionReading(BaseModel):
    id: str = Field(description="Criterion id, for example K1")
    met: bool = Field(description="True only if the student's handwritten work shows this criterion")
    confidence: float = Field(ge=0, le=1, description="How sure the reader is about met, 0 to 1")
    evidence: str = Field(description="The student's lines supporting the call, transcribed, under 200 characters")


class ScriptReading(BaseModel):
    student_work_visible: bool = Field(description="False when no student handwriting is in the images")
    declined: bool = Field(description="True when the reader cannot read a student's work and refuses to read criteria")
    decline_reason: str | None = Field(default=None, description="Why the reader declined, else null")
    criteria: list[CriterionReading]


PROMPT_VERSION_V2 = "t1"

SYSTEM_PROMPT_V2 = """You are one of two independent transcribers of a handwritten exam script. You copy what the student wrote; you never judge whether it is right.
The script is a Russian Unified State Exam (EGE) profile mathematics answer to a trigonometric equation task: part (a) solve the equation, part (b) list the roots in a given interval. The first image(s) are the student's handwritten work, in order. The last image, when labelled REFERENCE, is the official statement and solution; it is not the student's work and you must never copy from it.
For each part report:
- present: true if the student wrote a final answer for that part (usually after "Ответ" or at the end of the part).
- legible: false if you cannot read the student's final answer for that part.
- written: the student's final answer exactly as written, in plain text.
- step: the student's line where that answer is reached, transcribed.
- work_shown: true if the student wrote out the derivation that leads to that answer (transformations for (a); a selection method such as a circle, inequalities or substitution for (b)).
- Part (a) families: each root series as offset and period in units of pi, as fractions: "pi/4 + 2pi n" is offset "1/4", period "2"; "pi k" is offset "0", period "1"; "+-2pi/3 + 2pi k" is offset "2/3", period "2", plus_minus true; "pi/3 + 2pi k/3" is offset "1/3", period "2/3". Copy the student's series even if they look wrong.
- Part (b) roots: each number the student gives, in units of pi as a fraction: "-13pi/4" is "-13/4", "-3pi" is "-3", "2pi" is "2".
Also report computational_slip_only: true only if the student's method is complete in both parts and a wrong answer comes only from an arithmetic slip; false otherwise, and false when both answers look right.
If no student handwriting is visible, or you were given only the reference or only the question, set student_work_visible false and declined true with the reason, and leave both parts present false."""


class Family(BaseModel):
    offset: str = Field(description="Offset in units of pi, a fraction such as -1/2")
    period: str = Field(description="Period in units of pi, a fraction such as 2")
    plus_minus: bool = Field(default=False, description="True when the student wrote a plus-minus sign before the offset")


class PartATranscript(BaseModel):
    present: bool
    legible: bool
    written: str
    step: str
    work_shown: bool
    families: list[Family]


class PartBTranscript(BaseModel):
    present: bool
    legible: bool
    written: str
    step: str
    work_shown: bool
    roots: list[str] = Field(description="Each root in units of pi as a fraction, for example -13/4")


class ScriptTranscript(BaseModel):
    student_work_visible: bool
    declined: bool
    decline_reason: str | None = None
    part_a: PartATranscript
    part_b: PartBTranscript
    computational_slip_only: bool


def design_for(script: Script) -> int:
    from docket.answers import key_for, variant_of

    if os.environ.get("DOCKET_DESIGN", "2") == "1":
        return 1
    return 2 if key_for(variant_of(script.script_id)) else 1


def criteria_prompt(scheme: Scheme) -> str:
    lines = [f"Task {scheme.task}. Criteria to read (scheme {scheme.version}):"]
    lines += [f"- {c.id}: {c.text}" for c in scheme.criteria]
    lines.append(f"Official criteria text: {scheme.official}")
    return "\n".join(lines)


def prompt_version(scheme: Scheme, design: int = 1) -> str:
    if design == 2:
        material = json.dumps([PROMPT_VERSION_V2, SYSTEM_PROMPT_V2, ScriptTranscript.model_json_schema()])
        return "d2-" + hashlib.sha256(material.encode()).hexdigest()[:12]
    material = json.dumps([PROMPT_VERSION, SYSTEM_PROMPT, [(c.id, c.text) for c in scheme.criteria], scheme.official])
    return hashlib.sha256(material.encode()).hexdigest()[:12]


GEMINI_SETTINGS = {"thinking_config": {"thinking_level": "low"}, "max_output_tokens": 8192}
SETTINGS_TAGS = {"gemini": "thinking=low,max_output_tokens=8192"}


def settings_tag(spec: str) -> str:
    tag = SETTINGS_TAGS.get(spec.split(":", 1)[0])
    return f"@{tag}" if tag else ""


def build_model(spec: str):
    provider, model_id = spec.split(":", 1)
    if provider == "groq":
        from strands.models.openai import OpenAIModel

        return OpenAIModel(
            client_args={"api_key": os.environ["GROQ_API_KEY"], "base_url": "https://api.groq.com/openai/v1", "timeout": 300, "max_retries": 0},
            model_id=model_id,
            params={"temperature": 0, "max_completion_tokens": 3000},
        )
    if provider == "openrouter":
        from strands.models.openai import OpenAIModel

        return OpenAIModel(
            client_args={"api_key": os.environ["OPENROUTER_API_KEY"], "base_url": "https://openrouter.ai/api/v1", "timeout": 300, "max_retries": 0},
            model_id=model_id,
            params={"temperature": 0, "max_tokens": 8000},
        )
    if provider == "cohere":
        from strands.models.openai import OpenAIModel

        return OpenAIModel(
            client_args={"api_key": os.environ["COHERE_API_KEY"], "base_url": "https://api.cohere.ai/compatibility/v1"},
            model_id=model_id,
            params={"temperature": 0},
        )
    if provider == "gemini":
        from strands.models.gemini import GeminiModel

        return GeminiModel(
            client_args={"api_key": os.environ["GOOGLE_API_KEY"], "http_options": {"timeout": 300_000}},
            model_id=model_id,
            params={"temperature": 0, **GEMINI_SETTINGS},
        )
    raise ValueError(f"unknown reader provider {provider}")


def image_block(path: Path) -> dict:
    return {"image": {"format": "png", "source": {"bytes": path.read_bytes()}}}


def content_for(script: Script, scheme: Scheme, blind: bool = False, reference: bool = True, design: int = 1) -> list[dict]:
    blocks: list[dict] = [{"text": criteria_prompt(scheme) if design == 1 else f"Task {scheme.task}. Transcribe the student's final answers to parts (a) and (b)."}]
    if not blind:
        for index, path in enumerate(script.images, 1):
            blocks.append({"text": f"STUDENT WORK, page {index} of {len(script.images)}:"})
            blocks.append(image_block(path))
    if script.reference and reference:
        blocks.append({"text": "REFERENCE (official statement, solution and criteria; not the student's work):"})
        blocks.append(image_block(script.reference))
    return blocks


def cache_key(script: Script, spec: str, scheme: Scheme, blind: bool, design: int | None = None) -> str:
    design = design or design_for(script)
    material = f"{script.image_sha256}|{spec}{settings_tag(spec)}|{prompt_version(scheme, design)}|{'blind' if blind else 'scan'}"
    return hashlib.sha256(material.encode()).hexdigest()




RETRYABLE = ("429", "rate", "throttl", "503", "502", "504", "unavailable", "overloaded", "500", "internal", "timeout", "timed out", "temporarily", "connection", "disconnected", "reset")


def too_large(error: Exception) -> bool:
    text = str(error).lower()
    return "413" in text or "request too large" in text


def retryable(error: Exception) -> bool:
    text = f"{type(error).__name__} {error}".lower()
    return any(marker in text for marker in RETRYABLE)


def with_reading(record: dict, script: Script, scheme: Scheme) -> dict:
    if "transcript" not in record:
        return record
    from docket.answers import derive

    record["reading"] = derive(record["transcript"], script, scheme)
    record["definitions"] = {c.id: c.definition_hash for c in scheme.criteria}
    return record


def _normalise(reading: ScriptReading, scheme: Scheme) -> ScriptReading:
    by_id = {c.id: c for c in reading.criteria}
    reading.criteria = [by_id[c.id] for c in scheme.criteria if c.id in by_id]
    return reading


PROVIDER_LIMITS = {"groq": 1, "gemini": 3, "cohere": 1, "openrouter": 4}
_limits: dict[tuple[str, int], asyncio.Semaphore] = {}


def provider_limit(spec: str) -> asyncio.Semaphore:
    provider = spec.split(":", 1)[0]
    size = int(os.environ.get(f"DOCKET_LIMIT_{provider.upper()}", PROVIDER_LIMITS.get(provider, 2)))
    key = (provider, id(asyncio.get_running_loop()))
    if key not in _limits:
        _limits[key] = asyncio.Semaphore(size)
    return _limits[key]


async def read_script(script: Script, spec: str, scheme: Scheme, blind: bool = False, attempts: int = 6) -> dict:
    design = design_for(script)
    key = cache_key(script, spec, scheme, blind, design)
    cached = store.get(f"cache/{key}.json")
    if cached:
        cached["cached"] = True
        return with_reading(cached, script, scheme)
    last: Exception | None = None
    with_reference = True
    for attempt in range(attempts):
        started = time.monotonic()
        try:
            async with provider_limit(spec):
                started = time.monotonic()
                agent = Agent(model=build_model(spec), system_prompt=SYSTEM_PROMPT if design == 1 else SYSTEM_PROMPT_V2, callback_handler=None)
                result = await agent.invoke_async(content_for(script, scheme, blind, with_reference, design), structured_output_model=ScriptReading if design == 1 else ScriptTranscript)
            output = _normalise(result.structured_output, scheme) if design == 1 else result.structured_output
            record = {
                "key": key,
                "reader": spec,
                "settings": settings_tag(spec).lstrip("@") or None,
                "scriptId": script.script_id,
                "imageSha256": script.image_sha256,
                "promptVersion": prompt_version(scheme, design),
                "design": design,
                "blind": blind,
                "definitions": {c.id: c.definition_hash for c in scheme.criteria},
                ("reading" if design == 1 else "transcript"): output.model_dump(),
                "seconds": round(time.monotonic() - started, 1),
                "usage": dict(result.metrics.accumulated_usage) if result.metrics else None,
                "readAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "attempts": attempt + 1,
                "reference": bool(script.reference) and with_reference,
                "raw": result.message,
            }
            store.put(f"cache/{key}.json", json.loads(json.dumps(record, ensure_ascii=False, default=str)))
            record["cached"] = False
            return with_reading(record, script, scheme)
        except Exception as error:
            last = error
            if too_large(error):
                if not (with_reference and script.reference):
                    break
                with_reference = False
                log.warning("reader %s on %s: request too large, retrying without the reference image", spec, script.script_id)
                continue
            if not retryable(error) or attempt == attempts - 1:
                break
            wait = min(90, 6 * 2**attempt) + random.uniform(0, 3)
            log.warning("reader %s on %s failed (%s), retrying in %.0fs", spec, script.script_id, str(error)[:120], wait)
            await asyncio.sleep(wait)
    raise RuntimeError(f"reader {spec} failed on {script.script_id}: {last}") from last
