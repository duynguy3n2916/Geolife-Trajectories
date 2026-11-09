"""Số đêm / ngày làm việc tối thiểu để bỏ phiếu home / office (A11; notebook 13, mục 3).

Cách đo (hai mẫu rời nhau, không có chuẩn trùng với mẫu): với mỗi user và mỗi k, bốc ngẫu nhiên 2k phiếu, chia hai nhóm
rời nhau mỗi nhóm k phiếu, bỏ phiếu riêng từng nhóm, rồi hỏi hai nhóm có cho cùng nơi thắng không. Lặp N_REP lần, lấy
trung bình theo user rồi theo nhóm user. Hoà phiếu: chia đều khả năng giữa các nơi hoà.

Đo **độ tái lập** (ít phiếu có cho cùng kết quả như ít phiếu khác không), không đo độ đúng (chưa có nhãn, A13).
Nếu mỗi nhóm trùng với "nơi thắng thật" với xác suất q thì hai nhóm trùng nhau khoảng q², nên mức 0,81 hai nhóm trùng
nhau ứng với mỗi nhóm trùng chuẩn khoảng 90%.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from places import home_office_conf as hc

N_REP = 200
KS = [1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 14, 17, 20, 25]
THR = 0.81                      # hai nhóm trùng nhau; ứng với mỗi nhóm trùng chuẩn khoảng 90%
N_FIXED = 28                    # nhóm user cố định: đủ 28 phiếu thì dùng được mọi k đến 14
SEED = 20261106


def votes_of_user(stays: pd.DataFrame) -> dict:
    """{'home': [place_id theo từng đêm có phiếu], 'office': [...theo từng ngày làm việc]} sắp theo ngày."""
    wd = hc.workday_for(stays)
    out = {}
    for kind, v in (("home", hc._votes(hc._minutes(stays, [hc.NIGHT]))),
                    ("office", hc._votes(hc._minutes(stays, hc.WORK, wd)))):
        out[kind] = [v[d] for d in sorted(v)]
    return out


def _winner_dist(sample) -> dict:
    c = Counter(sample)
    top = max(c.values())
    tied = [p for p, n in c.items() if n == top]
    return {p: 1.0 / len(tied) for p in tied}


def _agree(a, b) -> float:
    da, db = _winner_dist(a), _winner_dist(b)
    return float(sum(da[p] * db.get(p, 0.0) for p in da))


def split_agreement(seq: list, ks=KS, n_rep=N_REP, rng=None) -> dict:
    """{k: xác suất hai nhóm rời nhau k phiếu cho cùng nơi thắng}, chỉ các k có 2k <= số phiếu."""
    rng = rng or np.random.default_rng(SEED)
    n = len(seq)
    out = {}
    for k in ks:
        if 2 * k > n:
            continue
        vals = []
        for _ in range(n_rep):
            idx = rng.choice(n, 2 * k, replace=False)
            vals.append(_agree([seq[i] for i in idx[:k]], [seq[i] for i in idx[k:]]))
        out[k] = float(np.mean(vals))
    return out


def run(users, places_dir: Path = hc.PLACES_DIR) -> pd.DataFrame:
    """Bảng dài: user, kind, n (số phiếu), k, agree."""
    rng = np.random.default_rng(SEED)
    rows = []
    for u in users:
        f = Path(places_dir) / f"{u}_stays.parquet"
        if not f.exists():
            continue
        st = pd.read_parquet(f)
        if st.empty or "place_id" not in st.columns:
            continue
        for kind, seq in votes_of_user(st).items():
            rows.append({"user": u, "kind": kind, "n": len(seq), "k": 0, "agree": np.nan})     # k = 0: chỉ ghi số phiếu của user
            for k, a in split_agreement(seq, rng=rng).items():
                rows.append({"user": u, "kind": kind, "n": len(seq), "k": k, "agree": a})
    return pd.DataFrame(rows)


def coverage(D: pd.DataFrame, n_users: int, thresholds=(6, 10, 14, 20, 28)) -> pd.DataFrame:
    """Phép đo phủ bao nhiêu: với mỗi ngưỡng số phiếu t (user cần ít nhất t phiếu), có bao nhiêu user, bao nhiêu % user
    của nhóm đang xét (`n_users`, kể cả user không có stay) và bao nhiêu % tổng số phiếu."""
    rows = {}
    for kind in ("home", "office"):
        base = D[(D["kind"] == kind) & (D["k"] == 0)]
        tot = base["n"].sum()
        for t in thresholds:
            s = base[base["n"] >= t]
            rows[(kind, f"≥ {t} phiếu")] = {"số user": len(s), "% user của nhóm": 100 * len(s) / n_users,
                                            "% tổng số phiếu": 100 * s["n"].sum() / tot if tot else np.nan}
    t = pd.DataFrame(rows).T
    t.index.names = ["loại", "điều kiện"]
    return t


def table(D: pd.DataFrame, ks=(3, 5, 7, 10, 14), thr=THR) -> pd.DataFrame:
    """Bảng gọn: theo k, % cặp nhóm trùng nhau (trung bình user) và số user, cho home và office, trên mọi user dùng được
    và trên nhóm cố định (>= N_FIXED phiếu)."""
    rows = {}
    for k in ks:
        r = {}
        for kind in ("home", "office"):
            d = D[(D["kind"] == kind) & (D["k"] == k)]
            r[f"{kind}: mọi user (%)"] = 100 * d["agree"].mean() if len(d) else np.nan
            r[f"{kind}: số user"] = len(d)
            f = d[d["n"] >= N_FIXED]
            r[f"{kind}: nhóm cố định (%)"] = 100 * f["agree"].mean() if len(f) else np.nan
        rows[f"k = {k}"] = r
    t = pd.DataFrame(rows).T
    t.index.name = "số phiếu mỗi nhóm"
    return t


def first_k(D: pd.DataFrame, kind: str, fixed: bool, thr=THR):
    """k nhỏ nhất mà trung bình >= thr và không tụt xuống dưới thr ở các k lớn hơn (trong KS có dữ liệu)."""
    d = D[(D["kind"] == kind) & (D["k"] > 0)]
    if fixed:
        d = d[d["n"] >= N_FIXED]
    m = d.groupby("k")["agree"].mean()
    ok = m >= thr
    for k in m.index:
        if ok.loc[k:].all():
            return int(k), int(d[d["k"] == k]["user"].nunique())
    return None, int(d["user"].nunique())


def plot(D: pd.DataFrame, thr=THR):
    import matplotlib.pyplot as plt
    fig, axs = plt.subplots(1, 2, figsize=(11.5, 4.2), sharey=True)
    for a, kind, col, name in zip(axs, ("home", "office"), ("#2563eb", "#ea580c"), ("Home (phiếu đêm)", "Office (phiếu ngày làm việc)")):
        d = D[(D["kind"] == kind) & (D["k"] > 0)]
        allm = d.groupby("k")["agree"].mean()
        cnt = d.groupby("k")["user"].nunique()
        fx = d[d["n"] >= N_FIXED].groupby("k")["agree"].mean()
        a.plot(allm.index, 100 * allm.values, "-o", color=col, lw=2, ms=4, label="mọi user dùng được (số user giảm khi k tăng)")
        if len(fx):
            a.plot(fx.index, 100 * fx.values, "--s", color=col, lw=1.5, ms=4, alpha=.7, label=f"nhóm cố định (≥ {N_FIXED} phiếu)")
        a.axhline(100 * thr, color="#6b7280", lw=1)
        a.text(1, 100 * thr + 1, "81%: mỗi nhóm trùng chuẩn khoảng 90%", ha="left", va="bottom", fontsize=8, color="#6b7280")
        for k, n in cnt.items():
            if k in (3, 7, 14, 25):
                a.annotate(f"n={n}", (k, 100 * allm[k]), textcoords="offset points", xytext=(0, -14), ha="center", fontsize=8, color=col)
        a.set_title(name, loc="left", fontsize=11)
        a.set_xlabel("số phiếu mỗi nhóm (hai nhóm rời nhau)")
        a.set_ylim(40, 102)
        a.grid(alpha=.25)
        a.spines[["top", "right"]].set_visible(False)
    axs[0].set_ylabel("% hai nhóm cho cùng nơi thắng")
    axs[0].legend(fontsize=8, loc="lower right", frameon=False)
    fig.suptitle("Bao nhiêu đêm / ngày làm việc thì kết quả bỏ phiếu lặp lại được", x=0.01, ha="left", fontsize=12)
    fig.tight_layout()
    return fig
