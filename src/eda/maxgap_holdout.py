"""Đánh giá max gap bằng dự đoán sang giai đoạn khác (notebook 08, mục 23.4).

Với mỗi user và mỗi mức max gap: chia các tuần thành tuần chẵn và tuần lẻ. Home / office suy ra từ một nửa
(giờ trong khung đêm 0–6h, khung hành chính thứ 2–6 9–17h, kể cả gap-stay), rồi kiểm tra ở nửa còn lại: các điểm GPS
THẬT (máy đang bật) trong cùng khung giờ nằm trong SAME_M quanh nơi đã dự đoán chiếm bao nhiêu phần thời gian.
Đáp án là điểm GPS chứ không phải khoảng trống, nên không vòng tròn; mẫu số (GPS ở nửa kiểm tra) giống nhau cho mọi
mức max gap, nên so các mức với nhau là công bằng. Hạn chế: GPS chỉ có lúc máy bật, nên tuyệt đối thấp và thiên lệch.
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd

from eda import gap_evidence as ge
from eda import stay_anchor as sa
from preprocess.clean_trajectory import CLEAN_DIR, haversine_m

CAPS_H = [12, 20, 24, 36, 48]
SAME_M = 200.0
MIN_TEST_H = 3.0            # nửa kiểm tra phải có ít nhất ngần này giờ GPS trong khung thì mới tính
CACHE_DIR = sa.CACHE_DIR


class _Stays:
    def __init__(self, S, off):
        S = S.sort_values("t0").reset_index(drop=True)
        self.t0, self.t1, self.pid = S["t0"].to_numpy(), S["t1"].to_numpy(), S["pid"].to_numpy()
        self.off = off
        self.cen = {p: ge._center(g) for p, g in S.groupby("pid")}

    def vote(self, hour, days):
        """pid của stay đang phủ giờ `hour` (địa phương) của mỗi ngày; -1 nếu không có."""
        x = days * 86400.0 + hour * 3600 - self.off * 3600
        idx = np.searchsorted(self.t0, x, side="right") - 1
        ic = np.clip(idx, 0, None)
        ok = (idx >= 0) & (self.t1[ic] >= x)
        return np.where(ok, self.pid[ic], -1)

    def hours(self, h0, length_h, days):
        """(chỉ số ngày, pid, giờ) của các stay trong cửa sổ [h0, h0 + length_h) của mỗi ngày."""
        di, pp, hh = [], [], []
        ws = days * 86400.0 + h0 * 3600 - self.off * 3600
        we = ws + length_h * 3600
        lo = np.searchsorted(self.t1, ws, side="left")
        hi = np.searchsorted(self.t0, we, side="left")
        for i in range(len(days)):
            for j in range(lo[i], hi[i]):
                ov = min(self.t1[j], we[i]) - max(self.t0[j], ws[i])
                if ov > 0:
                    di.append(i); pp.append(self.pid[j]); hh.append(ov / 3600)
        return np.array(di, int), np.array(pp, int), np.array(hh, float)


def _top(pids, w, mask, exclude=None):
    """(pid nhiều nhất, tổng) trong các phần tử thoả mask, bỏ pid `exclude`."""
    m = mask & (pids >= 0)
    if exclude is not None:
        m = m & (pids != exclude)
    if not m.any():
        return None, 0.0
    s = pd.Series(w[m]).groupby(pids[m]).sum()
    return int(s.idxmax()), float(s.max())


def user_holdout(user: str, caps_h=CAPS_H, clean_dir: Path = CLEAN_DIR):
    from places.cluster_v1 import cluster_v1
    arr = sa.load_user(user, clean_dir)
    if arr is None:
        return None
    lat, lon, t = arr
    off = sa._tz_offset(user, clean_dir)
    dt = np.minimum(np.diff(t), sa.GAP_S)
    w = np.r_[dt, dt[-1]] / 3600.0                               # giờ đại diện của mỗi điểm GPS (tối đa 30 phút)
    loc = t + off * 3600
    day_pt = np.floor(loc / 86400).astype(np.int64)
    hour_pt = (loc % 86400) // 3600
    wd_pt = (day_pt + 3) % 7 < 5
    d0, d1 = int(day_pt.min()), int(day_pt.max())
    days = np.arange(d0, d1 + 1)
    half = (days // 7) % 2
    half_pt = (day_pt // 7) % 2
    weekday = (days + 3) % 7 < 5
    rows = []
    for cap in caps_h:
        res = sa.user_stays(user, ["h1_mean"], clean_dir, max_gap_s=cap * 3600)
        S = res["h1_mean"][0] if res else pd.DataFrame()
        if S.empty:
            continue
        S = S.copy()
        S["pid"] = cluster_v1(S["lat"].to_numpy(), S["lon"].to_numpy(), S["dur_h"].to_numpy())
        st = _Stays(S, off)
        di_h, pp_h, hh_h = st.hours(0, 6, days)
        di_o, pp_o, hh_o = st.hours(9, 8, days)
        k = weekday[di_o]
        di_o, pp_o, hh_o = di_o[k], pp_o[k], hh_o[k]
        for train in (0, 1):
            test = 1 - train
            home, nh = _top(pp_h, hh_h, half[di_h] == train)
            office, no = _top(pp_o, hh_o, half[di_o] == train, exclude=home)
            for kind, pid, win, wk in (("home", home, hour_pt < 6, None), ("office", office, (hour_pt >= 9) & (hour_pt < 17), wd_pt)):
                m = win & (half_pt == test)
                if wk is not None:
                    m = m & wk
                test_h = float(w[m].sum())
                if test_h < MIN_TEST_H:
                    continue
                if pid is None:
                    hit = 0.0
                else:
                    c = st.cen[pid]
                    near = haversine_m(c[0], c[1], lat[m], lon[m]) <= SAME_M
                    hit = float(w[m][near].sum())
                rows.append({"user": user, "cap_h": cap, "kind": kind, "train": train, "test_h": test_h,
                             "hit_h": hit, "score": hit / test_h, "predicted": pid is not None})
    return pd.DataFrame(rows)


def _job(u, caps_h, clean_dir, f):
    pd.to_pickle(user_holdout(u, caps_h, clean_dir), f)
    return u


def run_holdout(users, caps_h=CAPS_H, clean_dir: Path = CLEAN_DIR, cache_dir: Path = CACHE_DIR, n_jobs=None, verbose=True):
    """user_holdout cho nhiều user, song song, lưu từng user ở <user>_holdout.pkl (thiếu mức nào thì tính lại user đó)."""
    import os
    from concurrent.futures import ProcessPoolExecutor, as_completed
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    f_of = {u: cache_dir / f"{u}_holdout.pkl" for u in users}

    def _ok(u):
        if not f_of[u].exists():
            return False
        r = pd.read_pickle(f_of[u])
        return r is None or r.empty or set(caps_h) <= set(r["cap_h"])
    todo = [u for u in users if not _ok(u)]
    n_jobs = n_jobs or max(1, (os.cpu_count() or 2) - 1)
    t0 = time.time()
    if verbose:
        print(f"{len(users) - len(todo)} user đã có kết quả, {len(todo)} user cần tính, {n_jobs} tiến trình")
    if todo and n_jobs > 1:
        with ProcessPoolExecutor(max_workers=n_jobs) as ex:
            futs = [ex.submit(_job, u, caps_h, clean_dir, f_of[u]) for u in todo]
            for k, fu in enumerate(as_completed(futs), 1):
                fu.result()
                if verbose and (k % 10 == 0 or k == len(todo)):
                    print(f"[{k}/{len(todo)}] ({time.time() - t0:.0f} giây)")
    else:
        for u in todo:
            _job(u, caps_h, clean_dir, f_of[u])
    parts = [pd.read_pickle(f_of[u]) for u in users]
    parts = [p for p in parts if p is not None and len(p)]
    H = pd.concat(parts, ignore_index=True)
    return H[H["cap_h"].isin(set(caps_h))].reset_index(drop=True)


def holdout_summary(H: pd.DataFrame, base: int = 24, eps: float = 0.05) -> dict:
    """Mỗi (loại, mức max gap): điểm trung bình và so cặp với mức `base`, chỉ trên user có đủ mọi mức."""
    out = {}
    for kind, h in H.groupby("kind"):
        u = h.groupby(["user", "cap_h"])["score"].mean().unstack("cap_h")      # trung bình hai chiều dự đoán
        u = u.dropna()
        rows = []
        for cap in u.columns:
            d = u[cap] - u[base]
            rows.append({"max gap (giờ)": cap, "n user": len(u), "điểm trung bình": u[cap].mean(),
                         "điểm trung vị": u[cap].median(), "% user điểm ≥ 0,5": 100 * (u[cap] >= 0.5).mean(),
                         f"tốt hơn {base} giờ (user)": int((d > eps).sum()), f"kém hơn {base} giờ (user)": int((d < -eps).sum()),
                         f"như {base} giờ (user)": int((d.abs() <= eps).sum())})
        out[kind] = pd.DataFrame(rows).set_index("max gap (giờ)")
    return out
