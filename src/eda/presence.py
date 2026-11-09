"""Thời gian có mặt ở từng địa điểm theo giờ địa phương, cho notebook 12 (khung giờ home/office, A10).

Đầu vào: stay kèm place_id (data/processed/places_v1/<user>_stays) và điểm đã lọc (data/processed/clean).

Mỗi stay được tách thành các khoảng:
    - "gps": phần có điểm GPS liên tục (bước giữa hai điểm <= GAP_S = 30 phút);
    - "gap": phần nằm trong khoảng trống > 30 phút (máy tắt, A12). Đây là thời gian suy ra, không quan sát được.
Giờ địa phương của cả stay theo tz_offset_h của stay (giống arrive_local, leave_local).
Thứ trong tuần lấy theo ngày địa phương của từng phút: 1h sáng thứ Bảy thuộc thứ Bảy.

Notebook không chọn trước khung giờ nào. BASE_WINDOWS chỉ là khung đang thử ở slide CP1, dùng làm mốc so sánh.

Kết quả tính một lần, lưu tạm ở data/interim/eda_presence (xoá thư mục hoặc gọi refresh=True để tính lại).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

SRC = Path(__file__).resolve().parents[1]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
from preprocess import interim                                          # noqa: E402
from paths import PROJECT_ROOT                                          # noqa: E402
from preprocess.clean_trajectory import EPOCH, GAP_S, load_clean       # noqa: E402
from places.cluster_v1 import PLACES_DIR                                # noqa: E402

CACHE_DIR = PROJECT_ROOT / "data" / "interim" / "eda_presence"
TOP_K = 5                  # chỉ xét 5 địa điểm nhiều giờ nhất mỗi user (place_id 0..4)
BASE_WINDOWS = {"night": (20, 7), "work": (9, 18)}   # khung đang thử ở slide CP1 (mốc so sánh, chưa chốt)
NIGHT_GRID = [(s, e) for s in (19, 20, 21, 22, 23) for e in (5, 6, 7, 8)]
WORK_GRID = [(s, e) for s in (8, 9, 10) for e in (17, 18, 19)]
PROBE_HOUR = 3             # mốc giờ để đếm "đêm có mặt": stay chứa 3h sáng (giờ ít dữ liệu nhất, EDA mục 1 (notebook 04))
DAY_S = 86400
HOUR_S = 3600


# =============================================================================
# TÁCH STAY THÀNH KHOẢNG GPS / GAP
# =============================================================================
def _stay_pieces(t: np.ndarray, t0: float, t1: float):
    """Các khoảng (a, b, kind) trong [t0, t1] theo giây UTC; t đã sắp tăng dần."""
    i0, i1 = np.searchsorted(t, t0, "left"), np.searchsorted(t, t1, "right")
    tt = t[i0:i1]
    if len(tt) < 2:
        return [(t0, t1, "gps")]
    dt = np.diff(tt)
    big = np.nonzero(dt > GAP_S)[0]
    out, a = [], tt[0]
    for k in big:
        if tt[k] > a:
            out.append((a, tt[k], "gps"))
        out.append((tt[k], tt[k + 1], "gap"))
        a = tt[k + 1]
    if tt[-1] > a:
        out.append((a, tt[-1], "gps"))
    return out


def intervals_for_user(user: str, top_k: int = TOP_K) -> pd.DataFrame:
    """Bảng khoảng có mặt của một user ở top_k địa điểm.

    Cột: user, place_id, stay_idx, kind ("gps"/"gap"), a_loc, b_loc (giây theo giờ địa phương kể từ 1970-01-01).
    """
    cols = ["user", "place_id", "stay_idx", "kind", "a_loc", "b_loc"]
    s = interim.read_df(Path(PLACES_DIR) / f"{user}_stays")
    if s is None or s.empty or "place_id" not in s:
        return pd.DataFrame(columns=cols)
    s = s[s["place_id"] < top_k].reset_index(drop=True)
    pts = load_clean(user)
    if pts is None or pts.empty or s.empty:
        return pd.DataFrame(columns=cols)
    t = np.sort(np.unique((pts["timestamp"] - EPOCH).dt.total_seconds().to_numpy()))
    t0 = (s["arrive_utc"] - EPOCH).dt.total_seconds().to_numpy()
    t1 = (s["leave_utc"] - EPOCH).dt.total_seconds().to_numpy()
    off = s["tz_offset_h"].to_numpy(float) * HOUR_S
    rows = []
    for k in range(len(s)):
        for a, b, kind in _stay_pieces(t, t0[k], t1[k]):
            rows.append((user, int(s.at[k, "place_id"]), k, kind, a + off[k], b + off[k]))
    return pd.DataFrame(rows, columns=cols)


def load_intervals(users=None, refresh: bool = False, top_k: int = TOP_K) -> pd.DataFrame:
    """Khoảng có mặt của mọi user (có cache)."""
    if users is None:
        users = sorted({p.rsplit("_", 1)[0] for p in interim.list_stems(PLACES_DIR) if p.endswith("_stays")})
    if not users:
        raise SystemExit(f"Không có địa điểm trong {PLACES_DIR}. Chạy src/places/cluster_v1.py trước.")
    parts, t_start = [], time.time()
    for n, u in enumerate(users, 1):
        stem = CACHE_DIR / f"{u}_k{top_k}"
        d = None if refresh else interim.read_df(stem)
        if d is None:
            d = intervals_for_user(u, top_k)
            interim.save_df(d, stem)
        parts.append(d)
        if n % 20 == 0 or n == len(users):
            print(f"[{n}/{len(users)}] tới user {u} ({time.time() - t_start:.0f} giây)")
    out = pd.concat([p for p in parts if len(p)], ignore_index=True)
    out["place_id"] = out["place_id"].astype(int)
    return out


def load_stays(users=None, top_k: int = TOP_K) -> pd.DataFrame:
    """Bảng stay (top_k địa điểm) của các user, kèm giờ đến/đi địa phương."""
    if users is None:
        users = sorted({p.rsplit("_", 1)[0] for p in interim.list_stems(PLACES_DIR) if p.endswith("_stays")})
    parts = []
    for u in users:
        s = interim.read_df(Path(PLACES_DIR) / f"{u}_stays")
        if s is not None and len(s) and "place_id" in s:
            parts.append(s[s["place_id"] < top_k])
    return pd.concat(parts, ignore_index=True)


# =============================================================================
# CẮT KHOẢNG THEO GIỜ TRONG TUẦN
# =============================================================================
def week_hour_minutes(a_loc: np.ndarray, b_loc: np.ndarray) -> np.ndarray:
    """Tổng số phút của các khoảng [a, b) rơi vào từng ô (thứ, giờ): mảng 7 x 24, thứ 0 = thứ Hai."""
    a = np.asarray(a_loc, float)
    b = np.asarray(b_loc, float)
    keep = b > a
    a, b = a[keep], b[keep]
    if not len(a):
        return np.zeros((7, 24))
    h0 = np.floor(a / HOUR_S).astype(np.int64)
    h1 = np.floor((b - 1e-9) / HOUR_S).astype(np.int64)
    n = (h1 - h0 + 1)
    rep = np.repeat(np.arange(len(a)), n)
    hh = np.repeat(h0, n) + (np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n))
    lo = np.maximum(hh * HOUR_S, a[rep])
    hi = np.minimum((hh + 1) * HOUR_S, b[rep])
    day = hh // 24
    wday = (day + 3) % 7                      # 1970-01-01 là thứ Năm
    out = np.zeros(7 * 24)
    np.add.at(out, wday * 24 + hh % 24, (hi - lo) / 60)
    return out.reshape(7, 24)


def profiles(iv: pd.DataFrame) -> pd.DataFrame:
    """Phút có mặt theo (user, place_id, kind) x 168 ô (thứ*24 + giờ)."""
    rows = []
    for (u, p, kind), g in iv.groupby(["user", "place_id", "kind"], sort=True):
        m = week_hour_minutes(g["a_loc"].to_numpy(), g["b_loc"].to_numpy()).ravel()
        rows.append({"user": u, "place_id": p, "kind": kind, **{i: m[i] for i in range(168)}})
    df = pd.DataFrame(rows)
    return df.set_index(["user", "place_id", "kind"])


def hour_mask(start: int, end: int) -> np.ndarray:
    """Mặt nạ 24 giờ cho khung [start, end), cho phép vắt qua nửa đêm (ví dụ 20 -> 7)."""
    h = np.arange(24)
    return (h >= start) & (h < end) if start < end else (h >= start) | (h < end)


def window_minutes(prof168: np.ndarray, night: tuple, work: tuple):
    """(phút trong khung đêm mọi ngày, phút trong khung làm việc T2–T6) cho mỗi dòng của prof168 (n x 168)."""
    p = prof168.reshape(-1, 7, 24)
    nm = p[:, :, hour_mask(*night)].sum(axis=(1, 2))
    wm = p[:, :5, hour_mask(*work)].sum(axis=(1, 2))
    return nm, wm


# =============================================================================
# GÁN THỬ HOME / OFFICE THEO KHUNG (chỉ để đo độ nhạy, không phải quy tắc của bước 7)
# =============================================================================
def assign(prof: pd.DataFrame, night: tuple, work: tuple, kinds=("gps", "gap")) -> pd.DataFrame:
    """Với mỗi user: home = địa điểm nhiều phút đêm nhất; office = địa điểm nhiều phút làm việc nhất,
    ưu tiên khác home. same = True khi chính home cũng là nơi nhiều phút làm việc nhất."""
    p = prof[prof.index.get_level_values("kind").isin(kinds)].groupby(level=["user", "place_id"]).sum()
    nm, wm = window_minutes(p.to_numpy(float), night, work)
    d = pd.DataFrame({"night": nm, "work": wm}, index=p.index).reset_index()
    rows = []
    for u, g in d.groupby("user", sort=True):
        if g["night"].max() <= 0:
            home = -1
        else:
            home = int(g.loc[g["night"].idxmax(), "place_id"])
        top_work = int(g.loc[g["work"].idxmax(), "place_id"]) if g["work"].max() > 0 else -1
        rest = g[(g["place_id"] != home) & (g["work"] > 0)]
        office = int(rest.loc[rest["work"].idxmax(), "place_id"]) if len(rest) else -1
        rows.append({"user": u, "home": home, "office": office, "same": top_work == home and home >= 0})
    return pd.DataFrame(rows)


def sensitivity(prof: pd.DataFrame, kinds=("gps", "gap"), base=BASE_WINDOWS) -> pd.DataFrame:
    """Số user đổi home / office so với khung gốc khi dời từng mốc (đổi khung đêm giữ khung làm việc, và ngược lại)."""
    ref = assign(prof, base["night"], base["work"], kinds).set_index("user")
    rows = []
    for night in NIGHT_GRID:
        r = assign(prof, night, base["work"], kinds).set_index("user")
        rows.append({"đổi": "đêm", "khung": f"{night[0]}–{night[1]}h",
                     "home_khác": int((r["home"] != ref["home"]).sum()),
                     "office_khác": int((r["office"] != ref["office"]).sum()),
                     "home=office": int(r["same"].sum())})
    for work in WORK_GRID:
        r = assign(prof, base["night"], work, kinds).set_index("user")
        rows.append({"đổi": "làm việc", "khung": f"{work[0]}–{work[1]}h",
                     "home_khác": int((r["home"] != ref["home"]).sum()),
                     "office_khác": int((r["office"] != ref["office"]).sum()),
                     "home=office": int(r["same"].sum())})
    return pd.DataFrame(rows)


# =============================================================================
# ĐẾN / ĐI, ĐÊM CÓ MẶT
# =============================================================================
def arrive_leave(stays: pd.DataFrame) -> pd.DataFrame:
    """Giờ đến, giờ đi (địa phương), loại ngày (ngày thường / cuối tuần theo ngày địa phương) của từng stay."""
    a, b = pd.to_datetime(stays["arrive_local"]), pd.to_datetime(stays["leave_local"])
    return pd.DataFrame({"user": stays["user"].to_numpy(), "place_id": stays["place_id"].to_numpy(),
                         "source": stays["source"].to_numpy(),
                         "arrive_h": a.dt.hour.to_numpy(), "leave_h": b.dt.hour.to_numpy(),
                         "arrive_wkend": (a.dt.weekday >= 5).to_numpy(),
                         "leave_wkend": (b.dt.weekday >= 5).to_numpy()})


def nights_present(iv: pd.DataFrame, probe_hour: int = PROBE_HOUR, kinds=("gps", "gap")) -> pd.DataFrame:
    """Số đêm khác nhau (ngày địa phương có mốc probe_hour) mà user có mặt ở mỗi địa điểm."""
    x = iv[iv["kind"].isin(kinds)]
    a, b = x["a_loc"].to_numpy(float), x["b_loc"].to_numpy(float)
    first = np.ceil((a - probe_hour * HOUR_S) / DAY_S)      # ngày đầu tiên có mốc probe >= a
    last = np.floor((b - probe_hour * HOUR_S) / DAY_S)      # ngày cuối cùng có mốc probe <= b
    n = np.maximum(last - first + 1, 0).astype(np.int64)
    rep = np.repeat(np.arange(len(x)), n)
    days = np.repeat(first.astype(np.int64), n) + (np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n))
    d = pd.DataFrame({"user": x["user"].to_numpy()[rep], "place_id": x["place_id"].to_numpy()[rep], "day": days})
    return d.drop_duplicates().groupby(["user", "place_id"]).size().rename("n_nights").reset_index()
