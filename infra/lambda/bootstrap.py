import importlib
import os

import boto3

_loaded = False


def _load_secrets():
    global _loaded
    if _loaded:
        return
    names = [n for n in os.environ.get("SECRET_PARAMETERS", "").split(",") if n]
    if names:
        found = boto3.client("ssm").get_parameters(Names=names, WithDecryption=True)
        for parameter in found["Parameters"]:
            os.environ.setdefault(parameter["Name"].rsplit("/", 1)[-1], parameter["Value"])
    _loaded = True


def handler(event, context):
    _load_secrets()
    try:
        target = importlib.import_module("docket.aws_handler")
    except ModuleNotFoundError as missing:
        if missing.name not in ("docket", "docket.aws_handler"):
            raise
        return {**event, "status": "awaiting-core", "credentialId": None}
    return target.handler(event, context)
