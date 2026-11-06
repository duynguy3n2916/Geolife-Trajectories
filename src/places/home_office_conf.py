"""Bước 7: gán home / office cho từng user bằng bỏ phiếu theo ngày, kèm độ tin cậy (D14, D18).

Đầu vào: data/processed/places_v1/{user}_stays.parquet (stay đã gán place_id, giờ địa phương).

Cách làm (D18):
- Mỗi **đêm** (20–7h giờ địa phương, đêm bắt đầu từ ngày d) chọn địa điểm có nhiều phút chồng lên khung nhất: 1 phiếu home.
- Mỗi **ngày làm việc** (T2–T6; với user ở Trung Quốc bỏ ngày lễ và thêm ngày làm bù, `calendar_cn.py`) chọn địa điểm có nhiều phút trong
  8:30–18:00 liền (giờ trưa tính như giờ khác): 1 phiếu office.
- home = địa điểm nhiều phiếu đêm nhất. office = địa điểm nhiều phiếu ngày làm việc nhất;
  nếu trùng home thì office = None, cờ `home_eq_office`.
- confidence (%) = lấy mẫu lại (bootstrap): bốc lại các ngày có phiếu của user, có hoàn lại, cùng số lượng, bỏ phiếu lại;
  lặp N_BOOT lần; confidence = % lần vẫn ra đúng nơi đã chọn (hoà thì chia đều). Tự gộp tỉ lệ phiếu, chênh lệch với
  nơi thứ hai và số phiếu. Dưới N_MIN_NIGHTS / N_MIN_WORKDAYS phiếu: vẫn trả home / office nhưng confidence để trống
  (NaN) và có cờ few_nights / few_workdays, vì với ít phiếu cùng một nơi, bốc lại luôn cho 100%.
- Cột báo cáo thêm, không vào confidence: tỉ lệ phiếu (*_share), chênh lệch với nơi thứ hai (*_margin), ổn định khi đổi
  tuần chẵn / lẻ, nửa đầu / nửa sau, khung giờ (*_stable; < 0,5 thì cờ unstable_*), tỉ lệ giờ GPS thật (*_gps).

Điểm này đo độ chắc của quy tắc, không phải xác suất đúng (chưa có nhãn thật, A13).
"""
from __future__ import annotations

import argparse
import zlib
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PLACES_DIR = ROOT / "data" / "processed" / "places_v1"

H = 3600.0
# Khung (giờ địa phương, số thực). work là danh sách đoạn trong ngày.
NIGHT = (20.0, 31.0)                       # 20h tới 7h hôm sau
WORK = [(8.5, 18.0)]                       # lõi 10–17h nằm trong; giờ trưa không loại; 18–20h vùng xám, không tính
MIN_VOTE_MIN = 60.0                        # ít hơn 60 phút trong khung thì ngày đó không có phiếu
N_MIN_NIGHTS = 7                           # A11: dưới mức này có cờ few_nights / few_workdays và không tính confidence
N_MIN_WORKDAYS = 7

N_BOOT = 200                               # số lần lấy mẫu lại cho confidence
SEED = 20261106

# Biến thể khung để đo độ ổn định
NIGHT_ALT = [(19.0, 30.0), (21.0, 31.0), (20.0, 30.0)]
WORK_ALT = [[(9.0, 18.0)], [(8.5, 17.0)], [(10.0, 17.0)]]


def _secs(ts: pd.Series) -> np.ndarray:
    return ts.to_numpy("datetime64[s]").astype("int64").astype(float)


def _is_weekday(day: np.datetime64) -> bool:
    return (day.astype("datetime64[D]").astype(int) + 4) % 7 < 5      # 1970-01-01 là thứ Năm


def _minutes(stays: pd.DataFrame, windows, day_ok=None) -> dict:
    """{ngày: Counter(place_id -> phút)} cho các đoạn `windows` (giờ, có thể > 24) bắt đầu từ ngày đó."""
    a = _secs(stays["arrive_local"])
    b = _secs(stays["leave_local"])
    p = stays["place_id"].to_numpy()
    out: dict = {}
    lo_h = min(w[0] for w in windows)
    hi_h = max(w[1] for w in windows)
    for s, e, pid in zip(a, b, p):
        d0 = int(np.floor((s - hi_h * H) / 86400.0))
        d1 = int(np.floor((e - lo_h * H) / 86400.0))
        for d in range(d0, d1 + 1):
            t = 0.0
            for w0, w1 in windows:
                ov = min(e, d * 86400.0 + w1 * H) - max(s, d * 86400.0 + w0 * H)
                if ov > 0:
                    t += ov
            if t > 0:
                day = np.datetime64(d, "D")
                if day_ok is not None and not day_ok(day):
                    continue
                out.setdefault(day, Counter())[int(pid)] += t / 60.0
    return out


