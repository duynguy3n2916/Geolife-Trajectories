"""Đào sâu timestamp trùng cho notebook 01 (mục 3.1–3.14; quét mọi user ở mục 3.1–3.4 là scan_all_users).

Vì sao phải đọc lại file .plt gốc: data/interim và read_plt chỉ giữ lat, lon, timestamp. Độ cao và cột ngày kiểu
Excel bị bỏ, nên không biết hai dòng trùng timestamp có "giống hệt mọi trường" hay không. Ở đây mỗi dòng được
đọc lại nguyên văn (chữ gốc), chỉ cho một vài user được chọn.

Nhóm trùng = mọi dòng của một user có cùng timestamp (UTC). Mỗi nhóm thuộc một trong ba loại:
    identical    mọi trường giống hệt nhau (so chữ gốc của cả dòng)
    same_coord   cùng lat, lon nhưng khác trường khác (độ cao ...)
    diff_coord   khác lat hoặc lon
"Dòng thừa" của nhóm = số dòng - 1 (số dòng bị bỏ nếu chỉ giữ một dòng mỗi timestamp).

Phần cuối (compare_policies) đo xem cách chọn dòng giữ lại có làm đổi số stay point hay không.
Đây là phép đo trên dữ liệu thô, chưa lọc outlier; chỉ để so sánh các cách giữ dòng với nhau.
"""
from __future__ import annotations

import hashlib
import os
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from preprocess import interim
from preprocess.clean_trajectory import COLUMNS, HEADER_LINES, haversine_m
from stays.detect import MAX_GAP_S, detect_stays

RAW_DIR = interim.RAW_DIR
FIELDS = list(COLUMNS)          # lat, lon, zero, altitude_ft, days_1899, date, time: đủ mọi trường của một dòng .plt
POLICIES = ("first", "last", "mean", "drop_conflict", "drop_far")
SAME_SECOND_MAX_M = 300 / 3.6   # quãng đi được trong 1 giây ở 300 km/h (ngưỡng outlier A5), khoảng 83 m
_EPOCH = pd.Timestamp("1970-01-01")


def _join(df: pd.DataFrame, cols: list[str]) -> pd.Series:
    s = df[cols[0]]
    for c in cols[1:]:
        s = s + "," + df[c]
    return s


# =============================================================================
# ĐỌC DỮ LIỆU
# =============================================================================
def load_user_raw(user: str, raw_dir=None) -> pd.DataFrame:
    """Mọi dòng của mọi file .plt của một user, giữ nguyên chữ gốc của từng trường.

    Cột: file, row (số thứ tự dòng trong file), 7 trường gốc (chuỗi), ts (UTC, không gắn timezone; NaT nếu không đọc
    được), lat_f, lon_f, alt_f (số). Các file được nối theo thứ tự tên, giống cách pipeline xử lý.
    """
    raw_dir = Path(raw_dir or RAW_DIR)
    parts = []
    for f in sorted((raw_dir / user / "Trajectory").glob("*.plt")):
        d = pd.read_csv(f, skiprows=HEADER_LINES, header=None, names=FIELDS, dtype=str, keep_default_na=False)
        if d.empty:
            continue
        d.insert(0, "row", np.arange(len(d), dtype=np.int32))
        d.insert(0, "file", f.name)
        parts.append(d)
    if not parts:
        df = pd.DataFrame(columns=["file", "row", *FIELDS])
        df["file"] = df["file"].astype("category")
    else:
        df = pd.concat(parts, ignore_index=True)
        df["file"] = df["file"].astype("category")
    df["ts"] = pd.to_datetime(df["date"] + " " + df["time"], format="%Y-%m-%d %H:%M:%S", errors="coerce")
    for src, dst in (("lat", "lat_f"), ("lon", "lon_f"), ("altitude_ft", "alt_f")):
        df[dst] = pd.to_numeric(df[src], errors="coerce")
    return df


