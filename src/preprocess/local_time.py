"""Đổi timestamp UTC sang giờ địa phương.

Cách mới (notes/decisions.md D10): tra tên múi giờ IANA từ tọa độ bằng `timezonefinder`, rồi đổi giờ bằng
`zoneinfo` (có tính giờ mùa hè theo đúng ngày). Tra theo ô lưới CELL_DEG và lưu cache, vì tra từng điểm
quá chậm với hàng chục triệu điểm.

Cách cũ (hình chữ nhật Trung Quốc UTC+8, ngoài đó round(lon / 15)) vẫn giữ nguyên: CN_BOX, in_box, local_offset_h.
Chúng được dùng cho thống kê EDA (src/eda/scan.py) và để so sánh với cách mới (check_timezone.py).

Cột thêm vào bảng điểm:
    tz_name        tên múi giờ IANA của ô lưới chứa điểm (ví dụ Asia/Shanghai)
    tz_offset_h    số giờ lệch so với UTC tại thời điểm của điểm (số thực: có múi giờ lệch 5,5 giờ)
    local_time     giờ địa phương, không gắn timezone (mỗi điểm một offset)
Cột timestamp (UTC) giữ nguyên; mọi phép tính khoảng thời gian vẫn dùng timestamp.

Cần cài: pip install timezonefinder tzdata   (Windows không có sẵn cơ sở dữ liệu múi giờ, cần tzdata)
"""
from __future__ import annotations

from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

# ---- Cách cũ: giữ nguyên để EDA và so sánh
# Vùng Trung Quốc xấp xỉ bằng hình chữ nhật: lat_min, lat_max, lon_min, lon_max.
# Thô: lẫn một phần nước láng giềng (Mông Cổ, Triều Tiên...). Điểm ở đó vẫn được gán UTC+8.
CN_BOX = (18.0, 54.0, 73.0, 135.0)
CN_OFFSET_H = 8


def in_box(lat, lon, box):
    return (lat >= box[0]) & (lat <= box[1]) & (lon >= box[2]) & (lon <= box[3])


def local_offset_h(lat, lon) -> np.ndarray:
    """(Cách cũ) Số giờ lệch so với UTC cho từng điểm: UTC+8 trong CN_BOX, ngoài đó round(lon / 15)."""
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    return np.where(in_box(lat, lon, CN_BOX), CN_OFFSET_H, np.round(lon / 15)).astype(int)


# ---- Cách mới: timezonefinder + zoneinfo
CELL_DEG = 0.5            # cạnh ô lưới (độ) khi tra múi giờ; nhỏ hơn thì chính xác hơn ở ranh giới nhưng tra nhiều hơn
_KEY_OFFSET = 100_000     # dời chỉ số ô thành số dương
_KEY_MULT = 1_000_000     # ghép chỉ số ô vĩ độ và kinh độ thành một khoá số nguyên

_finder_obj = None                              # TimezoneFinder, tạo khi cần dùng lần đầu (nạp dữ liệu khá lâu)
_cell_tz: dict[tuple[float, int], str] = {}     # (cell_deg, khoá ô) -> tên múi giờ; dùng lại giữa các lần gọi


def _finder():
    global _finder_obj
    if _finder_obj is None:
        try:
            from timezonefinder import TimezoneFinder
        except ImportError as e:
            raise ImportError("Thiếu thư viện timezonefinder. Cài: pip install timezonefinder tzdata") from e
        _finder_obj = TimezoneFinder()
    return _finder_obj


def _fallback_name(lon: float) -> str:
    """Điểm không tra được múi giờ (ví dụ giữa biển): xấp xỉ theo kinh độ, như cách cũ.

    Lưu ý dấu của tên IANA: Etc/GMT-8 nghĩa là UTC+8.
    """
    off = int(max(-12, min(12, np.round(lon / 15))))
    return "Etc/GMT" if off == 0 else f"Etc/GMT{-off:+d}"


def timezone_names(lat, lon, cell_deg: float = CELL_DEG) -> np.ndarray:
    """Tên múi giờ IANA cho từng điểm, tra theo ô lưới cell_deg x cell_deg.

    Mỗi ô được tra một lần, tại TÂM của ô (không phụ thuộc thứ tự điểm, nên kết quả lặp lại được),
    rồi lưu cache. Điểm nằm sát ranh giới hai múi giờ có thể bị gán theo múi giờ của tâm ô.
    """
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    ci = np.floor(lat / cell_deg).astype(np.int64)
    cj = np.floor(lon / cell_deg).astype(np.int64)
    key = (ci + _KEY_OFFSET) * _KEY_MULT + (cj + _KEY_OFFSET)
    uniq, inv = np.unique(key, return_inverse=True)
    names = np.empty(len(uniq), dtype=object)
    for u, k in enumerate(uniq):
        ck = (float(cell_deg), int(k))
        name = _cell_tz.get(ck)
        if name is None:
            lat_c = (int(k) // _KEY_MULT - _KEY_OFFSET + 0.5) * cell_deg
            lon_c = (int(k) % _KEY_MULT - _KEY_OFFSET + 0.5) * cell_deg
            name = _finder().timezone_at(lat=lat_c, lng=lon_c) or _fallback_name(lon_c)
            _cell_tz[ck] = name
        names[u] = name
    return names[np.asarray(inv).reshape(-1)]


def add_local_time(df: pd.DataFrame, cell_deg: float = CELL_DEG) -> pd.DataFrame:
    """Thêm cột tz_name, tz_offset_h và local_time (xem docstring đầu file).

    Đổi từ UTC sang giờ địa phương luôn xác định (không mơ hồ), kể cả lúc chuyển giờ mùa hè.
    """
    out = df.copy()
    if out.empty:
        out["tz_name"] = pd.Series(dtype="category")
        out["tz_offset_h"] = pd.Series(dtype=float)
        out["local_time"] = pd.Series(dtype="datetime64[ns]")
        return out

    names = timezone_names(out["lat"].to_numpy(), out["lon"].to_numpy(), cell_deg)
    ts = out["timestamp"]
    utc_ns = ts.dt.tz_convert(None).to_numpy(dtype="datetime64[ns]")
    local_ns = utc_ns.copy()
    off_h = np.zeros(len(out), dtype=float)
    for name in np.unique(names):                       # mỗi múi giờ đổi một lần cho cả nhóm điểm
        m = names == name
        loc = ts[m].dt.tz_convert(ZoneInfo(name)).dt.tz_localize(None).to_numpy(dtype="datetime64[ns]")
        local_ns[m] = loc
        off_h[m] = (loc - utc_ns[m]) / np.timedelta64(1, "h")

    out["tz_name"] = pd.Categorical(names)
    out["tz_offset_h"] = off_h
    out["local_time"] = pd.Series(local_ns, index=out.index)
    return out


def add_local_time_box(df: pd.DataFrame) -> pd.DataFrame:
    """(Cách cũ) Thêm tz_offset_h (nguyên) và local_time theo local_offset_h. Chỉ để so sánh với cách mới."""
    out = df.copy()
    off = local_offset_h(out["lat"].to_numpy(), out["lon"].to_numpy())
    out["tz_offset_h"] = off
    out["local_time"] = out["timestamp"].dt.tz_convert(None) + pd.to_timedelta(off, unit="h")
    return out
