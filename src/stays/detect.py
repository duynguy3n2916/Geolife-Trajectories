"""Phát hiện stay point theo Li et al. (2008), trên dữ liệu đã lọc (data/processed/clean).

Stay point là một vùng người dùng ở lại đủ lâu: các điểm liên tiếp nằm trong bán kính DIST_M
quanh một điểm neo, kéo dài ít nhất TIME_S.

Thuật toán (Li et al., 2008, "Mining user similarity based on location history", ACM SIGSPATIAL GIS;
Figure 2 "Algorithm for stay point detection"; tham số ở mục 5.1.2: 200 m, 30 phút):

    i = 0                                   điểm neo
    lặp:
        j = điểm đầu tiên sau i cách i hơn DIST_M
        nếu t[j-1] - t[i] >= TIME_S:        ở trong bán kính đủ lâu
            stay = các điểm i..j-1;  i = j
        ngược lại:
            i = i + 1                       neo sang điểm kế tiếp

Mặc định dùng biến thể h1_mean (D13): chạy Li, đặt lại neo vào điểm gần nhất với trung bình tọa độ của stay,
mở rộng cả hai phía trong bán kính, chỉ nhận stay mới nếu không ngắn hơn stay của Li. Giảm stay bị tách đôi
và neo lệch. Muốn chạy Li thuần: --method li.

Khác bài gốc ở ba điểm nhỏ (ghi trong notes/decisions.md, D7):
    - Thời gian và tâm tính trên các điểm thật sự nằm trong bán kính (i..j-1); bài gốc dùng cả điểm j.
    - Stay ở cuối dữ liệu (không có điểm j ra khỏi bán kính) vẫn được ghi nhận.
    - Chạy liền qua các file của cùng user, chỉ ngắt ở khoảng trống > MAX_GAP_S.
      Nhờ vậy, khi máy tắt lúc đứng yên (ví dụ qua đêm ở nhà) và bật lại cùng chỗ, khoảng
      trống đó được tính vào stay (A12). Stay như vậy có source = "gap".

Chạy:
    python src/stays/detect.py                         # mọi user trong data/processed/clean
    python src/stays/detect.py --users 000 163         # vài user
    python src/stays/detect.py --method li             # Li thuần, để so sánh
Đầu ra:
    data/processed/stays/<user>.parquet   một dòng mỗi stay (xem STAY_COLS)
    reports/stay_stats.csv                số stay, thời lượng, tỷ lệ gap theo user
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

SRC = Path(__file__).resolve().parents[1]                 # thư mục src
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
from preprocess import interim                                       # noqa: E402
from preprocess.clean_trajectory import CLEAN_DIR, EPOCH, GAP_S, PROJECT_ROOT, haversine_m   # noqa: E402

# =============================================================================
# THAM SỐ (A12, A14 trong notes/assumptions.md)
# =============================================================================
DIST_M = 200.0             # bán kính stay (mét); Li et al. (2008), mục 5.1.2: distThreh = 200 m
TIME_S = 30 * 60           # thời gian tối thiểu ở trong bán kính (giây); Li et al. (2008), mục 5.1.2: timeThreh = 30 phút
MAX_GAP_S = 24 * 3600      # khoảng trống dài hơn mức này thì không được tính vào stay (A12)
METHOD = "h1_mean"         # "h1_mean" (D13) hoặc "li"
WINDOW = 64                # số điểm xét bằng numpy cho mọi điểm neo cùng lúc (chỉ để chạy nhanh)
CHUNK = 4096               # số điểm mỗi lần quét khi vùng ở lại dài hơn WINDOW điểm

STAYS_DIR = PROJECT_ROOT / "data" / "processed" / "stays"
STAY_COLS = ["user", "lat", "lon", "arrive_utc", "leave_utc", "arrive_local", "leave_local",
             "duration_min", "gap_min", "n_points", "source", "tz_offset_h"]


# =============================================================================
# THUẬT TOÁN
# =============================================================================
def _exit_short(lat, lon, dist_m, window):
    """exit[i] = điểm đầu tiên trong i+1..i+window cách i hơn dist_m; -1 nếu không có.

    Tính cho mọi i cùng lúc. Phần lớn điểm neo đang di chuyển nên ra khỏi bán kính rất nhanh;
    nhờ vậy vòng lặp chính chỉ phải quét lâu ở những chỗ đứng yên.
    """
    n = len(lat)
    ex = np.full(n, -1, dtype=np.int64)
    for w in range(1, min(window, n - 1) + 1):
        idx = np.nonzero(ex[:n - w] == -1)[0]                # điểm neo chưa tìm thấy điểm ra
        if not len(idx):
            break
        d = haversine_m(lat[idx], lon[idx], lat[idx + w], lon[idx + w])
        hit = idx[d > dist_m]
        ex[hit] = hit + w
    return ex


def _exit_long(lat, lon, i, start, dist_m):
    """Điểm đầu tiên từ `start` trở đi cách điểm i hơn dist_m; len(lat) nếu không có."""
    n = len(lat)
    s = start
    while s < n:
        e = min(n, s + CHUNK)
        d = haversine_m(lat[i], lon[i], lat[s:e], lon[s:e])
        out = np.nonzero(d > dist_m)[0]
        if len(out):
            return s + int(out[0])
        s = e
    return n


def detect_stays(lat, lon, t, dist_m: float = DIST_M, time_s: float = TIME_S,
                 window: int = WINDOW) -> list[tuple[int, int]]:
    """Stay point trên một chuỗi điểm liên tục (đã sắp theo thời gian, không có khoảng trống > MAX_GAP_S).

    Trả về list (i, last): stay gồm các điểm i..last.
    """
    n = len(t)
    stays = []
    if n < 2:
        return stays
    ex = _exit_short(lat, lon, dist_m, window)
    i = 0
    while i < n - 1:
        e = ex[i]
        if e == -1:                                          # còn trong bán kính sau window điểm
            e = _exit_long(lat, lon, i, i + window + 1, dist_m)
        last = e - 1                                         # điểm cuối còn trong bán kính
        if t[last] - t[i] >= time_s:
            stays.append((i, last))
            i = e
        else:
            i += 1
    return stays


# =============================================================================
# h1_mean (D13): đặt lại neo vào tâm stay của Li rồi mở rộng hai phía
# =============================================================================
def grow(lat, lon, c, lo, hi, step, D=DIST_M, chunk=2048):
    """Từ điểm c, đi theo hướng step (+1/-1) trong [lo, hi], trả về điểm xa nhất còn cách c không quá D.

    Dừng ở điểm đầu tiên ra ngoài D (giống Li)."""
    last_in = c
    k = c + step
    while (k <= hi) if step > 0 else (k >= lo):
        e = min(hi + 1, k + chunk) if step > 0 else max(lo - 1, k - chunk)
        idx = np.arange(k, e, step)
        out = np.nonzero(haversine_m(lat[c], lon[c], lat[idx], lon[idx]) > D)[0]
        if len(out):
            return int(idx[out[0]] - step) if out[0] > 0 else last_in
        last_in = int(idx[-1])
        k = e
    return last_in


def mean_center(lat, lon, a, b):
    """Điểm trong a..b gần nhất với (trung bình vĩ độ, trung bình kinh độ) của các điểm a..b."""
    la, lo = lat[a:b + 1], lon[a:b + 1]
    return a + int(np.argmin(haversine_m(la.mean(), lo.mean(), la, lo)))


def detect_stays_h1(lat, lon, t, dist_m: float = DIST_M, time_s: float = TIME_S, li=None, stats=None) -> list[tuple[int, int]]:
    """h1_mean: chạy Li, đặt lại neo vào điểm gần trung bình tọa độ của stay, mở rộng hai phía; chỉ nhận nếu không ngắn hơn stay cũ.

    li: stay của Li trên cùng đoạn nếu đã tính (để khỏi chạy Li lại).
    stats: dict để đếm (không bắt buộc): "moved" stay dùng neo mới, "kept" giữ stay cũ của Li vì stay mới
    ngắn hơn, "absorbed" stay Li bị stay trước nuốt (đã gộp vào stay trước).
    """
    n = len(t)
    out = []
    floor = 0                                     # điểm đầu tiên chưa thuộc stay nào
    D, T = dist_m, time_s
    for a, b in (li if li is not None else detect_stays(lat, lon, t, D, T)):
        a = max(a, floor)
        if a > b or t[b] - t[a] < T:              # stay cũ đã bị stay trước nuốt
            if stats is not None:
                stats["absorbed"] = stats.get("absorbed", 0) + 1
            continue
        m = mean_center(lat, lon, a, b)
        L = grow(lat, lon, m, floor, n - 1, -1, D)
        R = grow(lat, lon, m, floor, n - 1, +1, D)
        kept = t[R] - t[L] < t[b] - t[a]
        if kept:                                      # stay mới ngắn hơn: giữ stay cũ của Li
            L, R = a, b
        if stats is not None:
            k = "kept" if kept else "moved"
            stats[k] = stats.get(k, 0) + 1
        if out and L <= out[-1][1]:
            L = out[-1][1] + 1
        if t[R] - t[L] >= T:
            out.append((L, R))
            floor = R + 1
    return out


# =============================================================================
# CHẠY CHO MỘT USER
# =============================================================================
def _prepare(df: pd.DataFrame) -> pd.DataFrame:
    """Gộp mọi file của user, sắp theo thời gian, bỏ timestamp trùng giữa các file (bước 2 chỉ bỏ trùng trong file)."""
    d = df.sort_values("timestamp", kind="stable").drop_duplicates("timestamp", keep="first")
    return d.reset_index(drop=True)


def stays_for_user(df: pd.DataFrame, user: str, dist_m: float = DIST_M, time_s: float = TIME_S,
                   max_gap_s: float = MAX_GAP_S, method: str = METHOD) -> pd.DataFrame:
    """Bảng stay của một user từ dữ liệu đã lọc (cột lat, lon, timestamp, tz_offset_h)."""
    if df is None or df.empty:
        return pd.DataFrame(columns=STAY_COLS)
    d = _prepare(df)
    lat = d["lat"].to_numpy(float)
    lon = d["lon"].to_numpy(float)
    t = (d["timestamp"] - EPOCH).dt.total_seconds().to_numpy()
    off = d["tz_offset_h"].to_numpy(float)       # giờ lệch có thể lẻ (ví dụ 5,5)

    # chia thành các đoạn liên tục: ngắt ở khoảng trống > max_gap_s
    cuts = np.nonzero(np.diff(t) > max_gap_s)[0] + 1
    bounds = np.concatenate([[0], cuts, [len(t)]])

    rows = []
    for a, b in zip(bounds[:-1], bounds[1:]):
        args = (lat[a:b], lon[a:b], t[a:b])
        found = detect_stays(*args, dist_m, time_s)
        if method == "h1_mean":
            found = detect_stays_h1(*args, dist_m, time_s, li=found)
        for i, last in found:
            i, last = a + i, a + last
            dts = np.diff(t[i:last + 1])
            gap_s = float(dts[dts > GAP_S].sum())            # phần thời gian nằm trong khoảng trống > 30 phút
            rows.append({"lat": float(lat[i:last + 1].mean()), "lon": float(lon[i:last + 1].mean()),
                         "t0": t[i], "t1": t[last], "off": float(off[i]),
                         "duration_min": (t[last] - t[i]) / 60, "gap_min": gap_s / 60,
                         "n_points": last - i + 1, "source": "gap" if gap_s > 0 else "gps"})
    if not rows:
        return pd.DataFrame(columns=STAY_COLS)
    s = pd.DataFrame(rows)
    s["user"] = user
    s["arrive_utc"] = EPOCH + pd.to_timedelta(s["t0"], unit="s")
    s["leave_utc"] = EPOCH + pd.to_timedelta(s["t1"], unit="s")
    shift = pd.to_timedelta(s["off"], unit="h")
    s["arrive_local"] = s["arrive_utc"].dt.tz_convert(None) + shift
    s["leave_local"] = s["leave_utc"].dt.tz_convert(None) + shift
    s["tz_offset_h"] = s["off"]
    return s[STAY_COLS]


def load_stays(user: str, stays_dir: Path = STAYS_DIR) -> pd.DataFrame | None:
    return interim.read_df(Path(stays_dir) / user)


def _summary(s: pd.DataFrame, user: str, n_points: int) -> dict:
    days = 0
    if len(s):
        days = pd.Series(s["arrive_local"].dt.date).nunique()
    return {"user": user, "n_points": n_points, "n_stays": len(s), "n_stay_days": days,
            "stay_hours": float(s["duration_min"].sum() / 60) if len(s) else 0.0,
            "median_stay_min": float(s["duration_min"].median()) if len(s) else np.nan,
            "n_gap_stays": int((s["source"] == "gap").sum()) if len(s) else 0,
            "gap_hours": float(s["gap_min"].sum() / 60) if len(s) else 0.0}


# =============================================================================
# Main
# =============================================================================
def _from_project(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def main() -> None:
    ap = argparse.ArgumentParser(description="Bước 5: phát hiện stay point (Li et al., 2008; mặc định h1_mean, D13).")
    ap.add_argument("--users", nargs="*", help="chỉ chạy các user này")
    ap.add_argument("--clean-dir", type=Path, default=CLEAN_DIR, help="thư mục dữ liệu đã lọc")
    ap.add_argument("--out-dir", type=Path, default=STAYS_DIR, help="thư mục ghi stay")
    ap.add_argument("--stats", type=Path, default=Path("reports/stay_stats.csv"), help="file thống kê")
    ap.add_argument("--dist-m", type=float, default=DIST_M)
    ap.add_argument("--time-min", type=float, default=TIME_S / 60)
    ap.add_argument("--method", choices=["h1_mean", "li"], default=METHOD, help="cách chọn neo (D13)")
    args = ap.parse_args()
    clean_dir, out_dir = _from_project(args.clean_dir), _from_project(args.out_dir)
    users = interim.list_stems(clean_dir)
    if args.users:
        users = [u for u in users if u in set(args.users)]
    if not users:
        raise SystemExit(f"Không có dữ liệu đã lọc trong {clean_dir}. Chạy clean_trajectory.py --save-clean trước.")
    rows, t0 = [], time.time()
    for u in users:
        df = interim.read_df(clean_dir / u)
        s = stays_for_user(df, u, args.dist_m, args.time_min * 60, method=args.method)
        interim.save_df(s, out_dir / u)
        r = _summary(s, u, 0 if df is None else len(df))
        rows.append(r)
        print(f"{u}: {r['n_stays']} stay ({r['n_gap_stays']} qua khoảng trống), "
              f"{r['stay_hours']:.0f} giờ  ({time.time() - t0:.0f} giây)")
    stats = _from_project(args.stats)
    stats.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(stats, index=False)
    print("Đã ghi:", out_dir, "và", stats)


if __name__ == "__main__":
    main()
