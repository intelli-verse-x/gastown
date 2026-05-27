#!/usr/bin/env bash
# 07_deploy_eks.sh — seamless EKS deploy for contentx-postiz-webhook + CronJobs.
#
# Idempotent. Safe to re-run; image will be re-pushed with a content-hash tag.
#
# Required env (with sensible defaults):
#   AWS_REGION         (us-east-1)
#   ECR_REGISTRY       (970547373533.dkr.ecr.us-east-1.amazonaws.com)
#   ECR_REPO           (contentx-postiz-webhook)
#   NAMESPACE          (content-factory)
#   KUBECONFIG_CONTEXT (current context)
#   APPLY              ("dryrun" -> server-side dry-run only; "apply" -> real apply)
#                       defaults to "dryrun"
set -euo pipefail

HERE=$(cd "$(dirname "$0")"/.. && pwd)
EKS_DIR="$HERE/eks"

AWS_REGION="${AWS_REGION:-us-east-1}"
ECR_REGISTRY="${ECR_REGISTRY:-970547373533.dkr.ecr.us-east-1.amazonaws.com}"
ECR_REPO="${ECR_REPO:-contentx-postiz-webhook}"
NAMESPACE="${NAMESPACE:-content-factory}"
APPLY="${APPLY:-dryrun}"

red()   { printf "\033[31m%s\033[0m\n" "$*"; }
green() { printf "\033[32m%s\033[0m\n" "$*"; }
blue()  { printf "\033[34m%s\033[0m\n" "$*"; }

blue "==> 1. preflight: kubectl/docker/aws"
command -v kubectl >/dev/null || { red "kubectl missing"; exit 2; }
command -v docker  >/dev/null || { red "docker missing"; exit 2; }
command -v aws     >/dev/null || { red "aws missing"; exit 2; }
docker info >/dev/null 2>&1   || { red "docker daemon not running"; exit 2; }

CTX=$(kubectl config current-context)
blue "    context: $CTX"
green "    OK"

blue "==> 2. ensure ECR repo exists"
if ! aws ecr describe-repositories --repository-names "$ECR_REPO" --region "$AWS_REGION" >/dev/null 2>&1; then
  aws ecr create-repository --repository-name "$ECR_REPO" --region "$AWS_REGION" \
    --image-scanning-configuration scanOnPush=true \
    --image-tag-mutability MUTABLE \
    --encryption-configuration encryptionType=AES256 >/dev/null
  green "    created $ECR_REPO"
else
  green "    $ECR_REPO already exists"
fi

blue "==> 3. compute image tag (content-hash for idempotency)"
HASH=$(find "$HERE/services" "$HERE/tools" -type f -name '*.py' \
       -exec sha256sum {} + 2>/dev/null | sort | sha256sum | cut -c1-12)
IMAGE_TAG="sha-${HASH}"
IMAGE="${ECR_REGISTRY}/${ECR_REPO}:${IMAGE_TAG}"
blue "    image: $IMAGE"

blue "==> 4. ECR login"
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$ECR_REGISTRY" >/dev/null
green "    OK"

blue "==> 5. docker build"
if docker image inspect "$IMAGE" >/dev/null 2>&1; then
  green "    cached: $IMAGE"
else
  # Build for the target platform. EKS nodes are linux/amd64 by default.
  docker buildx build \
    --platform linux/amd64 \
    -f "$HERE/services/postiz_webhook/Dockerfile" \
    -t "$IMAGE" \
    --load \
    "$HERE"
  green "    built $IMAGE"
fi

blue "==> 6. docker push"
docker push "$IMAGE" >/dev/null
green "    pushed $IMAGE"

blue "==> 7. assemble manifests with image substitution + secret materialization"
WORK=$(mktemp -d)
trap "rm -rf $WORK" EXIT
cp -r "$EKS_DIR/manifests/." "$WORK/"

# Inject the real image into every manifest
find "$WORK" -name '*.yaml' -print0 | xargs -0 sed -i.bak "s|IMAGE_PLACEHOLDER|${IMAGE}|g"

# Materialize the bootstrap secret values if Mode B (no ExternalSecret yet)
if [[ "${USE_EXTERNAL_SECRET:-no}" != "yes" ]]; then
  CERT_KEY=$(openssl rand -hex 32)
  WEBHOOK_SECRET=$(openssl rand -hex 32)
  # Store the generated values for the smoke test to use
  echo "$CERT_KEY"        > "$WORK/.cert_key"
  echo "$WEBHOOK_SECRET"  > "$WORK/.webhook_secret"
  sed -i.bak "s|CONTENTX_CERT_KEY:.*|CONTENTX_CERT_KEY: \"${CERT_KEY}\"|g; \
              s|CONTENTX_WEBHOOK_SECRET:.*|CONTENTX_WEBHOOK_SECRET: \"${WEBHOOK_SECRET}\"|g" \
      "$WORK/30-secret-bootstrap.yaml"
fi
find "$WORK" -name '*.bak' -delete
green "    OK"

APPLY_UPPER=$(echo "$APPLY" | tr '[:lower:]' '[:upper:]')
blue "==> 8. ${APPLY_UPPER} apply"
if [[ "$APPLY" == "dryrun" ]]; then
  kubectl apply --dry-run=server -f "$WORK/00-namespace.yaml" \
                                 -f "$WORK/10-serviceaccount.yaml" \
                                 -f "$WORK/20-configmap.yaml" \
                                 -f "$WORK/30-secret-bootstrap.yaml" \
                                 -f "$WORK/40-deployment.yaml" \
                                 -f "$WORK/50-service.yaml" \
                                 -f "$WORK/70-keda-scaledobject.yaml" \
                                 -f "$WORK/80-pdb.yaml" \
                                 -f "$WORK/90-networkpolicy.yaml" \
                                 -f "$WORK/cronjobs/"
  green "    server-side dry-run PASSED"
elif [[ "$APPLY" == "apply" ]]; then
  kubectl apply -f "$WORK/00-namespace.yaml"
  kubectl apply -f "$WORK/10-serviceaccount.yaml" \
                -f "$WORK/20-configmap.yaml" \
                -f "$WORK/30-secret-bootstrap.yaml" \
                -f "$WORK/50-service.yaml" \
                -f "$WORK/80-pdb.yaml" \
                -f "$WORK/90-networkpolicy.yaml"
  kubectl apply -f "$WORK/40-deployment.yaml"
  # KEDA is optional — skip if CRD missing
  if kubectl get crd scaledobjects.keda.sh >/dev/null 2>&1; then
    kubectl apply -f "$WORK/70-keda-scaledobject.yaml"
  else
    blue "    (warn) KEDA CRD not installed; skipping ScaledObject"
  fi
  kubectl apply -f "$WORK/cronjobs/"

  blue "==> 9. wait for rollout"
  kubectl -n "$NAMESPACE" rollout status deploy/contentx-postiz-webhook --timeout=180s
  green "    rolled out"
else
  red "APPLY must be 'dryrun' or 'apply'; got '$APPLY'"
  exit 2
fi

# Preserve work dir for the smoke test to pick up the cert key
cp -r "$WORK" /tmp/contentx-deploy-last
green "DONE"
