"""Đọc kết quả GeoLife tính sẵn từ api/store/geolife.sqlite (tạo bằng api/build_store.py). Nạp hết vào bộ nhớ."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
import infer                                    # noqa: E402


def _flags(x) -> list[str]:
    return [f for f in str(x).split(";") if f] if isinstance(x, str) else []


def _has(x) -> bool:
    return x is not None and not (isinstance(x, float) and np.isnan(x))


class GeolifeStore:
    def __init__(self, path: Path):
        if not Path(path).exists():
            raise FileNotFoundError(f"Không có {path}; chạy python api/build_store.py trước")
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as con:
            res = pd.read_sql("SELECT * FROM results", con, dtype={"user": str})
            pl = pd.read_sql("SELECT * FROM places", con, dtype={"user": str})
            self.built_at = dict(con.execute("SELECT key, value FROM meta").fetchall()).get("built_at")
        res = res.sort_values(["model_version", "user"])
        self._results = {v: g.set_index("user", drop=False) for v, g in res.groupby("model_version")}
        self._places = {k: g.sort_values("place_id").reset_index(drop=True)
                        for k, g in pl.groupby(["model_version", "user"])}

    def versions(self) -> set[str]:
        return set(self._results)

    def _row(self, version: str, user: str):
        r = self._results.get(version)
        return None if r is None or user not in r.index else r.loc[user].to_dict()

    def _user_places(self, version: str, user: str) -> pd.DataFrame:
        return self._places.get((version, user), pd.DataFrame(columns=["place_id", "lat", "lon", "n_stays",
                                                                         "total_hours", "gap_hours"]))

    def list_users(self, version: str, limit: int, offset: int, has_home=None, has_office=None) -> tuple[int, list]:
        r = self._results.get(version)
        if r is None:
            return 0, []
        hh, ho = r["home"].notna(), r["office"].notna()
        m = pd.Series(True, index=r.index)
        if has_home is not None:
            m &= hh == has_home
        if has_office is not None:
            m &= ho == has_office
        sel = r[m]
        items = [{"user_id": u, "has_home": bool(hh[u]), "has_office": bool(ho[u]), "flags": _flags(f)}
                 for u, f in zip(sel["user"].iloc[offset:offset + limit], sel["flags"].iloc[offset:offset + limit])]
        return int(m.sum()), items

    def locations(self, version: str, user: str):
        row = self._row(version, user)
        if row is None:
            return None
        pl = self._user_places(version, user)
        return {"user_id": user, "model_version": version,
                "home": infer.location(pl, row, "home") if _has(row["home"]) else None,
                "office": infer.location(pl, row, "office") if _has(row["office"]) else None,
                "flags": _flags(row["flags"])}

    def places(self, version: str, user: str, limit: int):
        row = self._row(version, user)
        if row is None:
            return None
        home = int(row["home"]) if _has(row["home"]) else None
        office = int(row["office"]) if _has(row["office"]) else None
        return {"user_id": user, "model_version": version,
                "items": infer.place_rows(self._user_places(version, user), home, office, limit)}
