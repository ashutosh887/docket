from docket import store
from docket.signing import sign, verify


def load_revocations() -> dict:
    return store.get(store.REVOCATIONS) or {"issuedAt": None, "entries": []}


def publish_revocations(entries: list[dict]) -> dict:
    document = sign({"issuedAt": store.now(), "entries": entries})
    store.put(store.REVOCATIONS, document)
    return document


def revoke(credential_id: str, reason: str, status: str = "revoked", replaced_by: str | None = None) -> dict:
    current = load_revocations()
    entries = [e for e in current["entries"] if e["credentialId"] != credential_id]
    entries.append({"credentialId": credential_id, "status": status, "reason": reason, "replacedBy": replaced_by})
    return publish_revocations(entries)


def status_of(credential: dict, revocations: dict | None = None) -> dict:
    if not verify(credential):
        return {"status": "invalid", "reason": "signature does not verify against the Docket public key"}
    revocations = revocations or load_revocations()
    if revocations.get("signature") and not verify(revocations):
        return {"status": "unknown", "reason": "revocation list signature does not verify"}
    entry = next((e for e in revocations["entries"] if e["credentialId"] == credential["credentialId"]), None)
    if entry:
        return {"status": entry["status"], "reason": entry["reason"], "replacedBy": entry["replacedBy"]}
    return {"status": "valid", "reason": None}
