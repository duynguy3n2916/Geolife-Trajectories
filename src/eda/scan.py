"""Quét dữ liệu cho các notebook EDA: đọc data/interim, tính số liệu theo user và cộng dồn số liệu chung.

Mỗi notebook chỉ cần một vài chủ đề, nên run(topics=...) chỉ tính phần được yêu cầu:

    Chủ đề         Notebook   Kết quả
    (luôn có)      mọi        users (một dòng mỗi user), files (một dòng mỗi file .plt), A["n_steps"]
    "speed"        02         phân phối dt, histogram dt × tốc độ, đếm theo mốc, nhãn phương tiện (modes)
    "outliers"     03         exc: các chuỗi "đi ra rồi quay về"
    "space_time"   04         heatmap thế giới, Bắc Kinh, số điểm theo giờ UTC / địa phương, months, năm × giờ
    "coverage"     05         phút có dữ liệu theo thứ × giờ, số ngày theo giờ, gaps (mọi khoảng trống)

Các bước khi quét (chỉ để đo, không phải bước lọc):
1. Đọc points của user (đọc bằng read_plt khi chuyển đổi, giống pipeline).
2. Bỏ timestamp không đọc được, sắp xếp, bỏ timestamp trùng (đếm lại). Bỏ trùng là bắt buộc để đo bước.
3. Bước, tốc độ, khoảng trống tính trên mọi bước, không giới hạn dt.
4. Phân tích theo giờ, ngày, tháng chỉ dùng điểm có timestamp trong khoảng thu thập (User Guide).
"""
from __future__ import annotations

import time
from collections import defaultdict
from types import SimpleNamespace

import numpy as np
import pandas as pd

from preprocess.clean_trajectory import haversine_m
from preprocess.local_time import CN_BOX, in_box, local_offset_h
from preprocess import interim
from .config import (TIME_MIN, TIME_MAX, BJ_BOX, SPEED_MARKS, GAP_MARKS_MIN, DT_CUTS_S, QUANTILES,
                     DT_BINS, SPEED_BINS, WORLD_LAT, WORLD_LON, BJ_LAT, BJ_LON, EPOCH,
                     EXC_SPEED_KMH, EXC_STEP_DT_S)

TOPICS = ("speed", "outliers", "space_time", "coverage")


# -----------------------------------------------------------------------------
# Giỏ cộng dồn số liệu của mọi user
# -----------------------------------------------------------------------------
def _new_agg():
    return {
        "users": [], "files": [], "n_steps": 0,
        # speed
        "dt": [], "dt_sp": np.zeros((len(DT_BINS) - 1, len(SPEED_BINS) - 1)),
        "cut_mark": np.zeros((len(DT_CUTS_S), len(SPEED_MARKS)), dtype=np.int64),
        "n_le_cut": np.zeros(len(DT_CUTS_S), dtype=np.int64),
        "modes": defaultdict(lambda: {"n_labels": 0, "hours": 0.0, "n_steps": 0,
                                      "hist": np.zeros(len(SPEED_BINS) - 1)}),
        # outliers
        "exc": [],
        # space_time
        "world": np.zeros((len(WORLD_LAT) - 1, len(WORLD_LON) - 1)),
        "bj": np.zeros((len(BJ_LAT) - 1, len(BJ_LON) - 1)),
        "hour_utc_cn": np.zeros(24), "hour_loc_cn": np.zeros(24),
        "hour_utc_out": np.zeros(24), "hour_loc_out": np.zeros(24),
        "year_hour": defaultdict(lambda: np.zeros(24)),
        "month_pts": defaultdict(int), "month_users": defaultdict(set),
        # coverage
        "cov_ids": [], "cov_wd_hour": [], "days_hour": [], "days_hour_wk": [], "gaps": [],
    }


