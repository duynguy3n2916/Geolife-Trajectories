"""Mục 2.6 (notebook 11): khoảng trống dài (đến 72 giờ) so với home / office suy ra từ GPS thật.

`gap_evidence.py` chỉ giữ khoảng trống ≤ 24 giờ (đúng như pipeline). Ở đây đọc lại điểm sạch của từng user và xét mọi
khoảng trống 30 phút – 72 giờ, để có mẫu cho cả khoảng 24–72 giờ.

Đáp án tham chiếu: nơi nhiều giờ GPS thật nhất trong 0–6h (home) và 9–17h thứ 2–6 (office), lấy từ bảng user của
`gap_evidence.run_evidence`, chỉ user đủ giờ GPS (`MIN_GPS_NIGHT_H`, `MIN_GPS_OFFICE_H`).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from eda import gap_evidence as ge
from preprocess.clean_trajectory import CLEAN_DIR, haversine_m

MAX_LONG_H = 72.0
BINS_H = [0.5, 1, 2, 4, 8, 12, 24, 36, 48, 72]


def user_long_gaps(user: str, refs: dict, clean_dir: Path = CLEAN_DIR) -> pd.DataFrame:
    """Mỗi khoảng trống 30 phút–72 giờ: độ dài, hai đầu cách nhau, xa nhất trong hai đầu cách home / office (m)."""
    arr = ge._load(user, clean_dir)
    if arr is None:
        return pd.DataFrame()
    lat, lon, t, _ = arr
    dt = np.diff(t)
    g = np.nonzero((dt > ge.GAP_S) & (dt <= MAX_LONG_H * 3600))[0]
    if len(g) == 0:
        return pd.DataFrame()
    out = pd.DataFrame({"user": user, "gap_h": dt[g] / 3600,
                        "end_m": haversine_m(lat[g], lon[g], lat[g + 1], lon[g + 1])})
    for what, ref in refs.items():
        if ref is None:
            out[f"d_{what}"] = np.nan
        else:
            da = haversine_m(ref[0], ref[1], lat[g], lon[g])
            db = haversine_m(ref[0], ref[1], lat[g + 1], lon[g + 1])
            out[f"d_{what}"] = np.maximum(da, db)
    return out


def run_long(U: pd.DataFrame, clean_dir: Path = CLEAN_DIR) -> pd.DataFrame:
    """U: bảng user của gap_evidence.run_evidence. Trả về bảng các khoảng trống dài của user đủ giờ GPS."""
    parts = []
    for r in U.itertuples():
        refs = {
            "home": (r.home_lat, r.home_lon) if r.home_gps_hours >= ge.MIN_GPS_NIGHT_H and not np.isnan(r.home_lat) else None,
            "office": (r.office_lat, r.office_lon) if r.office_gps_hours >= ge.MIN_GPS_OFFICE_H and not np.isnan(r.office_lat) else None,
        }
        if refs["home"] is None and refs["office"] is None:
            continue
        p = user_long_gaps(r.user, refs, clean_dir)
        if len(p):
            parts.append(p)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def long_table(G: pd.DataFrame, what: str) -> pd.DataFrame:
    """Theo độ dài khoảng trống: số khoảng trống / user, % hai đầu gần nhau (≤ NEAR_M), % cả hai đầu ở `what` (≤ AT_M),
    và % ở `what` trong số khoảng trống có hai đầu gần nhau (loại sẽ bị nối thành stay)."""
    x = G[G[f"d_{what}"].notna()].copy()
    x["độ dài (giờ)"] = pd.cut(x["gap_h"], BINS_H)
    x["near"] = x["end_m"] <= ge.NEAR_M
    x["at"] = x[f"d_{what}"] <= ge.AT_M
    rows = {}
    for k, d in x.groupby("độ dài (giờ)", observed=True):
        n_near = int(d["near"].sum())
        rows[k] = {"n khoảng trống": len(d), "n user": d["user"].nunique(),
                   "hai đầu gần nhau (%)": 100 * d["near"].mean(),
                   f"cả hai đầu ở {what} (%)": 100 * d["at"].mean(),
                   "n (hai đầu gần)": n_near,
                   f"ở {what}, trong số hai đầu gần (%)": 100 * d.loc[d["near"], "at"].mean() if n_near else np.nan}
    return pd.DataFrame(rows).T
