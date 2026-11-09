"""Phiên bản v2 (clustering): gom stay point thành địa điểm bằng DBSCAN (mặc định min_samples = 1).

Khác v1 (cluster_v1.py): không có điểm neo hay hình tròn quanh tâm. Hai stay cùng một địa điểm nếu nối được với nhau
qua một chuỗi stay mà mỗi cặp liền kề cách nhau <= EPS_M. Địa điểm có thể dài hơn EPS_M.

Thuật toán (loang dần):
    1. Lấy một stay "lõi" chưa gán (có ít nhất min_samples stay, gồm chính nó, trong bán kính EPS_M), mở địa điểm mới.
    2. Thêm mọi stay chưa gán cách nó <= EPS_M; với mỗi stay vừa thêm mà cũng là lõi, lại thêm các stay chưa gán cách nó <= EPS_M.
    3. Hết stay để thêm thì đóng địa điểm, quay lại bước 1. Stay không vào cụm nào là nhiễu (-1).

Với min_samples = 1 mọi stay đều là lõi nên không có nhiễu. Đây đúng là DBSCAN(eps = EPS_M, min_samples): kết quả không phụ thuộc
thứ tự duyệt (trừ điểm biên khi min_samples > 1) (xem `sklearn.cluster.DBSCAN(eps=EPS_M / 6371008.8, min_samples=..., metric="haversine")`). Viết bằng numpy
để không thêm thư viện (scikit-learn không có trong requirements.txt), cùng cách tính khoảng cách với v1 (haversine).
Mặc định min_samples = 1 (D20): không đếm số stay hay số giờ tối thiểu, vì stay đã >= T = 30 phút (A14) và ngưỡng vote ở
bước 7 (A11) lo phần còn lại. `min_samples` > 1 (đếm số lần ghé, gồm chính stay đó, như scikit-learn) chỉ để kiểm
(notebooks/tuning/14_place_eps.ipynb): stay không thuộc cụm nào là nhiễu, `place_id` = -1, không thành địa điểm và
`home_office_conf.infer_user` bỏ qua khi bỏ phiếu.

Bước 5 (stay point) và bước 7 (home / office) giữ nguyên; chỉ bước 6 đổi. `place_id` đánh theo tổng thời gian,
0 là nơi ở lâu nhất; `lat`, `lon` vẫn là stay dài nhất của địa điểm (như v1, để cùng khuôn đầu ra).

Chạy:
    python src/places/cluster_v2.py                    # mọi user trong data/processed/stays
    python src/places/cluster_v2.py --users 000 163 --eps-m 150
Đầu ra (thư mục data/processed/places_v2/):
    <user>_places.parquet   một dòng mỗi địa điểm (PLACE_COLS; thêm diam_m: đường kính, hai stay xa nhau nhất)
    <user>_stays.parquet    bảng stay của user kèm cột place_id
    reports/place_stats_v2.csv
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
from places.common import PLACE_COLS_DIAM as PLACE_COLS  # noqa: E402,F401

VERSION = "v2"
MIN_SAMPLES = 1            # D20: mỗi stay đã >= T (A14); > 1 chỉ để kiểm ở notebook 14
EPS_M = 200.0              # D20 / A16: khoảng cách tối đa giữa hai stay liền kề trong một địa điểm
PLACES_DIR = common.places_dir(VERSION)


def cluster_v2(lat, lon, eps_m: float = EPS_M, min_samples: int = MIN_SAMPLES) -> np.ndarray:
    """Nhãn cụm (0, 1, ...) cho từng stay; -1 là nhiễu (chỉ xảy ra khi min_samples > 1).

    Bộ nhớ O(n), thời gian O(n^2) (mỗi stay quét các stay còn lại một lần; min_samples > 1 thêm một lượt đếm lõi).
    """
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    n = len(lat)
    if min_samples <= 1:
        core = np.ones(n, dtype=bool)
    else:
        core = np.array([(haversine_m(lat[i], lon[i], lat, lon) <= eps_m).sum() >= min_samples for i in range(n)])
    pid = np.full(n, -1, dtype=np.int64)
    k = 0
    for start in np.nonzero(core)[0]:
        if pid[start] != -1:
            continue
        pid[start] = k
        frontier = [start]
        while frontier:
            i = frontier.pop()
            free = np.nonzero(pid == -1)[0]
            if free.size == 0:
                break
            near = free[haversine_m(lat[i], lon[i], lat[free], lon[free]) <= eps_m]
            pid[near] = k
            frontier.extend(near[core[near]].tolist())     # chỉ lõi mới loang tiếp; điểm biên dừng ở đây
        k += 1
    return pid


def places_for_user(stays, user: str, eps_m: float = EPS_M, min_samples: int = MIN_SAMPLES):
    """Trả về (bảng địa điểm, bảng stay kèm place_id). Stay nhiễu (min_samples > 1) có place_id = -1 và không vào bảng địa điểm."""
    return common.build_places(stays, user, lambda lat, lon, dur: cluster_v2(lat, lon, eps_m, min_samples), with_diam=True)


def main() -> None:
    common.cli(VERSION, "Bước 6 (v2): gom stay point thành địa điểm bằng DBSCAN (mặc định min_samples = 1).", places_for_user,
               {"--eps-m": (float, EPS_M, "khoảng cách tối đa giữa hai stay liền kề (mét)"),
                "--min-samples": (int, MIN_SAMPLES, "mặc định 1 (D20); > 1 chỉ để kiểm")}, with_diam=True)


if __name__ == "__main__":
    main()