# -----------------------------------------------------------------------------
# Phần chung: chất lượng, bước, không gian, giờ địa phương, độ phủ theo phút (luôn tính, nhanh)
# -----------------------------------------------------------------------------
def _base(u, agg):
    """Trả về (row, ctx). row: dòng thống kê của user. ctx: các mảng dùng cho các chủ đề, hoặc None nếu rỗng."""
    raw = interim.load_points(u)
    files = interim.load_files(u)
    labels = interim.load_labels(u)
    agg["files"].append(files.assign(user=u))
    row = {"user": u, "n_files": len(files), "has_labels": labels is not None}
    if raw is None or raw.empty:
        return row, None

    # ---- chất lượng dữ liệu
    row["n_raw"] = len(raw)
    row["n_bad_coord"] = int((~(raw["lat"].between(-90, 90) & raw["lon"].between(-180, 180))).sum())
    row["n_nat"] = int(raw["timestamp"].isna().sum())
    df = raw.dropna(subset=["timestamp"]).sort_values("timestamp", kind="stable")
    n0 = len(df)
    df = df.drop_duplicates("timestamp", ignore_index=True)
    row["n_dup"] = n0 - len(df)
    ts = df["timestamp"]
    v = ((ts >= TIME_MIN) & (ts < TIME_MAX)).to_numpy()
    row["n_bad_time"] = int((~v).sum())
    row["n_points"] = len(df)
    row["start"], row["end"] = ts.min(), ts.max()
    row["start_valid"] = ts[v].min() if v.any() else pd.NaT
    row["end_valid"] = ts[v].max() if v.any() else pd.NaT

    lat = df["lat"].to_numpy(float)
    lon = df["lon"].to_numpy(float)
    t = (ts - EPOCH).dt.total_seconds().to_numpy()
    fid = df["file"].astype(str).to_numpy()

    # ---- bước giữa hai điểm liên tiếp: mọi bước, không giới hạn dt
    dt = np.diff(t)
    dist = haversine_m(lat[:-1], lon[:-1], lat[1:], lon[1:])
    speed = np.where(dt > 0, dist / np.where(dt > 0, dt, 1.0) * 3.6, np.nan)
    agg["n_steps"] += len(dt)
    row["n_steps"] = len(dt)
    row["median_dt_s"] = float(np.median(dt)) if len(dt) else np.nan
    for s in (1, 2, 5):
        row[f"share_dt_{s}s"] = float(np.mean(np.round(dt) == s)) if len(dt) else np.nan
    for m in GAP_MARKS_MIN:
        row[f"n_gap_gt_{m}min"] = int((dt > m * 60).sum())
    for m in (1000, 2000):
        row[f"n_speed_gt_{m}"] = int((speed > m).sum())

    # ---- không gian
    bj = in_box(lat, lon, BJ_BOX)
    cn = in_box(lat, lon, CN_BOX)
    row["share_bj"] = float(bj.mean())
    row["share_cn"] = float(cn.mean())
    row["n_in_bj"] = int(bj.sum())
    row["n_outside_cn"] = int((~cn).sum())
    row["lat_med"], row["lon_med"] = float(np.median(lat)), float(np.median(lon))

    # ---- giờ địa phương (giả thuyết, kiểm chứng ở notebook 04 mục 10); chỉ điểm có timestamp hợp lệ
    off = local_offset_h(lat, lon)
    tl = t + off * 3600.0
    day_loc = np.floor(tl / 86400).astype(np.int64)
    row["n_days"] = int(np.unique(day_loc[v]).size)
    # số ngày địa phương từ ngày đầu đến ngày cuối (tính cả hai đầu), cùng đơn vị với n_days
    row["n_span_days"] = int(day_loc[v].max() - day_loc[v].min() + 1) if v.any() else 0

    # ---- phút có dữ liệu: phút (giờ địa phương) có ít nhất một điểm
    mins = np.unique(np.floor(tl[v] / 60).astype(np.int64))
    row["data_hours"] = len(mins) / 60

    ctx = dict(u=u, df=df, ts=ts, v=v, lat=lat, lon=lon, t=t, fid=fid, dt=dt, dist=dist, speed=speed,
               bj=bj, cn=cn, tl=tl, mins=mins, labels=labels)
    return row, ctx


# -----------------------------------------------------------------------------
# Chủ đề "speed" (notebook 02): khoảng lấy mẫu, tốc độ, khoảng trống, nhãn phương tiện
# -----------------------------------------------------------------------------
def _speed(c, agg):
    dt, speed, t = c["dt"], c["speed"], c["t"]
    agg["dt"].append(dt.astype(np.float32))
    pos = (dt > 0) & (speed > 0)
    agg["dt_sp"] += np.histogram2d(dt[pos], speed[pos], bins=[DT_BINS, SPEED_BINS])[0]
    for i, cut in enumerate(DT_CUTS_S):
        le = dt <= cut
        agg["n_le_cut"][i] += int(le.sum())
        agg["cut_mark"][i] += [int((le & (speed > m)).sum()) for m in SPEED_MARKS]
    lb = c["labels"]
    if lb is not None:
        t0 = t[:-1]
        for r in lb.itertuples(index=False):
            a = (r.start - EPOCH).total_seconds()
            b = (r.end - EPOCH).total_seconds()
            i0, i1 = np.searchsorted(t0, [a, b])
            sp = speed[i0:i1]
            sp = sp[np.isfinite(sp) & (sp > 0)]
            md_ = agg["modes"][r.mode]
            md_["n_labels"] += 1
            md_["hours"] += (b - a) / 3600
            md_["n_steps"] += int(sp.size)
            md_["hist"] += np.histogram(sp, bins=SPEED_BINS)[0]


