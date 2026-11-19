"""Lambda tra cứu: trả home / office đã tính sẵn cho API (không chạy model). Đứng sau API Gateway HTTP API (payload 2.0).

Route:
    GET /health                                   -> {"status": "ok", "default_model_version": ...}
    GET /v1/users/{user_id}/home-office[?model_version=dbscan-v2]
Đọc:
    s3://BUCKET/results/<version>/<user_id>.json   do Lambda batch ghi
    s3://BUCKET/results/_default.json              {"default_model_version": "heuristic-v1", "registered": [...]}  (nhớ 60 giây)
        default_model_version = bản đã duyệt (Approved) trong registry = model NỀN, cho người dùng không thuộc nhóm canary.
        registered = các version có trong registry (trừ Rejected); do Lambda registry-sync hoặc set-default ghi.
Biến môi trường:
    BUCKET (bắt buộc); VERSIONS (mặc định "heuristic-v1,dbscan-v2"); DEFAULT_VERSION (khi chưa có _default.json);
    AUTH_MODE = none (mặc định) | jwt: route tra cứu đứng sau JWT authorizer Cognito (deploy/terraform/cognito.tf).
        API Gateway đã kiểm chữ ký / hạn token (sai thì 401, Lambda không chạy). Lambda đọc claims của ID token:
        `custom:geolife_id` phải bằng {user_id}, trừ khi `cognito:groups` có ADMIN_GROUP (mặc định "admin"); sai thì 403.
    PINNED_VERSION: nếu có, luôn dùng version model đó làm mặc định (bỏ qua _default.json).
        Dùng khi demo canary: ghim model cũ làm mặc định, model mới chạy canary cho một phần người dùng.
    CANARY_MODEL + CANARY_PERCENT: canary model CỐ ĐỊNH THEO NGƯỜI DÙNG. Băm user_id (sha256) ra một số 0..99;
        số < CANARY_PERCENT thì người dùng đó luôn nhận CANARY_MODEL, còn lại nhận version mặc định.
    CANARY_SALT: "muối" băm cùng user_id (sha256("<muối>:<user_id>")), mặc định = CANARY_MODEL. Mỗi đợt canary (muối khác)
        rút một nhóm người dùng khác, nên không ai lần nào cũng vào canary trước; trong một đợt thì nhóm vẫn cố định.
        Cùng người dùng luôn ra cùng số, nên gọi bao nhiêu lần cũng thấy cùng một model; tăng phần trăm thì nhóm cũ
        vẫn nằm trong nhóm canary. Người gọi truyền ?model_version=... thì bỏ qua canary.
        CANARY_MODEL = bản ỨNG VIÊN và phải có trong registry: nếu _default.json có danh sách "registered" mà không chứa
        CANARY_MODEL thì tắt canary (log canary_model_not_registered). File thiếu danh sách hoặc đọc S3 lỗi thì không chặn,
        để API không lỗi theo registry.
    CANARY_USERS: danh sách user_id cách nhau dấu phẩy (do api/pick_canary_users.py chọn ngẫu nhiên đúng N%).
        Có danh sách thì CHỈ các user đó vào nhóm canary, CANARY_PERCENT và muối bị bỏ qua.
        Danh sách rỗng thì dùng cách băm theo CANARY_PERCENT như trên. Danh sách cũng phải đi cùng CANARY_MODEL
        (và CANARY_MODEL vẫn phải có trong registry).
    CANARY_SIMULATE_ERROR = 1: người dùng thuộc nhóm canary bị lỗi 500 (giả lập model mới hỏng, chỉ để demo
        alarm + rollback); người dùng khác và /health vẫn chạy bình thường.
Response của route tra cứu (200, và 404 user_not_found) có X-Model-Version và X-Canary (true / false).
Lỗi trả JSON {"code", "message"} theo schema Error của api/openapi.yaml. Không ghi toạ độ vào log.
"""
import hashlib
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
ADMIN_GROUP = os.environ.get("ADMIN_GROUP", "admin")
USER_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")          # chặn ký tự lạ để không ai chèn đường dẫn vào key S3
PINNED_VERSION = os.environ.get("PINNED_VERSION") or None
CANARY_MODEL = os.environ.get("CANARY_MODEL") or None
try:
    CANARY_PERCENT = max(0, min(100, int(os.environ.get("CANARY_PERCENT") or 0)))
