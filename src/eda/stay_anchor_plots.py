"""Biểu đồ cho notebook 10–13 (mục 1–3 (notebook 10, 13)). Mỗi hàm nhận bảng đã tính trong notebook và trả về Figure."""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

BLUE, ORANGE, GRAY = "#2a78d6", "#eb6834", "#b5b3ab"
INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
SURFACE = "#fcfcfb"


def _style(ax):
    ax.set_facecolor(SURFACE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color("#c3c2b7")
    ax.tick_params(colors=INK2, labelsize=9)
    ax.grid(axis="x", color=GRID, lw=0.6)
    ax.set_axisbelow(True)


def _fig(w, h, n=1):
    fig, axes = plt.subplots(1, n, figsize=(w, h), facecolor=SURFACE)
    return fig, np.atleast_1d(axes)


def _hbars(ax, labels, values, colors, fmt="{:.1f}", title=""):
    y = np.arange(len(labels))[::-1]
    ax.barh(y, values, color=colors, height=0.6)
    ax.set_yticks(y, labels)
    for yi, v in zip(y, values):
        ax.text(v, yi, " " + fmt.format(v), va="center", fontsize=9, color=INK)
    ax.set_xlim(0, max(values) * 1.25)
    ax.set_title(title, loc="left", fontsize=10, color=INK)
    _style(ax)


def far_gap_summary(moving_off, moving_on, still_both):
    """Mục 1 (notebook 11): ở gap-stay có hai đầu xa nhau, người dùng đang làm gì lúc tắt và lúc bật máy."""
    fig, ax = _fig(7.5, 3.0)
    _hbars(ax[0], ["đang đi lúc bật máy", "đang đi lúc tắt máy", "đứng yên cả hai lúc"],
           [moving_on, moving_off, still_both], [BLUE, BLUE, GRAY], "{:.0f}%",
           title="Hai đầu khoảng trống xa nhau: người dùng đang làm gì (% gap-stay)")
    ax[0].set_xlim(0, 110)
    ax[0].set_xlabel("%", color=MUTED, fontsize=9)
    fig.tight_layout()
    return fig


def gap_label_plot(tab: pd.DataFrame):
    """Mục 2.1c (notebook 11): theo độ dài khoảng trống (hai đầu gần nhau), bao nhiêu % có nhãn nói đang di chuyển ở một đầu."""
    fig, ax = _fig(8.5, 3.6)
    a = ax[0]
    x = np.arange(len(tab))
    a.plot(x, tab["% có nhãn di chuyển"], color=BLUE, lw=2, marker="o", ms=7, label="nhãn di chuyển (kể cả đi bộ)")
    a.plot(x, tab["% có nhãn xe"], color=ORANGE, lw=2, marker="o", ms=7, label="nhãn xe")
    for xi, n in zip(x, tab["n"]):
        a.text(xi, 1, f"n={n}", ha="center", fontsize=8, color=MUTED)
    a.set_xticks(x, [f"{iv.left:g}–{iv.right:g}" for iv in tab.index])
    a.set_xlabel("độ dài khoảng trống (giờ), chỉ gap hai đầu cách nhau ≤ 200 m", color=MUTED, fontsize=9)
    a.set_ylabel("% có nhãn ở một đầu", color=MUTED, fontsize=9)
    a.set_ylim(0, max(10, tab["% có nhãn di chuyển"].max() * 1.3))
    a.legend(frameon=False, fontsize=9)
    a.set_title("Khoảng trống sẽ bị nối thành stay nhưng nhãn nói đang di chuyển", loc="left", fontsize=10, color=INK)
    _style(a); a.grid(axis="y", color=GRID, lw=0.6); a.grid(axis="x", visible=False)
    fig.tight_layout()
    return fig


def routine_plot(tab: pd.DataFrame, ratio_min: float = 0.8):
    """Mục 2.5 (notebook 11): theo độ dài khoảng trống, % khoảng trống trùng nơi thường lệ so với % ngày GPS trùng."""
    fig, ax = _fig(12, 3.8, 2)
    x = np.arange(len(tab))
    lab = [f"{iv.left:g}–{iv.right:g}" for iv in tab.index]
    a = ax[0]
    a.plot(x, tab["% ngày GPS trùng nơi thường lệ"], color=GRAY, lw=2, ls="--", marker="o", ms=6, label="ngày có GPS")
    a.plot(x, tab["% khoảng trống trùng"], color=BLUE, lw=2, marker="o", ms=8, label="khoảng trống, tất cả")
    a.plot(x, tab["% trùng, hai đầu gần"], color=ORANGE, lw=2, marker="o", ms=7, label="khoảng trống, hai đầu gần")
    a.set_xticks(x, lab); a.set_ylim(0, 105)
    a.set_xlabel("độ dài khoảng trống (giờ)", color=MUTED, fontsize=9)
    a.set_ylabel("% trùng nơi thường lệ của khung giờ", color=MUTED, fontsize=9)
    a.legend(frameon=False, fontsize=8.5, loc="lower left")
    a.set_title("Khoảng trống có trùng nơi thường lệ như ngày có GPS không", loc="left", fontsize=10, color=INK)
    b = ax[1]
    b.axhline(ratio_min, color=MUTED, ls=":", lw=1)
    b.plot(x, tab["tỉ lệ (khoảng trống / ngày GPS)"], color=BLUE, lw=2, marker="o", ms=8, label="tất cả")
    b.plot(x, tab["% trùng, hai đầu gần"] / tab["% ngày GPS trùng nơi thường lệ"], color=ORANGE, lw=2, marker="o", ms=7, label="hai đầu gần")
    for xi, n in zip(x, tab["n khoảng trống"]):
        b.text(xi, 0.02, f"n={n}", ha="center", fontsize=8, color=MUTED)
    b.set_xticks(x, lab); b.set_ylim(0, 1.3)
    b.set_xlabel("độ dài khoảng trống (giờ)", color=MUTED, fontsize=9)
    b.set_ylabel("khoảng trống / ngày GPS", color=MUTED, fontsize=9)
    b.legend(frameon=False, fontsize=8.5, loc="upper right")
    b.set_title(f"Tỉ lệ (đường chấm: {ratio_min})", loc="left", fontsize=10, color=INK)
    for q in ax:
        _style(q); q.grid(axis="y", color=GRID, lw=0.6); q.grid(axis="x", visible=False)
    fig.tight_layout()
    return fig


def holdout_plot(summ: dict, base: int = 24):
    """Mục 2.4 (notebook 11): điểm dự đoán sang giai đoạn khác theo max gap, home và office."""
    fig, ax = _fig(11.5, 3.6, 2)
    for a, (kind, title) in zip(ax, [("home", "HOME (khung đêm 0–6h)"), ("office", "OFFICE (thứ 2–6, 9–17h)")]):
        t = summ[kind]
        x = np.arange(len(t))
        cols = [BLUE if c == base else GRAY for c in t.index]
        a.bar(x, 100 * t["điểm trung bình"], color=cols, width=0.6, zorder=2)
        for xi, v, n in zip(x, 100 * t["điểm trung bình"], t["n user"]):
            a.text(xi, v + 0.8, f"{v:.0f}%", ha="center", fontsize=9, color=INK)
        a.set_xticks(x, [str(c) for c in t.index]); a.set_xlabel("max gap (giờ)", color=MUTED, fontsize=9)
        a.set_ylabel("% GPS thật nằm trong 200 m quanh nơi dự đoán", color=MUTED, fontsize=9)
        a.set_ylim(0, max(10, 100 * t["điểm trung bình"].max() * 1.25))
        a.set_title(f"{title}, n = {int(t['n user'].iloc[0])} user", loc="left", fontsize=10, color=INK)
        _style(a); a.grid(axis="y", color=GRID, lw=0.6); a.grid(axis="x", visible=False)
    fig.tight_layout()
    return fig


def maxgap_plot(tab: pd.DataFrame):
    """Mục 2.2 (notebook 11): theo max gap, bao nhiêu giờ và bằng chứng còn lại, bao nhiêu user đổi nơi, stay tách."""
    fig, ax = _fig(13, 3.8, 3)
    x = tab.index.to_numpy()
    series = [("giờ stay còn lại (%)", "giờ stay (tất cả user)", GRAY),
              ("giờ đêm còn lại, trung vị user (%)", "giờ đêm 0–6h (trung vị user)", BLUE),
              ("giờ hành chính còn lại, trung vị user (%)", "giờ hành chính (trung vị user)", ORANGE)]
    for col, lab, c in series:
        ax[0].plot(x, tab[col], marker="o", color=c, lw=2, label=lab, zorder=3)
    ax[0].set_ylim(0, 105); ax[0].set_ylabel("% còn lại so với max gap 72 giờ", color=MUTED, fontsize=9)
    ax[0].legend(frameon=False, fontsize=8.5, loc="lower right")
    ax[0].set_title("Cắt khoảng trống dài: còn lại bao nhiêu giờ", loc="left", fontsize=10.5, color=INK)
    series = [("địa điểm 1 đổi nơi (% user)", "địa điểm 1 lệch > 100 m", GRAY),
              ("home đổi nơi (% user)", "home đổi nơi", BLUE), ("office đổi nơi (% user)", "office đổi nơi", ORANGE)]
    for col, lab, c in series:
        ax[1].plot(x, tab[col], marker="o", color=c, lw=2, label=lab, zorder=3)
    ax[1].axhline(5, color=INK2, ls="--", lw=1)
    ax[1].set_ylim(0, 100); ax[1].set_ylabel("% user", color=MUTED, fontsize=9)
    ax[1].legend(frameon=False, fontsize=8.5, loc="upper right")
    ax[1].set_title("Bao nhiêu user đổi nơi (đường chấm: 5%)", loc="left", fontsize=10.5, color=INK)
    ax[2].plot(x, tab["stay tách / 100 stay"], marker="o", color=BLUE, lw=2, zorder=3)
    ax[2].set_ylim(0, max(1, tab["stay tách / 100 stay"].max() * 1.3))
    ax[2].set_ylabel("stay bị tách / 100 stay", color=MUTED, fontsize=9)
    ax[2].set_title("Stay bị tách đôi", loc="left", fontsize=10.5, color=INK)
    for a in ax:
        a.set_xticks(x); a.set_xlabel("max gap (giờ)", color=MUTED, fontsize=9)
        _style(a); a.grid(axis="y", color=GRID, lw=0.6); a.grid(axis="x", visible=False)
    fig.tight_layout()
    return fig


def gap_length_summary(a: pd.DataFrame, g: pd.DataFrame, g2: pd.DataFrame):
    """Mục 2 (notebook 11): (trái) tỉ lệ hai đầu gần theo độ dài khoảng trống thật; (phải) precision khi xoá khoảng trống nhân tạo."""
    fig, ax = _fig(12, 3.8, 2)
    x = np.arange(len(a))
    lab = [f"{iv.left:g}–{iv.right:g}" for iv in a.index]
    l = ax[0]
    l.plot(x, a["gần, tất cả (%)"], color=GRAY, lw=2, ls="--", marker="o", ms=6, label="tất cả")
    l.plot(x, a["gần, ban ngày (%)"], color=BLUE, lw=2, ls="-", marker="o", ms=8, mec=SURFACE, mew=2, label="ban ngày")
    if "gần, qua đêm (%)" in a:
        l.plot(x, a["gần, qua đêm (%)"], color=ORANGE, lw=2, ls="-", marker="o", ms=8, mec=SURFACE, mew=2, label="qua đêm")
    l.set_xticks(x, lab)
    l.set_xlabel("độ dài khoảng trống thật (giờ)", color=MUTED, fontsize=9)
    l.set_ylim(0, 100)
    l.set_ylabel("% hai đầu cách nhau ≤ 200 m", color=MUTED, fontsize=9)
    l.set_title("Khoảng trống càng dài, hai đầu càng ít gần nhau", loc="left", fontsize=10, color=INK)
    l.legend(frameon=False, fontsize=9, loc="lower left")

    r = ax[1]
    L = list(g.index)
    xr = np.arange(len(L))
    r.axhline(90, color=MUTED, lw=1, ls=":")
    r.text(-0.35, 90.5, "90%  (điểm rỗng: 10–29 mẫu; dưới 10 mẫu: bỏ)", ha="left", va="bottom", fontsize=8, color=MUTED)
    r.plot(xr, g["precision (%)"], color=GRAY, lw=2, ls="--", marker="o", ms=6, label="tất cả")
    for col, c, name in [(False, BLUE, "ban ngày"), (True, ORANGE, "ban đêm")]:
        n = g2[("n", col)].reindex(L).fillna(0)
        p = g2[("precision", col)].reindex(L).where(n >= 10)     # dưới 10 mẫu: không vẽ
        r.plot(xr, p, color=c, lw=2, ls="-", label=name, zorder=2)
        ok = (n >= 30).to_numpy()
        r.scatter(xr[ok], p[ok], s=64, color=c, edgecolor=SURFACE, lw=2, zorder=3)
        r.scatter(xr[~ok], p[~ok], s=64, facecolor=SURFACE, edgecolor=c, lw=2, zorder=3)
    for xi, n in zip(xr, g["n"]):
        r.text(xi, 41, f"n={n:,}", ha="center", fontsize=8, color=MUTED)
    r.set_xticks(xr, [f"{v:g}" for v in L])
    r.set_ylim(40, 103)
    r.set_xlabel("độ dài khoảng trống nhân tạo L (giờ)", color=MUTED, fontsize=9)
    r.set_ylabel("precision: hai đầu gần ⇒ ở yên (%)", color=MUTED, fontsize=9)
    r.set_title("Xoá khoảng trống nhân tạo: hai đầu gần thì đúng bao nhiêu",
                loc="left", fontsize=10, color=INK)
    r.legend(frameon=False, fontsize=9, loc="center right")
    for x_ in ax:
        _style(x_)
        x_.grid(axis="y", color=GRID, lw=0.6)
        x_.grid(axis="x", visible=False)
    fig.suptitle("Độ dài khoảng trống: dưới 1 giờ dễ nối nhầm nhất; từ 2 giờ, hai đầu gần là đáng tin, ban đêm gần như chắc chắn",
                 x=0.01, ha="left", fontsize=11, color=INK)
    fig.tight_layout()
    return fig


# =============================================================================
# MỤC 18–21 (notebook 10): li so với h1_mean
# =============================================================================
GOOD, CRIT = "#006300", "#d03b3b"


def demo_li_vs_h1():
    """Quỹ đạo mẫu: Li đặt neo ở mép khu nên tách một lần ở thành 2 stay; h1_mean dời neo vào giữa, ra 1 stay.
    Chạy đúng run_li / run_h1 của stay_anchor.py."""
    from matplotlib.patches import Circle, FancyArrowPatch
    from eda import stay_anchor as sa
    rng = np.random.default_rng(3)
    lat0, lon0 = 39.98, 116.32
    my, mx = 111320.0, 111320.0 * np.cos(np.radians(lat0))
    xs, ys = [], []
    a = np.linspace((-650, -60), (-170, 0), 6, endpoint=False); xs += list(a[:, 0]); ys += list(a[:, 1])
    xs += list(-165 + rng.normal(0, 4, 3)); ys += list(rng.normal(0, 4, 3))                     # đứng ở cổng
    xs += list(np.clip(-80 + rng.normal(0, 25, 35), -140, -20)); ys += list(np.clip(rng.normal(0, 25, 35), -60, 60))
    xs += list(np.clip(30 + rng.normal(0, 35, 50), -40, 100)); ys += list(np.clip(rng.normal(0, 25, 50), -60, 60))
    a = np.linspace((180, 0), (700, 80), 7, endpoint=False); xs += list(a[:, 0]); ys += list(a[:, 1])
    x, y = np.array(xs), np.array(ys)
    t = np.arange(len(x)) * 60.0
    lat, lon = lat0 + y / my, lon0 + x / mx
    li = sa.run_li(lat, lon, t)
    h1 = sa.run_h1(lat, lon, t, li=li)
    (a1, b1), (a2, b2) = li[0], li[1]
    h0, h1e = h1[0]
    c1 = int(sa.mean_center(lat, lon, a1, b1))
    fig = plt.figure(figsize=(13, 7.4), facecolor=SURFACE)
    gs = fig.add_gridspec(2, 3, height_ratios=[1, 0.36])
    axs = [fig.add_subplot(gs[0, i]) for i in range(3)]
    tl = fig.add_subplot(gs[1, :])

    def base(ax, title, sub):
        ax.set_facecolor(SURFACE); ax.set_aspect("equal"); ax.set_xlim(-430, 330); ax.set_ylim(-290, 260)
        ax.set_xticks([]); ax.set_yticks([])
        for s in ax.spines.values():
            s.set_visible(False)
        ax.set_title(title, loc="left", fontsize=11.5, color=INK, pad=22)
        ax.text(0, 1.015, sub, transform=ax.transAxes, fontsize=9, color=INK2, va="bottom")
        ax.plot(x, y, color=GRAY, lw=0.8, zorder=1)
        ax.scatter(x, y, s=12, color=GRAY, edgecolor=SURFACE, lw=0.6, zorder=2)
        ax.plot([-400, -200], [-275, -275], color=INK2, lw=2); ax.text(-300, -262, "200 m", ha="center", fontsize=8, color=INK2)

    def pts(ax, i, c):
        ax.scatter(x[i], y[i], s=22, color=c, edgecolor=SURFACE, lw=0.8, zorder=3)

    def circ(ax, i, c, ls="-"):
        ax.add_patch(Circle((x[i], y[i]), 200, fill=False, ec=c, lw=1.6, ls=ls, zorder=2))

    def star(ax, i, c, label, dx, dy, hollow=False):
        ax.scatter(x[i], y[i], s=260, marker="*", color=SURFACE if hollow else c, edgecolor=c if hollow else INK,
                   lw=1.2 if hollow else 0.8, zorder=5)
        ax.annotate(label, (x[i], y[i]), xytext=(x[i] + dx, y[i] + dy), fontsize=9, color=INK, ha="center",
                    arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.8))

    ax = axs[0]; base(ax, "① Li: neo = điểm sớm nhất", "neo đặt ở cổng (mép khu), chỉ xét điểm SAU neo")
    pts(ax, np.arange(a1, b1 + 1), BLUE); circ(ax, a1, BLUE); star(ax, a1, BLUE, "neo (Li)", -60, -120)
    j = b1 + 1
    ax.scatter(x[j], y[j], s=90, marker="X", color=CRIT, edgecolor=SURFACE, lw=1, zorder=6)
    ax.annotate("điểm đầu tiên cách neo > 200 m\n→ stay dừng ở đây", (x[j], y[j]), xytext=(170, 195), fontsize=9,
                color=INK, ha="center", arrowprops=dict(arrowstyle="->", color=MUTED, lw=0.8))
    ax = axs[1]; base(ax, "② Li: một lần ở bị tách đôi", "phần còn lại phải bắt đầu một neo mới")
    pts(ax, np.arange(a1, b1 + 1), BLUE); pts(ax, np.arange(a2, b2 + 1), ORANGE)
    circ(ax, a1, BLUE, "--"); circ(ax, a2, ORANGE, "--")
    star(ax, a1, BLUE, "neo stay 1", -40, -120); star(ax, a2, ORANGE, "neo stay 2", 60, 150)
    ax = axs[2]; base(ax, "③ h1_mean: dời neo vào giữa stay", "rồi mở rộng cả hai phía, vẫn bán kính 200 m")
    pts(ax, np.arange(h0, h1e + 1), BLUE); circ(ax, c1, BLUE)
    star(ax, a1, MUTED, "neo cũ", -150, 120, hollow=True)
    star(ax, c1, BLUE, "neo mới = điểm gần\ntrung bình tọa độ của stay 1", 40, -245)
    ax.add_patch(FancyArrowPatch((x[a1] + 12, y[a1]), (x[c1] - 12, y[c1]), arrowstyle="-|>", mutation_scale=12,
                                 color=INK, lw=1.2, zorder=6))
    tl.set_facecolor(SURFACE)
    for s in ("top", "right", "left"):
        tl.spines[s].set_visible(False)
    tl.spines["bottom"].set_color("#c3c2b7"); tl.tick_params(colors=INK2, labelsize=9)
    m = t / 60

    def bar(row, a_, b_, c, txt):
        tl.barh(row, m[b_] - m[a_], left=m[a_], height=0.5, color=c)
        tl.text((m[a_] + m[b_]) / 2, row, txt, ha="center", va="center", fontsize=9, color="#ffffff")

    bar(1, a1, b1, BLUE, f"stay 1: {m[b1] - m[a1]:.0f} phút"); bar(1, a2, b2, ORANGE, f"stay 2: {m[b2] - m[a2]:.0f} phút")
    bar(0, h0, h1e, BLUE, f"1 stay: {m[h1e] - m[h0]:.0f} phút")
    tl.set_yticks([1, 0], ["li", "h1_mean"]); tl.set_ylim(-0.6, 1.6); tl.set_xlim(0, m[-1])
    tl.set_xlabel("thời gian (phút)", color=MUTED, fontsize=9)
    tl.set_title("④ Theo thời gian. Quy tắc an toàn: nếu stay mới NGẮN hơn stay của Li thì giữ stay của Li",
                 loc="left", fontsize=11, color=INK)
    fig.suptitle("Quỹ đạo mẫu (giả lập), chạy đúng code li và h1_mean, D = 200 m, T = 30 phút",
                 x=0.01, ha="left", fontsize=12, color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    return fig


def duration_dist(CS: pd.DataFrame):
    """Phân bố thời lượng stay của li và h1_mean (trục log)."""
    fig, ax = _fig(9, 3.6)
    ax = ax[0]
    bins = np.logspace(np.log10(0.5), np.log10(max(CS["dur_h"].max(), 1)), 40)
    for v, c, ls in [("li", GRAY, "--"), ("h1_mean", BLUE, "-")]:
        d = CS.loc[CS["variant"] == v, "dur_h"]
        ax.hist(d, bins=bins, histtype="step", color=c, lw=2, ls=ls, label=f"{v}: {len(d):,} stay, trung vị {d.median():.1f} giờ")
    ax.set_xscale("log")
    ax.set_xticks([0.5, 1, 2, 4, 8, 12, 24, 48], ["0,5", "1", "2", "4", "8", "12", "24", "48"])
    ax.set_xlabel("thời lượng stay (giờ, trục log)", color=MUTED, fontsize=9)
    ax.set_ylabel("số stay", color=MUTED, fontsize=9)
    ax.legend(frameon=False, fontsize=9)
    _style(ax); ax.grid(axis="y", color=GRID, lw=0.6); ax.grid(axis="x", visible=False)
    ax.set_title("Phân bố thời lượng gần như trùng nhau; h1_mean có ít stay ngắn hơn một chút (do gộp)",
                 loc="left", fontsize=10.5, color=INK)
    fig.tight_layout()
    return fig


def merge_example_plot(ex: dict):
    """Ví dụ thật, vẽ giống hình giả lập: (trái) Li với neo ở đầu mỗi stay và chỗ bị cắt; (phải) h1_mean với neo
    mới ở giữa; (dưới) theo thời gian."""
    from matplotlib.patches import Circle
    lat, lon, t = ex["lat"], ex["lon"], ex["t"]
    h1 = ex["h1"]
    la0, lo0 = ex["h1_anchor"]
    my, mx = 111320.0, 111320.0 * np.cos(np.radians(la0))
    xy = lambda la, lo: ((np.asarray(lo) - lo0) * mx, (np.asarray(la) - la0) * my)
    x, y = xy(lat, lon)
    ax_, ay_ = xy(*ex["li_anchor"])
    cx, cy = xy(ex["cut"][0], ex["cut"][1])
    cols = [BLUE, ORANGE, "#1baf7a", "#eda100", "#e87ba4", "#6250d6"]
    lim = 330
    fig = plt.figure(figsize=(13, 7.6), facecolor=SURFACE)
    gs = fig.add_gridspec(2, 2, height_ratios=[1, 0.42])
    A, B, tl = fig.add_subplot(gs[0, 0]), fig.add_subplot(gs[0, 1]), fig.add_subplot(gs[1, :])

    def base(ax, title, sub):
        ax.set_facecolor(SURFACE); ax.set_aspect("equal")
        ax.set_xlim(-lim, lim); ax.set_ylim(-lim * 0.8, lim * 0.8)
        ax.set_xticks([]); ax.set_yticks([])
        for s in ax.spines.values():
            s.set_visible(False)
        ax.set_title(title, loc="left", fontsize=11.5, color=INK, pad=22)
        ax.text(0, 1.015, sub, transform=ax.transAxes, fontsize=9, color=INK2, va="bottom")
        ax.plot(x, y, color=GRAY, lw=0.5, zorder=1, clip_on=True)
        ax.scatter(x, y, s=6, color=GRAY, zorder=2, clip_on=True)
        ax.plot([-lim + 20, -lim + 220], [-lim * 0.8 + 15] * 2, color=INK2, lw=2)
        ax.text(-lim + 120, -lim * 0.8 + 27, "200 m", ha="center", fontsize=8, color=INK2)

    base(A, f"Li: {ex['n_li']} stay liền nhau ở cùng một chỗ", "neo (★) = điểm đầu mỗi stay; ✕ = điểm đầu tiên cách neo > 200 m, Li cắt ở đây")
    for k, r in enumerate(ex["li"].itertuples()):
        c = cols[k % len(cols)]
        mk = (t >= r.t0) & (t <= r.t1)
        A.scatter(x[mk], y[mk], s=9, color=c, zorder=3)
        A.add_patch(Circle((ax_[k], ay_[k]), 200, fill=False, ec=c, lw=1.4, ls="--", zorder=4))
        A.scatter(ax_[k], ay_[k], s=230, marker="*", color=c, edgecolor=INK, lw=0.8, zorder=6)
        A.text(ax_[k] + 14, ay_[k] + 14, f"neo {k + 1}", fontsize=9, color=INK, zorder=7, weight="bold")
        if k < ex["n_li"] - 1:
            A.scatter(cx[k], cy[k], s=80, marker="X", color=CRIT, edgecolor=SURFACE, lw=1, zorder=7)
    base(B, "h1_mean: dời neo vào giữa, mở rộng hai phía", "neo mới (★) = điểm gần trung bình tọa độ của stay Li đầu tiên")
    mk = (t >= h1.t0) & (t <= h1.t1)
    B.scatter(x[mk], y[mk], s=9, color=BLUE, zorder=3)
    B.add_patch(Circle((0, 0), 200, fill=False, ec=BLUE, lw=1.6, zorder=4))
    B.scatter(ax_[0], ay_[0], s=230, marker="*", color=SURFACE, edgecolor=MUTED, lw=1.2, zorder=5)
    B.text(ax_[0] + 14, ay_[0] + 14, "neo cũ", fontsize=9, color=INK2, zorder=7)
    B.scatter(0, 0, s=260, marker="*", color=BLUE, edgecolor=INK, lw=0.8, zorder=6)
    B.text(14, -40, "neo mới", fontsize=9, color=INK, zorder=7, weight="bold")

    t0 = h1.t0 - 10 * 60
    hr = lambda v: (v - t0) / 3600
    tl.set_facecolor(SURFACE)
    for g in np.nonzero(np.diff(t) > 30 * 60)[0]:
        tl.axvspan(hr(t[g]), hr(t[g + 1]), color=GRID, zorder=0)
    for k, r in enumerate(ex["li"].itertuples()):
        tl.barh(1, (r.t1 - r.t0) / 3600, left=hr(r.t0), height=0.5, color=cols[k % len(cols)])
        tl.text(hr((r.t0 + r.t1) / 2), 1, f"stay {k + 1}\n{(r.t1 - r.t0) / 3600:.1f} giờ", ha="center", va="center",
                fontsize=8.5, color="#ffffff")
        if k < ex["n_li"] - 1:
            tl.scatter(hr(ex["cut"][2][k]), 1.38, s=60, marker="X", color=CRIT, zorder=5)
    tl.barh(0, h1.dur_h, left=hr(h1.t0), height=0.5, color=BLUE)
    tl.text(hr(h1.t0) + h1.dur_h / 2, 0, f"1 stay: {h1.dur_h:.1f} giờ", ha="center", va="center", fontsize=9, color="#ffffff")
    tl.set_yticks([1, 0], [f"li ({ex['n_li']} stay)", "h1_mean"]); tl.set_ylim(-0.6, 1.7)
    tl.set_xlim(0, hr(h1.t1) + 1 / 6)
    tl.set_xlabel(f"giờ, tính từ {pd.Timestamp(t0, unit='s'):%Y-%m-%d %H:%M} UTC   (nền xám: máy không ghi > 30 phút; ✕: chỗ Li cắt)",
                  color=MUTED, fontsize=9)
    for s in ("top", "right", "left"):
        tl.spines[s].set_visible(False)
    tl.spines["bottom"].set_color("#c3c2b7"); tl.tick_params(colors=INK2, labelsize=9)
    fig.suptitle(f"Ví dụ thật, user {ex['user']}: Li cắt một lần ở thành {ex['n_li']} stay vì neo nằm ở mép; h1_mean gộp lại thành 1",
                 x=0.01, ha="left", fontsize=12, color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    return fig


def user_change_hist(chg: pd.Series, title: str, xlabel: str):
    """Phân bố thay đổi theo user (vd. % đổi giờ stay)."""
    fig, ax = _fig(9, 3.4)
    ax = ax[0]
    lo, hi = np.percentile(chg.dropna(), [1, 99])
    ax.hist(chg.clip(lo, hi), bins=40, color=BLUE, edgecolor=SURFACE, lw=1)
    ax.axvline(0, color=INK2, lw=1)
    ax.axvline(chg.median(), color=INK, lw=1.5, ls="--")
    ax.text(chg.median(), ax.get_ylim()[1] * 0.92, f"  trung vị {chg.median():+.1f}", fontsize=9, color=INK)
    ax.set_xlabel(xlabel, color=MUTED, fontsize=9); ax.set_ylabel("số user", color=MUTED, fontsize=9)
    _style(ax); ax.grid(axis="y", color=GRID, lw=0.6); ax.grid(axis="x", visible=False)
    ax.set_title(title, loc="left", fontsize=10.5, color=INK)
    fig.tight_layout()
    return fig


def scorecard(m: dict):
    """Ba tiêu chí chốt h1_mean, mỗi tiêu chí một câu hỏi, li so với h1_mean và ngưỡng. m: số tính ở mục 4 (notebook 10)."""
    fig, axs = plt.subplots(1, 3, figsize=(13.5, 4.6), facecolor=SURFACE)
    items = [
        ("① Một lần ở có còn bị cắt đôi không?", "stay bị tách / 100 stay",
         m["split_li"], m["split_h1"], "{:.1f}", m["split_li"] * 0.8, "ngưỡng giảm ≥ 20%",
         m["split_h1"] <= m["split_li"] * 0.8,
         f"giảm {100 * (1 - m['split_h1'] / m['split_li']):.0f}%"),
        ("② Có nhận nhầm lúc đang đi là ở yên không?", f"% thời gian đang đi bị nhận là stay\n({m['n_label_users']} user có nhãn)",
         m["false_li"], m["false_h1"], "{:.2f}%", m["false_li"] + 1, "ngưỡng tăng ≤ 1 điểm",
         m["false_h1"] - m["false_li"] <= 1,
         f"tăng {m['false_h1'] - m['false_li']:.2f} điểm"),
        ("③ Nơi ở nhiều nhất có bị đổi chỗ không?", "% user giữ nguyên địa điểm 1\n(tâm lệch < 100 m)",
         100.0, 100 - m["shift1"], "{:.0f}%", 90, "ngưỡng ≥ 90% user",
         100 - m["shift1"] >= 90,
         f"lệch trung vị {m['shift1_med']:.1f} m"),
    ]
    for ax, (title, ylab, a, b, fmt, thr, thr_lab, ok, note) in zip(axs, items):
        lab = ["li\n(mốc)" if "③" in title else "li", "h1_mean"]
        bars = ax.bar(lab, [a, b], color=[GRAY, BLUE], width=0.55)
        for r, v in zip(bars, [a, b]):
            ax.text(r.get_x() + r.get_width() / 2, v, fmt.format(v), ha="center", va="bottom", fontsize=11, color=INK)
        ax.axhline(thr, color=INK2, ls=":", lw=1.3)
        top = max(a, b, thr) * 1.3
        ax.set_ylim(0, top)
        _style(ax); ax.grid(axis="x", visible=False); ax.grid(axis="y", color=GRID, lw=0.6)
        ax.set_ylabel(ylab, color=MUTED, fontsize=9)
        ax.set_title(title, loc="left", fontsize=11, color=INK, pad=28)
        ax.text(0, 1.035, ("✔ ĐẠT: " if ok else "✕ CHƯA ĐẠT: ") + note + f"   (chấm: {thr_lab})", transform=ax.transAxes,
                fontsize=9.5, color=GOOD if ok else CRIT, va="bottom")
    fig.suptitle(f"Chốt h1_mean: đạt cả ba tiêu chí ({m['n_users']} user, D = 200 m, T = 30 phút)" if all(i[7] for i in items)
                 else f"h1_mean so với li ({m['n_users']} user): chưa đạt hết tiêu chí", x=0.01, ha="left", fontsize=13, color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    return fig


# =============================================================================
# MỤC 27–29 (notebook 13): bằng chứng gộp gap vào home/office
# =============================================================================
def gap_coverage(H: pd.DataFrame, U: pd.DataFrame):
    """Mục 1 (notebook 13): gap chiếm bao nhiêu trong từng giờ của ngày, và với từng user."""
    fig, ax = _fig(13, 4, 3)
    hh = H.groupby("hour")[["gps_h", "gap_h"]].sum()
    share = 100 * hh["gap_h"] / (hh["gps_h"] + hh["gap_h"])
    a = ax[0]
    a.axvspan(-0.5, 5.5, color="#dbe8f8", zorder=0); a.axvspan(8.5, 16.5, color="#fbe5d8", zorder=0)
    a.bar(hh.index, share, color=BLUE, width=0.75, zorder=2)
    a.set_ylim(0, 105); a.set_xticks(range(0, 24, 3)); a.set_xlabel("giờ địa phương", color=MUTED, fontsize=9)
    a.set_ylabel("% thời gian là gap", color=MUTED, fontsize=9)
    a.text(2.5, 100, "khung đêm", ha="center", fontsize=8.5, color=INK2); a.text(12.5, 100, "khung hành chính", ha="center", fontsize=8.5, color=INK2)
    a.set_title("Mọi user gộp lại: gap chiếm bao nhiêu từng giờ", loc="left", fontsize=10.5, color=INK)
    for k, (col, lab, c) in enumerate([("night", "đêm 0–6h", BLUE), ("office", "hành chính, thứ 2–6, 9–17h", ORANGE)]):
        g, p = U[f"{col}_gap_h"], U[f"{col}_gps_h"]
        s = (100 * g / (g + p)).dropna()
        b = ax[1 + k]
        b.hist(s, bins=np.linspace(0, 100, 21), color=c, edgecolor=SURFACE, lw=1, zorder=2)
        b.axvline(s.median(), color=INK, ls="--", lw=1.4)
        b.text(s.median(), b.get_ylim()[1] * 0.93, f" trung vị {s.median():.0f}%", fontsize=9, color=INK)
        b.set_xlabel(f"% giờ {lab} là gap", color=MUTED, fontsize=9); b.set_ylabel("số user", color=MUTED, fontsize=9)
        b.set_title(f"Theo từng user: giờ {lab}", loc="left", fontsize=10.5, color=INK)
    for x_ in ax:
        _style(x_); x_.grid(axis="y", color=GRID, lw=0.6); x_.grid(axis="x", visible=False)
    fig.suptitle("Mục 1 (notebook 13): gap chiếm bao nhiêu giờ đêm và giờ hành chính",
                 x=0.01, ha="left", fontsize=12, color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    return fig


def gap_agreement(over_len: pd.DataFrame, over_ends: pd.DataFrame, day_len: pd.DataFrame, day_len_home: pd.DataFrame):
    """Mục 2 (notebook 13): gap có thật sự ở home / office (đáp án từ GPS) không."""
    fig, ax = _fig(13, 4.2, 3)

    def draw(a, t, title, color, xlabel, extra=None, extra_label=""):
        lab = [str(i).replace("(", "").replace("]", "").replace(", ", "–").replace(".0", "").replace("inf", "∞") for i in t.index]
        x = np.arange(len(t))
        a.bar(x, t["pct_ở_nơi_đó"], color=color, width=0.6, zorder=2)
        for xi, v, n in zip(x, t["pct_ở_nơi_đó"], t["n"]):
            a.text(xi, v + 1.5, f"{v:.0f}%", ha="center", fontsize=9, color=INK)
            a.text(xi, 2, f"n={n:,}", ha="center", fontsize=8, color=SURFACE if v > 12 else MUTED)
        if extra is not None:
            a.plot(x, extra.reindex(t.index)["pct_ở_nơi_đó"].to_numpy(), color=INK2, ls="--", marker="o", ms=6, lw=1.6, zorder=3, label=extra_label)
            a.legend(frameon=False, fontsize=8.5, loc="upper right")
        a.set_xticks(x, lab); a.set_ylim(0, 112); a.axhline(90, color=MUTED, ls=":", lw=1)
        a.set_xlabel(xlabel, color=MUTED, fontsize=9); a.set_ylabel("% gap có hai đầu ≤ 300 m cách địa điểm", color=MUTED, fontsize=9)
        a.set_title(title, loc="left", fontsize=10.5, color=INK)
        _style(a); a.grid(axis="y", color=GRID, lw=0.6); a.grid(axis="x", visible=False)

    draw(ax[0], over_len, "Gap qua đêm, hai đầu gần nhau: có ở HOME không?", BLUE, "độ dài gap (giờ)")
    draw(ax[1], over_ends, "Gap qua đêm, theo hai đầu cách nhau: có ở HOME không?", BLUE, "hai đầu cách nhau (m)")
    draw(ax[2], day_len, "Gap ban ngày, hai đầu gần nhau: có ở OFFICE không?", ORANGE, "độ dài gap (giờ)", day_len_home, "ở HOME (không phải office)")
    fig.suptitle("Mục 2 (notebook 13): gap nằm ở đâu so với home/office suy ra từ GPS (đường chấm: mốc 90%)", x=0.01, ha="left", fontsize=12, color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    return fig


def rest_window_hist(start: pd.Series, fixed_start: int = 0):
    """Giờ bắt đầu cửa sổ nghỉ học được của từng user; giờ của khung cố định (0h) tô xanh để so."""
    fig, ax = _fig(9, 3.6)
    ax = ax[0]
    cnt = start.dropna().astype(int).value_counts().reindex(range(24), fill_value=0)
    cols = [BLUE if h == fixed_start else GRAY for h in cnt.index]
    ax.bar(cnt.index, cnt.values, color=cols, zorder=2)
    for h, v in zip(cnt.index, cnt.values):
        if v:
            ax.text(h, v + 0.3, str(v), ha="center", fontsize=8, color=INK2)
    ax.set_xticks(range(0, 24, 2))
    ax.set_xlabel("giờ bắt đầu cửa sổ nghỉ 6 giờ học được (xanh = đúng giả định cố định 0h)", color=MUTED, fontsize=9)
    ax.set_ylabel("số user", color=MUTED, fontsize=9)
    ax.set_title("Cửa sổ nghỉ của từng user học từ gap dài", loc="left", fontsize=10.5, color=INK)
    _style(ax)
    ax.grid(axis="y", color=GRID, lw=0.6); ax.grid(axis="x", visible=False)
    fig.tight_layout()
    return fig


def rest_stability(tab: pd.DataFrame, labels: dict):
    """tab: cột what, method, n, pct_same (chỉ trên các user hợp lệ ở mọi cách)."""
    fig, ax = _fig(12.5, 3.6, 2)
    for a, what, title in [(ax[0], "home", "HOME: nửa tuần chẵn và lẻ cho cùng nơi"), (ax[1], "office", "OFFICE: nửa tuần chẵn và lẻ cho cùng nơi")]:
        t = tab[tab["what"] == what].set_index("method")
        y = np.arange(len(t))[::-1]
        a.barh(y, t["pct_same"], color=[BLUE if m.startswith("learn") else GRAY for m in t.index], height=0.6, zorder=2)
        for yi, v, n in zip(y, t["pct_same"], t["n"]):
            a.text(v + 1, yi, f"{v:.0f}%  (n={n})", va="center", fontsize=9, color=INK)
        a.set_yticks(y, [labels[m] for m in t.index]); a.set_xlim(0, 125)
        a.set_xlabel("% user có địa điểm đứng đầu giống nhau giữa hai nửa", color=MUTED, fontsize=9)
        a.set_title(title, loc="left", fontsize=10.5, color=INK)
        _style(a)
    ax[1].set_yticklabels([])
    fig.suptitle("Độ ổn định của home/office (cùng tập user ở mọi cách)", x=0.01, ha="left", fontsize=12, color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    return fig
