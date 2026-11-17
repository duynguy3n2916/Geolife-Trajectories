"""Lambda tra cứu: trả home / office đã tính sẵn cho API (không chạy model). Đứng sau API Gateway HTTP API (payload 2.0).

Route:
    GET /health                                   -> {"status": "ok", "default_model_version": ...}
    GET /v1/users/{user_id}/home-office[?model_version=dbscan-v2]
Đọc:
    s3://BUCKET/results/<version>/<user_id>.json   do Lambda batch ghi
    s3://BUCKET/results/_default.json              {"default_model_version": "heuristic-v1"}  (nhớ 60 giây)
Biến môi trường:
    BUCKET (bắt buộc); VERSIONS (mặc định "heuristic-v1,dbscan-v2"); DEFAULT_VERSION (khi chưa có _default.json);
    AUTH_MODE = none (mặc định) | jwt: claim `sub` của token phải ứng với user_id theo SUB_MAP (JSON {"<sub>": "<user_id>"}).
    PINNED_VERSION: nếu có, bản Lambda này luôn dùng version model đó làm mặc định (bỏ qua _default.json).
        Dùng cho canary: bản cũ theo registry, bản mới ghim version mới; alias "live" chia traffic giữa hai bản.
    SIMULATE_ERROR = 1: route tra cứu cố ý ném lỗi (chỉ để demo rollback canary; /health vẫn chạy).
Mọi response có header X-Lambda-Version (số version Lambda đã trả lời) để đếm tỉ lệ canary.
Lỗi trả JSON {"code", "message"} theo schema Error của api/openapi.yaml. Không ghi toạ độ vào log.
"""
import json
import os
import re
import time

import boto3
from botocore.exceptions import ClientError

S3 = boto3.client("s3")
BUCKET = os.environ["BUCKET"]
VERSIONS = [v.strip() for v in os.environ.get("VERSIONS", "heuristic-v1,dbscan-v2").split(",") if v.strip()]
FALLBACK_DEFAULT = os.environ.get("DEFAULT_VERSION", "heuristic-v1")
AUTH_MODE = os.environ.get("AUTH_MODE", "none")
SUB_MAP = json.loads(os.environ.get("SUB_MAP", "{}"))
USER_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")          # chặn ký tự lạ để không ai chèn đường dẫn vào key S3
PINNED_VERSION = os.environ.get("PINNED_VERSION") or None
SIMULATE_ERROR = os.environ.get("SIMULATE_ERROR") == "1"
_DEFAULT = {"v": None, "t": 0.0}
_FN_VERSION = {"v": "$LATEST"}                           # số version Lambda của lần gọi hiện tại


def _resp(status: int, body: dict, version: str | None = None) -> dict:
    headers = {"Content-Type": "application/json", "Cache-Control": "no-store", "X-Lambda-Version": _FN_VERSION["v"]}
    if version:
        headers["X-Model-Version"] = version
    return {"statusCode": status, "headers": headers, "body": json.dumps(body, ensure_ascii=False, allow_nan=False)}


def _err(status: int, code: str, message: str) -> dict:
    return _resp(status, {"code": code, "message": message})


def _get_json(key: str):
    """Đọc một object JSON trên S3. Không có thì trả None; lỗi khác thì ném tiếp."""
    try:
        return json.loads(S3.get_object(Bucket=BUCKET, Key=key)["Body"].read())
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return None
        raise


def default_version() -> str:
    """Version mặc định: PINNED_VERSION nếu bản Lambda này được ghim, không thì results/_default.json (đọc lại sau 60 giây)."""
    if PINNED_VERSION:
        return PINNED_VERSION
    if _DEFAULT["v"] is None or time.time() - _DEFAULT["t"] > 60:
        try:
            d = _get_json("results/_default.json") or {}
            _DEFAULT["v"] = d.get("default_model_version") or FALLBACK_DEFAULT
        except ClientError:
            _DEFAULT["v"] = _DEFAULT["v"] or FALLBACK_DEFAULT
        _DEFAULT["t"] = time.time()
    return _DEFAULT["v"]


def _loc(x):
    """Giữ đúng các trường của schema Location (bỏ place_id, components)."""
    if not x:
        return None
    return {"lat": x["lat"], "lon": x["lon"], "confidence": x.get("confidence"), "n_votes": x["n_votes"]}


def _caller_user(event):
    """AUTH_MODE=jwt: user_id của người đang đăng nhập (None nếu không có token hoặc chưa ánh xạ)."""
    claims = (((event.get("requestContext") or {}).get("authorizer") or {}).get("jwt") or {}).get("claims") or {}
    sub = claims.get("sub")
    return SUB_MAP.get(sub) if sub else None


def lambda_handler(event, context):
    """Điểm vào: API Gateway gọi hàm này cho mỗi request."""
    _FN_VERSION["v"] = getattr(context, "function_version", None) or "$LATEST"
    route = event.get("routeKey") or ""
    if route == "GET /health":
        return _resp(200, {"status": "ok", "default_model_version": default_version()})
    if route != "GET /v1/users/{user_id}/home-office":
        return _err(404, "not_found", "Không có đường dẫn này")
    if SIMULATE_ERROR:
        raise RuntimeError("Lỗi giả lập (SIMULATE_ERROR=1) để demo rollback canary")

    user = (event.get("pathParameters") or {}).get("user_id") or ""
    if not USER_RE.match(user):
        return _err(422, "validation_error", "user_id không hợp lệ")
    qs = event.get("queryStringParameters") or {}
    version = qs.get("model_version") or default_version()
    if version not in VERSIONS:
        return _err(422, "unknown_model_version", f"model_version phải là một trong: {', '.join(VERSIONS)}")

    if AUTH_MODE == "jwt":
        caller = _caller_user(event)
        if caller is None or caller != user:
            return _err(403, "forbidden", "Không được đọc kết quả của người dùng này")

    try:
        doc = _get_json(f"results/{version}/{user}.json")
    except ClientError:
        print(json.dumps({"event": "store_error", "version": version}))
        return _err(503, "store_unavailable", "Chưa đọc được kết quả tính sẵn")
    if doc is None or (not doc.get("home") and not doc.get("office")):
        return _err(404, "user_not_found", "Chưa có kết quả cho người dùng này")

    return _resp(200, {"user_id": user, "model_version": version, "home": _loc(doc.get("home")),
                       "office": _loc(doc.get("office")), "flags": doc.get("flags", [])}, version)
