"""Mục 23.8 (notebook 08): nhịp bật / tắt máy của từng user, trung bình trên cả nhóm dev.

Mỗi user có phân phối độ dài khoảng trống riêng (máy tắt qua đêm, tắt cuối tuần, mất tín hiệu...). Với mỗi mức max gap
ứng viên, tính phần khoảng trống (và phần giờ trống) của user mà mức đó giữ lại, rồi lấy **trung bình các user** (mỗi user
một phiếu ngang nhau, user ghi nhiều không lấn át) để so sánh với tổng gộp.

Đây là thống kê về **máy tắt bao lâu**, không phải về việc người đó có ở yên không (cái đó ở 23.1, 23.6).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from eda import gap_evidence as ge
from preprocess.clean_trajectory import CLEAN_DIR

CAPS_H = [4, 8, 12, 16, 20, 24, 36, 48, 72, 168]
PCTS = [50, 75, 90, 95, 99]
MIN_GAPS = 10                   # user có ít hơn số này khoảng trống thì không đưa vào trung bình


def user_gap_hours(user: str, clean_dir: Path = CLEAN_DIR) -> np.ndarray:
    """Độ dài (giờ) mọi khoảng trống > 30 phút của user (không giới hạn trên)."""
    arr = ge._load(user, clean_dir)
    if arr is None:
        return np.array([])
    t = arr[2]
    dt = np.diff(t)
    return dt[dt > ge.GAP_S] / 3600.0


def run_rhythm(users, clean_dir: Path = CLEAN_DIR) -> dict:
    return {u: user_gap_hours(u, clean_dir) for u in users}


def rhythm_tables(gaps: dict, caps=CAPS_H, pcts=PCTS, min_gaps: int = MIN_GAPS):
    """(bảng theo mức max gap, bảng phân vị độ dài khoảng trống). Trung bình theo user và gộp chung."""
    G = {u: g for u, g in gaps.items() if len(g) >= min_gaps}
    rows = {}
    for cap in caps:
        kept_n = np.array([(g <= cap).mean() for g in G.values()]) * 100
        kept_h = np.array([g[g <= cap].sum() / g.sum() for g in G.values()]) * 100
        allg = np.concatenate(list(G.values()))
        rows[cap] = {"khoảng trống giữ lại, TB user (%)": kept_n.mean(),
                     "khoảng trống giữ lại, p10 user (%)": np.percentile(kept_n, 10),
                     "giờ trống giữ lại, TB user (%)": kept_h.mean(),
                     "khoảng trống giữ lại, gộp chung (%)": 100 * (allg <= cap).mean(),
                     "giờ trống giữ lại, gộp chung (%)": 100 * allg[allg <= cap].sum() / allg.sum()}
    by_cap = pd.DataFrame(rows).T
    by_cap.index.name = "max gap (giờ)"
    per = pd.DataFrame({u: {f"p{p}": np.percentile(g, p) for p in pcts} | {"n": len(g)} for u, g in G.items()}).T
    pct = pd.DataFrame({"trung bình user (giờ)": per[[f"p{p}" for p in pcts]].mean(),
                        "trung vị user (giờ)": per[[f"p{p}" for p in pcts]].median(),
                        "p10 user (giờ)": per[[f"p{p}" for p in pcts]].quantile(0.1),
                        "p90 user (giờ)": per[[f"p{p}" for p in pcts]].quantile(0.9)})
    pct.index.name = "phân vị độ dài khoảng trống của user"
    return by_cap, pct, len(G)