# =============================================================================
# PHÂN LOẠI NHÓM TRÙNG
# =============================================================================
def duplicate_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Các dòng thuộc nhóm trùng timestamp (nhóm có từ 2 dòng trở lên), kèm cột line, coord, file_id."""
    d = df[df["ts"].notna()]
    n = d.groupby("ts")["ts"].transform("size")
    dd = d[n.to_numpy() > 1].copy()
    dd["line"] = _join(dd, FIELDS)
    dd["coord"] = dd["lat"] + "," + dd["lon"]
    dd["file_id"] = dd["file"].cat.codes
    return dd


_GROUP_COLS = ["n_rows", "n_lines", "n_coords", "n_files", "row_min", "row_max", "max_d_first_m",
               "alt_range_ft", "category", "same_file", "contiguous", "extra_rows"]


def group_table(dd: pd.DataFrame) -> pd.DataFrame:
    """Một dòng mỗi nhóm trùng (index = timestamp): số dòng, số dòng khác nhau, số tọa độ khác nhau, số file,
    khoảng cách lớn nhất tới dòng đầu nhóm (m), chênh lệch độ cao (ft), loại nhóm, cùng file hay không,
    các dòng có liền nhau trong file hay không."""
    if dd.empty:
        return pd.DataFrame(columns=_GROUP_COLS)
    g = dd.groupby("ts", sort=True)
    t = g.agg(n_rows=("line", "size"), n_lines=("line", "nunique"), n_coords=("coord", "nunique"),
              n_files=("file_id", "nunique"), row_min=("row", "min"), row_max=("row", "max"),
              alt_min=("alt_f", "min"), alt_max=("alt_f", "max"))
    first = g[["lat_f", "lon_f"]].transform("first")
    d_first = haversine_m(first["lat_f"].to_numpy(), first["lon_f"].to_numpy(),
                          dd["lat_f"].to_numpy(), dd["lon_f"].to_numpy())
    t["max_d_first_m"] = pd.Series(d_first, index=dd.index).groupby(dd["ts"]).max()
    t["alt_range_ft"] = t["alt_max"] - t["alt_min"]
    t["category"] = np.select([t["n_lines"] == 1, t["n_coords"] == 1], ["identical", "same_coord"], "diff_coord")
    t["same_file"] = t["n_files"] == 1
    t["contiguous"] = t["same_file"] & ((t["row_max"] - t["row_min"] + 1) == t["n_rows"])
    t["extra_rows"] = t["n_rows"] - 1
    return t[_GROUP_COLS]


def file_pairs(dd: pd.DataFrame, t: pd.DataFrame, df: pd.DataFrame, top: int = 10) -> pd.DataFrame:
    """Các tổ hợp file chia sẻ nhiều timestamp nhất (chỉ nhóm trùng nằm ở nhiều file)."""
    cols = ["các file", "số timestamp chung", "số dòng file nhỏ nhất", "chung / file nhỏ nhất %"]
    cross_ts = t.index[~t["same_file"]]
    if len(cross_ts) == 0:
        return pd.DataFrame(columns=cols)
    cross = dd[dd["ts"].isin(cross_ts)]
    sig = cross.groupby("ts", sort=False)["file_id"].agg(lambda s: tuple(sorted(set(s))))
    names = list(dd["file"].cat.categories)
    rows_per_file = df.groupby("file", observed=True).size()
    out = []
    for ids, n in sig.value_counts().head(top).items():
        fs = [names[i] for i in ids]
        mn = min(int(rows_per_file[f]) for f in fs)
        out.append({cols[0]: " + ".join(fs), cols[1]: int(n), cols[2]: mn, cols[3]: 100 * n / mn})
    return pd.DataFrame(out, columns=cols)


def identical_files(df: pd.DataFrame) -> pd.DataFrame:
    """Các file có nội dung giống hệt nhau (cùng tập dòng, bất kể thứ tự), tính bằng dấu vân tay của từng dòng."""
    cols = ["các file giống hệt nhau", "số dòng mỗi file"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    h = pd.util.hash_pandas_object(_join(df, FIELDS), index=False).to_numpy()
    h = (h >> np.uint64(33)).astype("int64")                       # bớt bit để tổng không tràn
    fp = (pd.DataFrame({"file": df["file"].astype(str).to_numpy(), "h": h})
          .groupby("file").agg(h=("h", "sum"), n=("h", "size")).reset_index())
    cl = fp.groupby(["h", "n"])["file"].agg(list)
    cl = cl[cl.map(len) > 1]
    if cl.empty:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame({cols[0]: cl.map(", ".join).to_numpy(),
                         cols[1]: cl.index.get_level_values("n").to_numpy()})


def summarize(df: pd.DataFrame) -> dict:
    """Tổng hợp nhóm trùng của một user. Trả về dict: row (một dòng số liệu), groups, dd, sizes, pairs, identical_files.

    Các tỷ lệ theo loại tính trên DÒNG THỪA (số dòng bị bỏ), không phải trên số nhóm.
    """
    dd = duplicate_rows(df)
    t = group_table(dd)
    n_valid = int(df["ts"].notna().sum())
    extra = int(t["extra_rows"].sum()) if len(t) else 0
    by_cat = t.groupby("category")["extra_rows"].sum() if len(t) else pd.Series(dtype=int)

    def pc(x):
        return 100 * x / extra if extra else np.nan

    n_same = int(t["same_file"].sum()) if len(t) else 0
    row = {
        "số dòng": len(df), "số file": df["file"].nunique(), "số nhóm trùng": len(t), "dòng thừa": extra,
        "dòng thừa %": 100 * extra / n_valid if n_valid else np.nan,
        "giống hệt %": pc(by_cat.get("identical", 0)),
        "cùng tọa độ, khác trường khác %": pc(by_cat.get("same_coord", 0)),
        "khác tọa độ %": pc(by_cat.get("diff_coord", 0)),
        "nhóm cùng file %": 100 * n_same / len(t) if len(t) else np.nan,
        "nhóm liền nhau trong file %": 100 * int(t["contiguous"].sum()) / n_same if n_same else np.nan,
        "cỡ nhóm trung vị": float(t["n_rows"].median()) if len(t) else np.nan,
        "cỡ nhóm lớn nhất": int(t["n_rows"].max()) if len(t) else 0,
    }
    return {"row": row, "groups": t, "dd": dd,
            "sizes": t["n_rows"].value_counts().sort_index() if len(t) else pd.Series(dtype=int),
            "pairs": file_pairs(dd, t, df), "identical_files": identical_files(df)}




# =============================================================================
# ẢNH HƯỞNG TỚI STAY POINT CỦA CÁCH GIỮ DÒNG
# =============================================================================
def policy_points(df: pd.DataFrame, policy: str):
    """Chuỗi điểm (t giây, lat, lon) sau khi chọn dòng cho mỗi timestamp.

    first          giữ dòng đầu (cách pipeline đang dùng)
    last           giữ dòng cuối
    mean           lấy trung bình lat, lon của nhóm
    drop_conflict  bỏ cả nhóm nếu các dòng khác tọa độ; nhóm cùng tọa độ thì giữ một dòng
    drop_far       giữ dòng đầu, trừ khi có dòng cách dòng đầu hơn SAME_SECOND_MAX_M mét thì bỏ cả nhóm
    """
    d = df[df["ts"].notna() & df["lat_f"].between(-90, 90) & df["lon_f"].between(-180, 180)]
    d = d.sort_values("ts", kind="stable")
    if policy in ("first", "last"):
        d = d.drop_duplicates("ts", keep=policy)
        ts, lat, lon = d["ts"], d["lat_f"], d["lon_f"]
    elif policy == "mean":
        g = d.groupby("ts", sort=True).agg(lat_f=("lat_f", "mean"), lon_f=("lon_f", "mean")).reset_index()
        ts, lat, lon = g["ts"], g["lat_f"], g["lon_f"]
    elif policy == "drop_conflict":
        coord = d["lat"] + "," + d["lon"]
        n = coord.groupby(d["ts"]).transform("nunique")
        d = d[n.to_numpy() == 1].drop_duplicates("ts")
        ts, lat, lon = d["ts"], d["lat_f"], d["lon_f"]
    elif policy == "drop_far":
        first = d.groupby("ts")[["lat_f", "lon_f"]].transform("first")
        dist = pd.Series(haversine_m(first["lat_f"].to_numpy(), first["lon_f"].to_numpy(),
                                     d["lat_f"].to_numpy(), d["lon_f"].to_numpy()), index=d.index)
        far = dist.groupby(d["ts"]).transform("max") > SAME_SECOND_MAX_M
        d = d[~far.to_numpy()].drop_duplicates("ts")
        ts, lat, lon = d["ts"], d["lat_f"], d["lon_f"]
    else:
        raise ValueError(f"policy không hợp lệ: {policy}")
    t = (ts - _EPOCH).dt.total_seconds().to_numpy()
    return t, lat.to_numpy(float), lon.to_numpy(float)


def stay_summary(lat, lon, t) -> tuple[int, float]:
    """(số stay, tổng giờ stay) bằng đúng thuật toán và ngưỡng của stays/detect.py (ngắt ở khoảng trống > MAX_GAP_S)."""
    if len(t) < 2:
        return 0, 0.0
    cuts = np.nonzero(np.diff(t) > MAX_GAP_S)[0] + 1
    bounds = np.concatenate([[0], cuts, [len(t)]])
    n, hours = 0, 0.0
    for a, b in zip(bounds[:-1], bounds[1:]):
        ts = t[a:b]
        for i, last in detect_stays(lat[a:b], lon[a:b], ts):
            n += 1
            hours += (ts[last] - ts[i]) / 3600
    return n, hours


def compare_policies(df: pd.DataFrame, policies=POLICIES) -> pd.DataFrame:
    """Số điểm, số stay, tổng giờ stay của một user theo từng cách giữ dòng."""
    rows = []
    for p in policies:
        t, lat, lon = policy_points(df, p)
        n, h = stay_summary(lat, lon, t)
        rows.append({"policy": p, "n_points": len(t), "n_stays": n, "stay_hours": h})
    return pd.DataFrame(rows)


# =============================================================================
# CHI TIẾT TỪNG DÒNG TRÙNG: dòng nào, ở file nào, bao nhiêu, cách nhau bao xa
# =============================================================================












# =============================================================================
# TỔNG HỢP NHIỀU USER
# =============================================================================




# =============================================================================
# QUÉT MỌI USER: DÒNG THỪA KHỚP VỚI DÒNG ĐẦU NHÓM Ở NHỮNG CỘT NÀO
# =============================================================================
# Trường được so (date, time luôn giống nhau vì chính chúng tạo ra timestamp). Tên hiển thị dùng trong notebook.
MATCH_FIELDS = {"lat": "lat", "lon": "lon", "altitude_ft": "độ cao", "zero": "cột 0", "days_1899": "cột ngày"}


def match_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Mỗi DÒNG THỪA (không phải dòng đầu nhóm) một dòng, so với dòng đầu nhóm, tức dòng được giữ nếu giữ dòng đầu.

    Cột: eq_<trường> (chữ gốc giống dòng đầu hay không), identical (giống mọi trường), same_file (cùng file với
    dòng đầu), adjacent (ngay sau dòng trước nó trong cùng file), group_size, d_first_m, alt_diff_ft.
    """
    cols = [*(f"eq_{c}" for c in MATCH_FIELDS), "identical", "same_file", "adjacent", "group_size", "d_first_m",
            "alt_diff_ft", "ts"]
    dd = duplicate_rows(df) if "ts" in df else pd.DataFrame()
    if dd.empty:
        return pd.DataFrame(columns=cols)
    d = dd.sort_values(["ts", "file_id", "row"], kind="stable")
    g = d.groupby("ts", sort=False)
    pos = g.cumcount().to_numpy()
    first = g[[*MATCH_FIELDS, "file_id", "lat_f", "lon_f", "alt_f"]].transform("first")
    prev_row = g["row"].shift().to_numpy()
    prev_file = g["file_id"].shift().to_numpy()
    out = pd.DataFrame({f"eq_{c}": (d[c].to_numpy() == first[c].to_numpy()) for c in MATCH_FIELDS})
    out["identical"] = out.all(axis=1).to_numpy()
    out["same_file"] = d["file_id"].to_numpy() == first["file_id"].to_numpy()
    out["adjacent"] = (d["file_id"].to_numpy() == prev_file) & (d["row"].to_numpy() == prev_row + 1)
    out["group_size"] = g["ts"].transform("size").to_numpy().astype(np.int32)
    out["d_first_m"] = haversine_m(first["lat_f"].to_numpy(), first["lon_f"].to_numpy(),
                                   d["lat_f"].to_numpy(), d["lon_f"].to_numpy()).astype(np.float32)
    out["alt_diff_ft"] = (d["alt_f"].to_numpy() - first["alt_f"].to_numpy()).astype(np.float32)
    out["ts"] = d["ts"].to_numpy()
    return out.loc[pos > 0, cols].reset_index(drop=True)


