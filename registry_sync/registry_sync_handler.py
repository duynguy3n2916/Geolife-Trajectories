"""Lambda đồng bộ registry: version nào được duyệt (Approved) trong SageMaker Model Registry thì API dùng version đó.

Chuỗi sự kiện:
    duyệt version trên SageMaker (Studio, CLI, hoặc register_models.py set-default)
      -> SageMaker phát sự kiện "SageMaker Model Package State Change"
      -> EventBridge rule (deploy/terraform/registry_sync.tf) gọi Lambda này
      -> Lambda tìm version Approved của group, ghi s3://BUCKET/results/_default.json
         {"default_model_version": <bản Approved>, "registered": [<mọi version trong registry trừ Rejected>]}
      -> Lambda tra cứu đọc lại file đó sau tối đa 60 giây.

Quy tắc chọn (ghi rõ vì registry cho phép nhiều version cùng Approved):
    1. Chỉ xét Model Package của group GROUP có ModelApprovalStatus = Approved và tên model nằm trong VERSIONS.
       Tên model lấy từ CustomerMetadataProperties["model_version"], không có thì lấy phần trước dấu ":" của Description.
    2. Nhiều version cùng Approved: lấy bản có LastModifiedTime mới nhất (bản vừa được duyệt), in cảnh báo multiple_approved.
    3. Không có version Approved nào: KHÔNG ghi gì (giữ nguyên _default.json cũ, API không bị gián đoạn), in no_approved.
    4. Version chọn được và danh sách registered trùng với _default.json đang có: không ghi lại (unchanged).
    5. registered dùng để Lambda tra cứu chỉ cho phép CANARY_MODEL là version có trong registry (bản ứng viên).
Lambda chỉ đọc registry, không tự đổi trạng thái version nào.

Biến môi trường: BUCKET (bắt buộc), GROUP (mặc định "home-office"), VERSIONS (mặc định "heuristic-v1,dbscan-v2").
"""
import json
import os

import boto3
from botocore.exceptions import ClientError

BUCKET = os.environ["BUCKET"]
GROUP = os.environ.get("GROUP", "home-office")
VERSIONS = [v.strip() for v in os.environ.get("VERSIONS", "heuristic-v1,dbscan-v2").split(",") if v.strip()]
DEFAULT_KEY = "results/_default.json"

SM = boto3.client("sagemaker")
S3 = boto3.client("s3")


def model_name(desc: dict) -> str | None:
    """Tên model của một Model Package: metadata model_version, không có thì phần đầu Description ("dbscan-v2: ...")."""
    name = (desc.get("CustomerMetadataProperties") or {}).get("model_version")
    if not name:
        name = (desc.get("ModelPackageDescription") or "").split(":", 1)[0].strip()
    return name or None


def registry_packages() -> list[dict]:
    """Mọi Model Package của group có tên model hợp lệ: [{name, arn, status, modified}]."""
    out = []
    for page in SM.get_paginator("list_model_packages").paginate(ModelPackageGroupName=GROUP):
        for s in page.get("ModelPackageSummaryList", []):
            d = SM.describe_model_package(ModelPackageName=s["ModelPackageArn"])
            name = model_name(d)
            if name not in VERSIONS:
                print(json.dumps({"event": "unknown_model", "arn": s["ModelPackageArn"], "model": name}))
                continue
            out.append({"name": name, "arn": s["ModelPackageArn"], "status": d.get("ModelApprovalStatus"),
                        "modified": d.get("LastModifiedTime") or d.get("CreationTime")})
    return out


def approved_packages(pkgs: list[dict] | None = None) -> list[dict]:
    """Các bản Approved (trạng thái đọc bằng describe, mới nhất)."""
    return [p for p in (registry_packages() if pkgs is None else pkgs) if p["status"] == "Approved"]


def registered_names(pkgs: list[dict]) -> list[str]:
    """Version có trong registry và không bị từ chối: được phép làm canary."""
    return sorted({p["name"] for p in pkgs if p["status"] != "Rejected"})


def choose(pkgs: list[dict]) -> dict | None:
    """Quy tắc 2: bản Approved đổi gần nhất thắng."""
    if not pkgs:
        return None
    return max(pkgs, key=lambda p: (p["modified"] is not None, p["modified"] or 0))


def current_doc() -> dict:
    try:
        body = S3.get_object(Bucket=BUCKET, Key=DEFAULT_KEY)["Body"].read()
        d = json.loads(body)
        return d if isinstance(d, dict) else {}
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("NoSuchKey", "404", "AccessDenied"):
            return {}
        raise
    except ValueError:
        return {}


def lambda_handler(event, context):
    detail = (event or {}).get("detail") or {}
    print(json.dumps({"event": "registry_change", "arn": detail.get("ModelPackageArn"),
                      "status": detail.get("ModelApprovalStatus")}))
    pkgs = registry_packages()
    approved = approved_packages(pkgs)
    best = choose(approved)
    if best is None:
        print(json.dumps({"event": "no_approved", "group": GROUP}))
        return {"written": False, "reason": "no_approved"}
    if len(approved) > 1:
        print(json.dumps({"event": "multiple_approved", "approved": sorted(p["name"] for p in approved), "chosen": best["name"]}))
    doc = {"default_model_version": best["name"], "registered": registered_names(pkgs)}
    old_doc = current_doc()
    old = old_doc.get("default_model_version")
    if old_doc.get("default_model_version") == doc["default_model_version"] and old_doc.get("registered") == doc["registered"]:
        print(json.dumps({"event": "unchanged", **doc}))
        return {"written": False, "reason": "unchanged", "default_model_version": old}
    S3.put_object(Bucket=BUCKET, Key=DEFAULT_KEY, ContentType="application/json", Body=json.dumps(doc).encode())
    print(json.dumps({"event": "default_written", "from": old, "to": best["name"], "registered": doc["registered"], "arn": best["arn"]}))
    return {"written": True, "default_model_version": best["name"], "previous": old, "registered": doc["registered"]}
