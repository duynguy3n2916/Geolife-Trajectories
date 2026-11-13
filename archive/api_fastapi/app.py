"""API Home/Office Inference theo api/openapi.yaml (bản 0.2.0-cp2-draft).

Chạy cục bộ (từ thư mục Home_Office), không cần key:

    uvicorn api.app:app --port 8000

Biến môi trường:
    API_KEYS        các key hợp lệ, cách nhau bằng dấu phẩy; khi đặt thì mọi endpoint trừ /health cần header X-API-Key.
                    Không đặt thì KHÔNG kiểm tra key (chỉ dùng khi chạy ở máy; deploy công khai phải đặt).
    GEOLIFE_STORE   đường dẫn file store (mặc định api/store/geolife.sqlite, tạo bằng api/build_store.py)
    GIT_COMMIT      commit của bản đang chạy, hiện ở GET /v1/models (Docker / CI truyền vào)

Spec ở api/openapi.yaml là bản gốc: /docs và /openapi.json hiển thị đúng file đó (thêm danh sách model_version
lấy từ src/models.py), không dùng spec FastAPI tự sinh.
Dữ liệu tải lên chỉ nằm trong bộ nhớ; không ghi tọa độ vào log. Chưa làm: giới hạn tốc độ gọi (429).
"""
from __future__ import annotations

import copy
import hmac
import logging
import os
import sys
from functools import lru_cache
from pathlib import Path

import yaml
from fastapi import Depends, FastAPI, Path as PathParam, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.formparsers import MultiPartParser

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
import infer                                                    # noqa: E402
import models                                                   # noqa: E402
from api import uploads                                         # noqa: E402
from api.store import GeolifeStore                              # noqa: E402

SPEC_PATH = ROOT / "api" / "openapi.yaml"
STORE_PATH = Path(os.environ.get("GEOLIFE_STORE", ROOT / "api" / "store" / "geolife.sqlite"))
STATUS = {"payload_too_large": 413, "unsupported_format": 415, "validation_error": 422,
          "unknown_model_version": 422, "unauthorized": 401, "user_not_found": 404}


class APIError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details


def _error(status: int, code: str, message: str, details: dict | None = None, headers=None) -> JSONResponse:
    body = {"code": code, "message": message}
    if details:
        body["details"] = details
    return JSONResponse(body, status_code=status, headers=headers)


@lru_cache(maxsize=1)
def _spec() -> dict:
    spec = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    spec = copy.deepcopy(spec)
    schema = spec["components"]["parameters"]["ModelVersion"]["schema"]
    schema["enum"] = list(models.MODELS)                          # danh sách lấy từ registry, không gõ tay
    return spec


app = FastAPI(title="Home/Office Inference API", docs_url="/docs", redoc_url=None)
if not os.environ.get("API_KEYS", "").strip():
    logging.getLogger("uvicorn.error").warning("API_KEYS chưa đặt: KHÔNG kiểm tra API key (chỉ dùng khi chạy ở máy)")
app.openapi = _spec


# ---------------------------------------------------------------- lỗi: mọi lỗi trả schema Error
@app.exception_handler(APIError)
async def _api_error(_, e: APIError):
    return _error(e.status, e.code, e.message, e.details,
                  {"WWW-Authenticate": "ApiKey"} if e.status == 401 else None)


@app.exception_handler(infer.InferError)
async def _infer_error(_, e: infer.InferError):
    return _error(getattr(e, "status", STATUS.get(e.code, 400)), e.code, str(e))


@app.exception_handler(models.UnknownModelVersion)
async def _unknown_model(_, e: models.UnknownModelVersion):
    return _error(422, e.code, str(e), {"available": list(models.MODELS)})


@app.exception_handler(RequestValidationError)
async def _validation(_, e: RequestValidationError):
    errs = [{"loc": list(x.get("loc", ())), "msg": x.get("msg")} for x in e.errors()]
    return _error(422, "validation_error", "tham số không hợp lệ", {"errors": errs})


@app.exception_handler(StarletteHTTPException)
async def _http(_, e: StarletteHTTPException):
    return _error(e.status_code, "not_found" if e.status_code == 404 else "http_error", str(e.detail))


@app.exception_handler(Exception)
async def _internal(_, e: Exception):                            # không trả chi tiết (có thể chứa dữ liệu)
    return _error(500, "internal_error", "lỗi máy chủ")


# ---------------------------------------------------------------- phụ thuộc chung
def require_key(request: Request) -> None:
    keys = [k.strip() for k in os.environ.get("API_KEYS", "").split(",") if k.strip()]
    if not keys:                                                 # chạy ở máy: không đặt API_KEYS thì bỏ kiểm tra
        return
    got = request.headers.get("X-API-Key", "")
    if not got or not any(hmac.compare_digest(got, k) for k in keys):
        raise APIError(401, "unauthorized", "thiếu hoặc sai API key (header X-API-Key)")


