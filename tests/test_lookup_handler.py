"""Test Lambda tra cứu (api/handler.py), phần đăng nhập Cognito (AUTH_MODE=jwt). S3 giả, không gọi AWS.

Chạy: pytest tests/test_lookup_handler.py (từ thư mục Home_Office). Không cần boto3 (tự giả lập nếu chưa cài).
"""
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

HANDLER = Path(__file__).resolve().parents[1] / "api" / "handler.py"
RESULT = {"home": {"lat": 39.99, "lon": 116.30, "confidence": 98.0, "n_votes": 40},
          "office": {"lat": 39.98, "lon": 116.35, "confidence": 90.0, "n_votes": 20}, "flags": []}


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


class FakeS3:
    """Chỉ có results/dbscan-v2/002.json và results/dbscan-v2/153.json."""

    def __init__(self, err):
        self.err = err

    def get_object(self, Bucket, Key):
        user = Key.rsplit("/", 1)[-1].removesuffix(".json")
        if Key.startswith("results/dbscan-v2/") and user in ("002", "153"):
            return {"Body": types.SimpleNamespace(read=lambda: json.dumps(RESULT).encode())}
        raise self.err({"Error": {"Code": "NoSuchKey"}}, "GetObject")


def load_handler(monkeypatch, auth_mode):
    """Nạp handler.py mới với biến môi trường cho trước (biến đọc lúc import)."""
    err = _client_error_cls()
    monkeypatch.setenv("BUCKET", "test-bucket")
    monkeypatch.setenv("AUTH_MODE", auth_mode)
    monkeypatch.setenv("PINNED_VERSION", "dbscan-v2")
    monkeypatch.setitem(sys.modules, "boto3", types.SimpleNamespace(client=lambda *_a, **_k: FakeS3(err)))
    if "botocore.exceptions" not in sys.modules:
        monkeypatch.setitem(sys.modules, "botocore", types.ModuleType("botocore"))
        monkeypatch.setitem(sys.modules, "botocore.exceptions", types.SimpleNamespace(ClientError=err))
    spec = importlib.util.spec_from_file_location("lookup_handler_test", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def event(user, claims=None):
    """Event giống API Gateway HTTP API (payload 2.0). claims=None: không có authorizer."""
    ctx = {"authorizer": {"jwt": {"claims": claims, "scopes": None}}} if claims is not None else {}
    return {"routeKey": "GET /v1/users/{user_id}/home-office", "pathParameters": {"user_id": user},
            "queryStringParameters": None, "requestContext": ctx}


def call(h, ev):
    r = h.lambda_handler(ev, types.SimpleNamespace(function_version="7"))
    return r["statusCode"], json.loads(r["body"])


@pytest.fixture
def h(monkeypatch):
    return load_handler(monkeypatch, "jwt")


def test_own_user_ok(h):
    code, body = call(h, event("153", {"sub": "abc", "custom:geolife_id": "153"}))
    assert code == 200 and body["user_id"] == "153" and body["model_version"] == "dbscan-v2"


def test_other_user_forbidden(h):
    code, body = call(h, event("002", {"sub": "abc", "custom:geolife_id": "153"}))
    assert code == 403 and body["code"] == "forbidden"


def test_forbidden_before_store(h):
    """User khác mà không có kết quả: vẫn 403, không lộ 404 (không dò được ai có dữ liệu)."""
    code, _ = call(h, event("999", {"sub": "abc", "custom:geolife_id": "153"}))
    assert code == 403


def test_no_geolife_id_forbidden(h):
    code, _ = call(h, event("153", {"sub": "abc"}))
    assert code == 403


@pytest.mark.parametrize("groups", ["[admin]", "[viewer admin]", ["admin"]])
def test_admin_reads_any_user(h, groups):
    code, body = call(h, event("002", {"sub": "x", "cognito:groups": groups}))
    assert code == 200 and body["user_id"] == "002"


def test_admin_still_gets_404(h):
    code, body = call(h, event("999", {"sub": "x", "cognito:groups": "[admin]"}))
    assert code == 404 and body["code"] == "user_not_found"


def test_other_group_not_admin(h):
    code, _ = call(h, event("002", {"sub": "x", "cognito:groups": "[administrators]", "custom:geolife_id": "153"}))
    assert code == 403


def test_missing_authorizer_is_401(h):
    """Route quên gắn authorizer mà Lambda bật jwt: chặn, không mở."""
    code, body = call(h, event("153"))
    assert code == 401 and body["code"] == "unauthorized"


def test_health_needs_no_token(h):
    r = h.lambda_handler({"routeKey": "GET /health"}, types.SimpleNamespace(function_version="7"))
    assert r["statusCode"] == 200


def test_auth_off_open(monkeypatch):
    h = load_handler(monkeypatch, "none")
    code, _ = call(h, event("002"))
    assert code == 200
