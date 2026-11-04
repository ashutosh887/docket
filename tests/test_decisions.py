import base64
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from docket import comparator, signing, store
from docket.checkmat import Script
from docket.graph import Case, SigningGuard
from docket.scheme import changed_tasks, scheme_for


@pytest.fixture(autouse=True)
def local_store(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCKET_OUT", str(tmp_path / "out"))
    monkeypatch.delenv("DOCKET_STORE", raising=False)
    return tmp_path


def reading(values: dict[str, tuple[bool, float]], scheme, declined=False) -> dict:
    return {
        "definitions": {c.id: c.definition_hash for c in scheme.criteria},
        "reading": {
            "student_work_visible": not declined,
            "declined": declined,
            "decline_reason": "no student work" if declined else None,
            "criteria": [{"id": k, "met": met, "confidence": conf, "evidence": ""} for k, (met, conf) in values.items()],
        },
    }


def test_scheme_points_for_script_13_1_1():
    v1, v2 = scheme_for(13, "v1"), scheme_for(13, "v2")
    assert v1.score({"K1": 1, "K2": 1, "K3": 1}) == 2
    assert v1.score({"K1": 1, "K2": 0, "K3": 0}) == 1
    assert v1.score({"K1": 0, "K2": 1, "K3": 0}) == 0
    assert v2.score({"K1": 1, "K2": 0, "K3": 0}) == 0
    assert v2.score({"K1": 1, "K2": 0, "K3": 1}) == 1
    assert v2.score({"K1": 1, "K2": 1, "K3": 1}) == 2
    assert scheme_for(19, "v1").score({"K1": 1, "K2": 0, "K3": 1}) == 3
    assert scheme_for(18, "v1").score({"K5": 1}) == 1


def test_comparator_routes_at_the_threshold():
    scheme = scheme_for(15, "v1")
    at = comparator.compare(scheme, reading({"K1": (True, 1.0), "K2": (True, 1.0)}, scheme), reading({"K1": (True, 0.5), "K2": (True, 1.0)}, scheme), 0.5, 0.5)
    assert [c.status for c in at] == ["agreed", "agreed"] and at[0].margin == 0.5
    assert comparator.route(at) == "signer"
    above = comparator.compare(scheme, reading({"K1": (True, 1.0), "K2": (True, 1.0)}, scheme), reading({"K1": (True, 0.49), "K2": (True, 1.0)}, scheme), 0.4, 0.5)
    assert above[0].status == "contested" and comparator.route(above) == "teacher"
    split = comparator.compare(scheme, reading({"K1": (True, 0.9), "K2": (False, 0.9)}, scheme), reading({"K1": (True, 0.9), "K2": (True, 0.9)}, scheme), 0.6, 0.5)
    assert [c.status for c in split] == ["agreed", "contested"]
    missing = comparator.compare(scheme, reading({"K1": (True, 0.9)}, scheme), reading({"K1": (True, 0.9), "K2": (True, 0.9)}, scheme), 0.6, 0.5)
    assert missing[1].status == "unread" and comparator.route(missing) == "unread"


class FakeKms:
    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())

    def sign(self, KeyId, Message, MessageType, SigningAlgorithm):
        assert MessageType == "DIGEST" and SigningAlgorithm == "ECDSA_SHA_256"
        return {"Signature": self.key.sign(Message, ec.ECDSA(utils.Prehashed(hashes.SHA256())))}

    def describe_key(self, KeyId):
        return {"KeyMetadata": {"Arn": "arn:test"}}


@pytest.fixture
def fake_kms(tmp_path, monkeypatch):
    fake = FakeKms()
    pem = tmp_path / "test.pem"
    pem.write_bytes(fake.key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo))
    signing.kms.cache_clear()
    signing.key_arn.cache_clear()
    monkeypatch.setattr(signing, "kms", lambda: fake)
    monkeypatch.setattr(signing, "key_arn", lambda: "arn:test")
    return pem


def test_sign_verify_and_tamper_fails(fake_kms):
    credential = signing.sign({"credentialId": "dkt_13.1.1_v1_1", "total": 2, "max": 2, "teacher": {"decided": [], "note": "проверено"}})
    assert signing.verify(credential, fake_kms)
    tampered = json.loads(json.dumps(credential))
    tampered["total"] = 1
    assert not signing.verify(tampered, fake_kms)
    raw = bytearray(base64.b64decode(credential["signature"]["value"]))
    raw[-1] ^= 1
    flipped = {**credential, "signature": {**credential["signature"], "value": base64.b64encode(bytes(raw)).decode()}}
    assert not signing.verify(flipped, fake_kms)


def test_canonical_bytes_are_sorted_compact_utf8():
    assert signing.canonical({"b": 1, "a": "й", "signature": {"x": 1}}) == '{"a":"й","b":1}'.encode("utf-8")


def test_affected_set_on_bump():
    from docket.remark import affected

    assert changed_tasks("v1", "v2") == [13]
    for script_id, task, credential in (("13.1.1", 13, "dkt_13.1.1_v1_1"), ("13.2.1", 13, None), ("15.1.1", 15, "dkt_15.1.1_v1_1")):
        store.save_case({"scriptId": script_id, "task": task, "credentialId": credential})
    assert [c["scriptId"] for c in affected("v1", "v2")] == ["13.1.1"]


def make_case(scheme, record_a, record_b) -> Case:
    script = Script("13.1.1", 13, (Path("x.png"),), None, 2)
    case = Case(script=script, scheme=scheme, readers={"a": "a:a", "b": "b:b"}, records={"a": record_a, "b": record_b})
    case.calls = comparator.compare(scheme, record_a, record_b, 0.6, 0.5)
    return case


def test_signing_guard_blocks_missing_reading_and_wrong_definition():
    scheme = scheme_for(13, "v1")
    full = {"K1": (True, 0.9), "K2": (True, 0.9), "K3": (True, 0.9)}
    guard = SigningGuard()
    assert guard.problems(make_case(scheme, reading(full, scheme), reading(full, scheme))) == []
    missing = reading({"K1": (True, 0.9), "K2": (True, 0.9)}, scheme)
    assert "K3 has no reading from reader b" in guard.problems(make_case(scheme, reading(full, scheme), missing))
    stale = reading(full, scheme)
    stale["definitions"]["K2"] = "0" * 16
    assert any("another definition" in p for p in guard.problems(make_case(scheme, stale, reading(full, scheme))))
    assert any("no reading from reader a" in p for p in guard.problems(make_case(scheme, None, reading(full, scheme))))
    declined = reading({k: (False, 0.0) for k in full}, scheme, declined=True)
    assert any("declined" in p for p in guard.problems(make_case(scheme, declined, reading(full, scheme))))


def test_signing_guard_blocks_scheme_mismatch():
    from docket.scheme import set_current_version

    set_current_version("v2")
    scheme = scheme_for(13, "v1")
    full = {"K1": (True, 0.9), "K2": (True, 0.9), "K3": (True, 0.9)}
    problems = SigningGuard().problems(make_case(scheme, reading(full, scheme), reading(full, scheme)))
    assert problems == ["case is on scheme v1 but the current scheme is v2"]
