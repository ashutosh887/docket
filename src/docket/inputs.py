import re
from pathlib import Path

from docket.checkmat import ESTIMATE, PART, Script
from docket.config import out_dir
from docket.store import s3

REFERENCE = re.compile(r"(reference|solve_true)[^/]*\.png$")


def _download(bucket: str, key: str, folder: Path) -> Path:
    target = folder / key.replace("/", "__")
    if not target.exists():
        s3().download_file(bucket, key, str(target))
    return target


def _part(key: str) -> int:
    match = PART.search(key)
    return int(match.group(1)) if match else 0


def resolve_keys(bucket: str, script_key: str) -> tuple[list[str], str | None]:
    if not script_key.endswith("/"):
        return [script_key], None
    listed = []
    for page in s3().get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=script_key):
        listed += [item["Key"] for item in page.get("Contents", []) if item["Key"].lower().endswith(".png")]
    references = [k for k in listed if REFERENCE.search(k)]
    pages = sorted((k for k in listed if k not in references), key=lambda k: (_part(k), k))
    return pages, (references[0] if references else None)


def script_from_s3(bucket: str, keys: list[str], reference_key: str | None, script_id: str, task: int) -> Script:
    folder = out_dir() / "inputs" / script_id
    folder.mkdir(parents=True, exist_ok=True)
    images = tuple(_download(bucket, key, folder) for key in keys)
    reference = _download(bucket, reference_key, folder) if reference_key else None
    match = ESTIMATE.search(keys[0])
    source = {"kind": "s3", "bucket": bucket, "keys": list(keys), "referenceKey": reference_key}
    return Script(script_id, task, images, reference, int(match.group(1)) if match else None, source)


def script_id_from_key(script_key: str) -> str:
    parts = [p for p in script_key.rstrip("/").split("/") if p]
    name = parts[-1]
    if script_key.endswith("/"):
        return name
    stem = Path(name).stem
    match = re.match(r"(\d+\.\d+\.\d+)", stem)
    return match.group(1) if match else stem
