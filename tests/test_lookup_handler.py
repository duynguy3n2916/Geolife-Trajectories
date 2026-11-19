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
    """Có kết quả của mọi user (cả 2 model), trừ user 999 (giả lập user không có nhà/công ty)."""

    def __init__(self, err):
        self.err = err

    def get_object(self, Bucket, Key):
        user = Key.rsplit("/", 1)[-1].removesuffix(".json")
        if Key.startswith(("results/dbscan-v2/", "results/heuristic-v1/")) and user != "999":
            return {"Body": types.SimpleNamespace(read=lambda: json.dumps(RESULT).encode())}
        raise self.err({"Error": {"Code": "NoSuchKey"}}, "GetObject")


def load_handler(monkeypatch, auth_mode, **env):
    """Nạp handler.py mới với biến môi trường cho trước (biến đọc lúc import).

    env: biến thêm, ví dụ CANARY_MODEL="heuristic-v1", CANARY_PERCENT="10".
    """
    err = _client_error_cls()
    monkeypatch.setenv("BUCKET", "test-bucket")
    monkeypatch.setenv("AUTH_MODE", auth_mode)
    monkeypatch.setenv("PINNED_VERSION", "dbscan-v2")
    for k in ("CANARY_MODEL", "CANARY_PERCENT", "CANARY_SALT"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
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


def call_full(h, ev):
    """Như call nhưng trả cả headers."""
    r = h.lambda_handler(ev, types.SimpleNamespace(function_version="7"))
    return r["statusCode"], json.loads(r["body"]), r.get("headers", {})


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


# ---------- Canary model theo user (CANARY_MODEL + CANARY_PERCENT) ----------

USERS = [f"{i:03d}" for i in range(182)]
ADMIN = {"sub": "x", "cognito:groups": "[admin]"}


def canary_handler(monkeypatch, percent, model="heuristic-v1"):
    return load_handler(monkeypatch, "jwt", CANARY_MODEL=model, CANARY_PERCENT=str(percent))


def canary_set(h):
    """Tập user rơi vào nhóm canary (đọc qua header X-Canary)."""
    out = set()
    for u in USERS:
        code, body, hd = call_full(h, event(u, ADMIN))
        assert code == 200
        if hd["X-Canary"] == "true":
            assert body["model_version"] == "heuristic-v1" and hd["X-Model-Version"] == "heuristic-v1"
            out.add(u)
        else:
            assert body["model_version"] == "dbscan-v2"
    return out


def test_bucket_deterministic(h):
    """sha256 cố định: cùng user luôn cùng bucket (không dùng hash() của Python vì đổi theo tiến trình)."""
    b = [h.user_bucket(u) for u in USERS]
    assert b == [h.user_bucket(u) for u in USERS]
    assert all(0 <= x < 100 for x in b)
    assert h.user_bucket("153", "dbscan-v2") == int(__import__("hashlib").sha256(b"dbscan-v2:153").hexdigest()[:8], 16) % 100


def test_no_canary_by_default(h):
    code, body, hd = call_full(h, event("153", {"sub": "abc", "custom:geolife_id": "153"}))
    assert code == 200 and body["model_version"] == "dbscan-v2" and hd["X-Canary"] == "false"


def test_canary_sticky_same_user(monkeypatch):
    """Một user canary gọi 20 lần: luôn cùng model, luôn X-Canary=true."""
    h = canary_handler(monkeypatch, 50)
    u = next(x for x in USERS if h.user_bucket(x) < 50)
    seen = {(call_full(h, event(u, ADMIN))[1]["model_version"], call_full(h, event(u, ADMIN))[2]["X-Canary"])
            for _ in range(20)}
    assert seen == {("heuristic-v1", "true")}


def test_salt_defaults_to_canary_model(monkeypatch):
    h = canary_handler(monkeypatch, 10)
    assert h.CANARY_SALT == "heuristic-v1"
    h = load_handler(monkeypatch, "jwt", CANARY_MODEL="heuristic-v1", CANARY_PERCENT="10", CANARY_SALT="dot-2")
    assert h.CANARY_SALT == "dot-2"


def test_different_salt_different_group(monkeypatch):
    """Muối khác (đợt canary khác) rút nhóm user khác; cùng muối thì nhóm giữ nguyên."""
    a = canary_set(load_handler(monkeypatch, "jwt", CANARY_MODEL="heuristic-v1", CANARY_PERCENT="10", CANARY_SALT="dot-1"))
    b = canary_set(load_handler(monkeypatch, "jwt", CANARY_MODEL="heuristic-v1", CANARY_PERCENT="10", CANARY_SALT="dot-2"))
    a2 = canary_set(load_handler(monkeypatch, "jwt", CANARY_MODEL="heuristic-v1", CANARY_PERCENT="10", CANARY_SALT="dot-1"))
    assert a == a2 and a != b


def test_canary_percent_0_and_100(monkeypatch):
    assert canary_set(canary_handler(monkeypatch, 0)) == set()
    assert canary_set(canary_handler(monkeypatch, 100)) == set(USERS)


def test_canary_grows_monotonic(monkeypatch):
    """Tăng 10 -> 50 -> 100: user đã ở nhóm canary thì vẫn ở đó (không bị đổi qua lại)."""
    s10 = canary_set(canary_handler(monkeypatch, 10))
    s50 = canary_set(canary_handler(monkeypatch, 50))
    assert s10 <= s50 <= set(USERS)
    assert 5 <= len(s10) <= 35 and 60 <= len(s50) <= 120  # xấp xỉ 10% và 50% của 182 user


def test_explicit_model_version_overrides_canary(monkeypatch):
    h = canary_handler(monkeypatch, 100)
    ev = event("153", ADMIN)
    ev["queryStringParameters"] = {"model_version": "dbscan-v2"}
    code, body, hd = call_full(h, ev)
    assert code == 200 and body["model_version"] == "dbscan-v2" and hd["X-Canary"] == "false"


def test_invalid_canary_model_ignored(monkeypatch):
    h = canary_handler(monkeypatch, 100, model="khong-co")
    assert h.CANARY_MODEL is None
    assert canary_set(h) == set()


@pytest.mark.parametrize("raw,want", [("abc", 0), ("-5", 0), ("150", 100), ("", 0)])
def test_canary_percent_clamped(monkeypatch, raw, want):
    h = load_handler(monkeypatch, "jwt", CANARY_MODEL="heuristic-v1", CANARY_PERCENT=raw)
    assert h.CANARY_PERCENT == want


def test_canary_header_on_404(monkeypatch):
    h = canary_handler(monkeypatch, 100)
    code, body, hd = call_full(h, event("999", ADMIN))
    assert code == 404 and hd["X-Canary"] == "true" and hd["X-Model-Version"] == "heuristic-v1"
