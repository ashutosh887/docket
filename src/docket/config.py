import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_env(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()


def out_dir() -> Path:
    default = "/tmp/docket-out" if os.environ.get("AWS_LAMBDA_FUNCTION_NAME") else ROOT / "out"
    path = Path(os.environ.get("DOCKET_OUT", default))
    path.mkdir(parents=True, exist_ok=True)
    return path


def dataset_dir() -> Path:
    return Path(os.environ.get("DOCKET_DATA", ROOT / "data" / "raw" / "Auto-check-EGE-math" / "dataset_benchmark"))


def reader_a() -> str:
    return os.environ.get("DOCKET_READER_A", "groq:qwen/qwen3.8-27b")


def reader_b() -> str:
    return os.environ.get("DOCKET_READER_B", "gemini:gemini-3.5-flash-lite")


def kms_key() -> str:
    return os.environ.get("DOCKET_KMS_KEY", "alias/docket-credentials")


def aws_profile() -> str | None:
    if os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        return None
    return os.environ.get("DOCKET_AWS_PROFILE", "cyclosentry") or None


def aws_session():
    import boto3

    return boto3.Session(profile_name=aws_profile(), region_name=aws_region())


def aws_region() -> str:
    return os.environ.get("DOCKET_AWS_REGION", "ap-south-1")


def min_confidence() -> float:
    return float(os.environ.get("DOCKET_MIN_CONFIDENCE", "0.6"))


def margin_threshold() -> float:
    return float(os.environ.get("DOCKET_MARGIN_THRESHOLD", "0.5"))
