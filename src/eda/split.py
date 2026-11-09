"""Chia user thành nhóm validation và nhóm test (D17).

Pipeline là quy tắc, không có bước học. Nhưng ngưỡng (D, T, max gap, khung giờ, giờ bỏ phiếu) được chọn
bằng EDA. Để đánh giá cuối cùng không bị rò rỉ, mọi EDA chọn ngưỡng chỉ đọc nhóm validation; nhóm test để dành
cho đánh giá một lần.

Chia theo user, không theo thời gian: nơi ở và nơi làm việc của một user giống nhau ở mọi tuần.
Cân bằng giữa validation và test (mục tiêu 1/3 vào test) theo số user, số ngày, số file, số user có labels.txt, số đoạn nhãn theo
nhóm phương tiện và số user ở từng tứ phân vị số ngày; tìm cách gán cụm user bằng simulated annealing để user nhiều dữ liệu
không dồn vào một nhóm.

Thứ tự: lọc user là bản sao (excluded_copies) rồi mới chia; user bị loại có group = 'excluded'.

Gom user trùng file (D17, cập nhật 2026-11-07): một số user có file .plt giống hệt từng byte với user khác
(file bị chép sang). Nếu hai user đó nằm ở hai nhóm khác nhau thì nhóm test đã bị "nhìn thấy" qua validation.
Vì vậy user nào dùng chung file thì vào CÙNG một nhóm (đơn vị chia là cụm user, không phải từng user).
Việc này chỉ so md5 của file, không đọc thông tin về vị trí hay giờ giấc, nên không làm lộ gì về nhóm test.
Kết quả so md5 lưu ở data/split/shared_files.csv (lần đầu quét mất khoảng 1–2 phút).
Cột copy_share = tỉ lệ file của user nằm trong nhóm file chép giữa các user; từ 0,9 trở lên là gần như toàn bộ
bản sao (cờ mostly_copy), do người dùng quyết định có bỏ hay không.

    python src/eda/split.py            # tạo data/split/users.csv nếu chưa có (không ghi đè)
    python src/eda/split.py --force    # tạo lại: chỉ làm khi chưa ai chọn ngưỡng trên bản chia cũ

Trong notebook:  from eda import split;  split.val_users()
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
from paths import PROJECT_ROOT                         # noqa: E402

RAW_DIR = PROJECT_ROOT / "data" / "raw" / "geolife" / "Data"
SPLIT_CSV = PROJECT_ROOT / "data" / "split" / "users.csv"
TEST_SHARE = 1 / 3
SEED = 20261107
SHARED_CSV = PROJECT_ROOT / "data" / "split" / "shared_files.csv"
MOSTLY_COPY = 0.9
KEEP_LABELS = 100        # user mostly_copy nhưng có từ ngần này đoạn nhãn thì giữ (nhãn là dữ liệu riêng)
N_STRATA = 4


MODE_GROUPS = {"walk": "walk", "bike": "bike", "bus": "bus", "car": "car", "taxi": "car", "train": "rail", "subway": "rail",
               "railway": "rail"}   # kiểu khác (run, airplane, boat, motorcycle) vào nhóm "other"
LABEL_COLS = ["lab_walk", "lab_bike", "lab_bus", "lab_car", "lab_rail", "lab_other"]


def raw_summary(raw_dir: Path = RAW_DIR) -> pd.DataFrame:
    """Mỗi user một dòng: số file .plt, số ngày khác nhau (theo tên file, UTC), có labels.txt hay không,
    và số đoạn nhãn theo nhóm phương tiện (chỉ đếm dòng của labels.txt, không đọc quỹ đạo)."""
    rows = []
    for u in sorted(p for p in Path(raw_dir).iterdir() if p.is_dir()):
        names = [f.stem for f in (u / "Trajectory").glob("*.plt")]
        days = {n[:8] for n in names}
        r = {"user": u.name, "n_files": len(names), "n_days": len(days), "has_labels": (u / "labels.txt").exists()}
        r.update({c: 0 for c in LABEL_COLS})
        if r["has_labels"]:
            for line in (u / "labels.txt").read_text(errors="ignore").splitlines()[1:]:
                parts = line.strip().split("\t")
                if len(parts) >= 3:
                    r["lab_" + MODE_GROUPS.get(parts[2].strip().lower(), "other")] += 1
        rows.append(r)
    d = pd.DataFrame(rows)
    d["n_labels"] = d[LABEL_COLS].sum(axis=1)
    return d


def shared_files(path: Path = SHARED_CSV, rescan: bool = False) -> pd.DataFrame:
    """Nhóm file .plt giống hệt từng byte ở nhiều user (md5, so các file trùng tên). Lưu cache ở SHARED_CSV."""
    if Path(path).exists() and not rescan:
        return pd.read_csv(path, dtype=str)
    from eda import duplicates as dups
    g = dups.cross_user_groups(progress=False)
    g = g[g["n_users"] >= 2].copy()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    g.to_csv(path, index=False)
    return g.astype(str)


def user_clusters(users, groups: pd.DataFrame) -> dict:
    """user -> mã cụm: hai user cùng cụm nếu (trực tiếp hoặc qua người khác) có chung file giống hệt."""
    parent = {u: u for u in users}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for uc in groups["user_counts"]:
        us = [p.split(":")[0] for p in uc.split(",")]
        for u in us[1:]:
            parent[find(u)] = find(us[0])
    return {u: find(u) for u in users}


def copy_share(summary: pd.DataFrame, groups: pd.DataFrame) -> pd.Series:
    """Tỉ lệ file của mỗi user nằm trong nhóm file giống hệt ở nhiều user (tính theo số file)."""
    n = {u: 0 for u in summary["user"]}
    for uc in groups["user_counts"]:
        for p in uc.split(","):
            u, c = p.split(":")
            n[u] += int(c)
    return pd.Series({u: min(n[u] / max(f, 1), 1.0) for u, f in zip(summary["user"], summary["n_files"])})


def excluded_copies(d: pd.DataFrame) -> pd.Series:
    """Loại user gần như toàn bộ là bản sao (mostly_copy), chỉ giữ MỘT đại diện cho mỗi nhóm bản sao giống nhau:
    - user mostly_copy có từ KEEP_LABELS đoạn nhãn trở lên thì giữ (nhãn là dữ liệu riêng của user đó);
    - nếu mọi user của cụm đều mostly_copy (chép lẫn nhau, không có bản gốc) thì giữ user đầu tiên của cụm;
    - còn lại bị loại. Chỉ dùng md5 file và số dòng labels.txt, không đọc quỹ đạo."""
    ex = d["mostly_copy"] & (d["n_labels"] < KEEP_LABELS)
    for c, g in d.groupby("cluster"):
        if g["mostly_copy"].all() and ex.loc[g.index].all():
            ex.loc[g.sort_values("user").index[0]] = False
    return ex


def make_split(summary: pd.DataFrame, groups: pd.DataFrame | None = None, test_share: float = TEST_SHARE,
               seed: int = SEED, n_strata: int = N_STRATA) -> pd.DataFrame:
    """Gán group = 'val' (validation) hoặc 'test' cho từng CỤM user (user trùng file cùng cụm); phân tầng theo số ngày và nhãn."""
    d = summary.sort_values("user").reset_index(drop=True).copy()
    d["quartile"] = pd.qcut(d["n_days"].rank(method="first"), n_strata, labels=False)
    d["stratum"] = d["quartile"].astype(int) * 2 + d["has_labels"].astype(int)
    if groups is None:
        groups = pd.DataFrame({"user_counts": []})
    cl = user_clusters(list(d["user"]), groups)
    d["cluster"] = d["user"].map(cl)
    d["cluster_size"] = d.groupby("cluster")["user"].transform("size")
    d["copy_share"] = d["user"].map(copy_share(d, groups)).round(3)
    d["mostly_copy"] = d["copy_share"] >= MOSTLY_COPY
    # Lọc bản sao TRƯỚC khi chia (thứ tự: khảo sát, lọc + gom trùng, chia, tuning): chỉ user còn lại mới được chia và cân bằng.
    d["excluded"] = excluded_copies(d)
    out_rows = d[d["excluded"]].copy()
    out_rows["group"] = "excluded"
    d = d[~d["excluded"]].copy().reset_index(drop=True)
    d["quartile"] = pd.qcut(d["n_days"].rank(method="first"), n_strata, labels=False)
    d["stratum"] = d["quartile"].astype(int) * 2 + d["has_labels"].astype(int)
    # Chia theo CỤM (user trùng file cùng nhóm), chọn cách gán làm các đại lượng sau của test sát test_share nhất:
    # số user, số ngày, số file, số user có nhãn, số đoạn nhãn theo từng nhóm phương tiện, và số user ở từng tứ phân vị số ngày.
    # Chỉ dùng số đếm (tên file, dòng labels.txt, md5 file), không đọc quỹ đạo nên không lộ gì về phương pháp.
    # Cụm có tổng số ngày > 1/6 tổng số ngày (nếu vào test thì một nhóm user chép lẫn nhau chiếm phần lớn test) cố định vào validation.
    # Tìm bằng simulated annealing (hạt giống cố định, lặp lại được).
    d["lab_users"] = d["has_labels"].astype(int)
    for q in range(n_strata):
        d[f"q{q}"] = (d["quartile"] == q).astype(int)
    d["users_n"] = 1
    feats = ["users_n", "n_days", "n_files", "lab_users", "n_labels"] + LABEL_COLS + [f"q{q}" for q in range(n_strata)]
    w = np.array([3, 3, 1, 2, 2] + [1] * len(LABEL_COLS) + [1] * n_strata, dtype=float)
    cl_feat = d.groupby("cluster")[feats].sum()
    cls = list(cl_feat.index)
    X = cl_feat.to_numpy(dtype=float)
    tot = X.sum(axis=0)
    ok = tot > 0
    days_col = feats.index("n_days")
    fixed_val = X[:, days_col] > tot[days_col] / 6
    rng = np.random.default_rng(seed)

    def loss(t):
        share = t[ok] / tot[ok]
        return float((w[ok] * ((share - test_share) / test_share) ** 2).sum())
    # khởi đầu: ngẫu nhiên khoảng test_share số cụm
    state = (rng.random(len(cls)) < test_share) & ~fixed_val
    cur = X[state].sum(axis=0); cur_l = loss(cur)
    best_state, best_l = state.copy(), cur_l
    free = np.nonzero(~fixed_val)[0]
    n_iter = 60000
    for i in range(n_iter):
        temp = 0.5 * (1 - i / n_iter) + 1e-3
        j = rng.choice(free)
        new = cur + (-X[j] if state[j] else X[j])
        nl = loss(new)
        if nl < cur_l or rng.random() < np.exp((cur_l - nl) / temp):
            state[j] = ~state[j]; cur, cur_l = new, nl
            if cur_l < best_l:
                best_state, best_l = state.copy(), cur_l
    test_cl = {c for c, s_ in zip(cls, best_state) if s_}
    d["group"] = np.where(d["cluster"].isin(test_cl), "test", "val")
    d = pd.concat([d, out_rows], ignore_index=True).sort_values("user").reset_index(drop=True)
    d["stratum"] = d["stratum"].fillna(-1).astype(int)
    return d[["user", "group", "n_days", "n_files", "has_labels", "n_labels"] + LABEL_COLS + ["stratum", "cluster", "cluster_size", "copy_share", "mostly_copy", "excluded"]]


def load_split(path: Path = SPLIT_CSV) -> pd.DataFrame:
    if not Path(path).exists():
        raise FileNotFoundError(f"Chưa có {path}. Chạy: python src/eda/split.py")
    return pd.read_csv(path, dtype={"user": str})


def val_users() -> list[str]:
    s = load_split()
    return sorted(s.loc[(s["group"] == "val") & ~s.get("excluded", False), "user"])


def test_users() -> list[str]:
    """Chỉ dùng cho đánh giá cuối. Không dùng trong EDA chọn ngưỡng."""
    s = load_split()
    return sorted(s.loc[(s["group"] == "test") & ~s.get("excluded", False), "user"])


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--force", action="store_true", help="ghi đè bản chia hiện có")
    args = ap.parse_args()
    if SPLIT_CSV.exists() and not args.force:
        print(f"Đã có {SPLIT_CSV}, giữ nguyên (dùng --force để tạo lại).")
        s = load_split()
    else:
        summ = raw_summary()
        s = make_split(summ, shared_files(rescan=args.force))
        SPLIT_CSV.parent.mkdir(parents=True, exist_ok=True)
        s.to_csv(SPLIT_CSV, index=False)
        print(f"Đã ghi {SPLIT_CSV}")
    agg = {"user": ("user", "size"), "ngay_tong": ("n_days", "sum"), "ngay_trung_vi": ("n_days", "median"), "file": ("n_files", "sum"),
           "co_nhan": ("has_labels", "sum")}
    if "n_labels" in s:
        agg["doan_nhan"] = ("n_labels", "sum")
        agg.update({c: (c, "sum") for c in LABEL_COLS})
    g = s.groupby("group").agg(**agg)
    g.loc["test / tong"] = (g.loc["test"] / g.sum(numeric_only=True)).where(~g.columns.isin(["ngay_trung_vi"]))
    print(g.round(3).T.to_string())
    if "cluster_size" in s:
        multi = s[s["cluster_size"] > 1]
        mixed = multi[multi["group"] != "excluded"].groupby("cluster")["group"].nunique().gt(1).sum()
        print(f"Cụm có từ 2 user trở lên: {multi['cluster'].nunique()} cụm, {len(multi)} user; cụm bị tách giữa validation và test: {mixed}")
        print("User gần như toàn bộ là bản sao (mostly_copy):", ", ".join(s.loc[s['mostly_copy'], 'user']) or "không có")


if __name__ == "__main__":
    main()
