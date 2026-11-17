#!/usr/bin/env bash
# Bước 3b của quy trình: chạy TRONG CloudShell, ở thư mục đã giải nén batch_bundle.tar.gz (build_bundle.ps1 in sẵn lệnh).
# Build image của Lambda batch theo batch/Dockerfile rồi đẩy lên ECR với tag v1 (ghi đè bản cũ).
set -euo pipefail
REGION=ap-southeast-1
REPO=home-office-lambda
ACCT=$(aws sts get-caller-identity --query Account --output text)
REGISTRY="$ACCT.dkr.ecr.$REGION.amazonaws.com"
IMAGE="$REGISTRY/$REPO:v1"

echo "== Kho ECR $REPO"
aws ecr describe-repositories --repository-names "$REPO" --region "$REGION" >/dev/null 2>&1 \
  || aws ecr create-repository --repository-name "$REPO" --region "$REGION" >/dev/null

echo "== Build $IMAGE"
docker build --platform linux/amd64 --provenance=false -f batch/Dockerfile -t "$IMAGE" .

echo "== Đăng nhập ECR và đẩy image"
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"
docker push "$IMAGE"
echo "Xong: $IMAGE"