except ValueError:
    CANARY_PERCENT = 0
if CANARY_MODEL and CANARY_MODEL not in VERSIONS:  # cấu hình sai: tắt canary thay vì trả lỗi cho người dùng
    print(json.dumps({"event": "canary_model_ignored", "canary_model": CANARY_MODEL}))
    CANARY_MODEL = None
CANARY_SALT = os.environ.get("CANARY_SALT") or CANARY_MODEL or ""
CANARY_USERS = frozenset(u.strip() for u in (os.environ.get("CANARY_USERS") or "").split(",") if u.strip())
CANARY_SIMULATE_ERROR = os.environ.get("CANARY_SIMULATE_ERROR") == "1"
_DEFAULT = {"v": None, "registered": None, "t": 0.0}


def _resp(status: int, body: dict, version: str | None = None, canary: bool | None = None) -> dict:
    headers = {"Content-Type": "application/json", "Cache-Control": "no-store"}
    if version:
        headers["X-Model-Version"] = version
    if canary is not None:
        headers["X-Canary"] = "true" if canary else "false"
    return {"statusCode": status, "headers": headers, "body": json.dumps(body, ensure_ascii=False, allow_nan=False)}


def _err(status: int, code: str, message: str, version: str | None = None, canary: bool | None = None) -> dict:
    return _resp(status, {"code": code, "message": message}, version, canary)


def _get_json(key: str):
    """Đọc một object JSON trên S3. Không có thì trả None; lỗi khác thì ném tiếp."""
    try:
        return json.loads(S3.get_object(Bucket=BUCKET, Key=key)["Body"].read())
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return None
        raise


def _registry_state() -> dict:
    """Đọc results/_default.json (nhớ 60 giây). Lỗi S3 thì giữ giá trị cũ, không ném lỗi ra ngoài."""
    if _DEFAULT["v"] is None or time.time() - _DEFAULT["t"] > 60:
        try:
            d = _get_json("results/_default.json") or {}
            _DEFAULT["v"] = d.get("default_model_version") or FALLBACK_DEFAULT
            reg = d.get("registered")
            _DEFAULT["registered"] = [str(x) for x in reg] if isinstance(reg, list) else None
        except (ClientError, ValueError):
            _DEFAULT["v"] = _DEFAULT["v"] or FALLBACK_DEFAULT
        _DEFAULT["t"] = time.time()
    return _DEFAULT


def default_version() -> str:
    """Model nền: PINNED_VERSION nếu được ghim, không thì bản Approved trong registry (results/_default.json)."""
    if PINNED_VERSION:
        return PINNED_VERSION
    return _registry_state()["v"]


def canary_model() -> str | None:
    """CANARY_MODEL nếu được phép chạy: có cấu hình và (registry không có danh sách, hoặc có trong danh sách)."""
    if not CANARY_MODEL:
        return None
    reg = _registry_state()["registered"]
    if reg is not None and CANARY_MODEL not in reg:
        print(json.dumps({"event": "canary_model_not_registered", "canary_model": CANARY_MODEL, "registered": reg}))
        return None
    return CANARY_MODEL


def user_bucket(user: str, salt: str | None = None) -> int:
    """Số cố định 0..99 của một người dùng trong một đợt canary: sha256("<muối>:<user_id>").

    Dùng sha256, không dùng hash() của Python (hash() đổi mỗi lần khởi động). Muối mặc định CANARY_SALT.
    """
    key = f"{CANARY_SALT if salt is None else salt}:{user}"
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16) % 100