# -----------------------------------------------------------------------------
# Chủ đề "outliers" (notebook 03): chuỗi đi ra rồi quay về
# -----------------------------------------------------------------------------
def find_excursions(lat, lon, t, dt, speed, same_file):
    """Dò các chuỗi X1..Xk "đi ra rồi quay về", tham lam từ trái sang phải, không chồng nhau.

        A ──► X1 ... Xk ──► B
    - bước vào A→X1 và bước ra Xk→B: cùng file, dt ≤ EXC_STEP_DT_S, tốc độ > EXC_SPEED_KMH
    - mọi bước từ A đến B nằm trong cùng một file và không có khoảng trống (dt > EXC_STEP_DT_S)
    - bỏ cả chuỗi thì A→B có tốc độ ≤ EXC_SPEED_KMH
    - không giới hạn k hay thời lượng (D11): để thấy đủ mọi độ dài chuỗi
    Với mỗi bước vào, lấy bước ra gần nhất thoả điều kiện. Trả về list (e, j): A = điểm e, B = điểm j + 1.
    """
    stop = ~same_file | (dt > EXC_STEP_DT_S)                    # sang file khác hoặc khoảng trống: chuỗi dừng
    fast = ~stop & (speed > EXC_SPEED_KMH)
    stop_idx = np.nonzero(stop)[0]
    found, last_end = [], -1
    for e in np.nonzero(fast)[0]:
        if e <= last_end:
            continue
        g = np.searchsorted(stop_idx, e)
        hi = (stop_idx[g] - 1) if g < len(stop_idx) else len(dt) - 1
        js = e + 1 + np.nonzero(fast[e + 1:hi + 1])[0]          # các bước ra có thể
        if not len(js):
            continue
        dur = t[js + 1] - t[e]
        v_ab = haversine_m(lat[e], lon[e], lat[js + 1], lon[js + 1]) / dur * 3.6
        ok = np.nonzero(v_ab <= EXC_SPEED_KMH)[0]
        if len(ok):
            j = int(js[ok[0]])
            found.append((int(e), j))
            last_end = j
    return found


def _outliers(c, agg):
    lat, lon, t, dt, speed, fid, ts = c["lat"], c["lon"], c["t"], c["dt"], c["speed"], c["fid"], c["ts"]
    same_file = fid[:-1] == fid[1:]
    is_air = np.zeros(len(dt), dtype=bool)          # bước nằm trong nhãn airplane: chỉ để đối chiếu
    lb = c["labels"]
    if lb is not None:
        for r in lb[lb["mode"] == "airplane"].itertuples(index=False):
            i0, i1 = np.searchsorted(t[:-1], [(r.start - EPOCH).total_seconds(), (r.end - EPOCH).total_seconds()])
            is_air[i0:i1] = True
    rows = []
    for e, j in find_excursions(lat, lon, t, dt, speed, same_file):
        xs = np.arange(e + 1, j + 1)                # các điểm X1..Xk
        rows.append({
            "user": c["u"], "file": fid[e], "start_utc": ts.iloc[e], "lat_a": lat[e], "lon_a": lon[e],
            "k": j - e, "dur_s": t[j + 1] - t[e],
            "ab_m": float(haversine_m(lat[e], lon[e], lat[j + 1], lon[j + 1])),
            "max_dist_m": float(haversine_m(lat[e], lon[e], lat[xs], lon[xs]).max()),
            "max_kmh": float(speed[e:j + 1].max()),
            "airplane": bool(is_air[e:j + 1].any())})
    if rows:
        agg["exc"].append(pd.DataFrame(rows))


