"""Chọn eps cho cluster_v2 (tuning, chỉ nhóm validation) và so với cluster_v1.

Với mỗi user và mỗi cách gom (v1; v2 với từng eps) chạy cùng một bước bỏ phiếu home / office (home_office_conf.infer_user)
trên cùng bảng stay, rồi lấy các chỉ số không cần nhãn (A13):
    - số địa điểm, đường kính địa điểm home / office;
    - home / office có cùng chỗ với v1 không (cách nhau <= SAME_M);
    - gộp nhầm: home_eq_office ở v2 mà v1 không có;
    - độ ổn định (h_stable, o_stable từ infer_user) và confidence.
Kết quả lưu cache từng (user, cách gom) ở data/interim/eda_place_eps/. Cache cũ hơn file stay của user hoặc cũ hơn code gom cụm /
bỏ phiếu (CODE_FILES) thì tự tính lại, không cần xoá thủ công.

Quét min_samples (đếm số lần ghé, gồm chính stay đó) ở một eps cố định: `compare_ms`. Stay nhiễu (place_id = -1) bị
infer_user bỏ qua khi bỏ phiếu.

Dùng trong notebooks/tuning/14_place_eps.ipynb.
"""
from __future__ import annotations

import pickle
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

SRC = Path(__file__).resolve().parents[1]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
from geo import haversine_m                                            # noqa: E402
from paths import PROJECT_ROOT                                         # noqa: E402
from places import cluster_v1, cluster_v2, common, home_office_conf as hoc   # noqa: E402
from preprocess import interim                                         # noqa: E402
from stays.detect import STAYS_DIR                                     # noqa: E402

EPS_LIST = [100, 150, 200, 300, 500]       # m
EPS_MS = 200                               # eps cố định khi quét min_samples (D20)
MS_LIST = [1, 2, 3, 5]                     # min_samples
SAME_M = 200.0                             # hai kết quả "cùng chỗ" nếu tâm cách nhau không quá mức này (bằng D, A14)
CACHE_DIR = PROJECT_ROOT / "data" / "interim" / "eda_place_eps"
CODE_FILES = [Path(m.__file__) for m in (cluster_v1, cluster_v2, common, hoc)]     # đổi các file này thì cache cũ bị bỏ


def _code_mtime() -> float:
    return max(f.stat().st_mtime for f in CODE_FILES)


def _stays_mtime(stays_dir: Path, user: str) -> float:
    """Giờ sửa file stay của user (0 nếu không thấy)."""
    return max((p.stat().st_mtime for p in (Path(stays_dir) / f"{user}.parquet", Path(stays_dir) / f"{user}.pkl") if p.exists()), default=0.0)


def _spec(method) -> tuple[float, int]:
    """method: "v1" (không dùng), eps (m) với min_samples = 1, hoặc (eps, min_samples)."""
    if isinstance(method, tuple):
        return float(method[0]), int(method[1])
    return float(method), 1


def _key(method) -> str:
    if method == "v1":
        return "v1"
    eps, ms = _spec(method)
    return f"eps{int(eps)}" if ms == 1 else f"eps{int(eps)}_m{ms}"


def _place_xy(places: pd.DataFrame, pid):
    """Tâm (trung bình có trọng số thời lượng) của địa điểm; nhất quán giữa v1 và v2."""
    if pid is None or (isinstance(pid, float) and np.isnan(pid)):
        return np.nan, np.nan
    r = places.loc[places["place_id"] == pid]
    return (float(r["lat_mean"].iloc[0]), float(r["lon_mean"].iloc[0])) if len(r) else (np.nan, np.nan)


def _second(votes: dict, places: pd.DataFrame) -> tuple[float, float]:
    """(khoảng cách m giữa nơi nhất và nơi nhì, phiếu nơi nhì / phiếu nơi nhất); NaN nếu chỉ có một nơi."""
    mc = Counter(votes.values()).most_common(2)
    if len(mc) < 2:
        return np.nan, np.nan
    (p1, n1), (p2, n2) = mc
    a, b = _place_xy(places, p1), _place_xy(places, p2)
    return float(haversine_m(a[0], a[1], b[0], b[1])), n2 / n1


