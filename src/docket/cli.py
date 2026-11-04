import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from docket import store
from docket.checkmat import Script, find_script, script_from_path


def resolve(target: str, task: int | None) -> Script:
    path = Path(target)
    if path.exists():
        try:
            return script_from_path(path)
        except ValueError:
            if task is None:
                raise SystemExit("a script outside CHECK-MAT needs --task 13..19")
            return Script(script_id=path.stem, task=task, images=(path.resolve(),), reference=None, official_score=None, source={"kind": "local", "paths": [str(path.resolve())]})
    return find_script(target)


def show(document) -> None:
    print(json.dumps(document, ensure_ascii=False, indent=2))


def cmd_mark(args) -> None:
    from docket.service import mark

    case = asyncio.run(mark(resolve(args.target, args.task), args.version, blind=args.blind))
    if case.credential:
        print(f"signed {store.where(store.credential_key(case.credential['credentialId']))}")
        print(f"total {case.credential['total']}/{case.credential['max']}, route {case.credential['route']}, official {case.script.official_score}")
    elif case.interrupt:
        print(f"stopped for the teacher on {case.script.script_id}:")
        for item in case.interrupt["reason"]["contested"]:
            print(f"  {item['id']} readerA={item['readerA']} readerB={item['readerB']} margin={item['margin']} ({item['why']}): {item['criterion']}")
        ids = " ".join(f"--criterion {i['id']} --points <0|1>" for i in case.interrupt["reason"]["contested"])
        print(f"decide with: python -m docket teacher {case.script.script_id} {ids}")
    elif case.unchanged:
        print("unchanged")
    else:
        print(f"not signed: {case.blocked}")


def cmd_teacher(args) -> None:
    from docket.service import teacher

    if len(args.criterion) != len(args.points):
        raise SystemExit("give one --points per --criterion")
    case, pending = asyncio.run(teacher(args.script_id, dict(zip(args.criterion, args.points)), args.note))
    if case is None:
        contested = [c["id"] for c in pending["interrupt"]["reason"]["contested"]]
        print(f"recorded {pending['decisions']}; still to decide: {[c for c in contested if c not in pending['decisions']]}")
    elif case.credential:
        print(f"signed {store.where(store.credential_key(case.credential['credentialId']))}: total {case.credential['total']}/{case.credential['max']}, teacher decided {case.credential['teacher']['decided']}")
    else:
        print(f"not signed: {case.blocked or ('unchanged' if case.unchanged else 'interrupted again')}")


def cmd_bump(args) -> None:
    from docket.remark import bump

    report = asyncio.run(bump(args.version, args.concurrency))
    summary = {k: v for k, v in report.items() if k != "outcomes"}
    show(summary)
    for o in report["outcomes"]:
        print(f"  {o['scriptId']}: {o['status']} {o.get('oldTotal')} -> {o.get('newTotal')} {o.get('new') or ''}")


def cmd_appeal(args) -> None:
    from docket.appeals import appeal

    result = asyncio.run(appeal(args.script_id, args.reason, args.criterion or None))
    if result["outcome"] == "not decided":
        show(result)
        sys.exit(1)
    print(f"{result['appealId']} on {result['appealed']}: {result['decision']}")
    print(f"total {result['oldTotal']} -> {result['newTotal']}/{result['max']}, readers swapped to {result['readers']['a']} first, same calls after the swap: {result['swapCheck']['sameCalls']}")
    print(f"teacher decided {result['teacher']['decisions']}; standing credential {result['standingCredential']}")
    print(f"signed appeal record {result['key']}")


def cmd_export_appeals(args) -> None:
    from docket.appeals import export_appeals

    for path in export_appeals(args.target):
        print(path)


def cmd_verify(args) -> None:
    from docket.revocations import status_of
    from docket.signing import verify

    credential = json.loads(Path(args.credential).read_text())
    if "appealId" in credential:
        valid = verify(credential)
        show({"appealId": credential["appealId"], "signature": "valid" if valid else "invalid", "outcome": credential.get("outcome"), "decision": credential.get("decision"), "standingCredential": credential.get("standingCredential")})
        sys.exit(0 if valid else 1)
    revocations = json.loads(Path(args.revocations).read_text()) if args.revocations else None
    result = status_of(credential, revocations)
    show({"credentialId": credential.get("credentialId"), **result})
    sys.exit(0 if result["status"] == "valid" else 1)


def cmd_batch(args) -> None:
    from docket.batch import class_set, mark_batch

    report = asyncio.run(mark_batch(class_set(args.task, args.n, args.ids), args.concurrency, args.version, args.official_stand_in))
    show({k: v for k, v in report.items() if k != "outcomes"})
    for o in report["outcomes"]:
        print(f"  {o['scriptId']}: {o['status']} total={o.get('total')} official={o.get('officialScore')} contested={o.get('contested')} {o.get('error') or ''}")