# -----------------------------------------------------------------------------
# Chủ đề "space_time" (notebook 04): không gian, kiểm chứng múi giờ, theo tháng / năm
# -----------------------------------------------------------------------------
def _space_time(c, agg):
    lat, lon, t, tl, v, cn, bj, ts, mins = c["lat"], c["lon"], c["t"], c["tl"], c["v"], c["cn"], c["bj"], c["ts"], c["mins"]
    agg["world"] += np.histogram2d(lat, lon, bins=[WORLD_LAT, WORLD_LON])[0]
    agg["bj"] += np.histogram2d(lat[bj], lon[bj], bins=[BJ_LAT, BJ_LON])[0]
    hour_utc = ((t // 3600) % 24).astype(int)
    hour_loc = ((tl // 3600) % 24).astype(int)
    agg["hour_utc_cn"] += np.bincount(hour_utc[v & cn], minlength=24)
    agg["hour_loc_cn"] += np.bincount(hour_loc[v & cn], minlength=24)
    agg["hour_utc_out"] += np.bincount(hour_utc[v & ~cn], minlength=24)
    agg["hour_loc_out"] += np.bincount(hour_loc[v & ~cn], minlength=24)
    # theo tháng (UTC)
    m = ts[v].dt.tz_convert(None).to_numpy().astype("datetime64[M]")
    mm, cnt = np.unique(m, return_counts=True)
    for a, k in zip(mm, cnt):
        agg["month_pts"][str(a)] += int(k)
        agg["month_users"][str(a)].add(c["u"])
    # phút có dữ liệu theo năm × giờ (giờ địa phương)
    m_hour = ((mins // 60) % 24).astype(int)
    m_year = (mins // 1440).astype("datetime64[D]").astype("datetime64[Y]").astype(int) + 1970
    for y in np.unique(m_year):
        agg["year_hour"][int(y)] += np.bincount(m_hour[m_year == y], minlength=24)


# -----------------------------------------------------------------------------
# Chủ đề "coverage" (notebook 05): độ phủ theo thứ × giờ, khoảng trống
# -----------------------------------------------------------------------------
def _coverage(c, agg):
    mins, dt, dist, tl, v, lat, lon, bj = c["mins"], c["dt"], c["dist"], c["tl"], c["v"], c["lat"], c["lon"], c["bj"]
    m_hour = ((mins // 60) % 24).astype(int)
    m_day = mins // 1440
    m_wday = ((m_day + 3) % 7).astype(int)          # 0 = thứ Hai; 01/01/1970 là thứ Năm
    agg["cov_ids"].append(c["u"])
    agg["cov_wd_hour"].append(np.bincount(m_wday * 24 + m_hour, minlength=168).reshape(7, 24).astype(np.int32))
    day_hour = np.unique(m_day * 24 + m_hour)       # các cặp (ngày, giờ) có dữ liệu
    agg["days_hour"].append(np.bincount((day_hour % 24).astype(int), minlength=24).astype(np.int32))
    dh_wk = ((day_hour // 24 + 3) % 7 >= 5).astype(int)      # 0 = ngày thường, 1 = cuối tuần
    agg["days_hour_wk"].append(np.bincount(dh_wk * 24 + (day_hour % 24).astype(int), minlength=48)
                               .reshape(2, 24).astype(np.int32))
    # mọi khoảng trống dài hơn mốc nhỏ nhất, hai đầu có timestamp hợp lệ
    gi = np.nonzero((dt > GAP_MARKS_MIN[0] * 60) & v[:-1] & v[1:])[0]
    if len(gi):
        agg["gaps"].append(pd.DataFrame({
            "user": c["u"],
            "start_local": pd.to_datetime(tl[gi], unit="s"),
            "end_local": pd.to_datetime(tl[gi + 1], unit="s"),
            "gap_h": dt[gi] / 3600, "dist_m": dist[gi],
            "lat": lat[gi], "lon": lon[gi], "in_bj": bj[gi]}))


_TOPIC_FN = {"speed": _speed, "outliers": _outliers, "space_time": _space_time, "coverage": _coverage}


# -----------------------------------------------------------------------------
# Chạy cho mọi user và đóng gói kết quả
# -----------------------------------------------------------------------------
def run(topics=(), users=None, verbose=True):
    """Quét các user (mặc định: tất cả trong data/interim), tính phần chung và các chủ đề được yêu cầu.

    Trả về SimpleNamespace với users, files, A (dict mảng tổng hợp) và, tuỳ chủ đề:
    modes ("speed"), exc ("outliers"), months ("space_time"), gaps ("coverage").
    """
    bad = set(topics) - set(TOPICS)
    if bad:
        raise ValueError(f"Chủ đề không hợp lệ: {bad}. Chọn trong {TOPICS}")
    all_users = interim.require_interim()
    ulist = [u for u in all_users if users is None or u in set(users)]
    agg = _new_agg()
    t_start = time.time()
    for i, u in enumerate(ulist, 1):
        row, ctx = _base(u, agg)
        if ctx is not None:
            for tp in topics:
                _TOPIC_FN[tp](ctx, agg)
        agg["users"].append(row)
        if verbose and (i % 20 == 0 or i == len(ulist)):
            print(f"[{i}/{len(ulist)}] đã đọc tới user {u} ({time.time() - t_start:.0f} giây)")

    users_df = pd.DataFrame(agg["users"])
    users_df["span_days"] = (users_df["end_valid"] - users_df["start_valid"]).dt.total_seconds() / 86400
    users_df["active_ratio"] = users_df["n_days"] / users_df["n_span_days"].clip(lower=1)   # luôn trong (0, 1]
    files_df = pd.concat(agg["files"], ignore_index=True)[["user", "file", "n_points", "start", "end"]]
    files_df["duration_min"] = (files_df["end"] - files_df["start"]).dt.total_seconds() / 60
    A = {"n_steps": agg["n_steps"]}
    out = SimpleNamespace(users=users_df, files=files_df, A=A)

    if "speed" in topics:
        dt = np.concatenate(agg["dt"]) if agg["dt"] else np.zeros(0, np.float32)
        names = sorted(agg["modes"])
        A.update(
            dt_q=np.nanquantile(dt, QUANTILES), dt_max=np.nanmax(dt),
            gap_cnt=np.array([(dt > m * 60).sum() for m in GAP_MARKS_MIN]),
            dt_hist=np.histogram(dt[dt > 0], bins=DT_BINS)[0],
            dt_sp_hist=agg["dt_sp"], cut_mark=agg["cut_mark"], n_le_cut=agg["n_le_cut"],
            mode_names=np.array(names, dtype=str),
            mode_hist=np.array([agg["modes"][k]["hist"] for k in names]).reshape(len(names), len(SPEED_BINS) - 1))
        out.modes = pd.DataFrame([{"mode": k, **{x: agg["modes"][k][x] for x in ("n_labels", "hours", "n_steps")}}
                                  for k in names], columns=["mode", "n_labels", "hours", "n_steps"])
    if "outliers" in topics:
        cols = ["user", "file", "start_utc", "lat_a", "lon_a", "k", "dur_s", "ab_m", "max_dist_m", "max_kmh", "airplane"]
        out.exc = pd.concat(agg["exc"], ignore_index=True) if agg["exc"] else pd.DataFrame(columns=cols)
    if "space_time" in topics:
        years = sorted(agg["year_hour"])
        A.update(world=agg["world"], bj=agg["bj"],
                 hour_utc_cn=agg["hour_utc_cn"], hour_loc_cn=agg["hour_loc_cn"],
                 hour_utc_out=agg["hour_utc_out"], hour_loc_out=agg["hour_loc_out"],
                 years=np.array(years, dtype=int),
                 year_hour=np.array([agg["year_hour"][y] for y in years]).reshape(-1, 24))
        keys = sorted(agg["month_pts"])
        out.months = pd.DataFrame({"month": keys,
                                   "n_points": [agg["month_pts"][k] for k in keys],
                                   "n_users": [len(agg["month_users"][k]) for k in keys]})
    if "coverage" in topics:
        A.update(cov_ids=np.array(agg["cov_ids"], dtype=str),
                 cov_wd_hour=np.stack(agg["cov_wd_hour"]) if agg["cov_wd_hour"] else np.zeros((0, 7, 24), np.int32),
                 days_hour=np.stack(agg["days_hour"]) if agg["days_hour"] else np.zeros((0, 24), np.int32),
                 days_hour_wk=np.stack(agg["days_hour_wk"]) if agg["days_hour_wk"] else np.zeros((0, 2, 24), np.int32))
        gap_cols = ["user", "start_local", "end_local", "gap_h", "dist_m", "lat", "lon", "in_bj"]
        out.gaps = pd.concat(agg["gaps"], ignore_index=True) if agg["gaps"] else pd.DataFrame(columns=gap_cols)
    return out
