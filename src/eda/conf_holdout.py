"""Mục 30 (notebook 10): confidence có dự đoán được kết quả ở giai đoạn sau không.

Với mỗi user: chia stay thành hai nửa theo giờ đến (trung vị thời gian). Chạy bỏ phiếu home / office (D18) **chỉ trên nửa đầu**
để có kết quả và confidence; chạy riêng trên nửa sau. Hỏi: user confidence cao ở nửa đầu có giữ nguyên nơi ở nửa sau nhiều
hơn user confidence thấp không?

Đo độ tái lập theo thời gian, không đo độ đúng (không có đáp án, A13). Nơi "trùng" khi cùng `place_id` hoặc hai tâm cách
nhau ≤ 200 m (gom địa điểm v1 có thể cắt đôi một nơi).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from places import home_office_conf as hoc

SAME_M = 200.0


def _dist_m(a, b) -> float:
    p1, p2 = np.radians(a[0]), np.radians(b[0])
    dl = np.radians(b[1] - a[1])
    h = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return float(2 * 6371000.0 * np.arcsin(np.sqrt(h)))


def split_halves(stays: pd.DataFrame):
    cut = stays["arrive_local"].median()
    return stays[stays["arrive_local"] <= cut], stays[stays["arrive_local"] > cut]


def user_rows(user: str, stays: pd.DataFrame) -> list[dict]:
    if len(stays) < 4:
        return []
    first, second = split_halves(stays)
    if first.empty or second.empty:
        return []
    wf = hoc.workday_for(stays)                     # cùng lịch ngày làm việc cho cả hai nửa
    ra, rb = hoc.infer_user(first, wf), hoc.infer_user(second, wf)
    cen = stays.groupby("place_id")[["lat", "lon"]].median()
    out = []
    for kind in ("home", "office"):
        pa, pb = ra.get(kind), rb.get(kind)
        nv = "n_night_votes" if kind == "home" else "n_work_votes"
        row = {"user": user, "kind": kind, "conf_first": ra.get(f"conf_{kind}", np.nan),
               "n_first": int(ra.get(nv, 0) or 0), "n_second": int(rb.get(nv, 0) or 0),
               "has_first": pa is not None and not pd.isna(pa), "has_second": pb is not None and not pd.isna(pb),
               "agree": np.nan}
        if row["has_first"] and row["has_second"]:
            a, b = int(pa), int(pb)
            row["agree"] = float(a == b or _dist_m(tuple(cen.loc[a]), tuple(cen.loc[b])) <= SAME_M)
        out.append(row)
    return out


def run(users, places_dir: Path = hoc.PLACES_DIR) -> pd.DataFrame:
    rows = []
    for u in users:
        f = Path(places_dir) / f"{u}_stays.parquet"
        if f.exists():
            rows += user_rows(u, pd.read_parquet(f))
    return pd.DataFrame(rows)


def summary(R: pd.DataFrame, kind: str, bins=(0, 70, 90, 100.01), labels=("dưới 70%", "70–90%", "từ 90%")):
    """Bảng theo mức confidence (%) của nửa đầu (chỉ user có confidence, tức đủ phiếu ở nửa đầu) và hệ số tương quan hạng.
    Nếu confidence có ý nghĩa thì mức cao phải trùng nơi ở nửa sau nhiều hơn mức thấp."""
    x = R[(R["kind"] == kind) & R["has_first"] & R["conf_first"].notna()].copy()
    x["confidence nửa đầu"] = pd.cut(x["conf_first"], bins=list(bins), labels=list(labels), right=False)
    g = x.groupby("confidence nửa đầu", observed=False).agg(**{
        "user có confidence nửa đầu": ("user", "size"),
        "có kết quả nửa sau": ("has_second", "sum"),
        "trùng nơi (% trong số có cả hai)": ("agree", lambda s: 100 * s.mean()),
        "confidence nửa đầu, trung bình (%)": ("conf_first", "mean")})
    both = x.dropna(subset=["agree"])
    rho = both["conf_first"].rank().corr(both["agree"].rank()) if len(both) > 2 else np.nan      # Spearman = Pearson trên hạng
    return g, float(rho), len(both)


def summary_by_votes(R: pd.DataFrame, kind: str, min_second: int = 7,
                     bins=(0, 3, 6, 13, 10 ** 9), labels=("1–3", "4–6", "7–13", "từ 14")) -> pd.DataFrame:
    """Nơi thắng của nửa đầu có trùng nơi thắng của nửa sau không, theo số phiếu **thật** ở nửa đầu.
    Chỉ lấy user có ít nhất `min_second` phiếu ở nửa sau để chuẩn (nửa sau) không quá nhiễu; vì nửa sau vẫn là một mẫu nên
    tỉ lệ trùng bị đo thấp hơn thực tế một chút."""
    x = R[(R["kind"] == kind) & R["has_first"] & R["has_second"] & (R["n_second"] >= min_second)].copy()
    x["số phiếu nửa đầu"] = pd.cut(x["n_first"], bins=list(bins), labels=list(labels))
    g = x.groupby("số phiếu nửa đầu", observed=False).agg(**{"số user": ("user", "size"),
                                                           "trùng nơi (%)": ("agree", lambda s: 100 * s.mean())})
    return g
