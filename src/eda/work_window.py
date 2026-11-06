"""Chọn khung giờ làm việc từ dữ liệu, cho notebook 09 (mục 26.1–26.4, A10).

Ý tưởng: không lấy giờ hành chính làm đầu vào. Với mỗi user chọn một cặp (nơi ở, nơi làm việc ứng viên)
bằng tiêu chí rộng, không phụ thuộc khung cần tìm, rồi xem ở từng giờ ngày thường user có mặt ở nơi nào.
Khung làm việc là các giờ mà nơi ứng viên "thắng" nơi ở.

Đầu vào: PROF của presence.profiles (phút theo user, place_id, kind x 168 ô thứ*24 + giờ).
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from eda.presence import hour_mask

HOME_HOURS = (0, 5)          # giờ để chọn nơi ở: 0–5h mọi ngày (không phụ thuộc khung đêm cần tìm)
CORE_HOURS = (10, 16)        # giờ lõi để chọn nơi làm việc ứng viên: T2–T6 10–16h
CORE_ALT = (9, 17)           # khung lõi khác để thử độ nhạy của cách chọn ứng viên
MIN_HOME_H = 3.0             # nơi ở cần ít nhất ngần ấy giờ trong HOME_HOURS
MIN_OFFICE_H = 3.0           # nơi làm việc ứng viên cần ít nhất ngần ấy giờ trong giờ lõi
WIN_SHARE = 0.5              # giờ thuộc khung khi nơi ứng viên chiếm >= 50% thời gian (ở + làm)
N_BOOT = 300
SEED = 0


def _sum_kinds(prof: pd.DataFrame, kinds) -> pd.DataFrame:
    p = prof[prof.index.get_level_values("kind").isin(kinds)]
    return p.groupby(level=["user", "place_id"]).sum()


def pick_pairs(prof: pd.DataFrame, kinds=("gps", "gap"), core=CORE_HOURS) -> pd.DataFrame:
    """Mỗi user: home = nơi nhiều phút nhất trong HOME_HOURS; office = nơi khác home nhiều phút nhất ở
    T2–T6 trong giờ lõi. Bỏ user không đủ giờ."""
    p = _sum_kinds(prof, kinds)
    m = p.to_numpy(float).reshape(-1, 7, 24)
    night = m[:, :, hour_mask(*HOME_HOURS)].sum(axis=(1, 2)) / 60
    work = m[:, :5, hour_mask(*core)].sum(axis=(1, 2)) / 60
    d = pd.DataFrame({"night_h": night, "work_h": work}, index=p.index).reset_index()
    rows = []
    for u, g in d.groupby("user", sort=True):
        h = g.loc[g["night_h"].idxmax()]
        home = int(h["place_id"]) if h["night_h"] >= MIN_HOME_H else -1
        rest = g[g["place_id"] != home]
        o = rest.loc[rest["work_h"].idxmax()] if len(rest) else None
        office = int(o["place_id"]) if o is not None and o["work_h"] >= MIN_OFFICE_H else -1
        rows.append({"user": u, "home": home, "office": office})
    return pd.DataFrame(rows).set_index("user")


def office_share(prof: pd.DataFrame, pairs: pd.DataFrame, kinds=("gps", "gap")) -> dict:
    """Với mỗi user có đủ cặp: ma trận 7 x 24 của office/(office+home) theo phút (NaN khi cả hai bằng 0)."""
    p = _sum_kinds(prof, kinds)
    out = {}
    for u, r in pairs[(pairs["home"] >= 0) & (pairs["office"] >= 0)].iterrows():
        try:
            h = p.loc[(u, int(r["home"]))].to_numpy(float).reshape(7, 24)
            o = p.loc[(u, int(r["office"]))].to_numpy(float).reshape(7, 24)
        except KeyError:
            continue
        tot = h + o
        with np.errstate(invalid="ignore", divide="ignore"):
            out[u] = np.where(tot > 0, o / tot, np.nan)
    return out


def _day_mean(x: np.ndarray) -> np.ndarray:
    ok = np.isfinite(x)
    return np.where(ok.any(axis=0), np.where(ok, x, 0).sum(axis=0) / np.maximum(ok.sum(axis=0), 1), np.nan)


def hourly_share(shares: dict, days: slice) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Trung bình / trung vị qua user của tỷ lệ office theo giờ (gộp các thứ trong days), và số user có dữ liệu."""
    rows = np.vstack([_day_mean(m[days]) for m in shares.values()]) if shares else np.empty((0, 24))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)      # giờ không user nào có dữ liệu -> NaN
        return np.nanmean(rows, axis=0), np.nanmedian(rows, axis=0), np.isfinite(rows).sum(axis=0)


def window_from_curve(curve: np.ndarray, thr: float = WIN_SHARE) -> tuple[int, int] | None:
    """Đoạn giờ liên tiếp dài nhất có curve >= thr; trả (bắt đầu, kết thúc) với kết thúc loại trừ. None nếu không có."""
    ok = np.nan_to_num(curve, nan=0.0) >= thr
    best, start = (0, 0), None
    for h in range(25):
        on = h < 24 and ok[h]
        if on and start is None:
            start = h
        if not on and start is not None:
            if h - start > best[1] - best[0]:
                best = (start, h)
            start = None
    return best if best[1] > best[0] else None


def bootstrap_window(shares: dict, thr: float = WIN_SHARE, n_boot: int = N_BOOT, seed: int = SEED) -> pd.DataFrame:
    """Lấy mẫu lại user (có hoàn lại), tính lại khung từ đường trung bình ngày thường. Trả (bắt đầu, kết thúc) mỗi lần."""
    keys = list(shares)
    rng = np.random.default_rng(seed)
    res = []
    for _ in range(n_boot):
        pick = rng.integers(0, len(keys), len(keys))
        sub = {i: shares[keys[j]] for i, j in enumerate(pick)}
        mean, _, _ = hourly_share(sub, slice(0, 5))
        w = window_from_curve(mean, thr)
        res.append({"start": w[0] if w else np.nan, "end": w[1] if w else np.nan})
    return pd.DataFrame(res)


def arrive_leave_office(al: pd.DataFrame, pairs: pd.DataFrame) -> pd.DataFrame:
    """Giờ đến (5–13h) và giờ đi (12–23h) ngày thường của stay ở nơi làm việc ứng viên; loại các stay xuyên đêm."""
    pr = pairs[pairs["office"] >= 0]["office"]
    x = al[al["user"].isin(pr.index)]
    x = x[x["place_id"].to_numpy() == pr.reindex(x["user"]).to_numpy()]
    arr = x[(~x["arrive_wkend"]) & x["arrive_h"].between(5, 13)][["user", "arrive_h"]]
    lea = x[(~x["leave_wkend"]) & x["leave_h"].between(12, 23)][["user", "leave_h"]]
    return arr, lea
