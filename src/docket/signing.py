import base64
import hashlib
import json
from functools import lru_cache
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, load_der_public_key, load_pem_public_key

from docket.config import ROOT, aws_session, kms_key

ALG = "ECDSA_SHA_256"
PUBLIC_PEM = Path(__file__).with_name("docket-public.pem")


def whole_numbers(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {k: whole_numbers(v) for k, v in value.items()}
    if isinstance(value, list):
        return [whole_numbers(v) for v in value]
    return value


def canonical(document: dict) -> bytes:
    body = whole_numbers({k: v for k, v in document.items() if k != "signature"})
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest(document: dict) -> bytes:
    return hashlib.sha256(canonical(document)).digest()


@lru_cache(maxsize=1)
def kms():
    return aws_session().client("kms")


@lru_cache(maxsize=1)
def key_arn() -> str:
    return kms().describe_key(KeyId=kms_key())["KeyMetadata"]["Arn"]


def sign(document: dict) -> dict:
    response = kms().sign(KeyId=kms_key(), Message=digest(document), MessageType="DIGEST", SigningAlgorithm=ALG)
    signed = {k: v for k, v in document.items() if k != "signature"}
    signed["signature"] = {"alg": ALG, "keyId": key_arn(), "value": base64.b64encode(response["Signature"]).decode()}
    return signed


def export_public_key(*paths: Path) -> list[Path]:
    der = kms().get_public_key(KeyId=kms_key())["PublicKey"]
    pem = load_der_public_key(der).public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    targets = paths or (PUBLIC_PEM, ROOT / "examples" / "docket-public.pem")
    for path in targets:
        path.write_bytes(pem)
    return list(targets)


def verify(document: dict, pem: Path = PUBLIC_PEM) -> bool:
    signature = document.get("signature") or {}
    if signature.get("alg") != ALG or not signature.get("value"):
        return False
    key = load_pem_public_key(pem.read_bytes())
    try:
        key.verify(base64.b64decode(signature["value"]), digest(document), ec.ECDSA(utils.Prehashed(hashes.SHA256())))
        return True
    except (InvalidSignature, ValueError):
        return False
