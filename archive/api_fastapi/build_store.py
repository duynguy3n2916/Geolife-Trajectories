"""Tạo store cho các API GeoLife: gom kết quả bước 7 và bảng địa điểm của mọi version vào một file SQLite.

Chạy sau bước 7 của pipeline (cho từng version), từ thư mục Home_Office:

    python api/build_store.py                  # -> api/store/geolife.sqlite

Đọc:
    reports/home_office_<key>_val.csv, reports/home_office_<key>_test.csv     (bước 7)
    data/processed/places_<key>/<user>_places.parquet                        (bước 6)
với <key> là v1, v2 theo src/models.py. File ra chỉ gồm home/office, cờ và tối đa MAX_PLACES địa điểm mỗi user,
cỡ vài trăm KB, nên commit được và đóng vào image Docker; API không cần thư mục data/ khi chạy.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import models                                   # noqa: E402
from places import common                       # noqa: E402

STORE = ROOT / "api" / "store" / "geolife.sqlite"
GROUPS = ("val", "test")
MAX_PLACES = 100                                # khớp giới hạn `limit` của /places trong api/openapi.yaml
RESULT_COLS = ["user", "n_stays", "home", "office", "n_night_votes", "n_work_votes", "conf_home", "conf_office",
               "flags", "h_share", "h_margin", "h_gps", "h_stable", "o_share", "o_margin", "o_gps", "o_stable"]
PLACE_COLS = ["user", "place_id", "lat", "lon", "n_stays", "total_hours", "gap_hours"]


def _empty_stay_users(key: str) -> list[str]:
    """User có file stay rỗng (không có stay nào) trong places_<key>."""
    out = []
    for f in sorted(common.places_dir(key).glob("*_stays.parquet")):
        if pd.read_parquet(f, columns=["user"]).empty:
            out.append(f.name.split("_")[0])
    return out


def load_results(key: str) -> pd.DataFrame:
    parts = []
    for g in GROUPS:
        f = ROOT / "reports" / f"home_office_{key}_{g}.csv"
        if not f.exists():
            raise SystemExit(f"Thiếu {f.relative_to(ROOT)}: chạy bước 7 với --version {key} cho nhóm {g} trước")
        parts.append(pd.read_csv(f, dtype={"user": str}))
    d = pd.concat(parts, ignore_index=True)
    # CSV bước 7 tạo trước ngày 09/11 để trống cột user ở các user không có stay (lỗi đã sửa trong run()).
    # Các dòng đó giống hệt nhau (chỉ cờ no_stays), nên điền lại bằng các user có file stay rỗng.
    blank = d["user"].isna()
    if blank.any():
        cand = sorted(set(_empty_stay_users(key)) - set(d["user"].dropna()))
        if len(cand) != blank.sum() or not (d.loc[blank, "flags"] == "no_stays").all():
            raise SystemExit(f"home_office_{key}_*.csv có {blank.sum()} dòng thiếu user; chạy lại bước 7 "
                             f"(python src/places/home_office_conf.py --version {key}, rồi --test)")
        d.loc[blank, "user"] = cand
    if d["user"].duplicated().any():
        raise SystemExit(f"User trùng giữa các nhóm trong home_office_{key}_*.csv")
    return d[RESULT_COLS]


def load_places(key: str, users) -> pd.DataFrame:
    parts = []
    for u in users:
        f = common.places_dir(key) / f"{u}_places.parquet"
        if f.exists():                          # user không có stay thì không có file địa điểm
            parts.append(pd.read_parquet(f, columns=PLACE_COLS).sort_values("place_id").head(MAX_PLACES))
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=PLACE_COLS)


def write(out: Path, results: pd.DataFrame, places: pd.DataFrame) -> Path:
    """Ghi store. results, places đã có cột model_version. Ghi ra file tạm rồi đổi tên, để API không đọc file dở."""
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    try:
        results.to_sql("results", con, index=False)
        places.to_sql("places", con, index=False)
        pd.DataFrame({"key": ["built_at"], "value": [datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")]}
                     ).to_sql("meta", con, index=False)
        con.execute("CREATE INDEX ix_results ON results(model_version, user)")
        con.execute("CREATE INDEX ix_places ON places(model_version, user)")
        con.commit()
    finally:
        con.close()
    tmp.replace(out)
    return out


def build(out: Path = STORE) -> Path:
    rs, ps = [], []
    for m in models.MODELS.values():
        r = load_results(m.key)
        p = load_places(m.key, r["user"])
        rs.append(r.assign(model_version=m.version))
        ps.append(p.assign(model_version=m.version))
        print(f"{m.version}: {len(r)} user, {len(p)} địa điểm")
    write(out, pd.concat(rs, ignore_index=True), pd.concat(ps, ignore_index=True))
    print(f"-> {out} ({out.stat().st_size / 1024:.0f} KB)")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=STORE)
    build(ap.parse_args().out)
