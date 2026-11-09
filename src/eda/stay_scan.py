"""Kiểm chứng ngưỡng stay point bằng nhãn phương tiện (notebook 09).

Ý tưởng: labels.txt (69 user) ghi các khoảng thời gian người dùng ĐANG DI CHUYỂN (walk, bus, car...).
Chạy thuật toán stay point (Li et al., 2008) chỉ trên các điểm nằm trong những khoảng đó: mọi stay
tìm được đều là STAY GIẢ (kẹt xe, chờ đèn, chờ tàu, đi bộ loanh quanh). Đo tỷ lệ này với từng (D, T).

Đo được: ngưỡng có nhận nhầm lúc di chuyển thành stay không (dương tính giả).
Không đo được: ngưỡng có bỏ sót lần ở lại thật không (không có nhãn "đang ở yên").

Đọc dữ liệu đã lọc (data/processed/clean) và nhãn (data/interim/labels). Thời gian nhãn là UTC (A1).
Kết quả từng user được lưu tạm ở data/interim/eda_stays_labels/ để chạy lại nhanh.
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd

from eda import split
from preprocess import interim
from preprocess.clean_trajectory import CLEAN_DIR, EPOCH, haversine_m
from stays.detect import _prepare

CACHE_DIR = interim.INTERIM_DIR / "eda_stays_labels"
D_GRID = [100, 200, 300]          # mét
T_GRID_MIN = [10, 20, 30]         # phút
CHOSEN = (200, 30)                # Li et al. (2008), mục 5.1.2
WINDOW = 512                      # số điểm tính bằng numpy cho mọi điểm neo cùng lúc (đi bộ 1 điểm/giây cần vài trăm điểm mới ra khỏi 200 m)


def labeled_users(clean_dir: Path = CLEAN_DIR) -> list[str]:
    """User vừa có nhãn vừa có dữ liệu đã lọc, chỉ trong nhóm validation (D17)."""
    have = set(interim.list_stems(Path(clean_dir))) & set(split.val_users())
    return sorted(u for u in interim.list_stems(interim.INTERIM_DIR / "labels") if u in have)


def _exits(lat, lon, seg, D, window=WINDOW):
    """ex[i] = điểm đầu tiên sau i cách i hơn D hoặc thuộc đoạn khác; -1 nếu chưa tìm thấy trong window điểm."""
    n = len(lat)
    ex = np.full(n, -1, dtype=np.int64)
    for w in range(1, min(window, n - 1) + 1):
        idx = np.nonzero(ex[:n - w] == -1)[0]
        if not len(idx):
            break
        out = (seg[idx + w] != seg[idx]) | (haversine_m(lat[idx], lon[idx], lat[idx + w], lon[idx + w]) > D)
        hit = idx[out]
        ex[hit] = hit + w
    return ex


def _exit_long(lat, lon, i, start, stop, D):
    """Điểm đầu tiên trong [start, stop) cách điểm i hơn D; stop nếu không có."""
    s, step = start, 256                       # cửa sổ quét tăng dần: phần lớn ra khỏi bán kính sớm
    while s < stop:
        e = min(stop, s + step)
        out = np.nonzero(haversine_m(lat[i], lon[i], lat[s:e], lon[s:e]) > D)[0]
        if len(out):
            return s + int(out[0])
        s, step = e, step * 2
    return stop


def user_false_stays(user: str, clean_dir: Path = CLEAN_DIR) -> pd.DataFrame:
    """Chạy stay point trong các đoạn có nhãn của một user, với mọi (D, T) trong lưới.

    Trả về một dòng mỗi (nhãn, D, T): mode, số giờ của đoạn, số stay giả, số giờ nằm trong stay giả.
    Đoạn có nhãn được cắt thêm ở khoảng trống > 30 phút (giống bước 4), để không coi lúc tắt máy là stay.
    Cùng thuật toán với stays.detect.detect_stays (Li et al., 2008), chạy gộp mọi đoạn để nhanh:
    điểm ra khỏi bán kính chỉ phụ thuộc D nên được tính một lần cho cả ba giá trị T.
    """
    lb = interim.load_labels(user)
    df = interim.read_df(Path(clean_dir) / user)
    if lb is None or df is None or df.empty:
        return pd.DataFrame()
    d = _prepare(df)
    t_all = (d["timestamp"] - EPOCH).dt.total_seconds().to_numpy()
    lat_all, lon_all = d["lat"].to_numpy(float), d["lon"].to_numpy(float)

    # ghép các điểm nằm trong từng nhãn; lab = số thứ tự nhãn, seg = đoạn con (cắt ở khoảng trống > 30 phút)
    idx, lab = [], []
    for k, r in enumerate(lb.itertuples(index=False)):
        a = np.searchsorted(t_all, (r.start - EPOCH).total_seconds(), side="left")
        b = np.searchsorted(t_all, (r.end - EPOCH).total_seconds(), side="right")
        if b - a >= 2:
            idx.append(np.arange(a, b))
            lab.append(np.full(b - a, k))
    if not idx:
        return pd.DataFrame()
    idx, lab = np.concatenate(idx), np.concatenate(lab)
    t, lat, lon = t_all[idx], lat_all[idx], lon_all[idx]
    brk = np.r_[True, (lab[1:] != lab[:-1]) | (np.diff(t) > 30 * 60)]
    seg = np.cumsum(brk)
    seg_end = np.r_[np.nonzero(brk)[0][1:], len(t)][seg - 1]          # chỉ số đầu đoạn kế tiếp

    # số giờ có điểm của mỗi nhãn (tổng độ dài các đoạn con)
    first = np.nonzero(brk)[0]
    seg_hours = (t[seg_end[first] - 1] - t[first]) / 3600
    lab_hours = np.bincount(lab[first], weights=seg_hours, minlength=len(lb))

    rows = []
    for D in D_GRID:
        ex = _exits(lat, lon, seg, D)
        long_cache = {}
        for T in T_GRID_MIN:
            n_false = np.zeros(len(lb), dtype=np.int64)
            f_hours = np.zeros(len(lb))
            # điểm neo có thể là stay: đã biết điểm ra và ở trong bán kính đủ lâu, hoặc chưa biết điểm ra
            # nhưng phần còn lại của đoạn đủ dài. Các điểm neo khác chắc chắn không phải stay (i += 1).
            known = ex != -1
            dur_known = np.where(known, t[np.where(known, ex, 1) - 1] - t, 0)
            cand = np.nonzero((known & (dur_known >= T * 60)) |
                              (~known & (t[seg_end - 1] - t >= T * 60)))[0]
            i = 0
            while True:
                k = np.searchsorted(cand, i)
                if k == len(cand):
                    break
                i = int(cand[k])
                e = ex[i]
                if e == -1:
                    if i not in long_cache:
                        long_cache[i] = _exit_long(lat, lon, i, i + WINDOW + 1, seg_end[i], D)
                    e = long_cache[i]
                last = e - 1
                if t[last] - t[i] >= T * 60:
                    n_false[lab[i]] += 1
                    f_hours[lab[i]] += (t[last] - t[i]) / 3600
                    i = e
                else:
                    i += 1
            for k in np.unique(lab):
                rows.append({"user": user, "mode": lb["mode"].iat[k], "D": D, "T": T, "hours": float(lab_hours[k]),
                             "n_false": int(n_false[k]), "false_hours": float(f_hours[k])})
    return pd.DataFrame(rows)


def run(users, clean_dir: Path = CLEAN_DIR, cache_dir: Path = CACHE_DIR, verbose: bool = True) -> pd.DataFrame:
    """Gộp kết quả mọi user; dùng kết quả đã lưu nếu có."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    t0, parts = time.time(), []
    for n, u in enumerate(users, 1):
        f = cache_dir / f"{u}.pkl"
        if f.exists():
            r = pd.read_pickle(f)
        else:
            r = user_false_stays(u, clean_dir)
            pd.to_pickle(r, f)
        parts.append(r)
        if verbose and (n % 10 == 0 or n == len(users)):
            print(f"[{n}/{len(users)}] user {u} ({time.time() - t0:.0f} giây)")
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def false_stay_details(users, clean_dir: Path = CLEAN_DIR, D: float = CHOSEN[0], T_min: float = CHOSEN[1]) -> pd.DataFrame:
    """Chi tiết từng stay giả ở một cấu hình: stay giả trông như thế nào (đứng yên, đi loanh quanh, hay đang chạy xe).

    Cột: mode, lab_h (độ dài nhãn, giờ), stay_min, med_kmh (tốc độ trung vị giữa các điểm), path_km (quãng đường
    cộng dồn), rad95_m (95% điểm nằm trong bán kính này quanh tâm), at_label_edge (stay chạm đầu hoặc cuối nhãn).
    """
    from stays.detect import detect_stays
    rows = []
    for u in users:
        lb = interim.load_labels(u)
        df = interim.read_df(Path(clean_dir) / u)
        if lb is None or df is None or df.empty:
            continue
        d = _prepare(df)
        t = (d["timestamp"] - EPOCH).dt.total_seconds().to_numpy()
        lat, lon = d["lat"].to_numpy(float), d["lon"].to_numpy(float)
        for r in lb.itertuples(index=False):
            a = np.searchsorted(t, (r.start - EPOCH).total_seconds(), side="left")
            b = np.searchsorted(t, (r.end - EPOCH).total_seconds(), side="right")
            if b - a < 2:
                continue
            tt, la, lo = t[a:b], lat[a:b], lon[a:b]
            cuts = np.r_[0, np.nonzero(np.diff(tt) > 30 * 60)[0] + 1, len(tt)]
            for s, e in zip(cuts[:-1], cuts[1:]):
                for i, last in detect_stays(la[s:e], lo[s:e], tt[s:e], D, T_min * 60):
                    I = slice(s + i, s + last + 1)
                    st = np.diff(tt[I])
                    dd = haversine_m(la[I][:-1], lo[I][:-1], la[I][1:], lo[I][1:])
                    sp = np.where(st > 0, dd / np.maximum(st, 1) * 3.6, 0)
                    rows.append({"user": u, "mode": r.mode, "lab_h": (r.end - r.start).total_seconds() / 3600,
                                 "stay_min": (tt[s + last] - tt[s + i]) / 60, "med_kmh": float(np.median(sp)),
                                 "path_km": float(dd.sum() / 1000),
                                 "rad95_m": float(np.percentile(haversine_m(la[I].mean(), lo[I].mean(), la[I], lo[I]), 95)),
                                 "at_label_edge": bool((s + i == 0) or (s + last == len(tt) - 1))})
    return pd.DataFrame(rows)
