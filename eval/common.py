import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVAL = ROOT / "eval"
RUNS = EVAL / "runs"
RESULTS = EVAL / "results"
sys.path.insert(0, str(ROOT / "src"))
os.environ.pop("DOCKET_STORE", None)

from docket import config
from docket.checkmat import all_scripts


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def ist():
    return time.strftime("%H:%M IST", time.localtime())


def use_cache_for(run_id):
    if run_id in (None, "", "core") or run_id.endswith("r1"):
        os.environ.pop("DOCKET_OUT", None)
        return config.out_dir() / "cache"
    path = RUNS / run_id / "out"
    os.environ["DOCKET_OUT"] = str(path)
    return config.out_dir() / "cache"


def slice_scripts(name, limit=0):
    every = all_scripts()
    if name != "full":
        keep = set(json.loads((EVAL / f"slice_{name}.json").read_text())["scriptIds"])
        every = [s for s in every if s.script_id in keep]
    return every[:limit] if limit else every


def write_result(name, data):
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"{name}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n")


def tokens_of(record):
    usage = (record or {}).get("usage") or {}
    return {"in": usage.get("inputTokens"), "out": usage.get("outputTokens")}


FORMAT_ERRORS = ("tool call validation", "did not match schema", "structured output", "validation error", "not in request")


TRANSIENT = ("connection", "connect", "429", "rate limit", "timeout", "timed out", "503", "unavailable", "overloaded", "500", "internal", "temporarily")


DAILY_CAP: list[str] = []


async def with_outer_retry(make_call, tries=5, wait=60, log_path=None, label=""):
    last = None
    attempt = 0
    format_failures = 0
    while True:
        attempt += 1
        if DAILY_CAP:
            raise RuntimeError(f"stopped: daily cap reached earlier in this run: {DAILY_CAP[0][:200]}")
        try:
            return await make_call()
        except Exception as error:
            last = error
            text = str(error)
            low = text.lower()
            if "perday" in low.replace(" ", ""):
                DAILY_CAP.append(text[:600])
                raise last
            if any(m in low for m in FORMAT_ERRORS):
                format_failures += 1
                pause = 5
                if format_failures >= tries:
                    raise last
            elif any(m in low for m in TRANSIENT):
                pause = wait
            else:
                raise last
            if log_path:
                with open(log_path, "a") as handle:
                    handle.write(json.dumps({"at": now_iso(), "label": label, "attempt": attempt, "error": text[:300]}) + "\n")
            print(f"  {ist()} call failed ({text[:140]}); waiting {pause}s", flush=True)
            await asyncio.sleep(pause)