def _votes(per_day: dict, min_min: float = MIN_VOTE_MIN) -> dict:
    """{ngày: place_id thắng} — chỉ ngày có ít nhất `min_min` phút ở nơi thắng."""
    res = {}
    for day, c in per_day.items():
        pid, m = c.most_common(1)[0]
        if m >= min_min:
            res[day] = pid
    return res


def _top2(votes: dict):
    c = Counter(votes.values())
    mc = c.most_common(2)
    n = sum(c.values())
    if not mc:
        return None, 0.0, 0.0, 0
    share = mc[0][1] / n
    second = mc[1][1] / n if len(mc) > 1 else 0.0
    return mc[0][0], share, share - second, n


def _boot_conf(votes: dict, win, rng, n_boot: int = N_BOOT) -> float:
    """Tỉ lệ lần lấy mẫu lại (bốc lại các ngày có phiếu, có hoàn lại, cùng số lượng) mà `win` vẫn thắng; hoà thì chia đều."""
    if win is None or not votes:
        return 0.0
    places, codes = np.unique(np.array(list(votes.values())), return_inverse=True)
    n, k = len(codes), len(places)
    pick = codes[rng.integers(0, n, size=(n_boot, n))]
    counts = np.zeros((n_boot, k))
    np.add.at(counts, (np.repeat(np.arange(n_boot), n), pick.ravel()), 1)
    top = counts == counts.max(axis=1, keepdims=True)
    w = int(np.nonzero(places == win)[0][0])
    return float((top[:, w] / top.sum(axis=1)).mean())


