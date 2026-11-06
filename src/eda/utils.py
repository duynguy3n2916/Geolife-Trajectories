"""Hàm nhỏ dùng trong các notebook EDA."""
import numpy as np
import pandas as pd

from .config import QUANTILES


# Phần trăm a / b, trả về NaN khi b = 0.
def pct(a, b):
    return 100 * a / b if b else np.nan


# Phân vị xấp xỉ từ histogram (lấy tâm hình học của ô).
def hist_quantile(counts, edges, q):
    c = np.cumsum(counts)
    if c[-1] == 0:
        return np.nan
    i = int(np.searchsorted(c, q * c[-1]))
    return float(np.sqrt(edges[i] * edges[i + 1]))


# Bảng phân vị QUANTILES và giá trị lớn nhất.
def qtable(q, mx, name):
    return pd.Series(np.r_[q, mx], index=[f"p{x * 100:g}" for x in QUANTILES] + ["max"], name=name).round(1).to_frame()


# Định dạng số giây cho nhãn: 10 giây, 5 phút, 2 giờ, không giới hạn.
def fmt_s(s):
    if not np.isfinite(s):
        return "không giới hạn"
    if s < 60:
        return f"{s:g} giây"
    if s < 3600:
        return f"{s / 60:g} phút"
    return f"{s / 3600:g} giờ"
