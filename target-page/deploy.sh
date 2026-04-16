#!/bin/bash
set -euo pipefail

BUCKET="${1:?Usage: ./deploy.sh <bucket-name>}"
DIR="$(cd "$(dirname "$0")" && pwd)"

aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null || \
  aws s3api create-bucket --bucket "$BUCKET" --region ap-northeast-1 \
    --create-bucket-configuration LocationConstraint=ap-northeast-1

aws s3 website "s3://$BUCKET" --index-document index.html

aws s3api put-public-access-block --bucket "$BUCKET" \
  --public-access-block-configuration \
  "BlockPublicAcls=false,IgnorePublicAcls=false,BlockPublicPolicy=false,RestrictPublicBuckets=false"

aws s3api put-bucket-policy --bucket "$BUCKET" --policy \
  '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":"*","Action":"s3:GetObject","Resource":"arn:aws:s3:::'$BUCKET'/*"}]}'

aws s3 sync "$DIR/" "s3://$BUCKET/" --exclude "deploy.sh" --content-type "text/html; charset=utf-8"

echo "URL: http://$BUCKET.s3-website-ap-northeast-1.amazonaws.com"