def _diam(s: pd.DataFrame, pid) -> float:
    if pid is None or (isinstance(pid, float) and np.isnan(pid)):
        return np.nan
    g = s[s["place_id"] == pid]
    return common.diameter_m(g["lat"].to_numpy(float), g["lon"].to_numpy(float))


def one_user(stays: pd.DataFrame, user: str, method) -> dict:
    """Một dòng kết quả cho (user, method); method là "v1" hoặc eps (m) của v2."""
    if method == "v1":
        places, s = cluster_v1.places_for_user(stays, user)
    else:
        eps, ms = _spec(method)
        places, s = cluster_v2.places_for_user(stays, user, eps, ms)
    noise = s["place_id"] < 0 if len(s) else pd.Series(dtype=bool)
    r = {"user": user, "method": _key(method), "n_stays": len(s), "n_places": len(places),
         "n_noise": int(noise.sum()),
         "noise_hours_share": float(s.loc[noise, "duration_min"].sum() / s["duration_min"].sum()) if len(s) and s["duration_min"].sum() > 0 else 0.0}
    if s.empty:
        return r | {"flags": "no_stays"}
    s = s[s["place_id"] >= 0]                               # bỏ nhiễu khi bỏ phiếu
    if s.empty:
        return r | {"flags": "no_places"}
    wf = hoc.workday_for(s)
    res = hoc.infer_user(s, wf)
    home, office = res.get("home"), res.get("office")
    hxy, oxy = _place_xy(places, home), _place_xy(places, office)
    d2h, r2h = _second(hoc._votes(hoc._minutes(s, [hoc.NIGHT])), places)
    d2o, r2o = _second(hoc._votes(hoc._minutes(s, hoc.WORK, wf)), places)
    hs = s[s["place_id"] == home] if home is not None else s.iloc[:0]
    return r | {
        "home": home, "office": office, "flags": res.get("flags", ""),
        "home_lat": hxy[0], "home_lon": hxy[1], "office_lat": oxy[0], "office_lon": oxy[1],
        "home_diam_m": _diam(s, home), "office_diam_m": _diam(s, office),
        "home_d2_m": d2h, "home_ratio2": r2h, "office_d2_m": d2o, "office_ratio2": r2o,
        "conf_home": res.get("conf_home", np.nan), "conf_office": res.get("conf_office", np.nan),
        "h_stable": res.get("h_stable", np.nan), "o_stable": res.get("o_stable", np.nan),
        "n_night_votes": res.get("n_night_votes", 0), "n_work_votes": res.get("n_work_votes", 0),
        # khoảng cách từ mỗi stay của nơi home đến tâm nơi đó (m): căn cứ chọn eps
        "home_stay_d": haversine_m(hxy[0], hxy[1], hs["lat"].to_numpy(float), hs["lon"].to_numpy(float)) if home is not None else np.array([]),
    }