def scan_all_users(users=None, raw_dir=None, cache_dir=None, rebuild: bool = False, progress: bool = True):
    """Quét file .plt gốc của mọi user (hoặc danh sách users). Trả về (per_user, extras).

    per_user: mỗi user một dòng: n_rows (dòng đọc được), n_ts (dòng có timestamp), n_groups (số timestamp bị trùng),
              n_in_groups (số dòng thuộc nhóm trùng), n_extra (dòng thừa), n_identical_files (số file là bản sao
              giống hệt của một file khác cùng user).
    extras:   kết quả match_rows() của mọi user nối lại (kể cả cột ts), thêm cột user.
    Có cache_dir thì lưu / đọc lại parquet để không phải đọc lại dữ liệu thô (rebuild=True để tính lại).
    """
    import time
    cache = Path(cache_dir) if cache_dir else None
    if cache and not rebuild and (cache / "per_user.parquet").exists() and (cache / "extras.parquet").exists():
        per_user = pd.read_parquet(cache / "per_user.parquet")
        extras = pd.read_parquet(cache / "extras.parquet")
        if users is not None:
            per_user = per_user[per_user.index.isin(users)]
            extras = extras[extras["user"].isin(per_user.index)]
        return per_user, extras
    raw_dir = Path(raw_dir or RAW_DIR)
    users = users or sorted(p.name for p in raw_dir.iterdir() if (p / "Trajectory").is_dir())
    rows, parts, t0 = {}, [], time.time()
    for k, u in enumerate(users, 1):
        df = load_user_raw(u, raw_dir)
        m = match_rows(df)
        n_ts = int(df["ts"].notna().sum())
        n_extra = len(m)
        n_groups = int(m["ts"].nunique()) if n_extra else 0
        idf = identical_files(df)
        rows[u] = {"n_rows": len(df), "n_ts": n_ts, "n_groups": n_groups, "n_in_groups": n_extra + n_groups,
                   "n_extra": n_extra,
                   "n_identical_files": int((idf["các file giống hệt nhau"].str.count(",")).sum()) if len(idf) else 0}
        if n_extra:
            parts.append(m.assign(user=u))
        if progress and (k % 20 == 0 or k == len(users)):
            print(f"[{k}/{len(users)}] đã quét tới user {u} ({time.time() - t0:.0f} giây)")
    per_user = pd.DataFrame.from_dict(rows, orient="index")
    per_user.index.name = "user"
    extras = pd.concat(parts, ignore_index=True) if parts else match_rows(pd.DataFrame()).assign(user="")
    extras["user"] = extras["user"].astype("category")
    if cache:
        cache.mkdir(parents=True, exist_ok=True)
        per_user.to_parquet(cache / "per_user.parquet")
        extras.to_parquet(cache / "extras.parquet")
    return per_user, extras


