"""Server nhỏ cho giao diện mock app đặt xe (chỉ dùng thư viện chuẩn của Python).

Vai trò giống "backend của app đặt xe" trong spec: trình duyệt gọi server này, server gọi
Home/Office API (giữa hai hệ thống) rồi trả kết quả về. Nhờ vậy:
  - không vướng CORS (trang và /api cùng một địa chỉ),
  - token đăng nhập (Cognito) nằm ở server, không lộ ra trình duyệt.

Chạy (PowerShell, từ thư mục Home_Office):
    python demo_ui\\serve.py
    # mở http://localhost:8080

Biến môi trường (tuỳ chọn):
    API_URL   địa chỉ Home/Office API; không đặt thì đọc api\api_url.txt (terraform output), cuối cùng http://localhost:8000
    API_KEY   gửi kèm header X-API-Key nếu API bật kiểm tra key (không ghi key vào file)
    PORT      cổng của server này, mặc định 8080
    Đăng nhập OAuth 2.0 (API bật auth_enabled): Authorization Code + PKCE qua trang đăng nhập của Cognito (Hosted UI).
      1. /auth/login chuyển trình duyệt sang <domain>/oauth2/authorize (kèm state chống giả mạo và code_challenge PKCE);
      2. người dùng nhập email + mật khẩu trên trang của Cognito (app không bao giờ thấy mật khẩu);
      3. Cognito chuyển về /auth/callback?code=...; server đổi code (+ code_verifier) lấy token ở <domain>/oauth2/token;
      4. server giữ token trong bộ nhớ theo phiên (cookie HttpOnly `sid`), gửi ID token kèm mỗi lời gọi API,
         tự làm mới bằng refresh token khi gần hết hạn. Trình duyệt không thấy token. Tắt server là mất phiên.
    Tài khoản thường chỉ xem được user GeoLife của mình (custom:geolife_id); nhóm admin đổi được sang mọi user.
    COGNITO_CLIENT_ID   app client id; bỏ trống thì đọc api\\cognito_client_id.txt
    COGNITO_DOMAIN      https://<prefix>.auth.<vùng>.amazoncognito.com; bỏ trống thì đọc api\\cognito_domain.txt
                        (thiếu một trong hai: không cần đăng nhập, như khi API tắt auth_enabled)
    APP_URL             địa chỉ app mà Cognito chuyển về, mặc định http://localhost:<PORT> (phải có trong callback_urls)

Đường dẫn:
    GET /                                   -> index.html
    GET /api/users/{id}/home-office         -> gọi API theo spec 0.3.0: /v1/users/{id}/home-office;
                                               nếu API còn là bản cũ (chưa có route đó) thì gọi
                                               /v1/geolife/users/{id}/locations (cùng dạng dữ liệu)
    GET /api/users                          -> danh sách user (nếu API còn /v1/geolife/users), để chọn nhanh
    GET /api/health                         -> /health của API
    GET /api/me                             -> tài khoản đang đăng nhập {auth, email, geolife_id, admin}; 401 nếu cần đăng nhập
    GET /auth/login                         -> chuyển sang trang đăng nhập Cognito
    GET /auth/callback?code=&state=         -> đổi code lấy token, đặt cookie phiên, về trang chủ
    GET /auth/logout                        -> chuyển sang <domain>/logout (xoá cả phiên đăng nhập ở Cognito)
    POST /api/logout                        -> xoá phiên của server demo
    GET /api/geocode/reverse?lat=&lon=      -> tên địa chỉ thật của một tọa độ (OpenStreetMap Nominatim)
    GET /api/geocode/search?q=              -> tìm địa chỉ theo tên (Nominatim), tối đa 6 kết quả
Nominatim miễn phí, không cần key, nhưng giới hạn 1 lời gọi/giây: server tự giãn cách và lưu cache.
Khi không kết nối được API: trả 502 {code: api_unavailable}; giao diện tự chuyển sang dữ liệu mẫu.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
_URL_FILE = HERE.parent / "api" / "api_url.txt"   # do terraform output ghi ra; giống test.ps1, canary_check.ps1
API_URL = (os.environ.get("API_URL") or
           (_URL_FILE.read_text(encoding="ascii").strip() if _URL_FILE.exists() else "") or
           "http://localhost:8000").strip().rstrip("/")
API_KEY = os.environ.get("API_KEY", "").strip()
PORT = int(os.environ.get("PORT", "8080"))
_CID_FILE = HERE.parent / "api" / "cognito_client_id.txt"
COGNITO_CLIENT_ID = (os.environ.get("COGNITO_CLIENT_ID") or
                     (_CID_FILE.read_text(encoding="ascii").strip() if _CID_FILE.exists() else "")).strip()
_DOMAIN_FILE = HERE.parent / "api" / "cognito_domain.txt"
COGNITO_DOMAIN = (os.environ.get("COGNITO_DOMAIN") or
                  (_DOMAIN_FILE.read_text(encoding="ascii").strip() if _DOMAIN_FILE.exists() else "")).strip().rstrip("/")
AUTH_ON = bool(COGNITO_CLIENT_ID and COGNITO_DOMAIN)
APP_URL = os.environ.get("APP_URL", f"http://localhost:{PORT}").rstrip("/")
REDIRECT_URI = APP_URL + "/auth/callback"
PENDING: dict[str, tuple[str, float]] = {}   # state -> (code_verifier, thời điểm), sống 10 phút
SESSIONS: dict[str, dict] = {}       # sid -> {id_token, refresh, exp, email, geolife_id, admin}
_SESS_LOCK = threading.Lock()
TIMEOUT_S = 5
USER_RE = re.compile(r"^/api/users/([A-Za-z0-9_-]{1,64})/home-office$")
VERSIONS = {"heuristic-v1", "dbscan-v2"}
GEO_URL = os.environ.get("GEOCODER_URL", "https://nominatim.openstreetmap.org")
GEO_UA = "home-office-demo/0.1 (local student demo)"
_geo_lock, _geo_last, _geo_cache = threading.Lock(), [0.0], {}


def geocode(path: str, params: dict) -> tuple[int, object]:
    """Gọi Nominatim (≤ 1 lời gọi/giây, có cache). Lỗi -> 502 geocoder_unavailable."""
    url = f"{GEO_URL}{path}?" + urllib.parse.urlencode({**params, "format": "jsonv2", "accept-language": "vi,en"})
    if url in _geo_cache:
        return 200, _geo_cache[url]
    with _geo_lock:
        wait = 1.05 - (time.monotonic() - _geo_last[0])
        if wait > 0:
            time.sleep(wait)
        _geo_last[0] = time.monotonic()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": GEO_UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=8) as r:
                body = json.loads(r.read() or b"null")
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            return 502, {"code": "geocoder_unavailable", "message": str(e)}
    _geo_cache[url] = body
    return 200, body


_CJK = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")
try:  # không bắt buộc: pip install pypinyin -> tên tiếng Trung đổi sang pinyin (Hong Bin Lou)
    from pypinyin import lazy_pinyin
except ImportError:
    lazy_pinyin = None


def _latin(x):
    """Giữ nguyên nếu không có chữ Hán; có pypinyin thì đổi sang pinyin; không thì bỏ (trả chuỗi rỗng)."""
    if not x or not _CJK.search(x):
        return x or ""
    if lazy_pinyin is None:
        return ""
    return " ".join(w.capitalize() for w in lazy_pinyin(x) if w.strip())


def _short(addr, display, names=None):
    """Tên ngắn (tên địa điểm hoặc số nhà + đường) và dòng phụ (phường, quận, thành phố), ưu tiên chữ Latin."""
    a = addr or {}
    nd = names or {}
    own = next((nd[k] for k in ("name:vi", "name:en", "name:zh-Latn-pinyin", "name:zh_pinyin") if nd.get(k)), "")
    road = " ".join(x for x in (a.get("house_number"), _latin(a.get("road"))) if x)
    poi = next((a[k] for k in ("amenity", "building", "shop", "office", "tourism", "leisure") if a.get(k)), "")
    name = own or _latin(poi) or road
    area_parts = [_latin(x) for x in (a.get("quarter") or a.get("suburb") or a.get("neighbourhood"),
                                      a.get("city_district") or a.get("district") or a.get("county"),
                                      a.get("city") or a.get("town") or a.get("state"))]
    area_parts = [x for x in area_parts if x]
    if not name and area_parts:         # điểm/đường chỉ có tên chữ Hán: lấy khu vực làm tên
        name, area_parts = area_parts[0], area_parts[1:]
    if not name and not area_parts:     # hoàn toàn không có chữ Latin: đành để tên gốc
        parts = [x.strip() for x in (display or "").split(",")]
        return (parts[0] if parts else ""), ", ".join(parts[1:4])
    return name, ", ".join(area_parts)


class AuthError(Exception):
    pass


def token_request(form: dict) -> dict:
    """POST <domain>/oauth2/token (client không secret, nên chỉ gửi client_id). Trả JSON token."""
    data = urllib.parse.urlencode({**form, "client_id": COGNITO_CLIENT_ID}).encode()
    req = urllib.request.Request(COGNITO_DOMAIN + "/oauth2/token", data=data, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read() or b"{}").get("error", "")
        except ValueError:
            err = ""
        raise AuthError(f"Cognito từ chối đổi token (HTTP {e.code} {err})")
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise AuthError(f"Không kết nối được Cognito: {e}")


def _claims(token: str) -> dict:
    """Đọc phần payload của JWT (token vừa nhận thẳng từ Cognito qua HTTPS; API Gateway mới là nơi kiểm chữ ký)."""
    part = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


def _fill(sess: dict, res: dict) -> dict:
    c = _claims(res["id_token"])
    groups = c.get("cognito:groups") or []
    sess.update(id_token=res["id_token"], exp=time.time() + int(res.get("expires_in", 3600)) - 120,
                email=c.get("email", sess.get("email", "")), geolife_id=c.get("custom:geolife_id"),
                admin="admin" in groups)
    if res.get("refresh_token"):
        sess["refresh"] = res["refresh_token"]
    return sess


def start_login() -> str:
    """Tạo state + PKCE, trả địa chỉ trang đăng nhập Cognito."""
    now = time.time()
    with _SESS_LOCK:
        for k in [k for k, (_, t) in PENDING.items() if now - t > 600]:
            PENDING.pop(k, None)
        state, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(48)
        PENDING[state] = (verifier, now)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    q = urllib.parse.urlencode({"response_type": "code", "client_id": COGNITO_CLIENT_ID, "redirect_uri": REDIRECT_URI,
                                "scope": "openid email profile",  # profile: ID token mới có custom:geolife_id
                                "state": state,
                                "code_challenge": challenge, "code_challenge_method": "S256"})
    return f"{COGNITO_DOMAIN}/oauth2/authorize?{q}"


def finish_login(code: str, state: str) -> tuple[str, dict]:
    """Callback: kiểm state, đổi code lấy token, tạo phiên."""
    with _SESS_LOCK:
        verifier, t = PENDING.pop(state, ("", 0.0))
    if not verifier or time.time() - t > 600:
        raise AuthError("Phiên đăng nhập không hợp lệ hoặc đã quá 10 phút, bấm Đăng nhập lại")
    res = token_request({"grant_type": "authorization_code", "code": code,
                         "redirect_uri": REDIRECT_URI, "code_verifier": verifier})
    sid = secrets.token_urlsafe(24)
    sess = _fill({}, res)
    with _SESS_LOCK:
        SESSIONS[sid] = sess
    return sid, sess


def session_token(sess: dict, force: bool = False) -> str:
    """ID token còn hạn của phiên; gần hết hạn thì làm mới bằng refresh token. Lỗi: trả "" (API sẽ trả 401)."""
    if force or time.time() >= sess["exp"]:
        try:
            _fill(sess, token_request({"grant_type": "refresh_token", "refresh_token": sess.get("refresh", "")}))
        except AuthError as e:
            print(f"[demo_ui] làm mới token lỗi: {e}")
            return ""
    return sess["id_token"]


def public(sess: dict) -> dict:
    return {"auth": True, "email": sess["email"], "geolife_id": sess.get("geolife_id"), "admin": sess["admin"]}


def call_api(path: str, sess: dict | None = None, _retry: bool = True) -> tuple[int, dict, dict]:
    """Gọi API, trả (status, body JSON, header cần thiết). Lỗi kết nối -> 502 api_unavailable."""
    req = urllib.request.Request(API_URL + path, headers={"Accept": "application/json"})
    if API_KEY:
        req.add_header("X-API-Key", API_KEY)
    token = session_token(sess) if sess and path != "/health" else ""
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return r.status, json.loads(r.read() or b"{}"), {"X-Model-Version": r.headers.get("X-Model-Version", "")}
    except urllib.error.HTTPError as e:
        if e.code == 401 and token and _retry:  # token hết hạn sớm: làm mới một lần
            session_token(sess, force=True)
            return call_api(path, sess, _retry=False)
        try:
            body = json.loads(e.read() or b"{}")
        except ValueError:
            body = {"code": "bad_response", "message": f"API trả HTTP {e.code} không phải JSON"}
        return e.code, body, {}
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        return 502, {"code": "api_unavailable", "message": f"không kết nối được {API_URL}: {e}"}, {}


def home_office(user_id: str, version: str | None, sess: dict | None = None) -> tuple[int, dict, dict, str]:
    q = "?" + urllib.parse.urlencode({"model_version": version}) if version else ""
    path = f"/v1/users/{user_id}/home-office{q}"
    status, body, hdr = call_api(path, sess)
    # Route mới chưa có (API bản cũ): 404 nhưng không phải user_not_found -> thử route cũ
    if status == 404 and body.get("code") != "user_not_found":
        path = f"/v1/geolife/users/{user_id}/locations{q}"
        status, body, hdr = call_api(path, sess)
    return status, body, hdr, path


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            if v:
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, obj: dict, extra: dict | None = None):
        self._send(status, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8", extra)

    def _redirect(self, location: str, cookie: str = ""):
        self._send(302, b"", "text/plain", {"Location": location, "Set-Cookie": cookie})

    def _sid(self) -> str:
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "sid":
                return v
        return ""

    def _session(self) -> dict | None:
        with _SESS_LOCK:
            return SESSIONS.get(self._sid())

    def do_POST(self):
        url = urllib.parse.urlsplit(self.path)
        if url.path == "/api/logout":
            with _SESS_LOCK:
                SESSIONS.pop(self._sid(), None)
            return self._json(200, {"ok": True}, {"Set-Cookie": "sid=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"})
        self._json(404, {"code": "not_found", "message": url.path})

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        qs = urllib.parse.parse_qs(url.query)
        if url.path in ("/", "/index.html"):
            return self._send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        if url.path in ("/auth/login", "/auth/callback", "/auth/logout"):
            if not AUTH_ON:
                return self._redirect("/")
            if url.path == "/auth/login":
                return self._redirect(start_login())
            if url.path == "/auth/logout":
                q = urllib.parse.urlencode({"client_id": COGNITO_CLIENT_ID, "logout_uri": APP_URL + "/"})
                return self._redirect(f"{COGNITO_DOMAIN}/logout?{q}")
            if "error" in qs:  # người dùng huỷ, hoặc cấu hình client sai
                msg = (qs.get("error_description") or qs["error"])[0]
                return self._redirect("/?" + urllib.parse.urlencode({"login_error": msg}))
            try:
                sid, sess = finish_login((qs.get("code") or [""])[0], (qs.get("state") or [""])[0])
            except AuthError as e:
                return self._redirect("/?" + urllib.parse.urlencode({"login_error": str(e)}))
            print(f"[demo_ui] đăng nhập: {sess['email']}{' (admin)' if sess['admin'] else ''}")
            return self._redirect("/", f"sid={sid}; HttpOnly; SameSite=Lax; Path=/")
        if url.path == "/api/me":
            if not AUTH_ON:
                return self._json(200, {"auth": False})
            sess = self._session()
            if not sess:
                return self._json(401, {"code": "login_required", "message": "Cần đăng nhập"})
            return self._json(200, public(sess))
        if url.path == "/api/health":
            status, body, _ = call_api("/health")
            return self._json(status, body)
        if url.path == "/api/users":
            status, body, _ = call_api("/v1/geolife/users?limit=200")
            return self._json(status, body)
        if url.path == "/api/geocode/reverse":
            try:
                lat, lon = float(qs["lat"][0]), float(qs["lon"][0])
                assert -90 <= lat <= 90 and -180 <= lon <= 180
            except (KeyError, ValueError, AssertionError):
                return self._json(422, {"code": "validation_error", "message": "cần lat, lon hợp lệ"})
            status, b = geocode("/reverse", {"lat": f"{lat:.5f}", "lon": f"{lon:.5f}", "zoom": 18, "addressdetails": 1, "namedetails": 1})
            if status != 200:
                return self._json(status, b)
            if not b or "error" in b:
                return self._json(404, {"code": "no_address", "message": "không có địa chỉ ở điểm này"})
            name, area = _short(b.get("address"), b.get("display_name", ""), b.get("namedetails"))
            return self._json(200, {"name": name, "area": area, "display_name": b.get("display_name", "")})
        if url.path == "/api/geocode/search":
            q = (qs.get("q") or [""])[0].strip()[:200]
            if not q:
                return self._json(422, {"code": "validation_error", "message": "cần q"})
            params = {"q": q, "limit": 6, "addressdetails": 1, "namedetails": 1}
            for k in ("lat", "lon"):          # ưu tiên kết quả gần điểm đón
                if k in qs:
                    params[k] = qs[k][0]
            if "lat" in params and "lon" in params:
                la, lo = float(params.pop("lat")), float(params.pop("lon"))
                params["viewbox"] = f"{lo-0.5},{la+0.5},{lo+0.5},{la-0.5}"
            status, b = geocode("/search", params)
            if status != 200:
                return self._json(status, b)
            items = []
            for r in b or []:
                name, area = _short(r.get("address"), r.get("display_name", ""), r.get("namedetails"))
                items.append({"name": name or r.get("name"), "area": area, "lat": float(r["lat"]), "lon": float(r["lon"])})
            return self._json(200, {"items": items})
        m = USER_RE.match(url.path)
        if m:
            version = (qs.get("model_version") or [None])[0]
            if version and version not in VERSIONS:
                return self._json(422, {"code": "unknown_model_version", "message": version})
            sess = self._session()
            if AUTH_ON and not sess:
                return self._json(401, {"code": "login_required", "message": "Cần đăng nhập"})
            t0 = time.perf_counter()
            status, body, hdr, path = home_office(m.group(1), version, sess)
            ms = round((time.perf_counter() - t0) * 1000)
            return self._json(status, body, {**hdr, "X-Upstream-Path": path.split("?")[0],
                                             "X-Upstream-Ms": str(ms)})
        self._json(404, {"code": "not_found", "message": url.path})

    def log_message(self, fmt, *args):  # chỉ in đường dẫn và mã trạng thái, không in tọa độ
        print(f"[demo_ui] {self.command} {self.path.split('?')[0]} -> {args[1] if len(args) > 1 else ''}")


if __name__ == "__main__":
    auth = f"OAuth 2.0 qua {COGNITO_DOMAIN}, về {REDIRECT_URI}" if AUTH_ON else "không"
    print(f"Mock app đặt xe: http://localhost:{PORT}  (API: {API_URL}, key: {'có' if API_KEY else 'không'}, đăng nhập: {auth})")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