def run(users, eps_list=EPS_LIST, ms_list=None, eps_ms: float = EPS_MS, stays_dir: Path = STAYS_DIR,
        cache_dir: Path = CACHE_DIR, verbose: bool = True) -> pd.DataFrame:
    """Bảng một dòng mỗi (user, cách gom). Đọc cache nếu có.

    `ms_list`: thêm các cách gom (eps_ms, min_samples) với min_samples > 1 (min_samples = 1 chính là eps_ms trong eps_list).
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    methods = ["v1", *eps_list]
    if ms_list:
        if eps_ms not in eps_list:
            methods.append(eps_ms)
        methods += [(eps_ms, m) for m in ms_list if m > 1]
    rows = []
    for i, u in enumerate(users, 1):
        stays = None
        fresh_after = max(_code_mtime(), _stays_mtime(stays_dir, u))
        for m in methods:
            f = cache_dir / f"{u}_{_key(m)}.pkl"
            if f.exists() and f.stat().st_mtime >= fresh_after:
                rows.append(pickle.loads(f.read_bytes()))
                continue
            if stays is None:
                stays = interim.read_df(Path(stays_dir) / u)
            r = one_user(stays, u, m)
            f.write_bytes(pickle.dumps(r))
            rows.append(r)
        if verbose and i % 20 == 0:
            print(f"{i}/{len(users)} user")
    return pd.DataFrame(rows)


def _same(a_lat, a_lon, b_lat, b_lon) -> np.ndarray:
    d = haversine_m(a_lat, a_lon, b_lat, b_lon)
    return np.asarray(d <= SAME_M)


def compare(R: pd.DataFrame) -> pd.DataFrame:
    """Bảng tóm tắt theo cách gom: một dòng mỗi method (v1, eps100, ...)."""
    R = R[~R["method"].str.contains("_m")]                  # bỏ các cách gom có min_samples > 1 (xem compare_ms)
    base = R[R["method"] == "v1"].set_index("user")
    out = []
    for m, g in R.groupby("method", sort=False):
        g = g.set_index("user")
        b = base.reindex(g.index)
        has_h = g["home"].notna() & b["home"].notna()
        has_o = g["office"].notna() & b["office"].notna()
        sh = _same(g["home_lat"], g["home_lon"], b["home_lat"], b["home_lon"])[has_h.to_numpy()]
        so = _same(g["office_lat"], g["office_lon"], b["office_lat"], b["office_lon"])[has_o.to_numpy()]
        fl = g["flags"].fillna("")
        bfl = b["flags"].fillna("")
        out.append({
            "cách gom": m, "user": len(g),
            "số địa điểm (trung vị)": g["n_places"].median(),
            "home cùng chỗ v1 (%)": 100 * sh.mean() if len(sh) else np.nan,
            "home đổi so với v1 (user)": int((~sh).sum()),
            "office cùng chỗ v1 (%)": 100 * so.mean() if len(so) else np.nan,
            "home = office (user)": int(fl.str.contains("home_eq_office").sum()),
            "gộp mới so với v1 (user)": int((fl.str.contains("home_eq_office") & ~bfl.str.contains("home_eq_office")).sum()),
            "đường kính home trung vị (m)": g["home_diam_m"].median(),
            "đường kính home p95 (m)": g["home_diam_m"].quantile(0.95),
            "đường kính home lớn nhất (m)": g["home_diam_m"].max(),
            "ổn định home (trung bình)": g["h_stable"].mean(),
            "confidence home (trung vị)": g["conf_home"].median(),
            "confidence office (trung vị)": g["conf_office"].median(),
        })
    return pd.DataFrame(out).set_index("cách gom")


def compare_ms(R: pd.DataFrame, eps_m: float = EPS_MS, ms_list=MS_LIST) -> pd.DataFrame:
    """Quét min_samples ở eps cố định. Mốc so sánh: min_samples = 1 (D20) và v1."""
    v1 = R[R["method"] == "v1"].set_index("user")
    keys = [(m, _key((eps_m, m))) for m in ms_list]
    base = R[R["method"] == _key((eps_m, 1))].set_index("user")
    out = []
    for m, k in keys:
        g = R[R["method"] == k].set_index("user")
        if g.empty:
            continue
        b = base.reindex(g.index)
        v = v1.reindex(g.index)
        n_st = g["n_stays"].sum()
        row = {"min_samples": m, "user": len(g),
               "số địa điểm (trung vị)": g["n_places"].median(),
               "stay nhiễu (%)": 100 * g["n_noise"].fillna(0).sum() / n_st if n_st else np.nan,
               "giờ nhiễu (% trung vị theo user)": 100 * g["noise_hours_share"].fillna(0).median()}
        for kind in ("home", "office"):
            had = b[kind].notna()
            lost = had & g[kind].isna()
            both = had & g[kind].notna()
            same = _same(g[f"{kind}_lat"], g[f"{kind}_lon"], b[f"{kind}_lat"], b[f"{kind}_lon"])
            row[f"{kind} mất so với min_samples=1 (user)"] = int(lost.sum())
            row[f"{kind} đổi so với min_samples=1 (user)"] = int((both.to_numpy() & ~same).sum())
        fl = g["flags"].fillna("")
        row["home = office (user)"] = int(fl.str.contains("home_eq_office").sum())
        row["gộp mới so với v1 (user)"] = int((fl.str.contains("home_eq_office") & ~v["flags"].fillna("").str.contains("home_eq_office")).sum())
        row["hết phiếu (no_night / no_workday, user)"] = int(fl.str.contains("no_night|no_workday").sum())
        row["đường kính home p95 (m)"] = g["home_diam_m"].quantile(0.95)
        row["confidence home (trung vị)"] = g["conf_home"].median()
        row["confidence office (trung vị)"] = g["conf_office"].median()
        out.append(row)
    return pd.DataFrame(out).set_index("min_samples")


def stay_distances(R: pd.DataFrame, method: str = "v1") -> pd.Series:
    """Gộp khoảng cách từ stay của nơi home đến tâm nơi đó (m), mọi user."""
    d = [x for x in R.loc[R["method"] == method, "home_stay_d"] if isinstance(x, np.ndarray) and len(x)]
    return pd.Series(np.concatenate(d)) if d else pd.Series(dtype=float)


def differing(R: pd.DataFrame, method: str, kind: str = "home") -> pd.DataFrame:
    """User mà `kind` (home / office) của `method` khác v1 (tâm cách nhau > SAME_M), kèm lý do để xem tay."""
    base = R[R["method"] == "v1"].set_index("user")
    g = R[R["method"] == method].set_index("user")
    b = base.reindex(g.index)
    ok = g[kind].notna() & b[kind].notna()
    d = pd.Series(haversine_m(g[f"{kind}_lat"], g[f"{kind}_lon"], b[f"{kind}_lat"], b[f"{kind}_lon"]), index=g.index)
    d = d[ok & (d > SAME_M)]
    t = pd.DataFrame({"cách nhau (m)": d.round(0),
                      "địa điểm v1": b.loc[d.index, "n_places"], "địa điểm v2": g.loc[d.index, "n_places"],
                      f"{kind} v1: nơi nhì (m)": b.loc[d.index, f"{kind}_d2_m"].round(0),
                      f"{kind} v2: nơi nhì (m)": g.loc[d.index, f"{kind}_d2_m"].round(0),
                      f"{kind} v2: đường kính (m)": g.loc[d.index, f"{kind}_diam_m"].round(0),
                      "cờ v1": b.loc[d.index, "flags"], "cờ v2": g.loc[d.index, "flags"]})
    return t.sort_values("cách nhau (m)", ascending=False)


def merged(R: pd.DataFrame, method: str) -> pd.DataFrame:
    """User bị gộp home với office ở `method` mà v1 không bị (chaining)."""
    base = R[R["method"] == "v1"].set_index("user")
    g = R[R["method"] == method].set_index("user")
    b = base.reindex(g.index)
    m = g["flags"].fillna("").str.contains("home_eq_office") & ~b["flags"].fillna("").str.contains("home_eq_office")
    cols = ["n_places", "home_diam_m", "n_night_votes", "n_work_votes"]
    return g.loc[m, cols].join(b.loc[m, ["office"]].rename(columns={"office": "office v1 (place_id)"}))


def plot(S: pd.DataFrame):
    """Chỉ số theo eps, v1 là đường ngang."""
    import matplotlib.pyplot as plt
    v2 = S.drop(index="v1")
    x = [int(i.replace("eps", "")) for i in v2.index]
    items = [("home cùng chỗ v1 (%)", "% user"), ("home đổi so với v1 (user)", "số user"), ("gộp mới so với v1 (user)", "số user"),
             ("đường kính home p95 (m)", "m"), ("số địa điểm (trung vị)", "địa điểm"), ("confidence home (trung vị)", "%")]
    fig, axs = plt.subplots(2, 3, figsize=(13, 6.5))
    for ax, (c, yl) in zip(axs.ravel(), items):
        ax.plot(x, v2[c], "o-", color="#2a6fb0", label="v2 (DBSCAN)")
        if c in S.columns and not np.isnan(S.loc["v1", c]):
            ax.axhline(S.loc["v1", c], color="#999", ls="--", label="v1")
        ax.set_title(c, fontsize=10)
        ax.set_xlabel("eps (m)")
        ax.set_ylabel(yl)
        ax.set_xticks(x)
        ax.grid(alpha=0.3)
    axs[0, 0].legend()
    fig.tight_layout()
    return fig