def diff_pattern(extras: pd.DataFrame) -> pd.Series:
    """Nhãn tổ hợp các trường KHÁC dòng đầu nhóm, ví dụ 'giống hệt', 'khác: độ cao', 'khác: lat + lon + độ cao'."""
    names = np.array(list(MATCH_FIELDS.values()))
    eq = extras[[f"eq_{c}" for c in MATCH_FIELDS]].to_numpy()
    labels = ["giống hệt" if not (~r).any() else "khác: " + " + ".join(names[~r]) for r in eq]
    return pd.Series(labels, index=extras.index, name="tổ hợp")




def group_rules(extras: pd.DataFrame, near_m: float = SAME_SECOND_MAX_M) -> pd.DataFrame:
    """Mỗi NHÓM trùng một dòng (index user, ts): n_rows và quy tắc của nhóm, xếp theo dòng "tệ nhất" của nhóm:
    R4 nếu có dòng cách dòng đầu hơn near_m mét, R1 nếu mọi dòng giống hệt, R2 nếu mọi dòng cùng tọa độ, còn lại R3.
    kept / removed: số dòng giữ / bỏ khi R1–R3 giữ dòng đầu và R4 bỏ cả nhóm."""
    e = extras.assign(far=extras["d_first_m"] > near_m, same_coord=extras["eq_lat"] & extras["eq_lon"])
    g = e.groupby(["user", "ts"], observed=True).agg(n_rows=("group_size", "first"), far=("far", "any"),
                                                     identical=("identical", "all"), same_coord=("same_coord", "all"))
    g["quy tắc"] = np.select([g["far"], g["identical"], g["same_coord"]], ["R4", "R1", "R2"], "R3")
    g["kept"] = np.where(g["quy tắc"] == "R4", 0, 1)
    g["removed"] = g["n_rows"] - g["kept"]
    return g[["n_rows", "quy tắc", "kept", "removed"]]


