"""Bằng chứng để gộp khoảng trống (gap) vào home/office (notebook 10, mục 27–28).

Stay dùng h1_mean (kết quả của notebook 07). Với mỗi user:
  - giờ GPS và giờ gap của mỗi stay trong khung đêm (0–6h) và khung hành chính (thứ 2–6, 9–17h), giờ địa phương;
  - home_gps / office_gps: địa điểm nhiều giờ GPS nhất trong từng khung (làm đáp án tham chiếu);
  - mỗi khoảng trống trong stay: độ dài, hai đầu cách nhau, qua đêm không, hai đầu cách home_gps / office_gps bao xa.
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd

from eda import stay_anchor as sa
from preprocess import interim
from preprocess.clean_trajectory import CLEAN_DIR, EPOCH, GAP_S, haversine_m
from stays.detect import MAX_GAP_S, _prepare

NIGHT = (0, 6)                  # khung giờ đêm (giờ địa phương)
OFFICE = (9, 17)                # khung giờ hành chính, chỉ thứ 2–6
NEAR_M = 200.0                  # hai đầu khoảng trống "gần nhau"
AT_M = 300.0                    # "ở nơi đó": cả hai đầu cách tâm địa điểm không quá AT_M
MIN_GPS_NIGHT_H = 10.0          # user đủ giờ GPS đêm (ở địa điểm đó) để làm đáp án home; lọc ở notebook
MIN_GPS_OFFICE_H = 20.0         # user đủ giờ GPS hành chính để làm đáp án office; lọc ở notebook
CACHE_DIR = sa.CACHE_DIR


def _load(user: str, clean_dir: Path):
    df = interim.read_df(Path(clean_dir) / user)
    if df is None or df.empty:
        return None
    d = _prepare(df)
    t = (d["timestamp"] - EPOCH).dt.total_seconds().to_numpy()
    return d["lat"].to_numpy(float), d["lon"].to_numpy(float), t, float(d["tz_offset_h"].median())


def _cum_window(x, h0, h1, weekday_only=False):
    """Số giây tích luỹ, tính từ gốc đến x (giờ địa phương, giây), nằm trong khung [h0, h1) giờ của mỗi ngày
    (chỉ thứ 2–6 nếu weekday_only). Hiệu hai giá trị cho số giây trùng khung của một đoạn, tính chính xác."""
    day = np.floor(x / 86400).astype(np.int64)
    sec = x - day * 86400
    inday = np.clip(sec - h0 * 3600, 0, (h1 - h0) * 3600)
    if not weekday_only:
        return day * (h1 - h0) * 3600 + inday
    wd = (day + 3) % 7                                  # 0 = thứ 2; 1970-01-01 là thứ 5
    pre = np.array([0, 1, 2, 2, 2, 3, 4])               # số ngày thứ 2–6 trong r ngày đầu kể từ thứ 5
    n_week = (day // 7) * 5 + pre[day % 7]
    return n_week * (h1 - h0) * 3600 + (wd < 5) * inday


def _overlap(a, b, h0, h1, weekday_only=False):
    return _cum_window(b, h0, h1, weekday_only) - _cum_window(a, h0, h1, weekday_only)


def _h1_stays(user: str, clean_dir: Path) -> pd.DataFrame:
    f = Path(CACHE_DIR) / f"{user}_cmp.pkl"
    if f.exists():
        S = pd.read_pickle(f)[0]
        return S[S["variant"] == "h1_mean"].reset_index(drop=True)
    res = sa.user_stays(user, ["h1_mean"], clean_dir)
    return res["h1_mean"][0] if res else pd.DataFrame()


def _center(g: pd.DataFrame):
    a = g["dur_h"].idxmax()
    return float(g.at[a, "lat"]), float(g.at[a, "lon"])


def user_evidence(user: str, clean_dir: Path = CLEAN_DIR):
    """Trả về (bảng stay + bằng chứng, bảng khoảng trống, giờ theo giờ trong ngày, một dòng tóm tắt user)."""
    from places.cluster_v1 import cluster_v1
    arr = _load(user, clean_dir)
    S = _h1_stays(user, clean_dir)
    if arr is None or S.empty:
        return None
    lat, lon, t, off = arr
    n = len(t)
    a, b = t[:-1] + off * 3600, t[1:] + off * 3600
    dt = np.diff(t)
    is_gap = dt > GAP_S
    ok = dt <= MAX_GAP_S                                          # khoảng > 24 giờ đã bị cắt, không thuộc stay nào
    end_m = haversine_m(lat[:-1], lon[:-1], lat[1:], lon[1:])
    hs, he = (a % 86400) // 3600, (b % 86400) // 3600
    overnight = is_gap & ((hs >= 18) | (hs < 3)) & (he >= 5) & (he < 12)
    night = _overlap(a, b, *NIGHT)
    office = _overlap(a, b, *OFFICE, weekday_only=True)
    gps = ~is_gap
    arrays = {
        "n_gps": night * gps, "n_gap_all": night * is_gap,
        "o_gps": office * gps, "o_gap_all": office * is_gap,
    }
    i0, i1 = S["i0"].to_numpy(int), S["i1"].to_numpy(int)
    for k, v in arrays.items():
        c = np.r_[0.0, np.cumsum(v)]
        S[k] = (c[i1] - c[i0]) / 3600
    S["pid"] = cluster_v1(S["lat"].to_numpy(), S["lon"].to_numpy(), S["dur_h"].to_numpy())
    S["user"] = user

    # --- giờ theo giờ trong ngày (tất cả các khoảng, trừ > 24 giờ)
    rows = []
    for h in range(24):
        ov = _cum_window(b, h, h + 1) - _cum_window(a, h, h + 1)
        rows.append({"user": user, "hour": h, "gps_h": ov[gps & ok].sum() / 3600, "gap_h": ov[is_gap & ok].sum() / 3600})
    hourly = pd.DataFrame(rows)

    # --- địa điểm; đáp án tham chiếu home/office chỉ từ giờ GPS
    P = S.groupby("pid").agg(**{c: (c, "sum") for c in arrays}, hours=("dur_h", "sum"))
    cen = {p: _center(g) for p, g in S.groupby("pid")}

    def top(*cols):
        v = sum(P[c] for c in cols)
        return (v.idxmax(), float(v.max())) if v.max() > 0 else (None, 0.0)

    row = {"user": user, "off_h": off, "n_stays": len(S),
           "night_gps_h": arrays["n_gps"].sum() / 3600, "night_gap_h": arrays["n_gap_all"].sum() / 3600,
           "office_gps_h": arrays["o_gps"].sum() / 3600, "office_gap_h": arrays["o_gap_all"].sum() / 3600}
    ref = {}
    for what, gps_col, all_cols in (("home", "n_gps", ("n_gps", "n_gap_all")), ("office", "o_gps", ("o_gps", "o_gap_all"))):
        p, h = top(gps_col)
        row[f"{what}_gps_hours"] = h                         # đủ giờ GPS để tin hay không: lọc ở notebook (MIN_GPS_*)
        ref[what] = cen[p] if p is not None else None
        row[f"{what}_lat"], row[f"{what}_lon"] = cen[p] if p is not None else (np.nan, np.nan)
        pa, _ = top(*all_cols)                               # nơi nhiều giờ nhất khi đếm cả gap (như Li)
        tot = sum(P.at[pa, c] for c in all_cols) if pa is not None else 0.0
        row[f"{what}_gap_share"] = P.at[pa, all_cols[1]] / tot if tot > 0 else np.nan
    row["home_office_same_m"] = (float(haversine_m(row["home_lat"], row["home_lon"], row["office_lat"], row["office_lon"]))
                                 if not (np.isnan(row["home_lat"]) or np.isnan(row["office_lat"])) else np.nan)

    # --- từng khoảng trống nằm trong stay: hai đầu cách home/office (đáp án GPS) bao xa
    mark = np.zeros(n)
    np.add.at(mark, i0, 1)
    np.add.at(mark, i1, -1)
    in_stay = np.cumsum(mark)[:-1] > 0
    g = np.nonzero(is_gap & ok & in_stay)[0]
    G = pd.DataFrame({"user": user, "gap_h": dt[g] / 3600, "end_m": end_m[g], "overnight": overnight[g],
                      "start_hour": hs[g].astype(int), "end_hour": he[g].astype(int)})
    for what in ("home", "office"):
        if ref[what] is None or len(g) == 0:
            G[f"d_{what}"] = np.nan
        else:
            da = haversine_m(ref[what][0], ref[what][1], lat[g], lon[g])
            db = haversine_m(ref[what][0], ref[what][1], lat[g + 1], lon[g + 1])
            G[f"d_{what}"] = np.maximum(da, db)                 # xa nhất trong hai đầu
    return S, G, hourly, pd.Series(row)


def _job(u, clean_dir, f):
    pd.to_pickle(user_evidence(u, clean_dir), f)
    return u


def run_evidence(users, clean_dir: Path = CLEAN_DIR, cache_dir: Path = CACHE_DIR, n_jobs=None, verbose=True):
    """user_evidence cho nhiều user, song song, lưu từng user ở <user>_gapev.pkl.
    Trả về (user: bảng tóm tắt, gaps: từng khoảng trống, hourly: giờ theo giờ trong ngày)."""
    import os
    from concurrent.futures import ProcessPoolExecutor, as_completed
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    f_of = {u: cache_dir / f"{u}_gapev.pkl" for u in users}
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
    parts = [p for p in parts if p is not None]
    U = pd.DataFrame([p[3] for p in parts])
    G = pd.concat([p[1] for p in parts if len(p[1])], ignore_index=True)
    H = pd.concat([p[2] for p in parts], ignore_index=True)
    return U, G, H


# ---------------------------------------------------------------------------
# Bảng cho notebook
# ---------------------------------------------------------------------------
GAP_LEN_BINS = [0.5, 1, 2, 4, 8, 12, 24]
END_BINS = [0, 200, 400, 1000, np.inf]


def at_place_by_length(G: pd.DataFrame, what: str, mask) -> pd.DataFrame:
    """Với các gap thoả mask: % có CẢ HAI đầu cách địa điểm `what` (home/office, từ GPS) không quá AT_M, theo độ dài."""
    x = G[mask & G[f"d_{what}"].notna()].copy()
    x["độ dài (giờ)"] = pd.cut(x["gap_h"], GAP_LEN_BINS)
    t = x.groupby("độ dài (giờ)", observed=True)[f"d_{what}"].agg(n="size", pct_ở_nơi_đó=lambda d: 100 * (d <= AT_M).mean(),
                                                                  trung_vị_m="median")
    return t


def at_place_by_ends(G: pd.DataFrame, what: str, mask) -> pd.DataFrame:
    x = G[mask & G[f"d_{what}"].notna()].copy()
    x["hai đầu cách nhau (m)"] = pd.cut(x["end_m"], END_BINS)
    return x.groupby("hai đầu cách nhau (m)", observed=True)[f"d_{what}"].agg(
        n="size", pct_ở_nơi_đó=lambda d: 100 * (d <= AT_M).mean(), trung_vị_m="median")
