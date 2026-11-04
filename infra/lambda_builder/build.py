import io
import json
import os
import re
import shutil
import urllib.request
import zipfile

import boto3

s3 = boto3.client("s3")
WHEEL = re.compile(r"^(?P<name>.+?)-(?P<ver>[^-]+)(-\d[^-]*)?-(?P<py>[^-]+)-(?P<abi>[^-]+)-(?P<plat>[^-]+)\.whl$")
GLIBC = re.compile(r"manylinux_(\d+)_(\d+)_aarch64")


def platform_rank(plat):
    if plat == "any":
        return 1
    best = 0
    for tag in plat.split("."):
        if tag == "manylinux2014_aarch64":
            best = max(best, 3)
        match = GLIBC.match(tag)
        if match and (int(match.group(1)), int(match.group(2))) <= (2, 34):
            best = max(best, 3)
    return best


def python_rank(py, abi):
    tags = py.split(".")
    if "cp312" in tags and abi in ("cp312", "abi3", "none"):
        return 3
    if abi == "abi3" and any(t.startswith("cp3") and t[3:].isdigit() and int(t[3:]) <= 12 for t in tags):
        return 2
    if abi == "none" and any(t in ("py3", "py2.py3") or t.startswith("py3") for t in tags):
        return 1
    return 0


def choose(name, version):
    with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{version}/json", timeout=60) as res:
        files = json.load(res)["urls"]
    ranked = []
    for f in files:
        if f["packagetype"] != "bdist_wheel":
            continue
        m = WHEEL.match(f["filename"])
        if not m:
            continue
        p, q = platform_rank(m["plat"]), python_rank(m["py"], m["abi"])
        if p and q:
            ranked.append((p, q, f["url"]))
    if not ranked:
        raise RuntimeError(f"no aarch64 py3.12 wheel for {name}=={version}")
    return max(ranked)[2]


def handler(event, _context):
    bucket = event["bucket"]
    root = "/tmp/pkg"
    shutil.rmtree(root, ignore_errors=True)
    os.makedirs(root)
    skip = set(event.get("skip", []))
    picked = []
    for line in event["requirements"]:
        name, version = line.split("==")
        if name.lower().replace("_", "-") in skip:
            continue
        url = choose(name, version)
        with urllib.request.urlopen(url, timeout=120) as res:
            zipfile.ZipFile(io.BytesIO(res.read())).extractall(root)
        picked.append(url.rsplit("/", 1)[-1])
    source = s3.get_object(Bucket=bucket, Key=event["sourceKey"])["Body"].read()
    zipfile.ZipFile(io.BytesIO(source)).extractall(root)
    out = "/tmp/remark.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for folder, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for f in files:
                path = os.path.join(folder, f)
                z.write(path, os.path.relpath(path, root))
    unzipped = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(root) for f in fs)
    s3.upload_file(out, bucket, event["outputKey"])
    return {"outputKey": event["outputKey"], "zipBytes": os.path.getsize(out), "unzippedBytes": unzipped, "wheels": picked}