def center_shift(df: pd.DataFrame) -> pd.DataFrame:
    """Mỗi nhóm trùng một dòng: spread_m (khoảng cách trung bình từ các dòng tới tâm nhóm) và shift_m (dòng đầu cách
    tâm nhóm bao xa, tức điểm bị dời bao nhiêu nếu thay dòng đầu bằng trung bình tọa độ của nhóm)."""
    dd = duplicate_rows(df).sort_values(["ts", "file_id", "row"], kind="stable")
    g = dd.groupby("ts", sort=True)
    c = g[["lat_f", "lon_f"]].transform("mean")
    d_c = pd.Series(haversine_m(c["lat_f"].to_numpy(), c["lon_f"].to_numpy(), dd["lat_f"].to_numpy(),
                                dd["lon_f"].to_numpy()), index=dd.index)
    first = g[["lat_f", "lon_f"]].first()
    cen = g[["lat_f", "lon_f"]].mean()
    return pd.DataFrame({"spread_m": d_c.groupby(dd["ts"]).mean(),
                         "shift_m": haversine_m(first["lat_f"].to_numpy(), first["lon_f"].to_numpy(),
                                                cen["lat_f"].to_numpy(), cen["lon_f"].to_numpy())})


def conflict_groups(df: pd.DataFrame, near_m: float = SAME_SECOND_MAX_M) -> pd.DataFrame:
    """Nhóm lệch xa (có dòng cách dòng đầu hơn near_m mét): dòng nào trong nhóm khớp với quỹ đạo xung quanh?

    Điểm liền trước / liền sau là dòng đầu của timestamp khác gần nhất trước / sau nhóm. Với mỗi dòng của nhóm tính
    d_prev + d_next; dòng có tổng nhỏ nhất là dòng "khớp quỹ đạo". Mỗi nhóm một dòng: n_rows, max_d_first_m,
    first_is_best (dòng đầu là dòng khớp nhất), d_first_prev_m / d_best_prev_m (dòng đầu / dòng khớp nhất cách điểm
    liền trước bao xa), dt_prev_s, dt_next_s, ở đâu (file:số dòng của dòng đầu).
    """
    cols = ["n_rows", "max_d_first_m", "first_is_best", "d_first_prev_m", "d_best_prev_m", "dt_prev_s", "dt_next_s",
            "ở đâu (file:số dòng)"]
    d = df[df["ts"].notna()].copy()
    d["file_id"] = d["file"].cat.codes
    d = d.sort_values(["ts", "file_id", "row"], kind="stable").reset_index(drop=True)
    u = d.drop_duplicates("ts").reset_index()                       # cột index = vị trí dòng đầu trong d
    g = d.groupby("ts", sort=True)
    first = g[["lat_f", "lon_f"]].transform("first")
    dist = pd.Series(haversine_m(first["lat_f"].to_numpy(), first["lon_f"].to_numpy(),
                                 d["lat_f"].to_numpy(), d["lon_f"].to_numpy()), index=d.index)
    far_ts = dist.groupby(d["ts"]).max()
    far_ts = far_ts[far_ts > near_m]
    rows = []
    pos = pd.Series(np.arange(len(u)), index=u["ts"])
    for ts, mx in far_ts.items():
        i = pos[ts]
        if i == 0 or i == len(u) - 1:
            continue
        p, n = u.iloc[i - 1], u.iloc[i + 1]
        m = d[d["ts"] == ts]
        lat, lon = m["lat_f"].to_numpy(), m["lon_f"].to_numpy()
        d_prev = haversine_m(np.full(len(m), p["lat_f"]), np.full(len(m), p["lon_f"]), lat, lon)
        d_next = haversine_m(np.full(len(m), n["lat_f"]), np.full(len(m), n["lon_f"]), lat, lon)
        best = int(np.argmin(d_prev + d_next))
        rows.append({"ts": ts, "n_rows": len(m), "max_d_first_m": mx, "first_is_best": best == 0,
                     "d_first_prev_m": d_prev[0], "d_best_prev_m": d_prev[best],
                     "dt_prev_s": (ts - p["ts"]).total_seconds(), "dt_next_s": (n["ts"] - ts).total_seconds(),
                     cols[-1]: f"{m['file'].iloc[0]}:{int(m['row'].iloc[0]) + HEADER_LINES + 1}"})
    return pd.DataFrame(rows, columns=["ts", *cols]).set_index("ts")


