import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

REPO = "https://github.com/Karifannaa/Auto-check-EGE-math"
TARGET = ROOT / "data" / "raw" / "Auto-check-EGE-math"


def fetch() -> Path:
    if (TARGET / "dataset_benchmark").exists():
        print(f"already present: {TARGET}")
        return TARGET
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "--depth", "1", REPO, str(TARGET)], check=True)
    return TARGET


EXAMPLES = ("13.1.1", "13.2.3", "13.1.4")


def copy_examples() -> None:
    import shutil

    from docket.checkmat import find_script

    for script_id in EXAMPLES:
        script = find_script(script_id)
        folder = ROOT / "examples" / "scripts" / script_id
        folder.mkdir(parents=True, exist_ok=True)
        for image in (*script.images, script.reference):
            if image:
                shutil.copyfile(image, folder / image.name)
        print(f"examples/scripts/{script_id}/")


def upload(destination: str, ids: list[str] | None, task: int | None, n: int | None) -> None:
    from docket.batch import class_set
    from docket.config import aws_session

    bucket, _, prefix = destination[len("s3://"):].partition("/")
    prefix = prefix.strip("/")
    client = aws_session().client("s3")
    scripts = class_set(task, n or 10_000, ids)
    for script in scripts:
        base = f"{prefix}/{script.script_id}" if prefix else script.script_id
        for image in script.images:
            client.upload_file(str(image), bucket, f"{base}/{image.name}", ExtraArgs={"ContentType": "image/png"})
        if script.reference:
            client.upload_file(str(script.reference), bucket, f"{base}/{script.reference.name}", ExtraArgs={"ContentType": "image/png"})
        print(f"s3://{bucket}/{base}/ ({len(script.images)} pages, reference {'yes' if script.reference else 'no'}, official {script.official_score})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch CHECK-MAT into data/raw, optionally upload scripts to S3 in the handler's layout.")
    parser.add_argument("--upload", help="s3://bucket/prefix")
    parser.add_argument("--ids", nargs="*")
    parser.add_argument("--task", type=int)
    parser.add_argument("--n", type=int)
    args = parser.parse_args()
    fetch()
    copy_examples()
    if args.upload:
        upload(args.upload, args.ids, args.task, args.n)


if __name__ == "__main__":
    main()