def cmd_blind(args) -> None:
    from docket.batch import blind_check, class_set

    report = asyncio.run(blind_check(class_set(args.task, args.n, args.ids), args.concurrency))
    show({k: v for k, v in report.items() if k != "outcomes"})
    for o in report["outcomes"]:
        print(f"  {o['scriptId']}: declined={o.get('declined')} signed={o.get('signed')} {o.get('error') or ''}")


def cmd_export(args) -> None:
    from docket.batch import export_site

    for path in export_site(args.ids, args.target):
        print(path)


def cmd_revoke(args) -> None:
    from docket.revocations import revoke

    show(revoke(args.credential_id, args.reason))


def cmd_pending(args) -> None:
    for key in store.keys("pending/"):
        pending = store.get(key)
        contested = [c["id"] for c in pending["interrupt"]["reason"]["contested"]]
        print(f"{pending['scriptId']} ({pending['schemeVersion']}): contested {contested}, decided {pending['decisions']}")


def cmd_scheme(args) -> None:
    from docket.scheme import current_version, scheme_for

    version = args.version or current_version()
    scheme = scheme_for(args.task, version)
    show({"schemeId": scheme.scheme_id, "version": version, "max": scheme.max, "criteria": {c.id: c.text for c in scheme.criteria}, "rules": scheme.rules_text(), "official": scheme.official, "change": scheme.change})


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(prog="docket", description="The model reads, code decides.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("mark", help="mark one script: a CHECK-MAT id (13.1.1), image or folder")
    p.add_argument("target")
    p.add_argument("--task", type=int)
    p.add_argument("--version")
    p.add_argument("--blind", action="store_true", help="send the readers no student scan; they must decline")
    p.set_defaults(func=cmd_mark)

    p = sub.add_parser("teacher", help="decide contested criteria and resume the graph")
    p.add_argument("script_id")
    p.add_argument("--criterion", action="append", default=[])
    p.add_argument("--points", action="append", type=int, default=[])
    p.add_argument("--note")
    p.set_defaults(func=cmd_teacher)

    p = sub.add_parser("bump", help="change the scheme version and re-mark every affected script")
    p.add_argument("version")
    p.add_argument("--concurrency", type=int, default=4)
    p.set_defaults(func=cmd_bump)

    p = sub.add_parser("verify", help="verify a credential's signature and revocation status")
    p.add_argument("credential")
    p.add_argument("--revocations", help="a revocations.json file; default is the store's")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("batch", help="mark a class set concurrently")
    p.add_argument("--task", type=int, default=13)
    p.add_argument("--n", type=int, default=10)
    p.add_argument("--ids", nargs="*")
    p.add_argument("--concurrency", type=int, default=3)
    p.add_argument("--version")
    p.add_argument("--official-stand-in", action="store_true", help="answer each teacher interrupt with the CHECK-MAT expert grade")
    p.set_defaults(func=cmd_batch)

    p = sub.add_parser("blind", help="send readers no student scan; count how many decline")
    p.add_argument("--task", type=int, default=13)
    p.add_argument("--n", type=int, default=10)
    p.add_argument("--ids", nargs="*")
    p.add_argument("--concurrency", type=int, default=3)
    p.set_defaults(func=cmd_blind)

    p = sub.add_parser("export-site", help="copy scripts' credentials, readings and the revocation list for the hosted page")
    p.add_argument("ids", nargs="+")
    p.add_argument("--target", default="examples/site-data")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("revoke", help="revoke a credential, for example after an upheld appeal")
    p.add_argument("credential_id")
    p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_revoke)

    p = sub.add_parser("appeal", help="re-mark a script from its cached readings with the readers swapped; the teacher reviews the appealed criteria")
    p.add_argument("script_id")
    p.add_argument("--reason", required=True)
    p.add_argument("--criterion", action="append", default=[], help="an appealed criterion; default is every criterion")
    p.set_defaults(func=cmd_appeal)

    p = sub.add_parser("export-appeals", help="copy signed appeal records, their credentials and the revocation list for the hosted page")
    p.add_argument("--target", default="examples/site-data/appeals")
    p.set_defaults(func=cmd_export_appeals)

    p = sub.add_parser("pending", help="list scripts waiting for a teacher decision")
    p.set_defaults(func=cmd_pending)

    p = sub.add_parser("scheme", help="show a task's marking scheme")
    p.add_argument("task", type=int)
    p.add_argument("--version")
    p.set_defaults(func=cmd_scheme)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
