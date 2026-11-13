"""Đọc dữ liệu GPS tải lên (POST /v1/infer) thành DataFrame lat, lon, timestamp. Chỉ làm trong bộ nhớ.

Dạng nhận (khớp `PointsRequest`, `UploadFile` trong api/openapi.yaml):
    JSON      {"points": [{"lat": .., "lon": .., "timestamp": "2008-10-23T02:53:04Z"}, ...]}
    csv       .csv hoặc .csv.gz, có header, ít nhất cột lat, lon, timestamp
    plt_zip   .zip chứa các file .plt GeoLife (giờ trong file là UTC)
"""
from __future__ import annotations

import gzip
import io
import json
import sys
import zipfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
from infer import MAX_POINTS, InferError                 # noqa: E402
from preprocess.clean_trajectory import read_plt         # noqa: E402

MAX_BYTES = 50 * 1024 * 1024                             # 50 MB cho cả request
MAX_UNZIPPED = 10 * MAX_BYTES                            # chặn file nén bung quá lớn (zip bomb)
FORMATS = ("csv", "plt_zip")


class UploadError(InferError):
    """Lỗi đầu vào kèm HTTP status (InferError chỉ có code)."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(code, message)
        self.status = status


def points_from_json(body: bytes) -> pd.DataFrame:
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError) as e:
        raise UploadError(422, "validation_error", f"JSON không hợp lệ: {e}") from None
    pts = data.get("points") if isinstance(data, dict) else None
    if not isinstance(pts, list) or not all(isinstance(p, dict) for p in pts):
        raise UploadError(422, "validation_error", "cần object có trường 'points' là danh sách điểm")
    if len(pts) < 2:
        raise UploadError(422, "validation_error", "'points' cần ít nhất 2 điểm")
    if len(pts) > MAX_POINTS:
        raise UploadError(413, "payload_too_large", f"tối đa {MAX_POINTS:,} điểm, nhận {len(pts):,}")
    return pd.DataFrame.from_records(pts)


def guess_format(filename: str | None, fmt: str | None) -> str:
    if fmt:
        if fmt not in FORMATS:
            raise UploadError(415, "unsupported_format", f"format phải là một trong: {', '.join(FORMATS)}")
        return fmt
    name = (filename or "").lower()
    if name.endswith((".csv", ".csv.gz")):
        return "csv"
    if name.endswith(".zip"):
        return "plt_zip"
    raise UploadError(415, "unsupported_format", "chỉ nhận .csv, .csv.gz hoặc .zip các file .plt")


def _read_csv(data: bytes, filename: str | None) -> pd.DataFrame:
    if data[:2] == b"\x1f\x8b" or (filename or "").lower().endswith(".gz"):
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as g:
                data = g.read(MAX_UNZIPPED + 1)
        except (OSError, EOFError) as e:
            raise UploadError(400, "bad_archive", f"file .gz hỏng: {e}") from None
        if len(data) > MAX_UNZIPPED:
            raise UploadError(413, "payload_too_large", "file .gz bung ra quá lớn")
    try:
        return pd.read_csv(io.BytesIO(data))
    except (ValueError, pd.errors.ParserError, UnicodeDecodeError) as e:
        raise UploadError(400, "bad_file", f"không đọc được CSV: {e}") from None


def _read_plt_zip(data: bytes) -> pd.DataFrame:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise UploadError(400, "bad_archive", f"file .zip hỏng: {e}") from None
    with zf:
        infos = [i for i in zf.infolist() if i.filename.lower().endswith(".plt") and not i.is_dir()]
        if not infos:
            raise UploadError(400, "bad_archive", "file .zip không có file .plt nào")
        if sum(i.file_size for i in infos) > MAX_UNZIPPED:
            raise UploadError(413, "payload_too_large", "các file .plt bung ra quá lớn")
        parts = []
        for i in infos:
            try:
                parts.append(read_plt(io.BytesIO(zf.read(i))))
            except (zipfile.BadZipFile, ValueError, pd.errors.ParserError) as e:
                raise UploadError(400, "bad_archive", f"không đọc được {i.filename}: {e}") from None
    return pd.concat(parts, ignore_index=True)


def points_from_file(data: bytes, filename: str | None, fmt: str | None) -> pd.DataFrame:
    kind = guess_format(filename, fmt)
    return _read_csv(data, filename) if kind == "csv" else _read_plt_zip(data)
