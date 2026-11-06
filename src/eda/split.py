"""Chia user thành nhóm dev và nhóm test (D17).

Pipeline là quy tắc, không có bước học. Nhưng ngưỡng (D, T, max gap, khung giờ, giờ bỏ phiếu) được chọn
bằng EDA. Để đánh giá cuối cùng không bị rò rỉ, mọi EDA chọn ngưỡng chỉ đọc nhóm dev; nhóm test để dành
cho nhãn gán tay và đánh giá một lần.

Chia theo user, không theo thời gian: nơi ở và nơi làm việc của một user giống nhau ở mọi tuần.
Phân tầng theo (tứ phân vị số ngày có file .plt) x (có labels.txt hay không), để hai nhóm cùng kiểu user.
Chỉ đọc tên file .plt ở data/raw (tên file là thời điểm bắt đầu, UTC), không cần parquet.

    python src/eda/split.py            # tạo data/split/users.csv nếu chưa có (không ghi đè)
    python src/eda/split.py --force    # tạo lại: chỉ làm khi chưa ai chọn ngưỡng trên bản chia cũ

Trong notebook:  from eda import split;  split.dev_users()
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "geolife" / "Data"
SPLIT_CSV = PROJECT_ROOT / "data" / "split" / "users.csv"
TEST_SHARE = 1 / 3
SEED = 20261105
N_STRATA = 4


def raw_summary(raw_dir: Path = RAW_DIR) -> pd.DataFrame:
    """Mỗi user một dòng: số file .plt, số ngày khác nhau (theo tên file, UTC), có labels.txt hay không."""
    rows = []
    for u in sorted(p for p in Path(raw_dir).iterdir() if p.is_dir()):
        names = [f.stem for f in (u / "Trajectory").glob("*.plt")]
        days = {n[:8] for n in names}
        rows.append({"user": u.name, "n_files": len(names), "n_days": len(days), "has_labels": (u / "labels.txt").exists()})
    return pd.DataFrame(rows)


def make_split(summary: pd.DataFrame, test_share: float = TEST_SHARE, seed: int = SEED, n_strata: int = N_STRATA) -> pd.DataFrame:
    """Gán group = 'dev' hoặc 'test' cho từng user; trong mỗi tầng lấy round(test_share * n) user vào test."""
    d = summary.sort_values("user").reset_index(drop=True).copy()
    d["quartile"] = pd.qcut(d["n_days"].rank(method="first"), n_strata, labels=False)
    d["stratum"] = d["quartile"].astype(int) * 2 + d["has_labels"].astype(int)
    rng = np.random.default_rng(seed)
    d["group"] = "dev"
    for _, idx in d.groupby("stratum").groups.items():
        idx = np.array(sorted(idx))
        k = int(round(test_share * len(idx)))
        d.loc[rng.permutation(idx)[:k], "group"] = "test"
    return d[["user", "group", "n_days", "n_files", "has_labels", "stratum"]]


def load_split(path: Path = SPLIT_CSV) -> pd.DataFrame:
    if not Path(path).exists():
        raise FileNotFoundError(f"Chưa có {path}. Chạy: python src/eda/split.py")
    return pd.read_csv(path, dtype={"user": str})


def dev_users() -> list[str]:
    s = load_split()
    return sorted(s.loc[s["group"] == "dev", "user"])


def test_users() -> list[str]:
    """Chỉ dùng cho nhãn gán tay và đánh giá cuối. Không dùng trong EDA chọn ngưỡng."""
    s = load_split()
    return sorted(s.loc[s["group"] == "test", "user"])


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--force", action="store_true", help="ghi đè bản chia hiện có")
    args = ap.parse_args()
    if SPLIT_CSV.exists() and not args.force:
        print(f"Đã có {SPLIT_CSV}, giữ nguyên (dùng --force để tạo lại).")
        s = load_split()
    else:
        s = make_split(raw_summary())
        SPLIT_CSV.parent.mkdir(parents=True, exist_ok=True)
        s.to_csv(SPLIT_CSV, index=False)
        print(f"Đã ghi {SPLIT_CSV}")
    g = s.groupby("group").agg(user=("user", "size"), n_days_median=("n_days", "median"), n_days_tong=("n_days", "sum"),
                               co_nhan=("has_labels", "sum"))
    print(g.to_string())


if __name__ == "__main__":
    main()
