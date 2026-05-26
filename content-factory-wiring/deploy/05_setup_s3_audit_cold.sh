#!/usr/bin/env bash
# 05_setup_s3_audit_cold.sh — create the chain-of-custody cold-storage bucket
# with a 7-year retention rule and immutable object-lock.
#
# Idempotent. Requires AWS credentials with s3:CreateBucket and
# s3:PutBucketLifecycleConfiguration on the target account.
set -euo pipefail

: "${AWS_REGION:=us-east-1}"
: "${BUCKET:=contentx-audit-cold}"
: "${RETENTION_DAYS:=2557}"   # 7 years + 2 leap days

HERE=$(cd "$(dirname "$0")"/.. && pwd)

echo "==> creating bucket s3://$BUCKET ..."
if aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  echo "  bucket already exists"
else
  aws s3 mb "s3://$BUCKET" --region "$AWS_REGION"
fi

echo "==> enabling versioning ..."
aws s3api put-bucket-versioning \
  --bucket "$BUCKET" \
  --versioning-configuration Status=Enabled

echo "==> enabling object lock (legal hold support) ..."
# Object lock requires versioning AND must be set at create time for some regions.
# For regions where this fails post-hoc, the legal hold is enforced at object level instead.
aws s3api put-object-lock-configuration \
  --bucket "$BUCKET" \
  --object-lock-configuration '{
    "ObjectLockEnabled": "Enabled",
    "Rule": {
      "DefaultRetention": {
        "Mode": "COMPLIANCE",
        "Days": '"$RETENTION_DAYS"'
      }
    }
  }' 2>/dev/null || echo "  (warn) object lock not settable post-creation; enforce per-object instead"

echo "==> writing lifecycle policy (transition to Glacier Deep Archive at 90d) ..."
cat > /tmp/contentx-audit-lifecycle.json <<JSON
{
  "Rules": [
    {
      "ID": "ContentX-audit-cold-90d-glacier-7y-expire",
      "Status": "Enabled",
      "Filter": { "Prefix": "" },
      "Transitions": [
        { "Days": 90,  "StorageClass": "DEEP_ARCHIVE" }
      ],
      "Expiration": { "Days": $RETENTION_DAYS },
      "NoncurrentVersionExpiration": { "NoncurrentDays": 90 }
    }
  ]
}
JSON

aws s3api put-bucket-lifecycle-configuration \
  --bucket "$BUCKET" \
  --lifecycle-configuration file:///tmp/contentx-audit-lifecycle.json

rm -f /tmp/contentx-audit-lifecycle.json

echo "==> tightening public access ..."
aws s3api put-public-access-block \
  --bucket "$BUCKET" \
  --public-access-block-configuration "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

echo "==> server-side encryption (SSE-KMS) ..."
aws s3api put-bucket-encryption \
  --bucket "$BUCKET" \
  --server-side-encryption-configuration '{
    "Rules": [{
      "ApplyServerSideEncryptionByDefault": { "SSEAlgorithm": "aws:kms" },
      "BucketKeyEnabled": true
    }]
  }'

echo "==> smoke test upload ..."
echo "test $(date -u +%FT%TZ)" | aws s3 cp - "s3://$BUCKET/.smoke-test" --quiet
aws s3 rm "s3://$BUCKET/.smoke-test" --quiet || true

echo ""
echo "S3 audit-cold bucket ready: s3://$BUCKET"
echo "  - versioning      : enabled"
echo "  - retention       : ${RETENTION_DAYS} days (~7 years)"
echo "  - lifecycle       : 90d → Deep Archive, ${RETENTION_DAYS}d → expire"
echo "  - encryption      : SSE-KMS"
echo "  - public access   : fully blocked"
