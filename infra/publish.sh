#!/usr/bin/env bash
set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-cyclosentry}"
region="ap-south-1"
stack="DocketStack"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
web="$(cd "$here/../web" && pwd)"

output() {
  aws cloudformation describe-stacks --region "$region" --stack-name "$stack" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

site_bucket="$(output SiteBucketName)"
data_bucket="$(output DataBucketName)"
distribution="$(output DistributionId)"
url="$(output SiteUrl)"
for value in "$site_bucket" "$data_bucket" "$distribution" "$url"; do
  if [[ -z "$value" || "$value" == "None" ]]; then
    echo "$stack outputs are incomplete; run npm run deploy in infra/ first." >&2
    exit 1
  fi
done

skip_build=false
reset_data=false
local_data=false
appeals=false
for arg in "$@"; do
  case "$arg" in
    --skip-build) skip_build=true ;;
    --reset-data) reset_data=true ;;
    --local-data) local_data=true ;;
    --appeals) appeals=true ;;
    *) echo "usage: publish.sh [--skip-build] [--local-data] [--reset-data] [--appeals]" >&2; exit 2 ;;
  esac
done

if ! "$skip_build"; then
  (cd "$web" && npm ci --no-audit --no-fund && npm run build)
fi
[[ -f "$web/dist/index.html" ]] || { echo "web/dist is incomplete; build first." >&2; exit 1; }

export AWS_RETRY_MODE=adaptive AWS_MAX_ATTEMPTS=8
assets() {
  aws s3 sync "$web/dist" "s3://$site_bucket" --region "$region" "$@" \
    --exclude "data/*" --exclude "index.html" --cache-control "public,max-age=300"
}
assets
if "$reset_data"; then
  aws s3 rm "s3://$data_bucket/data" --recursive --region "$region" >/dev/null
fi
if "$local_data"; then
  aws s3 sync "$web/dist/data" "s3://$data_bucket/data" --region "$region" \
    --cache-control "public,max-age=30"
fi
if "$appeals" && [[ -d "$web/dist/data/appeals" ]]; then
  aws s3 sync "$web/dist/data/appeals" "s3://$data_bucket/data/appeals" --region "$region" --cache-control "public,max-age=30"
  source_dir="$(cd "$here/../examples/site-data/appeals" && pwd)"
  for file in "$source_dir"/credentials/*.json; do
    key="data/credentials/$(basename "$file")"
    if ! aws s3api head-object --bucket "$data_bucket" --key "$key" --region "$region" >/dev/null 2>&1; then
      aws s3 cp "$file" "s3://$data_bucket/$key" --region "$region" --cache-control "public,max-age=30" --content-type application/json
    fi
  done
  live_list="$(mktemp)"
  aws s3 cp "s3://$data_bucket/data/revocations.json" "$live_list" --region "$region" >/dev/null 2>&1 || echo '{"entries":[]}' > "$live_list"
  if node -e '
    const [live, next] = process.argv.slice(1).map((f) => JSON.parse(require("fs").readFileSync(f, "utf8")));
    const ids = new Set(next.entries.map((e) => e.credentialId));
    process.exit(next.signature && live.entries.every((e) => ids.has(e.credentialId)) ? 0 : 1);
  ' "$live_list" "$web/dist/data/revocations.json"; then
    aws s3 cp "$web/dist/data/revocations.json" "s3://$data_bucket/data/revocations.json" --region "$region" \
      --cache-control "public,max-age=30" --content-type application/json
  else
    echo "revocations.json in web/dist drops entries the live list holds; left the live list in place." >&2
  fi
  rm -f "$live_list"
fi
reindex="$(output ReindexFunctionName)"
if [[ -n "$reindex" && "$reindex" != "None" ]]; then
  aws lambda invoke --region "$region" --function-name "$reindex" \
    --cli-binary-format raw-in-base64-out --payload '{}' /dev/stdout >/dev/null
fi
aws s3 cp "$web/dist/index.html" "s3://$site_bucket/index.html" --region "$region" \
  --cache-control "no-cache" --content-type "text/html; charset=utf-8"
assets --delete

invalidation="$(aws cloudfront create-invalidation --distribution-id "$distribution" \
  --paths "/*" --query Invalidation.Id --output text)"
echo "source: $(node -e 'console.log(require(process.argv[1]).source)' "$web/dist/data/index.json")"
echo "invalidation $invalidation"
echo "$url"
