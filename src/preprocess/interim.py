"""Dữ liệu trung gian (data/interim): bản sao nguyên vẹn của dữ liệu thô GeoLife ở định dạng nhị phân.

Đọc 18.670 file .plt dạng văn bản mất khoảng 10 phút; đọc cùng dữ liệu từ file nhị phân chỉ vài giây.
Vì vậy dữ liệu thô được chuyển đổi MỘT LẦN (src/preprocess/convert_raw.py), sau đó EDA và bước lọc
đều đọc từ đây. Đây không phải dữ liệu đã xử lý: không lọc, không tính gì, chỉ đổi định dạng.

    data/interim/points/<user>.parquet   lat, lon, timestamp (UTC), file  (mọi dòng của mọi file .plt)
    data/interim/files/<user>.parquet    file, n_points, start, end       (mỗi file .plt một dòng)
    data/interim/labels/<user>.parquet   start, end, mode                 (chỉ user có labels.txt)

Định dạng: parquet nếu có thư viện pyarrow (gọn hơn, nên dùng); không có thì tự dùng pickle (.pkl).
Các hàm save_df / read_df cũng được bước lọc dùng để ghi data/processed/clean/<user>.parquet.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "geolife" / "Data"
INTERIM_DIR = PROJECT_ROOT / "data" / "interim"
KINDS = ("points", "files", "labels")

try:
    import pyarrow  # noqa: F401
    FORMAT = "parquet"
except ImportError:
    FORMAT = "pickle"


# Đọc / ghi một bảng theo đường dẫn KHÔNG có đuôi file (ví dụ data/processed/clean/000).
# Dùng chung cho data/interim và data/processed; giữ nguyên kiểu dữ liệu (thời gian có múi giờ, số nguyên...).
def save_df(df: pd.DataFrame, stem: Path) -> Path:
    path = Path(stem).with_suffix(".parquet" if FORMAT == "parquet" else ".pkl")
    path.parent.mkdir(parents=True, exist_ok=True)
    if FORMAT == "parquet":
        df.to_parquet(path, index=False)
    else:
        df.reset_index(drop=True).to_pickle(path)
    return path


# Ưu tiên parquet, không có thì đọc pickle; không có cả hai thì trả về None.
def read_df(stem: Path) -> pd.DataFrame | None:
    pq, pk = Path(stem).with_suffix(".parquet"), Path(stem).with_suffix(".pkl")
    if pq.exists():
        return pd.read_parquet(pq)
    if pk.exists():
        return pd.read_pickle(pk)
    return None


# Ghi / đọc một loại dữ liệu (points / files / labels) của một user trong data/interim.
def save_table(df: pd.DataFrame, kind: str, user: str) -> Path:
    return save_df(df, INTERIM_DIR / kind / user)


def read_table(kind: str, user: str) -> pd.DataFrame | None:
    return read_df(INTERIM_DIR / kind / user)


# Danh sách user có file trong một thư mục (parquet hoặc pickle).
def list_stems(d: Path) -> list[str]:
    d = Path(d)
    if not d.is_dir():
        return []
    return sorted({p.stem for p in d.iterdir() if p.suffix in (".parquet", ".pkl")})


# Danh sách user đã được chuyển đổi (có file points).
def list_users() -> list[str]:
    return list_stems(INTERIM_DIR / "points")


# Kiểm tra đã chuyển đổi chưa; báo lỗi rõ ràng nếu chưa.
def require_interim() -> list[str]:
    users = list_users()
    if not users:
        raise FileNotFoundError(
            f"Chưa có dữ liệu trong {INTERIM_DIR}. Chạy một lần: python src/preprocess/convert_raw.py")
    return users


def load_points(user: str) -> pd.DataFrame:
    return read_table("points", user)


def load_files(user: str) -> pd.DataFrame:
    return read_table("files", user)


def load_labels(user: str) -> pd.DataFrame | None:
    return read_table("labels", user)
