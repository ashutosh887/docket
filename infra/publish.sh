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
for arg in "$@"; do
  case "$arg" in
    --skip-build) skip_build=true ;;
    --reset-data) reset_data=true ;;
    --local-data) local_data=true ;;
    *) echo "usage: publish.sh [--skip-build] [--local-data] [--reset-data]" >&2; exit 2 ;;
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
