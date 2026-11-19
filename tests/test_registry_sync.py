"""Test Lambda đồng bộ registry (registry_sync/registry_sync_handler.py). SageMaker và S3 giả, không gọi AWS.

Chạy: pytest tests/test_registry_sync.py (từ thư mục Home_Office). Không cần boto3 (tự giả lập nếu chưa cài).
"""
import importlib.util
import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

HANDLER = Path(__file__).resolve().parents[1] / "registry_sync" / "registry_sync_handler.py"


def _client_error_cls():
    try:
        from botocore.exceptions import ClientError
        return ClientError
    except ImportError:
        class ClientError(Exception):
            def __init__(self, response, op):
                super().__init__(op)
                self.response = response
        return ClientError


def t(minute):
    return datetime(2026, 11, 19, 12, minute, tzinfo=timezone.utc)


class FakeSM:
    """packages: list of dict(arn, status, name, modified, meta=True|False)."""

    def __init__(self, packages):
        self.packages = packages
        self.updated = []

    def get_paginator(self, op):
        assert op == "list_model_packages"
        sm = self

        class P:
            def paginate(self, ModelPackageGroupName, ModelApprovalStatus=None):
                rows = [p for p in sm.packages if ModelApprovalStatus is None or p["status"] == ModelApprovalStatus]
                yield {"ModelPackageSummaryList": [{"ModelPackageArn": p["arn"]} for p in rows]}
        return P()

    def describe_model_package(self, ModelPackageName):
        p = next(x for x in self.packages if x["arn"] == ModelPackageName)
        d = {"ModelPackageArn": p["arn"], "ModelApprovalStatus": p["status"], "LastModifiedTime": p["modified"],
             "ModelPackageDescription": f"{p['name']}: mô tả"}
        if p.get("meta", True):
            d["CustomerMetadataProperties"] = {"model_version": p["name"]}
        return d

    def update_model_package(self, **kw):          # Lambda không được gọi hàm này
        self.updated.append(kw)


class FakeS3:
    def __init__(self, err, default=None):
        self.err = err
        self.store = {} if default is None else {"results/_default.json": json.dumps({"default_model_version": default}).encode()}
        self.puts = []

    def get_object(self, Bucket, Key):
        if Key not in self.store:
            raise self.err({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        body = self.store[Key]
        return {"Body": types.SimpleNamespace(read=lambda: body)}

    def put_object(self, Bucket, Key, Body, ContentType):
        assert Key == "results/_default.json"
        self.store[Key] = Body
        self.puts.append(json.loads(Body))


def load(monkeypatch, packages, default=None):
    err = _client_error_cls()
    sm, s3 = FakeSM(packages), FakeS3(err, default)
    monkeypatch.setenv("BUCKET", "test-bucket")
    monkeypatch.setitem(sys.modules, "boto3",
                        types.SimpleNamespace(client=lambda name, *a, **k: sm if name == "sagemaker" else s3))
    if "botocore.exceptions" not in sys.modules:
        monkeypatch.setitem(sys.modules, "botocore", types.ModuleType("botocore"))
        monkeypatch.setitem(sys.modules, "botocore.exceptions", types.SimpleNamespace(ClientError=err))
    spec = importlib.util.spec_from_file_location("registry_sync_test", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, sm, s3


EVENT = {"source": "aws.sagemaker", "detail-type": "SageMaker Model Package State Change",
         "detail": {"ModelPackageGroupName": "home-office", "ModelPackageArn": "arn:v2", "ModelApprovalStatus": "Approved"}}


def pkg(n, name, status, minute, meta=True):
    return {"arn": f"arn:v{n}", "name": name, "status": status, "modified": t(minute), "meta": meta}


def test_writes_approved_version(monkeypatch):
    h, sm, s3 = load(monkeypatch, [pkg(1, "heuristic-v1", "PendingManualApproval", 1), pkg(2, "dbscan-v2", "Approved", 2)],
                     default="heuristic-v1")
    r = h.lambda_handler(EVENT, None)
    assert r == {"written": True, "default_model_version": "dbscan-v2", "previous": "heuristic-v1"}
    assert s3.puts == [{"default_model_version": "dbscan-v2"}]
    assert sm.updated == []                         # chỉ đọc registry


def test_unchanged_does_not_write(monkeypatch):
    h, _, s3 = load(monkeypatch, [pkg(2, "dbscan-v2", "Approved", 2)], default="dbscan-v2")
    assert h.lambda_handler(EVENT, None)["reason"] == "unchanged"
    assert s3.puts == []


def test_multiple_approved_latest_wins(monkeypatch):
    """Quy tắc 2: hai bản cùng Approved, bản đổi gần nhất (heuristic-v1 phút 9) thắng."""
    h, _, s3 = load(monkeypatch, [pkg(1, "heuristic-v1", "Approved", 9), pkg(2, "dbscan-v2", "Approved", 5)],
                    default="dbscan-v2")
    r = h.lambda_handler(EVENT, None)
    assert r["default_model_version"] == "heuristic-v1" and s3.puts == [{"default_model_version": "heuristic-v1"}]


def test_no_approved_keeps_old_default(monkeypatch):
    """Quy tắc 3: bỏ duyệt hết thì giữ nguyên _default.json, API không gián đoạn."""
    h, _, s3 = load(monkeypatch, [pkg(1, "heuristic-v1", "Rejected", 1), pkg(2, "dbscan-v2", "PendingManualApproval", 2)],
                    default="dbscan-v2")
    assert h.lambda_handler(EVENT, None) == {"written": False, "reason": "no_approved"}
    assert s3.puts == [] and json.loads(s3.store["results/_default.json"])["default_model_version"] == "dbscan-v2"


def test_name_from_description_when_no_metadata(monkeypatch):
    h, _, s3 = load(monkeypatch, [pkg(2, "dbscan-v2", "Approved", 2, meta=False)])
    assert h.lambda_handler(EVENT, None)["default_model_version"] == "dbscan-v2"


def test_unknown_model_ignored(monkeypatch):
    """Version có tên lạ (không trong VERSIONS) không bao giờ thành mặc định của API."""
    h, _, s3 = load(monkeypatch, [pkg(3, "model-la", "Approved", 9), pkg(2, "dbscan-v2", "Approved", 2)],
                    default="heuristic-v1")
    assert h.lambda_handler(EVENT, None)["default_model_version"] == "dbscan-v2"


def test_first_write_when_no_default_file(monkeypatch):
    h, _, s3 = load(monkeypatch, [pkg(1, "heuristic-v1", "Approved", 1)])
    r = h.lambda_handler({}, None)
    assert r["written"] is True and r["previous"] is None


@pytest.mark.parametrize("desc,meta,want", [
    ({"ModelPackageDescription": "dbscan-v2: DBSCAN"}, None, "dbscan-v2"),
    ({"ModelPackageDescription": ""}, None, None),
    ({"ModelPackageDescription": "x: y"}, {"model_version": "heuristic-v1"}, "heuristic-v1"),
])
def test_model_name(monkeypatch, desc, meta, want):
    h, _, _ = load(monkeypatch, [])
    d = dict(desc)
    if meta:
        d["CustomerMetadataProperties"] = meta
    assert h.model_name(d) == want