def model_version(model_version: str | None = Query(None)) -> models.Model:
    return models.get_model(model_version)                       # sai tên -> UnknownModelVersion -> 422


@lru_cache(maxsize=1)
def get_store() -> GeolifeStore:
    return GeolifeStore(STORE_PATH)


def _store_for(m: models.Model) -> GeolifeStore:
    try:
        store = get_store()
    except FileNotFoundError as e:
        raise APIError(503, "store_unavailable", str(e)) from None
    if m.version not in store.versions():
        raise APIError(503, "store_unavailable", f"store chưa có kết quả cho {m.version}; chạy lại build_store.py")
    return store


def _with_version(body: dict, m: models.Model) -> JSONResponse:
    return JSONResponse(body, headers={"X-Model-Version": m.version})


UserId = PathParam(..., pattern=r"^[0-9]{3}$", description="Mã user GeoLife, ba chữ số")


# ---------------------------------------------------------------- meta
@app.get("/health")
def health():
    return {"status": "ok", "default_model_version": models.DEFAULT_MODEL}


@app.get("/v1/models", dependencies=[Depends(require_key)])
def list_models():
    return models.describe(os.environ.get("GIT_COMMIT") or None)


# ---------------------------------------------------------------- inference
async def _read_body(request: Request) -> bytes:
    """Đọc body trong bộ nhớ, dừng ngay khi vượt 50 MB."""
    n = request.headers.get("content-length")
    if n and n.isdigit() and int(n) > uploads.MAX_BYTES:
        raise APIError(413, "payload_too_large", "tối đa 50 MB", {"max_bytes": uploads.MAX_BYTES, "received": int(n)})
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > uploads.MAX_BYTES:
            raise APIError(413, "payload_too_large", "tối đa 50 MB", {"max_bytes": uploads.MAX_BYTES})
    return bytes(buf)


async def _form(request: Request, body: bytes):
    async def stream():
        yield body
        yield b""
    parser = MultiPartParser(request.headers, stream(), max_files=1, max_part_size=1024 * 1024)
    parser.spool_max_size = uploads.MAX_BYTES + 1                # giữ file trong bộ nhớ, không ghi ra đĩa
    try:
        return await parser.parse()
    except Exception as e:                                       # multipart hỏng
        raise APIError(400, "bad_file", f"multipart không hợp lệ: {e}") from None


@app.post("/v1/infer", dependencies=[Depends(require_key)])
async def run_infer(request: Request, m: models.Model = Depends(model_version)):
    ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if ctype not in ("application/json", "multipart/form-data"):
        raise APIError(415, "unsupported_format", "Content-Type phải là application/json hoặc multipart/form-data")
    body = await _read_body(request)
    if ctype == "application/json":
        points = await run_in_threadpool(uploads.points_from_json, body)
    else:
        form = await _form(request, body)
        f = form.get("file")
        if f is None or isinstance(f, str):
            raise APIError(422, "validation_error", "thiếu trường file trong multipart")
        data = await f.read()
        fmt = form.get("format")
        points = await run_in_threadpool(uploads.points_from_file, data, f.filename,
                                         fmt if isinstance(fmt, str) and fmt else None)
    result = await run_in_threadpool(infer.infer, points, m.version)
    return _with_version(result, m)


# ---------------------------------------------------------------- GeoLife (tính sẵn)
@app.get("/v1/geolife/users", dependencies=[Depends(require_key)])
def geolife_users(m: models.Model = Depends(model_version),
                  limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                  has_home: bool | None = None, has_office: bool | None = None):
    total, items = _store_for(m).list_users(m.version, limit, offset, has_home, has_office)
    return _with_version({"model_version": m.version, "total": total, "items": items}, m)


def _not_found(user_id: str):
    raise APIError(404, "user_not_found", f"không có user GeoLife {user_id} (user bản sao đã loại cũng không có)")


@app.get("/v1/geolife/users/{user_id}/locations", dependencies=[Depends(require_key)])
def geolife_locations(user_id: str = UserId, m: models.Model = Depends(model_version)):
    r = _store_for(m).locations(m.version, user_id)
    return _with_version(r, m) if r is not None else _not_found(user_id)


@app.get("/v1/geolife/users/{user_id}/places", dependencies=[Depends(require_key)])
def geolife_places(user_id: str = UserId, m: models.Model = Depends(model_version),
                   limit: int = Query(20, ge=1, le=100)):
    r = _store_for(m).places(m.version, user_id, limit)
    return _with_version(r, m) if r is not None else _not_found(user_id)
