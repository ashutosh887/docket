import json
import os
import time
from functools import lru_cache
from pathlib import Path

from docket.config import aws_session, out_dir


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def location() -> str:
    return os.environ.get("DOCKET_STORE", "")


def on_s3() -> bool:
    return location().startswith("s3://")


def _bucket_prefix() -> tuple[str, str]:
    rest = location()[len("s3://"):]
    bucket, _, prefix = rest.partition("/")
    return bucket, prefix.strip("/")


@lru_cache(maxsize=1)
def s3():
    return aws_session().client("s3")


def _s3_key(key: str) -> str:
    _, prefix = _bucket_prefix()
    return f"{prefix}/{key}" if prefix else key


def put(key: str, document: dict) -> str:
    body = json.dumps(document, ensure_ascii=False, indent=2)
    if on_s3():
        bucket, _ = _bucket_prefix()
        s3().put_object(Bucket=bucket, Key=_s3_key(key), Body=body.encode("utf-8"), ContentType="application/json")
        return f"s3://{bucket}/{_s3_key(key)}"
    path = out_dir() / key
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(body)
    tmp.replace(path)
    return str(path)


def get(key: str) -> dict | None:
    if on_s3():
        bucket, _ = _bucket_prefix()
        try:
            return json.loads(s3().get_object(Bucket=bucket, Key=_s3_key(key))["Body"].read())
        except s3().exceptions.NoSuchKey:
            return None
    path = out_dir() / key
    return json.loads(path.read_text()) if path.exists() else None


def delete(key: str) -> None:
    if on_s3():
        bucket, _ = _bucket_prefix()
        s3().delete_object(Bucket=bucket, Key=_s3_key(key))
        return
    path = out_dir() / key
    if path.exists():
        path.unlink()


def keys(prefix: str) -> list[str]:
    if on_s3():
        bucket, root = _bucket_prefix()
        full = _s3_key(prefix)
        found = []
        for page in s3().get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=full):
            found += [item["Key"][len(root) + 1 if root else 0:] for item in page.get("Contents", [])]
        return sorted(k for k in found if k.endswith(".json"))
    base = out_dir()
    folder = base / prefix.rsplit("/", 1)[0] if "/" in prefix else base
    if not folder.exists():
        return []
    return sorted(str(p.relative_to(base)) for p in folder.rglob("*.json") if str(p.relative_to(base)).startswith(prefix))


def where(key: str) -> str:
    if on_s3():
        bucket, _ = _bucket_prefix()
        return f"s3://{bucket}/{_s3_key(key)}"
    return str(out_dir() / key)


def load_case(script_id: str) -> dict | None:
    return get(f"cases/{script_id}.json")


def save_case(case: dict) -> str:
    return put(f"cases/{case['scriptId']}.json", case)


def all_cases() -> list[dict]:
    return [get(k) for k in keys("cases/")]


def credential_key(credential_id: str) -> str:
    return f"credentials/{credential_id}.json"


def save_credential(credential: dict) -> str:
    return put(credential_key(credential["credentialId"]), credential)


def load_credential(credential_id: str) -> dict | None:
    return get(credential_key(credential_id))


def credentials_for(script_id: str) -> list[dict]:
    return [get(k) for k in keys(f"credentials/dkt_{script_id}_")]


def pending_key(script_id: str) -> str:
    return f"pending/{script_id}.json"


def log_block(entry: dict) -> None:
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + f"{time.time() % 1:.6f}"[1:]
    put(f"blocks/{stamp}-{entry.get('scriptId', 'unknown')}.json", {"at": now(), **entry})


def blocks() -> list[dict]:
    return [get(k) for k in keys("blocks/")]


REVOCATIONS = "revocations.json"


def local_path(key: str) -> Path:
    return out_dir() / key
