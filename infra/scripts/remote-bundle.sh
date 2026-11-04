#!/usr/bin/env bash
set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-cyclosentry}"
region="ap-south-1"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo="$(cd "$here/.." && pwd)"
work="$here/build"
stamp="$(date -u +%Y%m%dT%H%M%S)"
mkdir -p "$work"

output() {
  aws cloudformation describe-stacks --region "$region" --stack-name DocketStack \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}
bucket="$(output DataBucketName)"
builder="$(output BuilderFunctionName)"

uv run --no-project --python 3.12 python -c 'import sys, tomllib; print("\n".join(tomllib.load(open(sys.argv[1], "rb"))["project"]["dependencies"]))' \
  "$repo/pyproject.toml" > "$work/requirements.in"
uv pip compile --quiet --python-version 3.12 --python-platform aarch64-manylinux_2_28 \
  "$work/requirements.in" -o "$work/requirements.txt" --no-header --no-annotate

rm -f "$work/source.zip"
(cd "$repo/src" && zip -qr "$work/source.zip" docket -x "*/__pycache__/*")
(cd "$here/lambda" && zip -q "$work/source.zip" bootstrap.py plan.py)
aws s3 cp "$work/source.zip" "s3://$bucket/build/source-$stamp.zip" --region "$region" --quiet

python3 - "$work/requirements.txt" "$bucket" "build/source-$stamp.zip" "build/remark-$stamp.zip" > "$work/builder-event.json" <<'PY'
import json, sys
lines = [l.strip() for l in open(sys.argv[1]) if "==" in l and not l.startswith("#")]
print(json.dumps({"requirements": [l.split(";")[0].strip() for l in lines], "bucket": sys.argv[2], "sourceKey": sys.argv[3], "outputKey": sys.argv[4]}))
PY
aws lambda invoke --region "$region" --function-name "$builder" --cli-read-timeout 900 \
  --cli-binary-format raw-in-base64-out --payload "file://$work/builder-event.json" "$work/builder-result.json" >/dev/null
cat "$work/builder-result.json"; echo
echo "remarkZip=build/remark-$stamp.zip"
