"""Bước 7 của quy trình: ghi các version model vào SageMaker Model Registry (group `home-office`) và chọn version mặc định.

Registry chỉ lưu con trỏ và metadata (không lưu file): mỗi Model Package trỏ tới params.json và thư mục kết quả trên S3.
Lambda tra cứu không gọi registry: `set-default` duyệt version trên registry và ghi luôn results/_default.json, Lambda đọc file đó.
Từ 19/11/2026 còn có Lambda home-office-registry-sync (deploy/terraform/registry_sync.tf): duyệt version ở bất cứ đâu (Studio, CLI)
thì EventBridge gọi Lambda đó ghi lại results/_default.json. `set-default` vẫn tự ghi file như cũ (hai bên ghi cùng một giá trị).

Chạy từ thư mục Home_Office (cần AWS CLI profile `home-office` đã đăng nhập và `pip install boto3 "botocore[crt]"`; gói crt cần để đọc phiên đăng nhập của `aws login`):
    python deploy/registry/register_models.py register            # tạo group + Model Package theo MODEL_ORDER (bỏ qua version đã có)
    python deploy/registry/register_models.py list                # liệt kê version, trạng thái duyệt
    python deploy/registry/register_models.py set-default dbscan-v2   # version này Approved, còn lại Pending; ghi results/_default.json
    python deploy/registry/register_models.py default             # in version đang Approved (JSON)
    python deploy/registry/register_models.py reset --yes         # XOÁ mọi Model Package và group (để đăng ký lại từ Version 1)

Số "Version" trên registry do AWS tự tăng theo thứ tự tạo và không đổi được, nên `register` tạo theo MODEL_ORDER
(heuristic-v1 trước = Version 1, dbscan-v2 sau = Version 2). Muốn đánh số lại thì chỉ có cách `reset --yes` rồi `register`.
Tên model nằm ở Description và metadata `model_version` (AWS không cho gắn tag vào từng version, chỉ vào group).

Cần có sẵn: params/<version>.json (python -m src.params write) và đã đẩy lên S3 (deploy/data/upload_params.ps1).
Quyền IAM cần: sagemaker:CreateModelPackageGroup, CreateModelPackage, ListModelPackages, DescribeModelPackage,
UpdateModelPackage, AddTags, DeleteModelPackage + DeleteModelPackageGroup (chỉ `reset`), sts:GetCallerIdentity, s3:GetObject (kiểm tra file params), s3:PutObject (ghi results/_default.json),
ecr (SageMaker kiểm tra image).
Đã chạy 16/11/2026: 2 version, khai báo image chạy được (lần đó đăng ký theo thứ tự chữ cái nên dbscan-v2 thành Version 1;
đã sửa bằng MODEL_ORDER, đăng ký lại 18/11/2026). Nếu sau này CreateModelPackage báo lỗi về image, thử `register --no-inference-spec`.
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
DEFAULT_VERSION = "dbscan-v2"             # version Approved khi `register` (= mặc định của API qua _default.json).
                                           # Khác models.DEFAULT_MODEL (heuristic-v1): đó là mặc định khi chạy infer cục bộ.
MODEL_ORDER = ["heuristic-v1", "dbscan-v2"]  # thứ tự đăng ký = số Version 1, 2 trên registry; version mới thêm vào cuối
MODEL_DESC = {                             # mô tả ngắn hiện trong cột Description của SageMaker Studio
    "heuristic-v1": "heuristic-v1: gom địa điểm tham lam quanh điểm neo, bán kính 200 m",
    "dbscan-v2": "dbscan-v2: gom địa điểm bằng DBSCAN, eps 200 m, min_samples 1",
}
IMAGE_REPO = "home-office-lambda"          # kho ECR chứa image của Lambda batch ($Repo trong deploy/common.ps1)
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
    return f"home-office-lambda-sg-{account}"      # cùng tên $Bucket trong deploy/common.ps1


def build_metadata(version: str, params: dict, bucket: str, commit: str, created_at: str) -> dict:
    """CustomerMetadataProperties của một Model Package. Mọi giá trị là chuỗi, dài nhất 256 ký tự, tối đa 50 cặp."""
    meta = {"model_version": version, "params_uri": f"s3://{bucket}/models/{version}/params.json",
            "results_prefix": f"s3://{bucket}/results/{version}/", "commit": commit, "created_at": created_at}
    for k, v in params.items():
        meta[f"p_{k}"] = str(v)
    meta = {k: str(v)[:MAX_VALUE_LEN] for k, v in meta.items()}
    if len(meta) > MAX_PAIRS:
        raise ValueError(f"metadata có {len(meta)} cặp, tối đa {MAX_PAIRS}")
    return meta


def _git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return "unknown"


def _ensure_group(sm) -> None:
    try:
        sm.describe_model_package_group(ModelPackageGroupName=GROUP)
        print(f"group {GROUP}: đã có")
    except sm.exceptions.ClientError:
        sm.create_model_package_group(ModelPackageGroupName=GROUP,
                                      ModelPackageGroupDescription="Home/Office GeoLife: các version model (heuristic-v1, dbscan-v2)",
                                      Tags=[{"Key": "project", "Value": "home-office"}])   # tag chỉ đặt được ở group, không ở từng version
        print(f"group {GROUP}: đã tạo")


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
    rank = {v: i for i, v in enumerate(MODEL_ORDER)}
    files = sorted(Path(args.params_dir).glob("*.json"), key=lambda f: (rank.get(f.stem, len(rank)), f.stem))
    if not files:
        sys.exit(f"Không có {args.params_dir}/*.json. Chạy: python -m src.params write")
    _ensure_group(sm)
    have = {p["meta"].get("model_version") for p in _packages(sm)}
    commit = args.commit or _git_commit()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for f in files:
        version = f.stem
        if version in have:
            print(f"{version}: đã có trong registry, bỏ qua")
            continue
        try:
            s3.head_object(Bucket=bucket, Key=f"models/{version}/params.json")
        except Exception:
            print(f"Cảnh báo: chưa thấy s3://{bucket}/models/{version}/params.json (chạy deploy\\data\\upload_params.ps1)")
        params = json.loads(f.read_text(encoding="utf-8"))
        kw = dict(ModelPackageGroupName=GROUP, ModelPackageDescription=MODEL_DESC.get(version, f"{version}: gom địa điểm"),
                  CustomerMetadataProperties=build_metadata(version, params, bucket, commit, now),
                  MetadataProperties={"CommitId": commit},
                  ModelApprovalStatus="Approved" if version == args.default else "PendingManualApproval")
        if not args.no_inference_spec:
            kw["InferenceSpecification"] = {"Containers": [{"Image": image}], "SupportedContentTypes": ["application/json"],
                                            "SupportedResponseMIMETypes": ["application/json"]}
        resp = sm.create_model_package(**kw)
        print(f"{version}: đã đăng ký {resp['ModelPackageArn']} ({kw['ModelApprovalStatus']})")


def cmd_list(args) -> None:
    sm, _, _ = _clients()
    for p in reversed(_packages(sm)):
        print(f"v{p['number']}  {p['meta'].get('model_version', '?'):14s} {p['status']}")


def cmd_set_default(args) -> None:
    """Duyệt (Approved) đúng một version trên registry, rồi ghi results/_default.json để API dùng version đó.

    Lambda tra cứu không gọi registry (để nhanh và ít phụ thuộc); nó chỉ đọc _default.json, nhớ trong 60 giây.
    """
    sm, sts, s3 = _clients()
    packages = _packages(sm)
    if not any(p["meta"].get("model_version") == args.version for p in packages):
        sys.exit(f"Không có version {args.version} trong registry")
    for p in packages:
        want = "Approved" if p["meta"].get("model_version") == args.version else "PendingManualApproval"
        if p["status"] != want:
            sm.update_model_package(ModelPackageArn=p["arn"], ModelApprovalStatus=want)
            print(f"{p['meta'].get('model_version')}: {p['status']} -> {want}")
    bucket = bucket_name(_account(sts))
    registered = sorted({p["meta"].get("model_version") for p in packages if p["meta"].get("model_version")})
    # Cùng định dạng với Lambda registry-sync: registered = version được phép làm canary (bản ứng viên).
    s3.put_object(Bucket=bucket, Key="results/_default.json", ContentType="application/json",
                  Body=json.dumps({"default_model_version": args.version, "registered": registered}).encode())
    print(f"Đã ghi s3://{bucket}/results/_default.json = {args.version} (API đổi theo sau tối đa 60 giây)")


def cmd_default(args) -> None:
    sm, _, _ = _clients()
    approved = [p for p in _packages(sm) if p["status"] == "Approved"]
    if len(approved) != 1:
        sys.exit(f"Cần đúng 1 version Approved, đang có {len(approved)}")
    m = approved[0]["meta"]
    print(json.dumps({"default": m.get("model_version"), "params_uri": m.get("params_uri"), "results_prefix": m.get("results_prefix")}))


def cmd_reset(args) -> None:
    """Xoá mọi Model Package rồi xoá group. Không đụng S3: results/_default.json và kết quả batch giữ nguyên, API vẫn chạy."""
    if not args.yes:
        sys.exit("Lệnh này XOÁ mọi version trong group home-office. Chạy lại với --yes nếu chắc chắn.")
    import time
    sm, _, _ = _clients()
    try:
        sm.describe_model_package_group(ModelPackageGroupName=GROUP)
    except sm.exceptions.ClientError:
        print(f"group {GROUP}: không có, không cần xoá")
        return
    for p in _packages(sm):
        sm.delete_model_package(ModelPackageName=p["arn"])
        print(f"đã xoá v{p['number']} {p['meta'].get('model_version', '?')} ({p['arn']})")
    sm.delete_model_package_group(ModelPackageGroupName=GROUP)
    for _ in range(30):                                   # chờ group xoá hẳn để `register` tạo lại được
        try:
            sm.describe_model_package_group(ModelPackageGroupName=GROUP)
            time.sleep(2)
        except sm.exceptions.ClientError:
            print(f"group {GROUP}: đã xoá")
            return
    print(f"group {GROUP}: đang xoá, chờ thêm vài giây rồi mới chạy register")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("register")
    r.add_argument("--params-dir", default="params")
    r.add_argument("--default", default=DEFAULT_VERSION, help="version đặt Approved (còn lại PendingManualApproval)")
    r.add_argument("--image", help="URI image ECR (mặc định: image của Lambda batch)")
    r.add_argument("--commit", help="git commit (mặc định: git rev-parse --short HEAD)")
    r.add_argument("--no-inference-spec", action="store_true", help="không khai báo InferenceSpecification / image")
    r.set_defaults(fn=cmd_register)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    s = sub.add_parser("set-default"); s.add_argument("version"); s.set_defaults(fn=cmd_set_default)
    sub.add_parser("default").set_defaults(fn=cmd_default)
    x = sub.add_parser("reset"); x.add_argument("--yes", action="store_true"); x.set_defaults(fn=cmd_reset)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