# =============================================================================
# FILE GIỐNG HỆT NHAU GIỮA CÁC USER
# =============================================================================
_CU_COLS = ["files", "md5", "n_rows", "n_files", "n_users", "user_counts"]


def cross_user_groups(raw_dir=None, all_files: bool = False, progress: bool = True) -> pd.DataFrame:
    """Nhóm các file .plt có nội dung giống hệt từng byte (so bằng md5). Mỗi nhóm một dòng.

    Mặc định chỉ so các file TRÙNG TÊN ở nhiều user (tên file là thời điểm bắt đầu ghi, nên bản sao thường giữ nguyên tên).
    all_files=True so nội dung của MỌI file, kể cả khác tên (đọc toàn bộ dữ liệu thô, chậm hơn nhiều).
    Cột: files (tên file, tối đa 3 tên đầu), md5, n_rows (số dòng dữ liệu của một file), n_files (số bản giống hệt),
    n_users, user_counts ('065:1,141:1' = user có bao nhiêu bản trong nhóm).
    Kết quả mặc định là cận dưới: file giống hệt nhưng khác tên không bị phát hiện.
    """
    raw_dir = Path(raw_dir or RAW_DIR)
    where = defaultdict(list)                          # tên file -> các user có file đó
    for udir in sorted(p for p in raw_dir.iterdir() if (p / "Trajectory").is_dir()):
        for f in os.scandir(udir / "Trajectory"):
            if f.name.endswith(".plt"):
                where[f.name].append(udir.name)
    if all_files:
        items = [(n, u) for n, us in where.items() for u in us]
    else:
        items = [(n, u) for n, us in where.items() if len(us) > 1 for u in us]
    by = defaultdict(list)
    for k, (n, u) in enumerate(items, 1):
        b = (raw_dir / u / "Trajectory" / n).read_bytes()
        n_lines = b.count(b"\n") + (0 if (not b or b.endswith(b"\n")) else 1)
        by[hashlib.md5(b).hexdigest()].append((u, n, max(n_lines - HEADER_LINES, 0)))
        if progress and k % 500 == 0:
            print(f"  đã so {k:,}/{len(items):,} file")
    rows = []
    for h, g in by.items():
        if len(g) < 2:
            continue
        cnt = Counter(u for u, _, _ in g)
        names = sorted({n for _, n, _ in g})
        rows.append({"files": ", ".join(names[:3]) + (" ..." if len(names) > 3 else ""), "md5": h,
                     "n_rows": g[0][2], "n_files": len(g), "n_users": len(cnt),
                     "user_counts": ",".join(f"{u}:{c}" for u, c in sorted(cnt.items()))})
    return pd.DataFrame(rows, columns=_CU_COLS)




