"""Suy ra home / office từ một chuỗi điểm GPS trong bộ nhớ (không đọc, không ghi file). Lõi của POST /v1/infer.

    result = infer(points, model_version="dbscan-v2")

`points`: DataFrame có cột lat, lon, timestamp. timestamp là datetime có múi giờ, hoặc chuỗi ISO 8601 có `Z` / offset,
hoặc số giây Unix (UTC). Giờ không có múi giờ bị từ chối, vì không biết là giờ nào.

Cùng pipeline với GeoLife: lọc (clean_trajectory.filter_track, không giới hạn khoảng thời gian 2007–2012 của GeoLife) ->
stay point (stays.detect.stays_for_user) -> gom địa điểm (version model) -> bỏ phiếu + confidence (home_office_conf.infer_user).
Trả về dict theo schema `InferenceResult` của api/openapi.yaml (toạ độ làm tròn 4 chữ số, khoảng 11 m).
Lỗi đầu vào: InferError có thuộc tính `code` (khớp mã lỗi trong spec).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SRC = Path(__file__).resolve().parent                    # thư mục src
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
import models                                          # noqa: E402
from places import home_office_conf as hoc             # noqa: E402
from preprocess.clean_trajectory import filter_track   # noqa: E402
from stays.detect import stays_for_user                # noqa: E402

MAX_POINTS = 1_000_000
TIME_MIN = pd.Timestamp("2000-01-01", tz="UTC")       # chặn timestamp rác; không dùng khoảng 2007–2012 của GeoLife
TIME_MAX = pd.Timestamp("2100-01-01", tz="UTC")
MAX_PLACES = 20
COORD_DECIMALS = 4
_HAS_OFFSET = re.compile(r"(?:Z|[+-]\d{2}:?\d{2})$")


class InferError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _parse_time(ts: pd.Series) -> pd.Series:
    """Về datetime UTC. Từ chối chuỗi / datetime không có múi giờ."""
    if pd.api.types.is_numeric_dtype(ts):
        return pd.to_datetime(ts, unit="s", utc=True, errors="coerce")
    if isinstance(ts.dtype, pd.DatetimeTZDtype):
        return ts.dt.tz_convert("UTC")
    if pd.api.types.is_datetime64_any_dtype(ts):
        raise InferError("bad_timestamp", "timestamp không có múi giờ; cần 'Z' hoặc offset (ví dụ 2008-10-23T02:53:04Z)")
    s = ts.astype(str).str.strip()
    if not s.str.contains(_HAS_OFFSET).all():
        raise InferError("bad_timestamp", "có timestamp không kèm 'Z' hoặc offset (ví dụ 2008-10-23T02:53:04Z)")
    return pd.to_datetime(s, utc=True, errors="coerce")


def _points(points: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in ("lat", "lon", "timestamp") if c not in points.columns]
    if missing:
        raise InferError("missing_column", f"thiếu cột: {', '.join(missing)}")
    if len(points) > MAX_POINTS:
        raise InferError("payload_too_large", f"tối đa {MAX_POINTS:,} điểm, nhận {len(points):,}")
    d = pd.DataFrame({"lat": pd.to_numeric(points["lat"], errors="coerce"),
                      "lon": pd.to_numeric(points["lon"], errors="coerce"),
                      "timestamp": _parse_time(points["timestamp"])})
    return d.sort_values("timestamp", kind="stable").reset_index(drop=True)


def _num(x):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else float(x)


def _xy(places: pd.DataFrame, pid) -> tuple[float, float]:
    r = places.loc[places["place_id"] == pid].iloc[0]
    return round(float(r["lat"]), COORD_DECIMALS), round(float(r["lon"]), COORD_DECIMALS)


def _location(places: pd.DataFrame, res: dict, kind: str):
    """Home hoặc office theo schema `Location`; None nếu chưa xác định."""
    pid = res.get(kind)
    if pid is None or (isinstance(pid, float) and np.isnan(pid)):
        return None
    pid = int(pid)
    p = "h" if kind == "home" else "o"
    lat, lon = _xy(places, pid)
    return {"place_id": pid, "lat": lat, "lon": lon, "confidence": _num(res.get(f"conf_{kind}")),
            "n_votes": int(res["n_night_votes" if kind == "home" else "n_work_votes"]),
            "components": {"share": float(res[f"{p}_share"]), "margin": float(res[f"{p}_margin"]),
                           "stable": float(res[f"{p}_stable"]), "gps_share": float(res[f"{p}_gps"])}}


def _place_rows(places: pd.DataFrame, home, office) -> list[dict]:
    out = []
    for r in places.head(MAX_PLACES).itertuples():
        pid = int(r.place_id)
        lat, lon = _xy(places, pid)
        out.append({"place_id": pid, "lat": lat, "lon": lon, "total_hours": round(float(r.total_hours), 2),
                    "n_stays": int(r.n_stays),
                    "gps_share": round(1.0 - float(r.gap_hours) / float(r.total_hours), 3) if r.total_hours > 0 else 0.0,
                    "role": "home" if pid == home else "office" if pid == office else "other"})
    return out


def _iso(ts: pd.Timestamp) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def infer(points: pd.DataFrame, model_version: str | None = None, user: str = "upload") -> dict:
    """Home / office từ một chuỗi điểm GPS. Xem docstring đầu file."""
    model = models.get_model(model_version)
    raw = _points(points)
    clean, _ = filter_track(raw, time_min=TIME_MIN, time_max=TIME_MAX)
    if len(clean) < 2:
        raise InferError("too_few_points", f"sau khi làm sạch chỉ còn {len(clean)} điểm (nhận {len(raw)})")

    stays = stays_for_user(clean, user)
    summary = {"n_points": int(len(raw)), "n_points_clean": int(len(clean)), "n_stays": int(len(stays)),
               "first_time": _iso(clean["timestamp"].min()), "last_time": _iso(clean["timestamp"].max()),
               "n_days": int(clean["local_time"].dt.normalize().nunique()),
               "timezones": sorted(clean["tz_name"].astype(str).unique())}
    base = {"model_version": model.version, "input": summary}
    if stays.empty:
        return base | {"home": None, "office": None, "flags": ["no_stays"], "places": []}

    places, s = model.places_for_user(stays, user)
    res = hoc.infer_user(s)
    flags = [f for f in str(res.get("flags") or "").split(";") if f]
    if len(summary["timezones"]) > 1:
        flags.append("multi_timezone")
    home, office = _location(places, res, "home"), _location(places, res, "office")
    return base | {"home": home, "office": office, "flags": flags,
                   "places": _place_rows(places, home and home["place_id"], office and office["place_id"])}