def in_canary(user: str) -> bool:
    """Người dùng có thuộc nhóm canary không: có CANARY_USERS thì theo danh sách, không thì băm theo CANARY_PERCENT."""
    if CANARY_USERS:
        return user in CANARY_USERS
    return user_bucket(user) < CANARY_PERCENT


def choose_version(user: str, requested: str | None) -> tuple[str, bool]:
    """(version model, có phải nhóm canary không). Thứ tự: model_version người gọi chỉ định > canary theo người dùng > mặc định."""
    if requested:
        return requested, False
    cm = canary_model()
    if cm and in_canary(user):
        return cm, True
    return default_version(), False


def _loc(x):
    """Giữ đúng các trường của schema Location (bỏ place_id, components)."""
    if not x:
        return None
    return {"lat": x["lat"], "lon": x["lon"], "confidence": x.get("confidence"), "n_votes": x["n_votes"]}


def _claims(event) -> dict:
    """Claims của token mà JWT authorizer đã kiểm (rỗng nếu route không gắn authorizer)."""
    return (((event.get("requestContext") or {}).get("authorizer") or {}).get("jwt") or {}).get("claims") or {}


def _groups(claims: dict) -> set:
    """cognito:groups. HTTP API đưa claim dạng mảng thành chuỗi "[admin other]"; chấp nhận cả list."""
    g = claims.get("cognito:groups") or []
    if isinstance(g, str):
        g = g.strip("[]").replace(",", " ").split()
    return {str(x).strip('"') for x in g}


def check_access(event, user: str):
    """AUTH_MODE=jwt: trả None nếu được đọc kết quả của `user`, không thì trả response lỗi 401 / 403."""
    claims = _claims(event)
    if not claims:  # route quên gắn authorizer: chặn luôn thay vì mở cho mọi người
        return _err(401, "unauthorized", "Cần đăng nhập (Authorization: Bearer <ID token>)")
    if ADMIN_GROUP in _groups(claims):
        return None
    if claims.get("custom:geolife_id") == user:
        return None
    print(json.dumps({"event": "forbidden", "has_geolife_id": bool(claims.get("custom:geolife_id"))}))
    return _err(403, "forbidden", "Không được đọc kết quả của người dùng này")


def lambda_handler(event, context):
    """Điểm vào: API Gateway gọi hàm này cho mỗi request."""
    route = event.get("routeKey") or ""
    if route == "GET /health":
        return _resp(200, {"status": "ok", "default_model_version": default_version()})
    if route != "GET /v1/users/{user_id}/home-office":
        return _err(404, "not_found", "Không có đường dẫn này")
    user = (event.get("pathParameters") or {}).get("user_id") or ""
    if not USER_RE.match(user):
        return _err(422, "validation_error", "user_id không hợp lệ")
    qs = event.get("queryStringParameters") or {}
    version, canary = choose_version(user, qs.get("model_version"))
    if canary and CANARY_SIMULATE_ERROR:
        raise RuntimeError("Lỗi giả lập (CANARY_SIMULATE_ERROR=1): model canary hỏng, để demo alarm + rollback")
    if version not in VERSIONS:
        return _err(422, "unknown_model_version", f"model_version phải là một trong: {', '.join(VERSIONS)}")

    if AUTH_MODE == "jwt":
        denied = check_access(event, user)
        if denied:
            return denied

    try:
        doc = _get_json(f"results/{version}/{user}.json")
    except ClientError:
        print(json.dumps({"event": "store_error", "version": version}))
        return _err(503, "store_unavailable", "Chưa đọc được kết quả tính sẵn")
    if doc is None or (not doc.get("home") and not doc.get("office")):
        return _err(404, "user_not_found", "Chưa có kết quả cho người dùng này", version, canary)

    return _resp(200, {"user_id": user, "model_version": version, "home": _loc(doc.get("home")),
                       "office": _loc(doc.get("office")), "flags": doc.get("flags", [])}, version, canary)