def _parse_counts(s: str) -> dict:
    return {u: int(c) for u, c in (p.split(":") for p in s.split(","))}


def cross_user_tables(groups: pd.DataFrame, n_raw) -> dict:
    """Từ bảng nhóm file giống hệt: totals (Series), per_user, pairs.

    n_raw: Series số dòng thô của mỗi user (index = user). Dòng thừa của một nhóm = n_rows x (n_files - 1).
    per_user: số dòng của user nằm trong các file có bản sao và tỷ lệ so với dữ liệu của user đó.
    pairs: cặp user chia sẻ nhiều dòng nhất.
    """
    n_raw = pd.Series(n_raw)
    total_raw = int(n_raw.sum())
    if groups.empty:
        return {"totals": pd.Series({"nhóm file giống hệt": 0, "bản sao thừa (file)": 0, "dòng thừa do nhân bản": 0,
                                     "tổng dòng thô": total_raw, "dòng thừa % tổng": 0.0, "số user liên quan": 0}),
                "per_user": pd.DataFrame(), "pairs": pd.DataFrame()}
    shared, nfiles = Counter(), Counter()
    pair_rows, pair_files = Counter(), Counter()
    for r in groups.itertuples():
        cnt = _parse_counts(r.user_counts)
        for u, c in cnt.items():
            shared[u] += r.n_rows * c
            nfiles[u] += c
        us = sorted(cnt)
        for i in range(len(us)):
            for j in range(i + 1, len(us)):
                m = min(cnt[us[i]], cnt[us[j]])
                pair_rows[(us[i], us[j])] += r.n_rows * m
                pair_files[(us[i], us[j])] += m
    extra = int((groups["n_rows"] * (groups["n_files"] - 1)).sum())
    totals = pd.Series({"nhóm file giống hệt": len(groups), "bản sao thừa (file)": int((groups["n_files"] - 1).sum()),
                        "dòng thừa do nhân bản": extra, "tổng dòng thô": total_raw,
                        "dòng thừa % tổng": 100 * extra / total_raw if total_raw else np.nan,
                        "số user liên quan": len(shared)})
    per_user = pd.DataFrame({"số file có bản sao": pd.Series(nfiles), "số dòng trong các file đó": pd.Series(shared)})
    per_user["số dòng thô của user"] = n_raw.reindex(per_user.index)
    per_user["% dữ liệu của user"] = 100 * per_user["số dòng trong các file đó"] / per_user["số dòng thô của user"]
    per_user = per_user.sort_values("số dòng trong các file đó", ascending=False)
    pairs = pd.DataFrame({"số file chung": pd.Series(pair_files), "số dòng chung": pd.Series(pair_rows)})
    pairs.index = [f"{a} - {b}" for a, b in pairs.index]
    return {"totals": totals, "per_user": per_user, "pairs": pairs.sort_values("số dòng chung", ascending=False)}


