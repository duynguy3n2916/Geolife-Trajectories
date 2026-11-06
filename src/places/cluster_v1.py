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

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

SRC = Path(__file__).resolve().parents[1]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
from preprocess import interim                                            # noqa: E402
from preprocess.clean_trajectory import PROJECT_ROOT, haversine_m         # noqa: E402
from stays.detect import STAYS_DIR                                        # noqa: E402

VERSION = "v1"
RADIUS_M = 200.0           # bán kính địa điểm quanh stay neo (A15); bằng bán kính stay (A14)
PLACES_DIR = PROJECT_ROOT / "data" / "processed" / f"places_{VERSION}"
PLACE_COLS = ["user", "place_id", "lat", "lon", "lat_mean", "lon_mean", "n_stays", "n_days",
              "total_hours", "gap_hours", "first_utc", "last_utc", "max_dist_m"]


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


def _days_covered(arrive_local: pd.Series, leave_local: pd.Series) -> set:
    """Các ngày địa phương mà các stay chạm tới (stay qua đêm tính cả hai ngày)."""
    days = set()
    for a, b in zip(arrive_local.dt.normalize(), leave_local.dt.normalize()):
        days.update(pd.date_range(a, b, freq="D").date)
    return days


def places_for_user(stays: pd.DataFrame, user: str, radius_m: float = RADIUS_M):
    """Trả về (bảng địa điểm, bảng stay kèm place_id)."""
    if stays is None or stays.empty:
        return pd.DataFrame(columns=PLACE_COLS), (stays if stays is not None else pd.DataFrame())
    s = stays.reset_index(drop=True).copy()
    lat, lon = s["lat"].to_numpy(float), s["lon"].to_numpy(float)
    s["place_id"] = cluster_v1(lat, lon, s["duration_min"].to_numpy(float), radius_m)

    rows = []
    for p, g in s.groupby("place_id", sort=True):
        anchor = g["duration_min"].idxmax()                   # stay neo = stay dài nhất của địa điểm
        w = g["duration_min"].to_numpy(float) + 1e-9
        rows.append({
            "user": user, "place_id": int(p),
            "lat": float(s.at[anchor, "lat"]), "lon": float(s.at[anchor, "lon"]),
            "lat_mean": float(np.average(g["lat"], weights=w)),
            "lon_mean": float(np.average(g["lon"], weights=w)),
            "n_stays": len(g), "n_days": len(_days_covered(g["arrive_local"], g["leave_local"])),
            "total_hours": float(g["duration_min"].sum() / 60), "gap_hours": float(g["gap_min"].sum() / 60),
            "first_utc": g["arrive_utc"].min(), "last_utc": g["leave_utc"].max(),
            "max_dist_m": float(haversine_m(s.at[anchor, "lat"], s.at[anchor, "lon"],
                                            g["lat"].to_numpy(float), g["lon"].to_numpy(float)).max()),
        })
    places = pd.DataFrame(rows, columns=PLACE_COLS).sort_values("total_hours", ascending=False, ignore_index=True)
    # đánh số lại: place_id 0 là địa điểm có tổng thời gian lớn nhất
    remap = dict(zip(places["place_id"], range(len(places))))
    places["place_id"] = np.arange(len(places))
    s["place_id"] = s["place_id"].map(remap)
    return places, s


def load_places(user: str, places_dir: Path = PLACES_DIR):
    """(bảng địa điểm, bảng stay kèm place_id) của một user."""
    return interim.read_df(Path(places_dir) / f"{user}_places"), interim.read_df(Path(places_dir) / f"{user}_stays")


def _from_project(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def main() -> None:
    ap = argparse.ArgumentParser(description="Bước 6 (v1): gom stay point thành địa điểm quanh điểm neo.")
    ap.add_argument("--users", nargs="*", help="chỉ chạy các user này")
    ap.add_argument("--stays-dir", type=Path, default=STAYS_DIR)
    ap.add_argument("--out-dir", type=Path, default=PLACES_DIR)
    ap.add_argument("--stats", type=Path, default=Path(f"reports/place_stats_{VERSION}.csv"))
    ap.add_argument("--radius-m", type=float, default=RADIUS_M)
    args = ap.parse_args()
    stays_dir, out_dir = _from_project(args.stays_dir), _from_project(args.out_dir)
    users = interim.list_stems(stays_dir)
    if args.users:
        users = [u for u in users if u in set(args.users)]
    if not users:
        raise SystemExit(f"Không có stay trong {stays_dir}. Chạy src/stays/detect.py trước.")
    rows, t0 = [], time.time()
    for u in users:
        places, s = places_for_user(interim.read_df(stays_dir / u), u, args.radius_m)
        interim.save_df(places, out_dir / f"{u}_places")
        interim.save_df(s, out_dir / f"{u}_stays")
        top = places.iloc[0] if len(places) else None
        total = places["total_hours"].sum() if len(places) else 0.0
        rows.append({"user": u, "n_stays": len(s), "n_places": len(places),
                     "n_places_2plus_days": int((places["n_days"] >= 2).sum()) if len(places) else 0,
                     "top1_hours": float(top["total_hours"]) if top is not None else 0.0,
                     "top1_share": float(top["total_hours"] / total) if total else np.nan,
                     "top2_share": float(places["total_hours"].iloc[:2].sum() / total) if total else np.nan})
        print(f"{u}: {len(s)} stay -> {len(places)} địa điểm ({time.time() - t0:.0f} giây)")
    stats = _from_project(args.stats)
    stats.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(stats, index=False)
    print("Đã ghi:", out_dir, "và", stats)


if __name__ == "__main__":
    main()
