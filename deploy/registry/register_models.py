"""Ghi hai version model vào SageMaker Model Registry (group `home-office`) và chọn version mặc định.

Registry chỉ lưu con trỏ và metadata (không lưu file): mỗi Model Package trỏ tới params.json và thư mục kết quả trên S3.
Lambda tra cứu không gọi registry; script deploy / batch gọi `default` để biết version nào đang được duyệt.

Chạy từ thư mục Home_Office (cần AWS CLI profile `home-office` đã đăng nhập và `pip install boto3`):
    python deploy/registry/register_models.py register            # tạo group + 2 Model Package (bỏ qua version đã có)
    python deploy/registry/register_models.py list                # liệt kê version, trạng thái duyệt
    python deploy/registry/register_models.py set-default dbscan-v2   # version này Approved, các version khác PendingManualApproval
    python deploy/registry/register_models.py default             # in version đang Approved (JSON)

Cần có sẵn: params/<version>.json (python -m src.params write) và đã đẩy lên S3 (deploy/data/upload_params.ps1).
Quyền IAM cần: sagemaker:CreateModelPackageGroup, CreateModelPackage, ListModelPackages, DescribeModelPackage,
UpdateModelPackage, sts:GetCallerIdentity, s3:GetObject (kiểm tra file params), ecr (SageMaker kiểm tra image).
Chưa chạy thử trên AWS thật: nếu CreateModelPackage báo lỗi về InferenceSpecification hoặc image, thử `register --no-inference-spec`.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REGION = "ap-southeast-1"
PROFILE = "home-office"
GROUP = "home-office"
DEFAULT_VERSION = "heuristic-v1"          # khớp models.DEFAULT_MODEL
IMAGE_REPO = "home-office-lambda"          # image của Lambda batch (deploy/batch)
IMAGE_TAG = "v1"
MAX_VALUE_LEN = 256                        # giới hạn giá trị CustomerMetadataProperties
MAX_PAIRS = 50                             # giới hạn số cặp


def _clients():
    import boto3
    session = boto3.Session(profile_name=PROFILE, region_name=REGION)
    return session.client("sagemaker"), session.client("sts"), session.client("s3")


def _account(sts) -> str:
    return sts.get_caller_identity()["Account"]


def bucket_name(account: str) -> str:
    return f"home-office-lambda-sg-{account}"      # cùng tên với deploy/common.ps1


def build_metadata(version: str, params: dict, bucket: str, commit: str, created_at: str) -> dict:
    """CustomerMetadataProperties của một Model Package. Mọi giá trị là chuỗi, dài nhất 256 ký tự, tối đa 50 cặp."""
    meta = {"model_version": version, "params_uri": f"s3://{bucket}/models/{version}/params.json",
            "results_prefix": f"s3://{bucket}/results/{version}/", "commit": commit, "created_at": created_at}
    for k, v in params.items():
        meta[f"p_{k}"] = str(v)
    meta = {k: str(v)[:MAX_VALUE_LEN] for k, v in meta.items()}
    if len(meta) > MAX_PAIRS:
        raise ValueError(f"metadata co {len(meta)} cap, toi da {MAX_PAIRS}")
    return meta


def _git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return "unknown"


def _ensure_group(sm) -> None:
    try:
        sm.describe_model_package_group(ModelPackageGroupName=GROUP)
        print(f"group {GROUP}: da co")
    except sm.exceptions.ClientError:
        sm.create_model_package_group(ModelPackageGroupName=GROUP,
                                      ModelPackageGroupDescription="Home/Office GeoLife: cac version model (heuristic-v1, dbscan-v2)")
        print(f"group {GROUP}: da tao")


def _packages(sm) -> list[dict]:
    """Mọi Model Package đã đăng ký, kèm metadata. Mới nhất trước."""
    out = []
    for page in sm.get_paginator("list_model_packages").paginate(ModelPackageGroupName=GROUP, SortBy="CreationTime", SortOrder="Descending"):
        for s in page["ModelPackageSummaryList"]:
            d = sm.describe_model_package(ModelPackageName=s["ModelPackageArn"])
            out.append({"arn": s["ModelPackageArn"], "number": s.get("ModelPackageVersion"),
                        "status": d.get("ModelApprovalStatus"), "meta": d.get("CustomerMetadataProperties", {})})
    return out


def cmd_register(args) -> None:
    sm, sts, s3 = _clients()
    account = _account(sts)
    bucket = bucket_name(account)
    image = args.image or f"{account}.dkr.ecr.{REGION}.amazonaws.com/{IMAGE_REPO}:{IMAGE_TAG}"
    files = sorted(Path(args.params_dir).glob("*.json"))
    if not files:
        sys.exit(f"Khong co {args.params_dir}/*.json. Chay: python -m src.params write")
    _ensure_group(sm)
    have = {p["meta"].get("model_version") for p in _packages(sm)}
    commit = args.commit or _git_commit()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for f in files:
        version = f.stem
        if version in have:
            print(f"{version}: da co trong registry, bo qua")
            continue
        try:
            s3.head_object(Bucket=bucket, Key=f"models/{version}/params.json")
        except Exception:
            print(f"canh bao: chua thay s3://{bucket}/models/{version}/params.json (chay deploy\\data\\upload_params.ps1)")
        params = json.loads(f.read_text(encoding="utf-8"))
        kw = dict(ModelPackageGroupName=GROUP, ModelPackageDescription=f"{version}: {params.get('stay_method', '')} stay, gom dia diem",
                  CustomerMetadataProperties=build_metadata(version, params, bucket, commit, now),
                  MetadataProperties={"CommitId": commit},
                  ModelApprovalStatus="Approved" if version == args.default else "PendingManualApproval")
        if not args.no_inference_spec:
            kw["InferenceSpecification"] = {"Containers": [{"Image": image}], "SupportedContentTypes": ["application/json"],
                                            "SupportedResponseMIMETypes": ["application/json"]}
        resp = sm.create_model_package(**kw)
        print(f"{version}: da dang ky {resp['ModelPackageArn']} ({kw['ModelApprovalStatus']})")


def cmd_list(args) -> None:
    sm, _, _ = _clients()
    for p in reversed(_packages(sm)):
        print(f"v{p['number']}  {p['meta'].get('model_version', '?'):14s} {p['status']}")


def cmd_set_default(args) -> None:
    sm, _, _ = _clients()
    found = False
    for p in _packages(sm):
        want = "Approved" if p["meta"].get("model_version") == args.version else "PendingManualApproval"
        found = found or want == "Approved"
        if p["status"] != want:
            sm.update_model_package(ModelPackageArn=p["arn"], ModelApprovalStatus=want)
            print(f"{p['meta'].get('model_version')}: {p['status']} -> {want}")
    if not found:
        sys.exit(f"Khong co version {args.version} trong registry")


def cmd_default(args) -> None:
    sm, _, _ = _clients()
    approved = [p for p in _packages(sm) if p["status"] == "Approved"]
    if len(approved) != 1:
        sys.exit(f"Can dung 1 version Approved, dang co {len(approved)}")
    m = approved[0]["meta"]
    print(json.dumps({"default": m.get("model_version"), "params_uri": m.get("params_uri"), "results_prefix": m.get("results_prefix")}))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("register")
    r.add_argument("--params-dir", default="params")
    r.add_argument("--default", default=DEFAULT_VERSION, help="version dat Approved (con lai PendingManualApproval)")
    r.add_argument("--image", help="URI image ECR (mac dinh: image cua Lambda batch)")
    r.add_argument("--commit", help="git commit (mac dinh: git rev-parse --short HEAD)")
    r.add_argument("--no-inference-spec", action="store_true", help="khong khai bao InferenceSpecification/image")
    r.set_defaults(fn=cmd_register)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    s = sub.add_parser("set-default"); s.add_argument("version"); s.set_defaults(fn=cmd_set_default)
    sub.add_parser("default").set_defaults(fn=cmd_default)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
