"""So sánh các cách chọn điểm neo cho stay point và kiểm tra gap-stay và chọn max gap (notebook 10 và 08, mục 1–2 (notebook 10, 11)).

Mọi cách dùng cùng D = 200 m, T = 30 phút và cùng cách chia đoạn như src/stays/detect.py
(gộp file của user, ngắt ở khoảng trống > 24 giờ). Chỉ khác cách chọn neo:

    li        Li et al. (2008): neo sớm nhất đủ T, chỉ mở rộng về sau.
    h1_mean   Chạy Li, đặt lại neo vào điểm gần nhất với trung bình tọa độ của stay, mở rộng hai phía; chỉ nhận
              nếu không ngắn hơn stay cũ (D13, đang dùng trong pipeline).

h1_mean nằm trong src/stays/detect.py (D13); file này import từ đó.
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd

from preprocess import interim
from preprocess.clean_trajectory import CLEAN_DIR, EPOCH, GAP_S, haversine_m
from stays.detect import DIST_M, MAX_GAP_S, TIME_S, _prepare, detect_stays, detect_stays_h1, mean_center

VARIANTS = ["li", "h1_mean"]
SPLIT_GAP_S = 10 * 60  # hai stay liền nhau, tâm cách < D, nghỉ < 10 phút: coi là stay bị tách đôi
D_FAR = DIST_M         # gap-stay có hai đầu khoảng trống cách nhau > D_FAR: "hai đầu xa nhau" (mục 1 (notebook 11))
CACHE_DIR = interim.INTERIM_DIR / "eda_stay_anchor_mean"      # thư mục mới: kết quả cũ (neo trung vị có trọng số) nằm ở eda_stay_anchor, không đọc lại


# =============================================================================
# CÔNG CỤ CHUNG
# =============================================================================
def chunks(t: np.ndarray, max_gap_s: float = MAX_GAP_S):
    """Chia thành các đoạn liên tục: ngắt ở khoảng trống > max_gap_s (như detect.py)."""
    brk = np.diff(t) > max_gap_s
    cuts = np.nonzero(brk)[0] + 1
    b = np.r_[0, cuts, len(t)]
    return list(zip(b[:-1], b[1:]))


# =============================================================================
# CÁC BIẾN THỂ (trên một đoạn liên tục; trả về list (L, R) theo thứ tự thời gian)
# =============================================================================
LI_WINDOW = 256        # chỉ để chạy nhanh: kết quả giống hệt WINDOW = 64 của detect.py (đã so trên user 000, 002)


def run_li(lat, lon, t, D=DIST_M, T=TIME_S):
    return detect_stays(lat, lon, t, D, T, window=LI_WINDOW)


def run_h1(lat, lon, t, D=DIST_M, T=TIME_S, li=None, stats=None):
    """h1_mean (định nghĩa ở stays/detect.py, D13)."""
    return detect_stays_h1(lat, lon, t, D, T, li=li, stats=stats)


RUNNERS = {"li": run_li, "h1_mean": run_h1}


# =============================================================================
# STAY CỦA MỘT USER, CHỈ SỐ
# =============================================================================
def load_user(user: str, clean_dir: Path = CLEAN_DIR):
    df = interim.read_df(Path(clean_dir) / user)
    if df is None or df.empty:
        return None
    d = _prepare(df)
    t = (d["timestamp"] - EPOCH).dt.total_seconds().to_numpy()
    return d["lat"].to_numpy(float), d["lon"].to_numpy(float), t


def stay_table(lat, lon, t, intervals) -> pd.DataFrame:
    """Một dòng mỗi stay: tâm (trung bình như detect.py), thời gian, phần khoảng trống, độ gọn."""
    rows = []
    for L, R in intervals:
        la, lo = lat[L:R + 1], lon[L:R + 1]
        cla, clo = la.mean(), lo.mean()
        dts = np.diff(t[L:R + 1])
        # khoảng trống dài nhất trong stay: hai đầu của nó cách nhau bao xa (gap-stay đáng tin khi hai đầu gần nhau)
        g = int(np.argmax(dts)) if len(dts) else 0
        gap_end_m = float(haversine_m(la[g], lo[g], la[g + 1], lo[g + 1])) if len(dts) and dts[g] > GAP_S else np.nan
        rows.append({"i0": L, "i1": R, "lat": cla, "lon": clo, "t0": t[L], "t1": t[R],
                     "dur_h": (t[R] - t[L]) / 3600, "gap_h": dts[dts > GAP_S].sum() / 3600,
                     "gap_end_m": gap_end_m,
                     "rad95_m": float(np.percentile(haversine_m(cla, clo, la, lo), 95)),
                     "n_points": R - L + 1})
    return pd.DataFrame(rows, columns=["i0", "i1", "lat", "lon", "t0", "t1", "dur_h", "gap_h", "gap_end_m",
                                       "rad95_m", "n_points"])


def user_stays(user: str, variants=VARIANTS, clean_dir: Path = CLEAN_DIR, stats=None, max_gap_s: float = MAX_GAP_S) -> dict:
    """{biến thể: (bảng stay, số giây chạy)} cho một user, trên toàn bộ dữ liệu đã lọc.

    stats: dict nhận số đếm của h1_mean (xem run_h1). max_gap_s: ngắt dữ liệu ở khoảng trống dài hơn mức này."""
    arr = load_user(user, clean_dir)
    res = {}
    if arr is None:
        return res
    lat, lon, t = arr
    li_cache = {}
    for v in variants:
        t0 = time.time()
        iv = []
        for a, b in chunks(t, max_gap_s):
            if b - a < 2:
                continue
            args = (lat[a:b], lon[a:b], t[a:b])
            if (a, b) not in li_cache:                           # Li trên đoạn này chỉ tính một lần, dùng chung
                li_cache[(a, b)] = run_li(*args)
            if v == "li":
                found = li_cache[(a, b)]
            else:
                found = run_h1(*args, li=li_cache[(a, b)], stats=stats)
            iv += [(a + L, a + R) for L, R in found]
        res[v] = (stay_table(lat, lon, t, iv), time.time() - t0)
    return res


def n_split(s: pd.DataFrame, D=DIST_M) -> int:
    """Số cặp stay liền nhau có tâm cách < D và nghỉ < SPLIT_GAP_S: một lần ở bị tách đôi."""
    if len(s) < 2:
        return 0
    d = haversine_m(s["lat"].to_numpy()[:-1], s["lon"].to_numpy()[:-1], s["lat"].to_numpy()[1:], s["lon"].to_numpy()[1:])
    brk = s["t0"].to_numpy()[1:] - s["t1"].to_numpy()[:-1]
    return int(((d < D) & (brk < SPLIT_GAP_S)).sum())


def overlap_h(a: pd.DataFrame, b: pd.DataFrame) -> float:
    """Số giờ nằm trong cả stay của a lẫn stay của b."""
    if a.empty or b.empty:
        return 0.0
    s1, e1 = a["t0"].to_numpy(), a["t1"].to_numpy()
    s2, e2 = b["t0"].to_numpy(), b["t1"].to_numpy()
    tot, j = 0.0, 0
    for x, y in zip(s1, e1):
        while j < len(s2) and e2[j] < x:
            j += 1
        k = j
        while k < len(s2) and s2[k] <= y:
            tot += max(0.0, min(y, e2[k]) - max(x, s2[k]))
            k += 1
    return tot / 3600


def summarize(user: str, res: dict) -> pd.DataFrame:
    rows = []
    base = res.get("li", (pd.DataFrame(), 0))[0]
    for v, (s, sec) in res.items():
        both = overlap_h(s, base)
        rows.append({"user": user, "variant": v, "n_stays": len(s),
                     "hours": s["dur_h"].sum(), "gap_hours": s["gap_h"].sum(),
                     "gps_hours": s["dur_h"].sum() - s["gap_h"].sum(),
                     "far_gap_hours": s.loc[s["gap_end_m"] > D_FAR, "dur_h"].sum(),
                     "n_split": n_split(s), "rad95_med_m": s["rad95_m"].median() if len(s) else np.nan,
                     "hours_only_variant": s["dur_h"].sum() - both,
                     "hours_only_li": base["dur_h"].sum() - both, "seconds": sec})
    return pd.DataFrame(rows)


def top_places(s: pd.DataFrame, k: int = 2) -> pd.DataFrame:
    """Gom stay bằng cluster_v1 (200 m, stay dài nhất làm tâm), trả về k địa điểm nhiều giờ nhất."""
    from places.cluster_v1 import cluster_v1
    if s.empty:
        return pd.DataFrame(columns=["lat", "lon", "hours"])
    pid = cluster_v1(s["lat"].to_numpy(), s["lon"].to_numpy(), s["dur_h"].to_numpy())
    g = s.assign(pid=pid)
    rows = []
    for p, x in g.groupby("pid"):
        a = x["dur_h"].idxmax()
        rows.append({"lat": x.at[a, "lat"], "lon": x.at[a, "lon"], "hours": x["dur_h"].sum()})
    return pd.DataFrame(rows).sort_values("hours", ascending=False).head(k).reset_index(drop=True)


def place_shift(user: str, res: dict, k: int = 2) -> pd.DataFrame:
    """Với mỗi biến thể: top-k địa điểm lệch bao nhiêu mét và đổi bao nhiêu giờ so với Li."""
    base = top_places(res["li"][0], k)
    rows = []
    for v, (s, _) in res.items():
        tp = top_places(s, k)
        for r in range(min(len(base), len(tp))):
            rows.append({"user": user, "variant": v, "rank": r + 1,
                         "shift_m": float(haversine_m(base.at[r, "lat"], base.at[r, "lon"], tp.at[r, "lat"], tp.at[r, "lon"])),
                         "hours_li": base.at[r, "hours"], "hours_variant": tp.at[r, "hours"]})
    return pd.DataFrame(rows)


def _user_job(u, variants, clean_dir, f):
    """Tính và lưu kết quả của một user (chạy trong tiến trình con)."""
    res = user_stays(u, variants, clean_dir)
    s = summarize(u, res) if res else pd.DataFrame()
    p = place_shift(u, res) if res else pd.DataFrame()
    pd.to_pickle((s, p), f)
    return u


def run_users(users, variants=VARIANTS, clean_dir: Path = CLEAN_DIR, cache_dir: Path = CACHE_DIR, verbose=True,
              tag: str = "full", n_jobs: int | None = None):
    """(bảng chỉ số, bảng lệch địa điểm) gộp mọi user; dùng kết quả đã lưu nếu có.

    tag: tên đuôi file lưu từng user ("full").
    n_jobs: số tiến trình chạy song song (mặc định: số nhân CPU - 1; 1 = chạy tuần tự).
    User lớn được chạy trước để các tiến trình xong gần cùng lúc.
    """
    import os
    from concurrent.futures import ProcessPoolExecutor, as_completed
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    f_of = {u: cache_dir / f"{u}_{tag}.pkl" for u in users}
    todo = [u for u in users if not f_of[u].exists()]
    size = {u: sum(Path(clean_dir, u + ext).stat().st_size for ext in (".parquet", ".pkl")
                   if Path(clean_dir, u + ext).exists()) for u in todo}
    todo.sort(key=lambda u: -size[u])
    n_jobs = n_jobs or max(1, (os.cpu_count() or 2) - 1)
    t0 = time.time()
    if verbose:
        print(f"{len(users) - len(todo)} user đã có kết quả, {len(todo)} user cần tính, {n_jobs} tiến trình")
    if todo and n_jobs > 1:
        with ProcessPoolExecutor(max_workers=n_jobs) as ex:
            futs = [ex.submit(_user_job, u, variants, clean_dir, f_of[u]) for u in todo]
            for n, fu in enumerate(as_completed(futs), 1):
                u = fu.result()
                if verbose:
                    print(f"[{n}/{len(todo)}] user {u} ({time.time() - t0:.0f} giây)")
    else:
        for n, u in enumerate(todo, 1):
            _user_job(u, variants, clean_dir, f_of[u])
            if verbose:
                print(f"[{n}/{len(todo)}] user {u} ({time.time() - t0:.0f} giây)")
    S, P = zip(*(pd.read_pickle(f_of[u]) for u in users)) if users else ([], [])
    S, P = pd.concat(S, ignore_index=True), pd.concat(P, ignore_index=True)
    keep = set(variants)      # file lưu từ lần chạy cũ có thể còn biến thể khác
    return S[S["variant"].isin(keep)].reset_index(drop=True), P[P["variant"].isin(keep)].reset_index(drop=True)


# =============================================================================
# NHẬN NHẦM TRÊN NHÃN (giống stay_scan.py, cho từng biến thể)
# =============================================================================
def user_false_stays(user: str, variants=VARIANTS, clean_dir: Path = CLEAN_DIR) -> pd.DataFrame:
    """Chạy từng biến thể chỉ trong các đoạn có nhãn di chuyển (cắt thêm ở khoảng trống > 30 phút).

    Một dòng mỗi (nhãn, biến thể): mode, số giờ có điểm, số stay giả, số giờ trong stay giả.
    """
    lb = interim.load_labels(user)
    arr = load_user(user, clean_dir)
    if lb is None or arr is None:
        return pd.DataFrame()
    lat, lon, t = arr
    rows = []
    for k, r in enumerate(lb.itertuples(index=False)):
        a = np.searchsorted(t, (r.start - EPOCH).total_seconds(), side="left")
        b = np.searchsorted(t, (r.end - EPOCH).total_seconds(), side="right")
        if b - a < 2:
            continue
        tt, la, lo = t[a:b], lat[a:b], lon[a:b]
        cuts = np.r_[0, np.nonzero(np.diff(tt) > GAP_S)[0] + 1, len(tt)]
        hours = sum((tt[e - 1] - tt[s]) / 3600 for s, e in zip(cuts[:-1], cuts[1:]))
        for v in variants:
            nf, fh = 0, 0.0
            for s, e in zip(cuts[:-1], cuts[1:]):
                if e - s < 2:
                    continue
                for L, R in RUNNERS[v](la[s:e], lo[s:e], tt[s:e]):
                    nf += 1
                    fh += (tt[s + R] - tt[s + L]) / 3600
            rows.append({"user": user, "label": k, "mode": r.mode, "variant": v, "hours": hours,
                         "n_false": nf, "false_hours": fh})
    return pd.DataFrame(rows)


def run_labels(users, variants=VARIANTS, clean_dir: Path = CLEAN_DIR, cache_dir: Path = CACHE_DIR, verbose=True):
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    parts, t0 = [], time.time()
    for n, u in enumerate(users, 1):
        f = cache_dir / f"{u}_labels.pkl"
        if f.exists():
            r = pd.read_pickle(f)
        else:
            r = user_false_stays(u, variants, clean_dir)
            pd.to_pickle(r, f)
        parts.append(r)
        if verbose and (n % 10 == 0 or n == len(users)):
            print(f"[{n}/{len(users)}] user {u} ({time.time() - t0:.0f} giây)")
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


# =============================================================================
# KIỂM TRA GAP-STAY (mục 1 (notebook 11))
# =============================================================================
def _hours_in(t0, t1, off_h, h_from, h_to, weekday_only=False):
    """Số giờ của đoạn [t0, t1] (UTC, giây) rơi vào khung giờ địa phương [h_from, h_to)."""
    if t1 <= t0:
        return 0.0
    a = pd.Timestamp(t0, unit="s") + pd.Timedelta(hours=off_h)
    b = pd.Timestamp(t1, unit="s") + pd.Timedelta(hours=off_h)
    tot = 0.0
    for d in pd.date_range(a.normalize(), b.normalize(), freq="D"):
        if weekday_only and d.dayofweek >= 5:
            continue
        lo, hi = max(a, d + pd.Timedelta(hours=h_from)), min(b, d + pd.Timedelta(hours=h_to))
        tot += max(0.0, (hi - lo).total_seconds() / 3600)
    return tot


def _top_detail(stays: dict, off: float, k: int = 3, user: str = "") -> pd.DataFrame:
    """k địa điểm nhiều giờ nhất của từng biến thể ({biến thể: bảng stay}), kèm giờ GPS/khoảng trống, giờ đêm
    (0–6h) và giờ hành chính (thứ 2–6, 9–17h) theo giờ địa phương, và giờ từ gap-stay hai đầu cách nhau > D_FAR."""
    from places.cluster_v1 import cluster_v1
    rows = []
    for v, s in stays.items():
        if s.empty:
            continue
        s = s.assign(pid=cluster_v1(s["lat"].to_numpy(), s["lon"].to_numpy(), s["dur_h"].to_numpy()))
        tot = s.groupby("pid")["dur_h"].sum().sort_values(ascending=False)
        for r, p in enumerate(tot.index[:k], 1):
            g = s[s["pid"] == p]
            a = g["dur_h"].idxmax()
            rows.append({"user": user, "variant": v, "rank": r, "lat": g.at[a, "lat"], "lon": g.at[a, "lon"],
                         "hours": g["dur_h"].sum(), "gap_hours": g["gap_h"].sum(),
                         "far_gap_hours": g.loc[g["gap_end_m"] > D_FAR, "dur_h"].sum(),
                         "night_hours": sum(_hours_in(x.t0, x.t1, off, 0, 6) for x in g.itertuples()),
                         "office_hours": sum(_hours_in(x.t0, x.t1, off, 9, 17, True) for x in g.itertuples()),
                         "n_stays": len(g)})
    return pd.DataFrame(rows)


def _tz_offset(user: str, clean_dir: Path = CLEAN_DIR) -> float:
    d = _prepare(interim.read_df(Path(clean_dir) / user))
    return float(d["tz_offset_h"].median())


def far_gap_ends(user: str, clean_dir: Path = CLEAN_DIR, n: int = 6) -> pd.DataFrame:
    """Mỗi gap-stay của li có hai đầu khoảng trống dài nhất cách nhau > D_FAR: khoảng trống dài bao lâu, tắt/bật lúc mấy
    giờ (giờ địa phương), có phải qua đêm không, và tốc độ của n điểm ngay trước / ngay sau khoảng trống.

    Nếu người dùng đang di chuyển ngay lúc tắt và lúc bật máy, hai đầu khoảng trống là điểm trên đường đi
    chứ không phải vị trí lúc ở yên; khi đó hai đầu xa nhau không có nghĩa là đã ở hai nơi khác nhau.
    """
    df = interim.read_df(Path(clean_dir) / user)
    if df is None or df.empty:
        return pd.DataFrame()
    d = _prepare(df)
    off = float(d["tz_offset_h"].median())
    t = (d["timestamp"] - EPOCH).dt.total_seconds().to_numpy()
    lat, lon = d["lat"].to_numpy(float), d["lon"].to_numpy(float)
    iv = []
    for a, b in chunks(t):
        if b - a >= 2:
            iv += [(a + L, a + R) for L, R in run_li(lat[a:b], lon[a:b], t[a:b])]
    s = stay_table(lat, lon, t, iv)
    s = s[s["gap_end_m"] > D_FAR]

    def kmh(a, b):
        a = max(a, 0)
        if b - a < 2:
            return np.nan
        dist = haversine_m(lat[a:b - 1], lon[a:b - 1], lat[a + 1:b], lon[a + 1:b]).sum()
        return dist / max(t[b - 1] - t[a], 1) * 3.6

    rows = []
    for r in s.itertuples():
        L, R = int(r.i0), int(r.i1)
        g = L + int(np.argmax(np.diff(t[L:R + 1])))
        st = pd.Timestamp(t[g], unit="s") + pd.Timedelta(hours=off)
        en = pd.Timestamp(t[g + 1], unit="s") + pd.Timedelta(hours=off)
        rows.append({"user": user, "dur_h": r.dur_h, "gap_h": (t[g + 1] - t[g]) / 3600, "end_m": r.gap_end_m,
                     "off_hour": st.hour, "on_hour": en.hour,
                     "overnight": bool((st.hour >= 18 or st.hour < 3) and 5 <= en.hour < 12),
                     "kmh_before": kmh(g - n + 1, g + 1), "kmh_after": kmh(g + 1, g + 1 + n)})
    return pd.DataFrame(rows)


def run_far_gap_ends(users, clean_dir: Path = CLEAN_DIR, n_jobs: int | None = None) -> pd.DataFrame:
    """far_gap_ends cho nhiều user, chạy song song."""
    import os
    from concurrent.futures import ProcessPoolExecutor
    n_jobs = n_jobs or max(1, (os.cpu_count() or 2) - 1)
    if n_jobs == 1:
        parts = [far_gap_ends(u, clean_dir) for u in users]
    else:
        with ProcessPoolExecutor(max_workers=n_jobs) as ex:
            parts = list(ex.map(far_gap_ends, users, [clean_dir] * len(users)))
    parts = [p for p in parts if len(p)]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


# =============================================================================
# MỤC 23: CHỌN ĐỘ DÀI KHOẢNG TRỐNG TỐI ĐA ĐƯỢC NỐI
# =============================================================================
DENSE_S = 120                       # đoạn GPS liên tục: hai điểm liền nhau cách nhau <= 2 phút
MASK_LEN_H = [0.5, 1, 2, 4, 8]      # độ dài khoảng trống nhân tạo thử xoá
LEN_BINS_H = [0.5, 1, 2, 4, 8, 12, 24, 36, 48, 72]
SCAN_GAP_S = 72 * 3600              # khoảng trống thật dài tối đa được khảo sát (dài hơn detect.MAX_GAP_S để xem mức > 24 giờ)


def _local_hour(ts, off_h):
    return int(((ts / 3600.0) + off_h) % 24)


def _is_night(h_start, h_end):
    """Qua đêm: tắt 18–3h, bật 5–12h (giống mục 1 (notebook 11)). Dùng cho khoảng trống thật."""
    return (h_start >= 18 or h_start < 3) and 5 <= h_end < 12


def real_gap_returns(user: str, clean_dir: Path = CLEAN_DIR) -> pd.DataFrame:
    """Mỗi khoảng trống thật 30 phút–72 giờ: độ dài, hai đầu cách nhau bao xa, có qua đêm không."""
    df = interim.read_df(Path(clean_dir) / user)
    if df is None or df.empty:
        return pd.DataFrame()
    d = _prepare(df)
    off = float(d["tz_offset_h"].median())
    t = (d["timestamp"] - EPOCH).dt.total_seconds().to_numpy()
    lat, lon = d["lat"].to_numpy(float), d["lon"].to_numpy(float)
    dt = np.diff(t)
    g = np.nonzero((dt > GAP_S) & (dt <= SCAN_GAP_S))[0]
    if len(g) == 0:
        return pd.DataFrame()
    dist = haversine_m(lat[g], lon[g], lat[g + 1], lon[g + 1])
    hs = np.array([_local_hour(x, off) for x in t[g]])
    he = np.array([_local_hour(x, off) for x in t[g + 1]])
    return pd.DataFrame({"user": user, "gap_h": dt[g] / 3600, "end_m": dist,
                         "overnight": [_is_night(a, b) for a, b in zip(hs, he)]})


def mask_test(user: str, clean_dir: Path = CLEAN_DIR, lengths_h=MASK_LEN_H, step_min: float = 15) -> pd.DataFrame:
    """Xoá khoảng trống nhân tạo trên đoạn GPS liên tục để biết "hai đầu gần nhau" đúng bao nhiêu.

    Với mỗi cửa sổ dài L giờ nằm trọn trong một đoạn GPS liên tục (cách nhau <= 2 phút):
      - near: điểm đầu và điểm cuối cửa sổ cách nhau <= D (cái mà quy tắc nối khoảng trống nhìn thấy);
      - stayed: MỌI điểm trong cửa sổ cách điểm đầu <= D (sự thật: người đó ở yên suốt thời gian đó).
    near mà không stayed = đi ra rồi quay lại (nối nhầm). Cửa sổ lấy mỗi step_min phút.
    """
    df = interim.read_df(Path(clean_dir) / user)
    if df is None or df.empty:
        return pd.DataFrame()
    d = _prepare(df)
    off = float(d["tz_offset_h"].median())
    t = (d["timestamp"] - EPOCH).dt.total_seconds().to_numpy()
    lat, lon = d["lat"].to_numpy(float), d["lon"].to_numpy(float)
    cuts = np.r_[0, np.nonzero(np.diff(t) > DENSE_S)[0] + 1, len(t)]
    rows = []
    for a0, b0 in zip(cuts[:-1], cuts[1:]):
        if b0 - a0 < 2:
            continue
        for L in lengths_h:
            span = L * 3600
            if t[b0 - 1] - t[a0] < span:
                continue
            starts = np.arange(t[a0], t[b0 - 1] - span, step_min * 60)
            ia = np.searchsorted(t[a0:b0], starts, side="left") + a0
            ib = np.searchsorted(t[a0:b0], starts + span, side="right") - 1 + a0
            for i, j in zip(ia, ib):
                if j <= i:
                    continue
                far = haversine_m(lat[i], lon[i], lat[i:j + 1], lon[i:j + 1]).max()
                end = haversine_m(lat[i], lon[i], lat[j], lon[j])
                hs = _local_hour(t[i], off)
                rows.append({"user": user, "L_h": L, "near": end <= DIST_M, "stayed": far <= DIST_M,
                             "overnight": hs >= 18 or hs < 5, "start_hour": hs})
    return pd.DataFrame(rows)


def _run_each(fn, users, clean_dir, n_jobs):
    import os
    from concurrent.futures import ProcessPoolExecutor
    n_jobs = n_jobs or max(1, (os.cpu_count() or 2) - 1)
    if n_jobs == 1:
        parts = [fn(u, clean_dir=clean_dir) for u in users]
    else:
        with ProcessPoolExecutor(max_workers=n_jobs) as ex:
            parts = list(ex.map(fn, users, [clean_dir] * len(users)))
    parts = [p for p in parts if len(p)]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


# =============================================================================
# MỤC 18–21: SO SÁNH CHI TIẾT li VÀ h1_mean
# =============================================================================
CMP = ["li", "h1_mean"]


def compare_user(user: str, clean_dir: Path = CLEAN_DIR):
    """Stay của li và h1_mean, số đếm cách h1_mean xử lý từng stay của Li, và hai địa điểm đầu kèm giờ đêm /
    giờ hành chính. Trả về (bảng stay, dict số đếm, bảng địa điểm)."""
    stats = {}
    res = user_stays(user, CMP, clean_dir, stats=stats)
    if not res:
        return pd.DataFrame(), {}, pd.DataFrame()
    stays = {v: res[v][0] for v in CMP}
    S = pd.concat([s.assign(user=user, variant=v) for v, s in stays.items()], ignore_index=True)
    stats = {"user": user, "n_li": len(stays["li"]), **{k: stats.get(k, 0) for k in ("moved", "kept", "absorbed")}}
    return S, stats, _top_detail(stays, _tz_offset(user, clean_dir), 2, user)


def _cmp_job(u, clean_dir, f):
    pd.to_pickle(compare_user(u, clean_dir), f)
    return u


def run_compare(users, clean_dir: Path = CLEAN_DIR, cache_dir: Path = CACHE_DIR, n_jobs: int | None = None,
                verbose=True):
    """compare_user cho nhiều user, song song, lưu từng user ở <user>_cmp.pkl.
    Trả về (mọi stay, số đếm theo user, hai địa điểm đầu theo user và biến thể)."""
    import os
    from concurrent.futures import ProcessPoolExecutor, as_completed
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    f_of = {u: cache_dir / f"{u}_cmp.pkl" for u in users}
    todo = [u for u in users if not f_of[u].exists()]
    n_jobs = n_jobs or max(1, (os.cpu_count() or 2) - 1)
    t0 = time.time()
    if verbose:
        print(f"{len(users) - len(todo)} user đã có kết quả, {len(todo)} user cần tính, {n_jobs} tiến trình")
    if todo and n_jobs > 1:
        with ProcessPoolExecutor(max_workers=n_jobs) as ex:
            futs = [ex.submit(_cmp_job, u, clean_dir, f_of[u]) for u in todo]
            for n, fu in enumerate(as_completed(futs), 1):
                u = fu.result()
                if verbose and (n % 20 == 0 or n == len(todo)):
                    print(f"[{n}/{len(todo)}] ({time.time() - t0:.0f} giây)")
    else:
        for u in todo:
            _cmp_job(u, clean_dir, f_of[u])
    parts = [pd.read_pickle(f_of[u]) for u in users]
    S = pd.concat([p[0] for p in parts if len(p[0])], ignore_index=True)
    H = pd.DataFrame([p[1] for p in parts if p[1]])
    PL = pd.concat([p[2] for p in parts if len(p[2])], ignore_index=True)
    return S, H, PL


def merge_example(user: str, S: pd.DataFrame, clean_dir: Path = CLEAN_DIR, max_h: float = 12.0):
    """Một stay của h1_mean chứa trọn nhiều stay của li nhất (dài <= max_h giờ để dễ nhìn).
    Trả về dict: điểm GPS trong khoảng đó (lat, lon, t), các stay li và stay h1_mean trong khoảng đó."""
    s = S[S["user"] == user]
    li, h1 = s[s["variant"] == "li"], s[s["variant"] == "h1_mean"]
    best, cnt = None, 1
    for r in h1[h1["dur_h"] <= max_h].itertuples():
        c = ((li["t0"] >= r.t0) & (li["t1"] <= r.t1)).sum()      # stay li nằm trọn trong stay h1_mean
        if c > cnt or (c == cnt and best is not None and c > 1 and r.dur_h < best.dur_h):
            best, cnt = r, c
    if best is None:
        return None
    lat, lon, t = load_user(user, clean_dir)
    pad = 10 * 60
    m = (t >= best.t0 - pad) & (t <= best.t1 + pad)
    inside = li[(li["t0"] >= best.t0) & (li["t1"] <= best.t1)].sort_values("t0")
    i0 = inside["i0"].astype(int).to_numpy()
    i1 = inside["i1"].astype(int).to_numpy()
    cut = np.minimum(i1 + 1, len(t) - 1)          # điểm đầu tiên sau mỗi stay Li: nơi Li cắt
    c = int(mean_center(lat, lon, i0[0], i1[0]))   # neo mới của h1_mean: gần trung bình tọa độ của stay Li đầu
    return {"user": user, "lat": lat[m], "lon": lon[m], "t": t[m], "li": inside, "h1": best, "n_li": len(inside),
            "li_anchor": (lat[i0], lon[i0]), "cut": (lat[cut], lon[cut], t[cut]), "h1_anchor": (lat[c], lon[c])}


VEHICLE_MODES = {"bus", "car", "taxi", "train", "subway", "airplane", "boat", "motorcycle"}


def gap_label_check(user: str, clean_dir: Path = CLEAN_DIR) -> pd.DataFrame:
    """Mỗi khoảng trống thật 30 phút–72 giờ của user có nhãn: độ dài, hai đầu cách nhau bao xa, và lúc tắt / lúc bật
    máy có nằm trong một đoạn nhãn di chuyển không (và nhãn gì). Nhãn chỉ phủ một phần dữ liệu, nên "không có nhãn"
    không có nghĩa là đứng yên."""
    lb = interim.load_labels(user)
    arr = load_user(user, clean_dir)
    if lb is None or arr is None:
        return pd.DataFrame()
    lat, lon, t = arr
    dt = np.diff(t)
    g = np.nonzero((dt > GAP_S) & (dt <= SCAN_GAP_S))[0]
    if len(g) == 0:
        return pd.DataFrame()
    st = np.array([(x - EPOCH).total_seconds() for x in lb["start"]])
    en = np.array([(x - EPOCH).total_seconds() for x in lb["end"]])
    modes = lb["mode"].to_numpy()
    order = np.argsort(st)
    st, en, modes = st[order], en[order], modes[order]

    def mode_at(x):
        k = np.searchsorted(st, x, side="right") - 1          # đoạn nhãn bắt đầu muộn nhất không sau x
        return modes[k] if k >= 0 and x <= en[k] else None
    off = [mode_at(t[i]) for i in g]
    on = [mode_at(t[i + 1]) for i in g]
    return pd.DataFrame({"user": user, "gap_h": dt[g] / 3600,
                         "end_m": haversine_m(lat[g], lon[g], lat[g + 1], lon[g + 1]),
                         "mode_off": off, "mode_on": on})


# =============================================================================
# MỤC 23.2: CHỌN MAX GAP (khoảng trống dài hơn mức này thì ngắt dữ liệu, không nối thành stay)
# =============================================================================
MAX_GAP_H = [4, 8, 12, 16, 20, 24, 36, 48, 72]   # 24 giờ là giá trị hiện tại của detect.MAX_GAP_S (quy ước, được đo như các mức khác)
BASE_CAP_H = 72                                  # chuẩn so sánh = mức dài nhất khảo sát (gần như không giới hạn); không dùng 24 để khỏi so với chính nó
MIN_NIGHT_H = 10.0              # dưới mức này coi là không còn bằng chứng đêm


def user_maxgap(user: str, caps_h=MAX_GAP_H, clean_dir: Path = CLEAN_DIR):
    """(chỉ số mỗi max gap, ba địa điểm đầu mỗi max gap) của h1_mean cho một user."""
    off = _tz_offset(user, clean_dir)
    rows, stays = [], {}
    for cap in caps_h:
        res = user_stays(user, ["h1_mean"], clean_dir, max_gap_s=cap * 3600)
        if not res:
            return None
        s = res["h1_mean"][0]
        stays[cap] = s
        rows.append({"user": user, "cap_h": cap, "n_stays": len(s), "hours": s["dur_h"].sum(),
                     "gap_hours": s["gap_h"].sum(), "n_split": n_split(s),
                     "night_h": sum(_hours_in(x.t0, x.t1, off, 0, 6) for x in s.itertuples()),
                     "office_h": sum(_hours_in(x.t0, x.t1, off, 9, 17, True) for x in s.itertuples())})
    P = _top_detail(stays, off, 3, user).rename(columns={"variant": "cap_h"})
    return pd.DataFrame(rows), P


def _maxgap_job(u, caps_h, clean_dir, f):
    pd.to_pickle(user_maxgap(u, caps_h, clean_dir), f)
    return u


def run_maxgap(users, caps_h=MAX_GAP_H, clean_dir: Path = CLEAN_DIR, cache_dir: Path = CACHE_DIR,
               n_jobs: int | None = None, verbose=True):
    """user_maxgap cho nhiều user, song song, lưu từng user ở <user>_maxgap.pkl (thiếu mức max gap nào thì tính lại user đó)."""
    import os
    from concurrent.futures import ProcessPoolExecutor, as_completed
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    f_of = {u: cache_dir / f"{u}_maxgap.pkl" for u in users}
    def _ok(u):                                  # có file và đủ các mức max gap đang hỏi
        if not f_of[u].exists():
            return False
        r = pd.read_pickle(f_of[u])
        return r is None or set(caps_h) <= set(r[0]["cap_h"])
    todo = [u for u in users if not _ok(u)]
    todo.sort(key=lambda u: -sum(Path(clean_dir, u + e).stat().st_size for e in (".parquet", ".pkl")
                                 if Path(clean_dir, u + e).exists()))
    n_jobs = n_jobs or max(1, (os.cpu_count() or 2) - 1)
    t0 = time.time()
    if verbose:
        print(f"{len(users) - len(todo)} user đã có kết quả, {len(todo)} user cần tính, {n_jobs} tiến trình")
    if todo and n_jobs > 1:
        with ProcessPoolExecutor(max_workers=n_jobs) as ex:
            futs = [ex.submit(_maxgap_job, u, caps_h, clean_dir, f_of[u]) for u in todo]
            for k, fu in enumerate(as_completed(futs), 1):
                fu.result()
                if verbose and (k % 10 == 0 or k == len(todo)):
                    print(f"[{k}/{len(todo)}] ({time.time() - t0:.0f} giây)")
    else:
        for u in todo:
            _maxgap_job(u, caps_h, clean_dir, f_of[u])
    parts = [pd.read_pickle(f_of[u]) for u in users]
    parts = [p for p in parts if p is not None]
    keep = set(caps_h)
    M = pd.concat([p[0] for p in parts], ignore_index=True)
    P = pd.concat([p[1] for p in parts], ignore_index=True)
    return M[M["cap_h"].isin(keep)].reset_index(drop=True), P[P["cap_h"].isin(keep)].reset_index(drop=True)


def _pick(P: pd.DataFrame, user: str, cap: int, col: str):
    """Địa điểm (trong ba địa điểm đầu) nhiều giờ `col` nhất của user ở max gap `cap`; None nếu col = 0 ở mọi nơi."""
    x = P[(P["user"] == user) & (P["cap_h"] == cap)]
    if x.empty or x[col].max() <= 0:
        return None
    r = x.loc[x[col].idxmax()]
    return float(r["lat"]), float(r["lon"])


def maxgap_summary(M: pd.DataFrame, P: pd.DataFrame, base: int = BASE_CAP_H) -> pd.DataFrame:
    """Bảng mỗi dòng một max gap, so với `base`: giờ còn lại, bằng chứng đêm / hành chính, đổi địa điểm, stay tách."""
    b = M[M["cap_h"] == base].set_index("user")
    out = []
    for cap, m in M.groupby("cap_h"):
        m = m.set_index("user")
        night = (100 * m["night_h"] / b["night_h"].where(b["night_h"] > 0)).dropna()
        office = (100 * m["office_h"] / b["office_h"].where(b["office_h"] > 0)).dropna()
        row = {"max gap (giờ)": cap, "số stay": m["n_stays"].sum(),
               "giờ stay còn lại (%)": 100 * m["hours"].sum() / b["hours"].sum(),
               "giờ gap còn lại (%)": 100 * m["gap_hours"].sum() / b["gap_hours"].sum(),
               "giờ đêm còn lại, trung vị user (%)": night.median(), "giờ đêm còn lại, p10 user (%)": night.quantile(0.1),
               "giờ hành chính còn lại, trung vị user (%)": office.median(),
               "giờ hành chính còn lại, p10 user (%)": office.quantile(0.1),
               "stay tách / 100 stay": 100 * m["n_split"].sum() / m["n_stays"].sum(),
               "user mất bằng chứng đêm": int(((b["night_h"] >= MIN_NIGHT_H) & (m["night_h"] < MIN_NIGHT_H)).sum())}
        for name, col in (("địa điểm 1", None), ("home", "night_hours"), ("office", "office_hours")):
            moved = []
            for u in b.index:
                if col is None:
                    x0 = P[(P["user"] == u) & (P["cap_h"] == base) & (P["rank"] == 1)]
                    x1 = P[(P["user"] == u) & (P["cap_h"] == cap) & (P["rank"] == 1)]
                    a_, c_ = ((float(x0["lat"].iloc[0]), float(x0["lon"].iloc[0])) if len(x0) else None,
                              (float(x1["lat"].iloc[0]), float(x1["lon"].iloc[0])) if len(x1) else None)
                else:
                    a_, c_ = _pick(P, u, base, col), _pick(P, u, cap, col)
                if a_ is None:
                    continue                                    # không có bằng chứng ở mốc so sánh: không đánh giá
                lim = 100.0 if col is None else DIST_M       # địa điểm 1: lệch > 100 m; home / office: khác nơi (> 200 m)
                moved.append(c_ is None or float(haversine_m(a_[0], a_[1], c_[0], c_[1])) > lim)
            row[f"{name} đổi nơi (% user)"] = 100 * np.mean(moved) if moved else np.nan
            row[f"{name}: n user"] = len(moved)
        out.append(row)
    return pd.DataFrame(out).set_index("max gap (giờ)")


def maxgap_pairwise(M: pd.DataFrame, P: pd.DataFrame, caps=(12, 20, 24, 36, 48, 72)) -> dict:
    """Mức đổi nơi (% user) giữa từng cặp max gap: hàng = mức chuẩn, cột = mức so. Một bảng cho mỗi loại địa điểm.
    Mỗi hàng chạy `maxgap_summary` với chuẩn khác nhau, nên tập user (có bằng chứng ở mức chuẩn) có thể khác chút giữa các hàng."""
    caps = list(caps)
    M2, P2 = M[M["cap_h"].isin(caps)], P[P["cap_h"].isin(caps)]
    out = {k: pd.DataFrame(index=caps, columns=caps, dtype=float) for k in ("địa điểm 1", "home", "office")}
    for base in caps:
        t = maxgap_summary(M2, P2, base=base)
        for k in out:
            for cap in caps:
                out[k].loc[base, cap] = t.loc[cap, f"{k} đổi nơi (% user)"]
    for k in out:
        out[k].index.name, out[k].columns.name = "chuẩn (giờ)", "so với (giờ)"
    return out
