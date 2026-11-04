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


async def with_outer_retry(make_call, tries=5, wait=75, log_path=None, label=""):
    last = None
    for attempt in range(tries):
        try:
            return await make_call()
        except Exception as error:
            last = error
            text = str(error)
            pause = 5 if any(m in text.lower() for m in FORMAT_ERRORS) else wait
            if log_path:
                with open(log_path, "a") as handle:
                    handle.write(json.dumps({"at": now_iso(), "label": label, "attempt": attempt + 1, "error": text[:300]}) + "\n")
            if attempt < tries - 1:
                print(f"  {ist()} call failed ({text[:140]}); waiting {pause}s", flush=True)
                await asyncio.sleep(pause)
    raise last
