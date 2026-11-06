"""Khoảng trống có trùng nơi thường lệ của cùng khung giờ không (notebook 08, mục 23.5).

Với mỗi user, mỗi (loại ngày: thứ 2–6 / cuối tuần, giờ trong ngày): lấy vị trí GPS của giờ đó ở mỗi ngày có GPS, nơi thường lệ là
vị trí có nhiều ngày khác nằm trong SAME_M nhất (medoid), độ mạnh = phần ngày có GPS nằm trong SAME_M quanh nơi đó.
Mỗi khoảng trống (30 phút–72 giờ): lấy khung giờ ở giữa khoảng trống, hỏi hai đầu có nằm trong AT_M quanh nơi thường lệ của khung
đó không. So với độ mạnh của chính khung đó (các ngày có GPS trùng nơi thường lệ bao nhiêu %): tỉ lệ khoảng trống trùng /
tỉ lệ ngày GPS trùng. Gần 1 nghĩa là khoảng trống đáng tin ngang một ngày có GPS.
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd

from eda import stay_anchor as sa
from preprocess.clean_trajectory import CLEAN_DIR, GAP_S, haversine_m

SAME_M = 200.0
AT_M = 300.0              # hai đầu khoảng trống cách nơi thường lệ không quá AT_M
MIN_DAYS = 5              # khung giờ phải có ít nhất ngần này ngày GPS
MIN_PTS = 2               # ngày GPS của một khung: ít nhất ngần này điểm trong giờ đó
MIN_STRENGTH = 0.6        # khung có "thói quen" khi >= 60% ngày GPS cùng nơi
CACHE_DIR = sa.CACHE_DIR


def _slots(lat, lon, loc):
    """{(loại ngày, giờ): (lat, lon của nơi thường lệ, độ mạnh, số ngày GPS)}."""
    day = np.floor(loc / 86400).astype(np.int64)
    hour = ((loc % 86400) // 3600).astype(np.int64)
    kind = ((day + 3) % 7 >= 5).astype(np.int64)                  # 0 = thứ 2–6, 1 = cuối tuần
    df = pd.DataFrame({"day": day, "hour": hour, "kind": kind, "lat": lat, "lon": lon})
    g = df.groupby(["kind", "hour", "day"]).agg(lat=("lat", "median"), lon=("lon", "median"), n=("lat", "size")).reset_index()
    g = g[g["n"] >= MIN_PTS]
    out = {}
    for (k, h), x in g.groupby(["kind", "hour"]):
        if len(x) < MIN_DAYS:
            continue
        la, lo = x["lat"].to_numpy(), x["lon"].to_numpy()
        d = haversine_m(la[:, None], lo[:, None], la[None, :], lo[None, :])
        near = (d <= SAME_M).sum(axis=1)
        m = int(np.argmax(near))
        out[(int(k), int(h))] = (float(la[m]), float(lo[m]), float(near[m] / len(x)), len(x))
    return out


def user_routine(user: str, clean_dir: Path = CLEAN_DIR):
    arr = sa.load_user(user, clean_dir)
    if arr is None:
        return None
    lat, lon, t = arr
    off = sa._tz_offset(user, clean_dir)
    slots = _slots(lat, lon, t + off * 3600)
    dt = np.diff(t)
    g = np.nonzero((dt > GAP_S) & (dt <= sa.SCAN_GAP_S))[0]
    if len(g) == 0:
        return None
    mid = (t[g] + t[g + 1]) / 2 + off * 3600
    day = np.floor(mid / 86400).astype(np.int64)
    hour = ((mid % 86400) // 3600).astype(np.int64)
    kind = ((day + 3) % 7 >= 5).astype(np.int64)
    end_m = haversine_m(lat[g], lon[g], lat[g + 1], lon[g + 1])
    rows = []
    for i, gi in enumerate(g):
        s = slots.get((int(kind[i]), int(hour[i])))
        if s is None:
            continue
        d0 = float(haversine_m(s[0], s[1], lat[gi], lon[gi]))
        d1 = float(haversine_m(s[0], s[1], lat[gi + 1], lon[gi + 1]))
        rows.append({"user": user, "gap_h": dt[gi] / 3600, "end_m": float(end_m[i]), "kind": int(kind[i]), "hour": int(hour[i]),
                     "strength": s[2], "n_days": s[3], "match": max(d0, d1) <= AT_M})
    return pd.DataFrame(rows)


def _job(u, clean_dir, f):
    pd.to_pickle(user_routine(u, clean_dir), f)
    return u


def run_routine(users, clean_dir: Path = CLEAN_DIR, cache_dir: Path = CACHE_DIR, n_jobs=None, verbose=True):
    """user_routine cho nhiều user, song song, lưu từng user ở <user>_routine.pkl."""
    import os
    from concurrent.futures import ProcessPoolExecutor, as_completed
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    f_of = {u: cache_dir / f"{u}_routine.pkl" for u in users}
    todo = [u for u in users if not f_of[u].exists()]
    n_jobs = n_jobs or max(1, (os.cpu_count() or 2) - 1)
    t0 = time.time()
    if verbose:
        print(f"{len(users) - len(todo)} user đã có kết quả, {len(todo)} user cần tính, {n_jobs} tiến trình")
    if todo and n_jobs > 1:
        with ProcessPoolExecutor(max_workers=n_jobs) as ex:
            futs = [ex.submit(_job, u, clean_dir, f_of[u]) for u in todo]
            for k, fu in enumerate(as_completed(futs), 1):
                fu.result()
                if verbose and (k % 20 == 0 or k == len(todo)):
                    print(f"[{k}/{len(todo)}] ({time.time() - t0:.0f} giây)")
    else:
        for u in todo:
            _job(u, clean_dir, f_of[u])
    parts = [pd.read_pickle(f_of[u]) for u in users]
    parts = [p for p in parts if p is not None and len(p)]
    return pd.concat(parts, ignore_index=True)


def routine_table(R: pd.DataFrame, min_strength: float = MIN_STRENGTH, bins=None) -> pd.DataFrame:
    """Theo độ dài khoảng trống, chỉ các khung có thói quen: % khoảng trống trùng nơi thường lệ, % ngày GPS trùng,
    tỉ lệ hai số đó; và riêng với khoảng trống hai đầu gần nhau (≤ 200 m)."""
    bins = bins or sa.LEN_BINS_H
    x = R[R["strength"] >= min_strength].copy()
    x["độ dài (giờ)"] = pd.cut(x["gap_h"], bins)
    rows = []
    for iv, g in x.groupby("độ dài (giờ)", observed=True):
        gn = g[g["end_m"] <= 200]
        rows.append({"độ dài (giờ)": iv, "n khoảng trống": len(g), "n user": g["user"].nunique(),
                     "% ngày GPS trùng nơi thường lệ": 100 * g["strength"].mean(),
                     "% khoảng trống trùng": 100 * g["match"].mean(),
                     "tỉ lệ (khoảng trống / ngày GPS)": g["match"].mean() / g["strength"].mean(),
                     "n (hai đầu gần)": len(gn),
                     "% trùng, hai đầu gần": 100 * gn["match"].mean() if len(gn) else np.nan,
                     "% trùng, hai đầu xa": 100 * g.loc[g["end_m"] > 200, "match"].mean() if (g["end_m"] > 200).any() else np.nan})
    return pd.DataFrame(rows).set_index("độ dài (giờ)")
