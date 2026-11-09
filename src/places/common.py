"""Phần dùng chung của hai cách gom địa điểm (bước 6): cluster_v1 (tham lam) và cluster_v2 (DBSCAN).

Mỗi cách gom chỉ cung cấp hàm gán nhãn cụm cho các stay; phần còn lại (bảng địa điểm, đánh số, thống kê, dòng lệnh,
đường dẫn theo version) nằm ở đây để hai bản không lệch nhau.

    build_places(stays, user, label_fn)   bảng địa điểm + bảng stay kèm place_id
    places_dir(version)                   data/processed/places_<version>
    load_places(user, version)            đọc lại kết quả của một user
    cli(...)                              hàm main() dùng chung
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

SRC = Path(__file__).resolve().parents[1]                 # thư mục src
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
from geo import haversine_m                              # noqa: E402
from paths import PROJECT_ROOT                           # noqa: E402
from preprocess import interim                           # noqa: E402
from stays.detect import STAYS_DIR                       # noqa: E402

PLACE_COLS = ["user", "place_id", "lat", "lon", "lat_mean", "lon_mean", "n_stays", "n_days",
              "total_hours", "gap_hours", "first_utc", "last_utc", "max_dist_m"]
PLACE_COLS_DIAM = PLACE_COLS + ["diam_m"]         # v2 thêm đường kính (hai stay xa nhau nhất)


def places_dir(version: str) -> Path:
    return PROJECT_ROOT / "data" / "processed" / f"places_{version}"


def from_project(path: Path) -> Path:
    """Đường dẫn tương đối được tính từ thư mục Home_Office, để chạy được từ bất kỳ thư mục nào."""
    return path if path.is_absolute() else PROJECT_ROOT / path


def load_places(user: str, version: str = "v1"):
    """(bảng địa điểm, bảng stay kèm place_id) của một user."""
    d = places_dir(version)
    return interim.read_df(d / f"{user}_places"), interim.read_df(d / f"{user}_stays")


def days_covered(arrive_local: pd.Series, leave_local: pd.Series) -> set:
    """Các ngày địa phương mà các stay chạm tới (stay qua đêm tính cả hai ngày)."""
    days = set()
    for a, b in zip(arrive_local.dt.normalize(), leave_local.dt.normalize()):
        days.update(pd.date_range(a, b, freq="D").date)
    return days


def diameter_m(lat: np.ndarray, lon: np.ndarray) -> float:
    """Khoảng cách lớn nhất giữa hai điểm (mét)."""
    if len(lat) < 2:
        return 0.0
    return float(max(haversine_m(lat[i], lon[i], lat[i + 1:], lon[i + 1:]).max() for i in range(len(lat) - 1)))


def build_places(stays: pd.DataFrame, user: str, label_fn: Callable[[np.ndarray, np.ndarray, np.ndarray], np.ndarray],
                 with_diam: bool = False):
    """Gom stay của một user thành địa điểm.

    `label_fn(lat, lon, duration_min)` trả về nhãn cụm cho từng stay (-1 là nhiễu: không thành địa điểm).
    Trả về (bảng địa điểm, bảng stay kèm place_id). `place_id` đánh theo tổng thời gian: 0 là nơi ở lâu nhất.
    """
    cols = PLACE_COLS_DIAM if with_diam else PLACE_COLS
    if stays is None or stays.empty:
        return pd.DataFrame(columns=cols), (stays if stays is not None else pd.DataFrame())
    s = stays.reset_index(drop=True).copy()
    lat, lon = s["lat"].to_numpy(float), s["lon"].to_numpy(float)
    s["place_id"] = label_fn(lat, lon, s["duration_min"].to_numpy(float))

    rows = []
    for p, g in s[s["place_id"] >= 0].groupby("place_id", sort=True):
        anchor = g["duration_min"].idxmax()                   # stay dài nhất của địa điểm (lat, lon đại diện)
        w = g["duration_min"].to_numpy(float) + 1e-9
        glat, glon = g["lat"].to_numpy(float), g["lon"].to_numpy(float)
        row = {
            "user": user, "place_id": int(p),
            "lat": float(s.at[anchor, "lat"]), "lon": float(s.at[anchor, "lon"]),
            "lat_mean": float(np.average(glat, weights=w)),
            "lon_mean": float(np.average(glon, weights=w)),
            "n_stays": len(g), "n_days": len(days_covered(g["arrive_local"], g["leave_local"])),
            "total_hours": float(g["duration_min"].sum() / 60), "gap_hours": float(g["gap_min"].sum() / 60),
            "first_utc": g["arrive_utc"].min(), "last_utc": g["leave_utc"].max(),
            "max_dist_m": float(haversine_m(s.at[anchor, "lat"], s.at[anchor, "lon"], glat, glon).max()),
        }
        if with_diam:
            row["diam_m"] = diameter_m(glat, glon)
        rows.append(row)
    places = pd.DataFrame(rows, columns=cols)
    if places.empty:
        return places, s
    places = places.sort_values("total_hours", ascending=False, ignore_index=True)
    remap = dict(zip(places["place_id"], range(len(places))))
    places["place_id"] = np.arange(len(places))
    s["place_id"] = s["place_id"].map(remap).fillna(-1).astype(np.int64)      # nhiễu giữ -1
    return places, s


def cli(version: str, description: str, places_fn: Callable, options: dict, with_diam: bool = False) -> None:
    """main() dùng chung. `places_fn(stays, user, **tham_số)`; `options`: {"--cờ": (kiểu, mặc định, mô tả)}."""
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--users", nargs="*", help="chỉ chạy các user này")
    ap.add_argument("--stays-dir", type=Path, default=STAYS_DIR)
    ap.add_argument("--out-dir", type=Path, default=places_dir(version))
    ap.add_argument("--stats", type=Path, default=Path(f"reports/place_stats_{version}.csv"))
    for flag, (typ, default, helptext) in options.items():
        ap.add_argument(flag, type=typ, default=default, help=helptext)
    args = ap.parse_args()
    params = {flag.lstrip("-").replace("-", "_"): getattr(args, flag.lstrip("-").replace("-", "_")) for flag in options}
    stays_dir, out_dir = from_project(args.stays_dir), from_project(args.out_dir)
    users = interim.list_stems(stays_dir)
    if args.users:
        users = [u for u in users if u in set(args.users)]
    if not users:
        raise SystemExit(f"Không có stay trong {stays_dir}. Chạy src/stays/detect.py trước.")
    rows, t0 = [], time.time()
    for u in users:
        places, s = places_fn(interim.read_df(stays_dir / u), u, **params)
        interim.save_df(places, out_dir / f"{u}_places")
        interim.save_df(s, out_dir / f"{u}_stays")
        top = places.iloc[0] if len(places) else None
        total = places["total_hours"].sum() if len(places) else 0.0
        row = {"user": u, "n_stays": len(s), "n_places": len(places),
               "n_places_2plus_days": int((places["n_days"] >= 2).sum()) if len(places) else 0,
               "top1_hours": float(top["total_hours"]) if top is not None else 0.0}
        if with_diam:
            row["n_noise"] = int((s["place_id"] < 0).sum()) if "place_id" in s else 0
            row["top1_diam_m"] = float(top["diam_m"]) if top is not None else np.nan
        row["top1_share"] = float(top["total_hours"] / total) if total else np.nan
        row["top2_share"] = float(places["total_hours"].iloc[:2].sum() / total) if total else np.nan
        rows.append(row)
        print(f"{u}: {len(s)} stay -> {len(places)} địa điểm ({time.time() - t0:.0f} giây)")
    stats = from_project(args.stats)
    stats.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(stats, index=False)
    print("Đã ghi:", out_dir, "và", stats)
