"""Phiên bản v1 (heuristic): gom stay point thành địa điểm quanh điểm neo.

Thuật toán (gom tham lam, bán kính cố định):
    1. Sắp các stay của user theo thời lượng giảm dần.
    2. Lấy stay dài nhất chưa được gán làm điểm neo (tâm) của một địa điểm mới.
    3. Gán vào địa điểm đó mọi stay chưa gán cách tâm <= RADIUS_M.
    4. Lặp lại tới khi mọi stay đều có địa điểm.

Bắt đầu từ stay dài nhất để tâm nằm ở nơi ở lâu, ổn định nhất (thường là nhà, nơi làm việc).
Tâm cố định là vị trí stay neo; vị trí trung bình (theo thời lượng) cũng được ghi để tham khảo.
Mọi stay đều có địa điểm, kể cả nơi chỉ đến một lần (khác v2 dùng DBSCAN, nơi đó là noise).

Chạy:
    python src/places/cluster_v1.py                    # mọi user trong data/processed/stays
    python src/places/cluster_v1.py --users 000 163
Đầu ra (thư mục data/processed/places_v1/):
    <user>_places.parquet   một dòng mỗi địa điểm; place_id 0 là nơi có tổng thời gian lớn nhất (xem PLACE_COLS)
    <user>_stays.parquet    bảng stay của user kèm cột place_id
    reports/place_stats_v1.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

SRC = Path(__file__).resolve().parents[1]                 # thư mục src
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
from geo import haversine_m                              # noqa: E402
from places import common                                # noqa: E402
from places.common import PLACE_COLS                     # noqa: E402,F401 (PLACE_COLS: các module khác import từ đây)

VERSION = "v1"
RADIUS_M = 200.0           # bán kính địa điểm quanh stay neo (A15); bằng bán kính stay (A14)
PLACES_DIR = common.places_dir(VERSION)


def cluster_v1(lat, lon, duration, radius_m: float = RADIUS_M) -> np.ndarray:
    """Gán nhãn cụm (0, 1, ...) cho từng stay, theo thứ tự stay neo dài nhất trước.

    places_for_user đánh số lại theo tổng thời gian của địa điểm.
    """
    n = len(lat)
    pid = np.full(n, -1, dtype=np.int64)
    k = 0
    for a in np.argsort(-np.asarray(duration, float), kind="stable"):
        if pid[a] != -1:
            continue
        free = np.nonzero(pid == -1)[0]                       # gồm cả chính stay a
        d = haversine_m(lat[a], lon[a], lat[free], lon[free])
        pid[free[d <= radius_m]] = k
        k += 1
    return pid


def places_for_user(stays, user: str, radius_m: float = RADIUS_M):
    """Trả về (bảng địa điểm, bảng stay kèm place_id)."""
    return common.build_places(stays, user, lambda lat, lon, dur: cluster_v1(lat, lon, dur, radius_m))


def main() -> None:
    common.cli(VERSION, "Bước 6 (v1): gom stay point thành địa điểm quanh điểm neo.", places_for_user,
               {"--radius-m": (float, RADIUS_M, "bán kính địa điểm (mét)")})


if __name__ == "__main__":
    main()
