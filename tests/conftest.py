"""Dữ liệu giả lập dùng chung cho các test. Chạy: pytest tests/ (từ thư mục Home_Office)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

HOME = (39.9900, 116.3000)
OFFICE = (39.9800, 116.3500)         # cách nhà khoảng 4,3 km
TZ_OFFSET_H = 8                      # Asia/Shanghai


def _segment(rng, t0, t1, step_s, a, b=None, jitter=0.0001):
    """Điểm GPS từ t0 đến t1 (giây, UTC), cách nhau step_s. Đứng yên ở a, hoặc đi thẳng từ a sang b."""
    t = np.arange(t0, t1, step_s, dtype=float)
    f = (t - t0) / max(t1 - t0, 1) if b is not None else np.zeros(len(t))
    lat = a[0] + (0 if b is None else (b[0] - a[0])) * f + rng.normal(0, jitter, len(t))
    lon = a[1] + (0 if b is None else (b[1] - a[1])) * f + rng.normal(0, jitter, len(t))
    return pd.DataFrame({"lat": lat, "lon": lon, "ts": t})


def make_points(days: int = 28, start="2024-03-04", seed: int = 1, wfh: bool = False) -> pd.DataFrame:
    """Chuỗi GPS giả lập: nhà (tối, sáng), cơ quan (T2–T6 9–12h, 13–17h30), máy tắt qua đêm. Giờ địa phương UTC+8.

    Cột: lat, lon, timestamp (chuỗi ISO có 'Z').
    """
    rng = np.random.default_rng(seed)
    d0 = (pd.Timestamp(start, tz="UTC") - pd.Timedelta(hours=TZ_OFFSET_H)).timestamp()    # 0h địa phương của ngày đầu
    parts = []
    for d in range(days):
        base = d0 + d * 86400
        h = lambda x: base + x * 3600
        weekday = (pd.Timestamp(start).weekday() + d) % 7 < 5
        if weekday and not wfh:
            parts += [_segment(rng, h(6.5), h(8.0), 30, HOME), _segment(rng, h(8.0), h(8.75), 30, HOME, OFFICE),
                      _segment(rng, h(9.0), h(12.0), 60, OFFICE), _segment(rng, h(13.0), h(17.5), 60, OFFICE),
                      _segment(rng, h(17.5), h(18.25), 30, OFFICE, HOME), _segment(rng, h(18.5), h(23.0), 30, HOME)]
        else:
            parts.append(_segment(rng, h(8.0), h(22.0), 60, HOME))
    d = pd.concat(parts, ignore_index=True)
    d["timestamp"] = pd.to_datetime(d.pop("ts"), unit="s", utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return d


@pytest.fixture(scope="session")
def points():
    return make_points()


@pytest.fixture(scope="session")
def home():
    return HOME


@pytest.fixture(scope="session")
def office():
    return OFFICE