def _week_parity(days) -> dict:
    return {d: (int((d.astype("datetime64[D]").astype(int) + 3) // 7) % 2) for d in days}   # tuần tính từ thứ Hai


def _winner(votes: dict, keep) -> int | None:
    sub = {d: p for d, p in votes.items() if keep(d)}
    return _top2(sub)[0] if sub else None


def _stability(votes_main: dict, win_main, alt_votes: list[dict]) -> float:
    """Tỉ lệ phép thử cho cùng nơi thắng: chẵn/lẻ tuần, nửa đầu/nửa sau, và các biến thể khung."""
    if win_main is None:
        return 0.0
    checks = []
    days = sorted(votes_main)
    if len(days) >= 4:
        par = _week_parity(days)
        w0, w1 = _winner(votes_main, lambda d: par[d] == 0), _winner(votes_main, lambda d: par[d] == 1)
        if w0 is not None and w1 is not None:
            checks.append(float(w0 == w1))
        mid = days[len(days) // 2]
        h0, h1 = _winner(votes_main, lambda d: d < mid), _winner(votes_main, lambda d: d >= mid)
        if h0 is not None and h1 is not None:
            checks.append(float(h0 == h1))
    for v in alt_votes:
        w = _top2(v)[0]
        if w is not None:
            checks.append(float(w == win_main))
    return float(np.mean(checks)) if checks else 0.0


def gps_share(stays: pd.DataFrame, pid) -> float:
    s = stays[stays["place_id"] == pid]
    tot = s["duration_min"].sum()
    return float(1.0 - s["gap_min"].sum() / tot) if tot > 0 else 0.0


def workday_default(day) -> bool:
    return _is_weekday(day)


def workday_for(stays: pd.DataFrame):
    """Lịch ngày làm việc của user: lịch nghỉ lễ Trung Quốc nếu vị trí (trung vị lat, lon của stay) nằm ở
    Trung Quốc, ngược lại T2–T6 thường."""
    try:
        from src.preprocess.calendar_cn import in_china, is_workday_cn
    except ImportError:          # notebook: src/ nằm trong sys.path
        from preprocess.calendar_cn import in_china, is_workday_cn
    if len(stays) and in_china(float(stays["lat"].median()), float(stays["lon"].median())):
        return is_workday_cn
    return workday_default


def infer_user(stays: pd.DataFrame, workday_fn=None) -> dict:
    """Home / office, confidence (lấy mẫu lại) và các cột báo cáo của một user. `workday_fn=None`: chọn lịch theo vị trí."""
    if workday_fn is None:
        workday_fn = workday_for(stays)
    r = {"user": stays["user"].iloc[0] if len(stays) else None, "n_stays": len(stays)}
    rng = np.random.default_rng([SEED, zlib.crc32(str(r["user"]).encode())])     # cùng user thì cùng kết quả
    flags = []
    if stays.empty:
        return r | {"home": None, "office": None, "flags": "no_stays", "conf_home": np.nan, "conf_office": np.nan}

    # ---- home
    nv = _votes(_minutes(stays, [NIGHT]))
    home, hshare, hmargin, hn = _top2(nv)
    alt_n = [_votes(_minutes(stays, [w])) for w in NIGHT_ALT]
    comp_h = dict(share=hshare, margin=hmargin,
                  gps=gps_share(stays, home) if home is not None else 0.0,
                  stable=_stability(nv, home, alt_n))
    if home is None:
        flags.append("no_night")

    # ---- office
    wv = _votes(_minutes(stays, WORK, workday_fn))
    office, oshare, omargin, on = _top2(wv)
    alt_w = [_votes(_minutes(stays, w, workday_fn)) for w in WORK_ALT]
    comp_o = dict(share=oshare, margin=omargin,
                  gps=gps_share(stays, office) if office is not None else 0.0,
                  stable=_stability(wv, office, alt_w))
    if office is None:
        flags.append("no_workday")
    elif home is not None and office == home:
        flags.append("home_eq_office")
        office = None
        comp_o = {k: 0.0 for k in comp_o}
    if hn < N_MIN_NIGHTS:
        flags.append("few_nights")
    if on < N_MIN_WORKDAYS:
        flags.append("few_workdays")
    if hn and home is not None and comp_h["stable"] < 0.5:
        flags.append("unstable_home")
    if on and office is not None and comp_o["stable"] < 0.5:
        flags.append("unstable_office")

    r.update(home=home, office=office, n_night_votes=hn, n_work_votes=on,
             conf_home=round(100 * _boot_conf(nv, home, rng), 1) if home is not None and hn >= N_MIN_NIGHTS else np.nan,
             conf_office=round(100 * _boot_conf(wv, office, rng), 1) if office is not None and on >= N_MIN_WORKDAYS else np.nan,
             flags=";".join(flags))
    r.update({f"h_{k}": v for k, v in comp_h.items()})
    r.update({f"o_{k}": v for k, v in comp_o.items()})
    return r


def run(users, places_dir: Path = PLACES_DIR, workday_fn=None) -> pd.DataFrame:
    rows = []
    for u in users:
        f = Path(places_dir) / f"{u}_stays.parquet"
        if not f.exists():
            continue
        rows.append(infer_user(pd.read_parquet(f), workday_fn))
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--all", action="store_true", help="chạy cả nhóm test (mặc định chỉ dev)")
    ap.add_argument("--test", action="store_true", help="chỉ nhóm test, chạy một lần sau khi khoá cấu hình (D19)")
    ap.add_argument("--out", default=None, help="mặc định reports/home_office_v1_{dev,test,all}.csv")
    a = ap.parse_args()
    from src.eda import split
    group = "test" if a.test else "all" if a.all else "dev"
    users = {"test": split.test_users, "all": lambda: split.dev_users() + split.test_users(), "dev": split.dev_users}[group]()
    a.out = a.out or str(ROOT / "reports" / f"home_office_v1_{group}.csv")
    df = run(users)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(a.out, index=False)
    print(f"{len(df)} user -> {a.out}")
    print("\nSố user theo cờ:")
    print(df["flags"].str.get_dummies(";").sum().to_string())
    print(f"Không cờ nào: {int((df['flags'].fillna('') == '').sum())}")
    print("\nConfidence (%):")
    print(conf_summary(df).to_string())


def conf_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Bảng tóm tắt confidence cho home và office."""
    out = {}
    for kind, col, place in (("home", "conf_home", "home"), ("office", "conf_office", "office")):
        c = df[col].dropna()
        out[kind] = {
            "có kết quả": int(df[place].notna().sum()),
            "có confidence (đủ 7 phiếu)": len(c),
            "trung vị (%)": f"{c.median():.1f}" if len(c) else "-",
            "dưới 70%": int((c < 70).sum()),
            "70–90%": int(((c >= 70) & (c < 90)).sum()),
            "từ 90%": int((c >= 90).sum()),
        }
    return pd.DataFrame(out, dtype=object)


if __name__ == "__main__":
    main()
