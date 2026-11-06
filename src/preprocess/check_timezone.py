"""So sánh giờ địa phương cách mới (timezonefinder + zoneinfo) với cách cũ (CN_BOX, round(lon / 15)) trên dữ liệu thật.

Lấy mẫu ngẫu nhiên mỗi user (mặc định 20.000 điểm, seed cố định) từ data/interim rồi in:
  1. Tỷ lệ điểm hai cách cho cùng giờ lệch, và các cặp (múi giờ, chênh lệch) khác nhau nhiều nhất.
  2. Điểm nằm trong CN_BOX nhưng không ra UTC+8, và số điểm ra Asia/Urumqi (IANA ghi UTC+6, trong khi
     giờ chính thức của Trung Quốc là giờ Bắc Kinh) -> cần xem có đúng với thiết bị ghi dữ liệu không.
  3. Sai khác giữa tra theo ô lưới và tra từng điểm (đo sai số của việc làm tròn theo ô).

Chạy (từ thư mục Home_Office), sau khi: pip install -r requirements.txt
    python src/preprocess/check_timezone.py
    python src/preprocess/check_timezone.py --users 000 163 --sample 50000 --cell-deg 0.25
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
from preprocess import local_time as lt                                   # noqa: E402


def load_sample(users: list[str], n_per_user: int) -> pd.DataFrame:
    parts = []
    for u in users:
        p = interim.load_points(u)
        if p is None or p.empty:
            continue
        p = p[["lat", "lon", "timestamp"]]
        if len(p) > n_per_user:
            p = p.sample(n_per_user, random_state=0)
        parts.append(p.assign(user=u))
    return pd.concat(parts, ignore_index=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="So sánh giờ địa phương cách mới với cách cũ.")
    ap.add_argument("--users", nargs="*", help="chỉ kiểm tra các user này (mặc định: tất cả trong data/interim)")
    ap.add_argument("--sample", type=int, default=20000, help="số điểm lấy mẫu mỗi user")
    ap.add_argument("--cell-deg", type=float, default=lt.CELL_DEG)
    ap.add_argument("--exact", type=int, default=3000, help="số điểm tra từng điểm để đo sai số của ô lưới")
    args = ap.parse_args()

    users = args.users or interim.require_interim()
    df = load_sample(users, args.sample)
    print(f"Mẫu: {len(df):,} điểm của {df['user'].nunique()} user")

    t0 = time.time()
    new = lt.add_local_time(df, args.cell_deg)
    print(f"Tra múi giờ + đổi giờ: {time.time() - t0:.1f} giây, {len(lt._cell_tz):,} ô lưới")
    old_off = lt.local_offset_h(df["lat"], df["lon"])
    new["diff_h"] = new["tz_offset_h"].to_numpy() - old_off
    new["in_cn_box"] = lt.in_box(df["lat"].to_numpy(), df["lon"].to_numpy(), lt.CN_BOX)

    print("\n1. Giờ lệch: cách mới so với cách cũ")
    print(f"   giống nhau: {(new['diff_h'] == 0).mean():.2%}")
    g = (new[new["diff_h"] != 0].groupby(["tz_name", "diff_h"], observed=True)
         .agg(n_points=("lat", "size"), n_users=("user", "nunique")).sort_values("n_points", ascending=False))
    print(g.head(15).to_string() if len(g) else "   (không có điểm nào khác)")

    print("\n2. Trung Quốc")
    cn = new[new["in_cn_box"]]
    print(f"   điểm trong CN_BOX: {len(cn):,}; không ra UTC+8: {(cn['tz_offset_h'] != 8).sum():,}")
    print(cn[cn["tz_offset_h"] != 8].groupby("tz_name", observed=True).size().sort_values(ascending=False)
          .head(10).to_string())
    urumqi = new[new["tz_name"] == "Asia/Urumqi"]
    print(f"   điểm ra Asia/Urumqi: {len(urumqi):,} ở {urumqi['user'].nunique()} user")

    print("\n3. Sai số của ô lưới so với tra từng điểm")
    s = df.sample(min(args.exact, len(df)), random_state=1)
    exact = [lt._finder().timezone_at(lat=a, lng=b) or lt._fallback_name(b)
             for a, b in zip(s["lat"], s["lon"])]
    grid = lt.timezone_names(s["lat"], s["lon"], args.cell_deg)
    bad = np.array(exact, dtype=object) != grid
    print(f"   {len(s):,} điểm, khác tên múi giờ: {bad.sum()} ({bad.mean():.2%})")
    if bad.any():
        print(pd.DataFrame({"exact": np.array(exact, dtype=object)[bad], "grid": grid[bad]})
              .value_counts().head(10).to_string())
        print("   Lưu ý: khác tên chưa chắc khác giờ lệch (ví dụ Asia/Shanghai và Asia/Chongqing cùng UTC+8).")


if __name__ == "__main__":
    main()
