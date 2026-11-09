"""Tiền xử lý quỹ đạo GPS GeoLife: loại lỗi, loại outlier, thêm giờ địa phương.

Mỗi file .plt (thường là một lần bật máy ghi) được xử lý riêng, qua 4 bước:

    Bước                          Xử lý            Hàm
    1. Lỗi dữ liệu                XOÁ điểm         drop_invalid_points
       (tọa độ sai, thời gian sai)
    2. Timestamp trùng            GỘP về dòng đầu  drop_duplicate_timestamps
       (nhóm lệch > 83 m: XOÁ cả nhóm)
    3. Outlier (chuỗi)            XOÁ điểm         remove_outliers
       (chuỗi ≤ 5 điểm nhảy ra rồi quay về)
    4. Giờ địa phương             THÊM cột         add_local_time (local_time.py)

Không cắt segment: không bước nào phía sau dùng tới (stay point cố ý chạy xuyên khoảng trống, D7);
xem notes/decisions.md, D10.

Bước 1–3 chỉ dùng timestamp UTC (GeoLife ghi theo GMT). Ngưỡng và căn cứ: notes/assumptions.md.

Đầu ra:
    data/processed/clean/<user>.parquet   lat, lon, timestamp (UTC), tz_name, tz_offset_h, local_time,
                                          source_file, user        (chỉ khi có --save-clean)
                                          Parquet giữ nguyên kiểu thời gian; pickle nếu thiếu pyarrow.
                                          Đọc lại bằng load_clean(user).
    reports/filter_stats.csv              số điểm bị loại ở từng bước, theo user (CSV để mở xem)

Nguồn dữ liệu: đọc từ data/interim (đã chuyển đổi bằng convert_raw.py, nhanh) nếu có; user nào chưa
chuyển đổi thì đọc thẳng file .plt. Hai nguồn cho kết quả giống hệt. --from-raw: luôn đọc file .plt.

Chạy (từ bất kỳ thư mục nào; đường dẫn tương đối tính từ thư mục Home_Office):
    python src/preprocess/clean_trajectory.py --save-clean data/processed/clean
    python src/preprocess/clean_trajectory.py --from-raw --root data/raw/geolife/Data --out reports/filter_stats.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SRC = Path(__file__).resolve().parents[1]                 # thư mục src
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
from geo import EARTH_R, haversine_m                   # noqa: E402,F401 (haversine_m, EARTH_R: các module khác vẫn import từ đây)
from paths import PROJECT_ROOT                         # noqa: E402,F401
from preprocess import interim                         # noqa: E402
from preprocess.local_time import add_local_time       # noqa: E402


# =============================================================================
# THAM SỐ
# =============================================================================

# ---- Định dạng file .plt (User Guide GeoLife 1.3)
HEADER_LINES = 6
COLUMNS = ["lat", "lon", "zero", "altitude_ft", "days_1899", "date", "time"]

# ---- Bước 1: khoảng thời gian thu thập (A2)
TIME_MIN = pd.Timestamp("2007-04-01", tz="UTC")  # User Guide: "from April 2007 to August 2012"
TIME_MAX = pd.Timestamp("2012-09-01", tz="UTC")  # không bao gồm: hết tháng 8/2012

# ---- Bước 2: timestamp trùng (A3, EDA notebook 01 mục 3)
# Các dòng cùng timestamp lệch nhau quá quãng đi được trong 1 giây ở MAX_SPEED_KMH thì không thể cùng đúng,
# và không biết dòng nào sai, nên bỏ cả nhóm.
DUP_MAX_DIST_M = 300.0 / 3.6   # A3 (chọn 2026-11-07, tuning/05): khoảng 83 m = 300 km/h × 1 giây; nhóm lệch xa hơn thì bỏ cả nhóm

# ---- Bước 3: outlier (A5, A6)
MAX_SPEED_KMH = 300.0      # A5 (chọn 2026-11-07, tuning/06): bước vào và bước ra đều vượt mức này mới bị nghi là chuỗi outlier; mốc vật lý: tàu tối đa khoảng 237 km/h, máy bay trung vị 668 km/h
OUTLIER_MAX_K = 5          # A6 (chọn 2026-11-07, tuning/07): chuỗi có tối đa bao nhiêu điểm X thì bị xoá
MAX_ITER = 5               # số vòng lặp tối đa (xoá một chuỗi có thể làm lộ chuỗi bên cạnh)

# ---- Khoảng trống (A7): bước có dt lớn hơn mức này là máy tắt / mất tín hiệu, không phải di chuyển.
# Dùng ở bước 3 (không dò outlier qua khoảng trống) và ở stays/detect.py (đánh dấu gap-stay).
GAP_S = 30 * 60            # giây

# ---- Hằng số tính toán và đường dẫn
EPOCH = pd.Timestamp("1970-01-01", tz="UTC")
CLEAN_DIR = PROJECT_ROOT / "data" / "processed" / "clean"   # nơi ghi dữ liệu đã lọc mặc định

# Các cột thống kê, cộng dồn theo user và ghi vào filter_stats.csv
STAT_KEYS = ("n_raw", "n_bad_coord", "n_bad_time", "n_dup", "n_dup_conflict", "n_outlier", "n_kept")


# =============================================================================
# ĐỌC DỮ LIỆU
# =============================================================================

# -----------------------------------------------------------------------------
# Đọc một file .plt -> bảng lat, lon, timestamp (UTC).
# Dòng sai định dạng thành NaT (bị loại ở bước 1), không làm dừng cả file.
# -----------------------------------------------------------------------------
def read_plt(path: str | Path) -> pd.DataFrame:

    df = pd.read_csv(path, skiprows=HEADER_LINES, header=None, names=COLUMNS,
                     dtype={"date": str, "time": str})
    if df.empty:
        return pd.DataFrame(columns=["lat", "lon", "timestamp"])
    ts = pd.to_datetime(df["date"] + " " + df["time"], format="%Y-%m-%d %H:%M:%S", errors="coerce")
    out = df[["lat", "lon"]].copy()
    out["timestamp"] = ts.dt.tz_localize("UTC")
    return out


# =============================================================================
# HÀM TÍNH TOÁN DÙNG CHUNG
# =============================================================================

# Đổi timestamp sang số giây kể từ 1970 để tính toán bằng numpy.
def _seconds(series: pd.Series) -> np.ndarray:
    """Timestamp -> số giây kể từ 1970 (để tính bằng numpy)."""
    return (series - EPOCH).dt.total_seconds().to_numpy()


# Tính dt (giây), khoảng cách (mét), tốc độ (km/h) cho từng cặp điểm liền nhau.
# Dùng ở bước 3.
def _steps(lat: np.ndarray, lon: np.ndarray, t: np.ndarray):
    """Thông số của từng bước i -> i+1: dt (giây), khoảng cách (mét), tốc độ (km/h).

    Bước có dt = 0 được gán tốc độ 0 (không xảy ra sau khi bỏ trùng; chỉ để tránh chia cho 0).
    """
    dt = np.diff(t)
    dist = haversine_m(lat[:-1], lon[:-1], lat[1:], lon[1:])
    speed = np.where(dt > 0, dist / np.where(dt > 0, dt, 1.0) * 3.6, 0.0)
    return dt, dist, speed


# =============================================================================
# CÁC BƯỚC LỌC (mỗi bước một hàm, cập nhật dict thống kê `stats`)
# =============================================================================

# -----------------------------------------------------------------------------
# BƯỚC 1 - XOÁ LỖI DỮ LIỆU
# Bỏ điểm có tọa độ ngoài phạm vi, hoặc timestamp không đọc được / ngoài 04/2007–08/2012.
# Làm trước tiên vì một timestamp sai sẽ làm sai mọi tốc độ quanh nó.
# -----------------------------------------------------------------------------
def drop_invalid_points(df: pd.DataFrame, stats: dict,
                        time_min: pd.Timestamp = TIME_MIN, time_max: pd.Timestamp = TIME_MAX) -> pd.DataFrame:
    """`time_min`, `time_max` mặc định là khoảng thu thập của GeoLife (A2); dữ liệu của người dùng API truyền khoảng khác."""
    valid_coord = df["lat"].between(-90, 90) & df["lon"].between(-180, 180)
    ts = df["timestamp"]
    valid_time = ts.notna() & (ts >= time_min) & (ts < time_max)
    stats["n_bad_coord"] = int((~valid_coord).sum())
    stats["n_bad_time"] = int((valid_coord & ~valid_time).sum())
    return df[valid_coord & valid_time]


# -----------------------------------------------------------------------------
# BƯỚC 2 - XỬ LÝ TIMESTAMP TRÙNG (A3). Bắt buộc trước khi tính tốc độ (tránh dt = 0).
# Sắp xếp ổn định theo thời gian rồi xét từng nhóm dòng cùng timestamp, so với dòng đầu nhóm:
#   R1 giống hệt, R2 chỉ khác độ cao, R3 lệch ≤ DUP_MAX_DIST_M   -> GỘP: giữ dòng đầu      (n_dup)
#   R4 có dòng lệch > DUP_MAX_DIST_M                             -> XOÁ cả nhóm           (n_dup_conflict)
# Không lấy trung bình tọa độ: dòng đầu chỉ cách tâm nhóm < 1 m và stay không đổi (EDA mục 1.1, 3.6 (notebook 01, 05)).
# -----------------------------------------------------------------------------
def drop_duplicate_timestamps(df: pd.DataFrame, stats: dict,
                              max_dist_m: float = DUP_MAX_DIST_M) -> pd.DataFrame:

    d = df.sort_values("timestamp", kind="stable")
    dup = d["timestamp"].duplicated(keep=False).to_numpy()
    conflict = np.zeros(len(d), dtype=bool)
    if dup.any():
        g = d[dup].groupby("timestamp", sort=False)
        first = g[["lat", "lon"]].transform("first")
        dist = pd.Series(haversine_m(first["lat"].to_numpy(), first["lon"].to_numpy(),
                                     d.loc[dup, "lat"].to_numpy(), d.loc[dup, "lon"].to_numpy()),
                         index=first.index)
        far = dist.groupby(d.loc[dup, "timestamp"].to_numpy()).transform("max").to_numpy() > max_dist_m
        conflict[np.nonzero(dup)[0][far]] = True
    stats["n_dup_conflict"] = int(conflict.sum())
    d = d[~conflict]
    before = len(d)
    d = d.drop_duplicates("timestamp", keep="first")
    stats["n_dup"] = before - len(d)
    return d


# -----------------------------------------------------------------------------
# BƯỚC 3 - XOÁ CHUỖI OUTLIER (các điểm nhảy ra xa rồi quay về)
#     A ──► X1 ... Xk ──► B
#     xoá X1..Xk khi A→X1 và Xk→B đều > 300 km/h (dt ≤ 30 phút), A→B ≤ 300 km/h
#     và k ≤ 5 (A5, A6)
# Xoá được vì A và B khớp nhau nên biết các điểm X là sai.
# Máy bay, tàu cao tốc đi một hướng (A→B vẫn nhanh) nên được giữ.
#
# Phạm vi tìm bước ra không dùng con số riêng (D11):
#   - theo số điểm: chỉ tìm trong max_k bước sau bước vào, vì chuỗi dài hơn cũng không bị xoá (A6);
#   - theo thời gian: dừng ở khoảng trống đầu tiên (dt > 30 phút, A7), chuỗi không vắt qua lúc máy tắt.
# Luôn lấy bước ra GẦN NHẤT thoả A→B ≤ 300 km/h.
# -----------------------------------------------------------------------------
def find_chains(lat: np.ndarray, lon: np.ndarray, t: np.ndarray, max_speed_kmh: float = MAX_SPEED_KMH,
                step_dt_s: float = GAP_S, max_k: int | None = OUTLIER_MAX_K) -> list[tuple[int, int]]:
    """Trả về list (e, j): A = điểm e, X = điểm e+1..j, B = điểm j+1. max_k=None: không giới hạn số điểm."""
    dt, _, speed = _steps(lat, lon, t)
    gap = dt > step_dt_s
    fast = ~gap & (speed > max_speed_kmh)                   # fast[i]: bước i -> i+1 nhanh, không phải khoảng trống
    gap_idx = np.nonzero(gap)[0]
    found, last_end = [], -1
    for e in np.nonzero(fast)[0]:
        if e <= last_end:                                    # nằm trong chuỗi vừa tìm
            continue
        g = np.searchsorted(gap_idx, e)                      # khoảng trống đầu tiên sau bước vào
        hi = (gap_idx[g] - 1) if g < len(gap_idx) else len(dt) - 1
        if max_k is not None:
            hi = min(hi, e + max_k)
        js = e + 1 + np.nonzero(fast[e + 1:hi + 1])[0]       # các bước ra có thể
        if not len(js):
            continue
        dur = t[js + 1] - t[e]
        v_ab = haversine_m(lat[e], lon[e], lat[js + 1], lon[js + 1]) / dur * 3.6
        ok = np.nonzero(v_ab <= max_speed_kmh)[0]
        if len(ok):
            j = int(js[ok[0]])
            found.append((int(e), j))
            last_end = j
    return found


def remove_outliers(df: pd.DataFrame, stats: dict, max_speed_kmh: float = MAX_SPEED_KMH,
                    max_k: int = OUTLIER_MAX_K, gap_s: float = GAP_S,
                    max_iter: int = MAX_ITER) -> pd.DataFrame:

    lat = df["lat"].to_numpy(float)
    lon = df["lon"].to_numpy(float)
    t = _seconds(df["timestamp"])
    alive = np.arange(len(df))                       # chỉ số các điểm đang được giữ

    for _ in range(max_iter):
        if len(alive) < 3:                           # cần ít nhất 3 điểm mới có chuỗi
            break
        la, lo, ta = lat[alive], lon[alive], t[alive]
        drop = np.zeros(len(alive), dtype=bool)
        for e, j in find_chains(la, lo, ta, max_speed_kmh, gap_s, max_k):   # mọi chuỗi tìm được đều có k ≤ max_k
            drop[e + 1:j + 1] = True
        if not drop.any():
            break
        stats["n_outlier"] += int(drop.sum())
        alive = alive[~drop]

    return df.iloc[alive].copy()


# =============================================================================
# GHÉP CÁC BƯỚC CHO MỘT FILE
# =============================================================================

# -----------------------------------------------------------------------------
# LỌC MỘT FILE: chạy lần lượt bước 1 -> 4, trả về bảng đã lọc và số điểm bị loại ở từng bước.
# Bước 4 (thêm giờ địa phương) dùng add_local_time trong local_time.py.
# -----------------------------------------------------------------------------
def filter_track(df: pd.DataFrame, max_speed_kmh: float = MAX_SPEED_KMH,
                 gap_s: float = GAP_S, outlier_max_k: int = OUTLIER_MAX_K,
                 max_iter: int = MAX_ITER, time_min: pd.Timestamp = TIME_MIN, time_max: pd.Timestamp = TIME_MAX):
    """Chạy bước 1–4 trên một file. Trả về (bảng đã lọc, dict thống kê)."""
    stats = {"n_raw": len(df), "n_bad_coord": 0, "n_bad_time": 0, "n_dup": 0, "n_dup_conflict": 0, "n_outlier": 0}
    if df.empty:
        stats.update(n_kept=0, n_removed=0)
        return df.assign(tz_name=pd.Series(dtype="category"), tz_offset_h=pd.Series(dtype=float),
                         local_time=pd.Series(dtype="datetime64[ns]")), stats

    d = drop_invalid_points(df, stats, time_min, time_max)               # bước 1
    d = drop_duplicate_timestamps(d, stats)                               # bước 2
    d = remove_outliers(d, stats, max_speed_kmh, outlier_max_k, gap_s, max_iter)   # bước 3
    d = add_local_time(d)                                                 # bước 4

    stats["n_kept"] = len(d)
    stats["n_removed"] = stats["n_raw"] - stats["n_kept"]
    return d, stats


# =============================================================================
# CHẠY TRÊN TOÀN BỘ DỮ LIỆU
# =============================================================================

# Lấy dữ liệu từng file .plt của một user: (tên file, bảng lat/lon/timestamp), theo thứ tự tên file.
# Đọc từ data/interim nếu user đã được chuyển đổi (nhanh), nếu không thì đọc thẳng file .plt.
def iter_user_files(udir: Path, from_raw: bool = False):
    points = None if from_raw else interim.load_points(udir.name)
    if points is None:
        for f in sorted((udir / "Trajectory").glob("*.plt")):
            yield f.name, read_plt(f)
        return
    files = interim.load_files(udir.name)
    groups = {name: g[["lat", "lon", "timestamp"]] for name, g in points.groupby("file", observed=True, sort=False)}
    empty = points.iloc[0:0][["lat", "lon", "timestamp"]]
    for name in files["file"]:
        yield name, groups.get(name, empty)


# Lọc mọi file .plt của một user, cộng dồn thống kê; ghi data/processed/clean/<user>.parquet nếu có --save-clean.
def process_user(udir: Path, save_clean: Path | None, from_raw: bool = False) -> dict:
    """Lọc mọi file .plt của một user. Trả về một dòng thống kê; ghi CSV sạch nếu có save_clean."""
    row = {"user": udir.name, "n_files": 0, **{k: 0 for k in STAT_KEYS}}
    clean_parts = []
    for fname, raw in iter_user_files(udir, from_raw):
        out, s = filter_track(raw)
        row["n_files"] += 1
        for k in STAT_KEYS:
            row[k] += s[k]
        if save_clean is not None and len(out):
            clean_parts.append(out.assign(source_file=fname, user=udir.name))
    if save_clean is not None and clean_parts:
        interim.save_df(pd.concat(clean_parts, ignore_index=True), save_clean / udir.name)
    return row


# Đọc dữ liệu đã lọc của một user (cho các bước sau: stay point, gán home/office...).
# Kiểu dữ liệu giữ nguyên: timestamp là thời gian UTC, local_time là thời gian địa phương.
def load_clean(user: str, clean_dir: Path = CLEAN_DIR) -> pd.DataFrame | None:
    return interim.read_df(Path(clean_dir) / user)


# Lọc mọi user trong thư mục dữ liệu gốc, ghi reports/filter_stats.csv.
def process_root(root: Path, out_csv: Path, save_clean: Path | None, from_raw: bool = False) -> None:
    """Lọc mọi user trong thư mục dữ liệu, ghi bảng thống kê ra out_csv."""
    rows = []
    user_dirs = sorted(p for p in root.iterdir() if (p / "Trajectory").is_dir())
    for udir in user_dirs:
        row = process_user(udir, save_clean, from_raw)
        rows.append(row)
        print(f"{udir.name}: {row['n_raw']} điểm -> {row['n_kept']} "
              f"(outlier {row['n_outlier']})")
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out_csv, index=False)
    print("Đã ghi:", out_csv)


# =============================================================================
# Main
# =============================================================================

# Đường dẫn tương đối được tính từ thư mục Home_Office, để chạy được từ bất kỳ thư mục nào.
def _from_project(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


# Đọc tham số dòng lệnh rồi chạy toàn bộ dữ liệu.
def main() -> None:
    ap = argparse.ArgumentParser(description="Tiền xử lý quỹ đạo GPS GeoLife.")
    ap.add_argument("--root", type=Path, default=Path("data/raw/geolife/Data"), help="thư mục dữ liệu gốc")
    ap.add_argument("--out", type=Path, default=Path("reports/filter_stats.csv"), help="file thống kê")
    ap.add_argument("--save-clean", type=Path, default=None, help="thư mục ghi dữ liệu sạch (bỏ trống: không ghi)")
    ap.add_argument("--from-raw", action="store_true", help="luôn đọc file .plt, bỏ qua data/interim")
    args = ap.parse_args()
    root = _from_project(args.root)
    if not root.is_dir():
        raise SystemExit(f"Không tìm thấy thư mục dữ liệu: {root}")
    save_clean = _from_project(args.save_clean) if args.save_clean else None
    process_root(root, _from_project(args.out), save_clean, args.from_raw)


if __name__ == "__main__":
    main()
