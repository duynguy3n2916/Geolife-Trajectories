"""Test Lambda tra cứu (api/lookup_handler.py), phần đăng nhập Cognito (AUTH_MODE=jwt). S3 giả, không gọi AWS.

Chạy: pytest tests/test_lookup_handler.py (từ thư mục Home_Office). Không cần boto3 (tự giả lập nếu chưa cài).
"""
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

HANDLER = Path(__file__).resolve().parents[1] / "api" / "lookup_handler.py"
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


DEFAULT_DOC = {"doc": None}   # nội dung results/_default.json giả; None = không có file


class FakeS3:
    """Có kết quả của mọi user (cả 2 model), trừ user 999 (giả lập user không có nhà/công ty)."""

    def __init__(self, err):
        self.err = err

    def get_object(self, Bucket, Key):
        if Key == "results/_default.json":
            if DEFAULT_DOC["doc"] is None:
                raise self.err({"Error": {"Code": "NoSuchKey"}}, "GetObject")
            body = json.dumps(DEFAULT_DOC["doc"]).encode()
            return {"Body": types.SimpleNamespace(read=lambda: body)}
        user = Key.rsplit("/", 1)[-1].removesuffix(".json")
        if Key.startswith(("results/dbscan-v2/", "results/heuristic-v1/")) and user != "999":
            return {"Body": types.SimpleNamespace(read=lambda: json.dumps(RESULT).encode())}
        raise self.err({"Error": {"Code": "NoSuchKey"}}, "GetObject")


def load_handler(monkeypatch, auth_mode, default_doc=None, **env):
    """Nạp lookup_handler.py mới với biến môi trường cho trước (biến đọc lúc import).

    env: biến thêm, ví dụ CANARY_MODEL="heuristic-v1", CANARY_PERCENT="10".
    """
    err = _client_error_cls()
    DEFAULT_DOC["doc"] = default_doc
    monkeypatch.setenv("BUCKET", "test-bucket")
    monkeypatch.setenv("AUTH_MODE", auth_mode)
    monkeypatch.setenv("PINNED_VERSION", "dbscan-v2")
    for k in ("CANARY_MODEL", "CANARY_PERCENT", "CANARY_SALT", "CANARY_SIMULATE_ERROR", "CANARY_USERS"):
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


def test_simulate_error_only_canary_users(monkeypatch):
    """CANARY_SIMULATE_ERROR: chỉ user canary bị lỗi (Lambda ném lỗi -> API trả 500), user khác vẫn 200."""
    h = load_handler(monkeypatch, "jwt", CANARY_MODEL="heuristic-v1", CANARY_PERCENT="10", CANARY_SIMULATE_ERROR="1")
    bad = [u for u in USERS if h.user_bucket(u) < 10]
    good = [u for u in USERS if h.user_bucket(u) >= 10]
    assert bad and good
    for u in bad:
        with pytest.raises(RuntimeError):
            call(h, event(u, ADMIN))
    assert all(call(h, event(u, ADMIN))[0] == 200 for u in good)
    r = h.lambda_handler({"routeKey": "GET /health"}, None)
    assert r["statusCode"] == 200


def test_simulate_error_off_when_canary_off(monkeypatch):
    h = load_handler(monkeypatch, "jwt", CANARY_SIMULATE_ERROR="1")
    assert all(call(h, event(u, ADMIN))[0] == 200 for u in USERS[:30])


# ---------- canary_model phải có trong registry (danh sách "registered" trong _default.json) ----------

def test_canary_blocked_when_not_registered(monkeypatch):
    h = load_handler(monkeypatch, "jwt", default_doc={"default_model_version": "dbscan-v2", "registered": ["dbscan-v2"]},
                     CANARY_MODEL="heuristic-v1", CANARY_PERCENT="100")
    assert canary_set(h) == set()


def test_canary_allowed_when_registered(monkeypatch):
    h = load_handler(monkeypatch, "jwt",
                     default_doc={"default_model_version": "dbscan-v2", "registered": ["heuristic-v1", "dbscan-v2"]},
                     CANARY_MODEL="heuristic-v1", CANARY_PERCENT="100")
    assert canary_set(h) == set(USERS)


def test_canary_not_blocked_without_list(monkeypatch):
    """File cũ không có "registered" (hoặc không có file): không chặn, giữ hành vi cũ."""
    h = load_handler(monkeypatch, "jwt", default_doc={"default_model_version": "dbscan-v2"},
                     CANARY_MODEL="heuristic-v1", CANARY_PERCENT="100")
    assert canary_set(h) == set(USERS)


def test_registry_read_error_does_not_break_api(monkeypatch):
    """S3 lỗi khi đọc _default.json: API vẫn trả 200, canary không bị chặn."""
    h = load_handler(monkeypatch, "jwt", CANARY_MODEL="heuristic-v1", CANARY_PERCENT="100")
    err = _client_error_cls()
    orig = h.S3.get_object

    def boom(Bucket, Key):
        if Key == "results/_default.json":
            raise err({"Error": {"Code": "InternalError"}}, "GetObject")
        return orig(Bucket=Bucket, Key=Key)
    h.S3.get_object = boom
    code, body = call(h, event("013", ADMIN))
    assert code == 200


def test_default_from_registry_when_not_pinned(monkeypatch):
    h = load_handler(monkeypatch, "jwt", default_doc={"default_model_version": "heuristic-v1", "registered": ["heuristic-v1"]})
    monkeypatch.setattr(h, "PINNED_VERSION", None)
    code, body = call(h, event("153", ADMIN))
    assert code == 200 and body["model_version"] == "heuristic-v1"


# ---------- canary theo danh sách (CANARY_USERS, do api/pick_canary_users.py chọn) ----------
def test_canary_users_list_exact(monkeypatch):
    """Có danh sách: đúng các user đó vào canary, CANARY_PERCENT bị bỏ qua."""
    h = load_handler(monkeypatch, "jwt", CANARY_MODEL="heuristic-v1", CANARY_PERCENT="100", CANARY_USERS="003, 017,153")
    got = {u for u in USERS if call_full(h, event(u, ADMIN))[2].get("X-Canary") == "true"}
    assert got == {"003", "017", "153"} & set(USERS)
    code, body, hd = call_full(h, event("153", ADMIN))
    assert body["model_version"] == "heuristic-v1" and hd["X-Canary"] == "true"


def test_canary_users_without_model_off(monkeypatch):
    h = load_handler(monkeypatch, "jwt", CANARY_USERS="153")
    assert call_full(h, event("153", ADMIN))[2]["X-Canary"] == "false"


def test_canary_users_still_needs_registry(monkeypatch):
    h = load_handler(monkeypatch, "jwt", default_doc={"default_model_version": "dbscan-v2", "registered": ["dbscan-v2"]},
                     CANARY_MODEL="heuristic-v1", CANARY_USERS="153")
    assert call_full(h, event("153", ADMIN))[2]["X-Canary"] == "false"


def test_simulate_error_with_list(monkeypatch):
    h = load_handler(monkeypatch, "jwt", CANARY_MODEL="heuristic-v1", CANARY_USERS="153", CANARY_SIMULATE_ERROR="1")
    with pytest.raises(RuntimeError):
        call(h, event("153", ADMIN))
    assert call(h, event("002", ADMIN))[0] == 200
