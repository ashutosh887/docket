import json
import os
from datetime import datetime, timezone

import boto3

s3 = boto3.client("s3")
DATA_PREFIX = os.environ.get("DATA_PREFIX", "data/")
IMAGES = (".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif")
PRIVATE_PARTS = ("cache/", "blocks/", "remarks/", "batches/", "pending/")


def read_json(bucket, key):
    return json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read())


def keys(bucket, prefix):
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            yield item["Key"]


def json_docs(bucket, prefix):
    for key in keys(bucket, prefix):
        if not key.endswith(".json") or key.endswith("/index.json") or key[len(prefix):].startswith(PRIVATE_PARTS):
            continue
        try:
            yield key, read_json(bucket, key)
        except ValueError:
            continue


def is_credential(doc):
    return isinstance(doc, dict) and "credentialId" in doc and "signature" in doc and "scriptId" in doc


def handler(event, _context):
    bucket, key = event["bucket"], event["key"]
    scheme = read_json(bucket, key)
    version = scheme.get("schemeVersion") or scheme.get("version") or key.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return {"action": "bump", "schemeVersion": version, "bucket": bucket, "schemeKey": key}


def reindex(event, _context):
    bucket = (event or {}).get("bucket") or os.environ["DATA_BUCKET"]
    index = {"source": "examples", "generatedAt": None, "credentials": [], "revocations": None, "schemes": [], "images": {}, "readings": {}, "other": []}
    images = []
    index["pending"] = []
    for key in keys(bucket, DATA_PREFIX):
        rel = key[len(DATA_PREFIX):]
        if rel.startswith("pending/") and rel.endswith(".json"):
            index["pending"].append(rel)
        if rel.lower().endswith(IMAGES) and not rel.startswith(PRIVATE_PARTS) and "/reference/" not in rel and "solve_true" not in rel:
            images.append(rel)
    for key, doc in json_docs(bucket, DATA_PREFIX):
        rel = key[len(DATA_PREFIX):]
        if not isinstance(doc, dict):
            continue
        if is_credential(doc):
            index["credentials"].append({"file": rel, "credentialId": doc["credentialId"], "scriptId": doc["scriptId"], "schemeVersion": doc.get("schemeVersion")})
        elif isinstance(doc.get("entries"), list) and doc.get("signature"):
            if not index["revocations"] or rel.endswith("revocations.json"):
                index["revocations"] = rel
        elif doc.get("schemeVersion") and isinstance(doc.get("criteria"), list) and not doc.get("signature"):
            index["schemes"].append({"file": rel, "schemeId": doc.get("schemeId"), "schemeVersion": doc["schemeVersion"]})
        elif doc.get("scriptId"):
            index["readings"].setdefault(doc["scriptId"], []).append(rel)
        else:
            index["other"].append(rel)
    pending_ids = {p.rsplit("/", 1)[-1][: -len(".json")] for p in index["pending"]}
    for script_id in {c["scriptId"] for c in index["credentials"]} | pending_ids:
        base = lambda f: f.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        exact = [f for f in images if base(f) == script_id]
        near = sorted((f for f in images if script_id in f.rsplit("/", 1)[-1]), key=len)
        folder = sorted(f for f in images if script_id in f.split("/")[:-1])
        if exact or near or folder:
            index["images"][script_id] = (exact or near or folder)[0]
    index["credentials"].sort(key=lambda c: c["credentialId"])
    index["schemes"].sort(key=lambda s: str(s["schemeVersion"]))
    try:
        previous = read_json(bucket, f"{DATA_PREFIX}index.json")
        index["source"] = previous.get("source", "examples")
    except s3.exceptions.NoSuchKey:
        pass

    index["generatedAt"] = datetime.now(timezone.utc).isoformat()
    s3.put_object(Bucket=bucket, Key=f"{DATA_PREFIX}index.json", Body=json.dumps(index, indent=2).encode(), ContentType="application/json", CacheControl="public,max-age=30")
    return {"credentials": len(index["credentials"]), "schemes": len(index["schemes"]), "revocations": index["revocations"]}
