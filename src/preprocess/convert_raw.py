"""Chuyển dữ liệu thô GeoLife (.plt, labels.txt) sang data/interim. Chạy MỘT LẦN, khoảng 10 phút.

Không lọc, không tính gì: chỉ đọc bằng read_plt (giống hệt pipeline) rồi ghi ra định dạng nhị phân,
để EDA và bước lọc đọc nhanh. Chỉ cần chạy lại khi đổi cách đọc file .plt (read_plt).

Chạy:
    python src/preprocess/convert_raw.py                 # mọi user chưa chuyển đổi
    python src/preprocess/convert_raw.py --force         # chuyển đổi lại tất cả
    python src/preprocess/convert_raw.py --users 000 163 # chỉ vài user
"""
from __future__ import annotations

import argparse
import time

import pandas as pd

if __package__:                       # import từ notebook / module khác
    from .clean_trajectory import read_plt
    from . import interim
else:                                 # chạy trực tiếp: python src/preprocess/convert_raw.py
    from clean_trajectory import read_plt
    import interim


# Đọc labels.txt của một user (nhãn phương tiện). Thời gian trong file là GMT theo User Guide.
def read_labels(path) -> pd.DataFrame:
    lb = pd.read_csv(path, sep="\t")
    lb.columns = ["start", "end", "mode"]
    lb["mode"] = lb["mode"].str.strip()
    for c in ("start", "end"):
        lb[c] = pd.to_datetime(lb[c].str.strip(), format="%Y/%m/%d %H:%M:%S", utc=True)
    return lb


# Chuyển đổi một user: gộp mọi file .plt thành bảng points, kèm bảng files và labels.
def convert_user(udir) -> int:
    u = udir.name
    parts, file_rows = [], []
    for f in sorted((udir / "Trajectory").glob("*.plt")):
        d = read_plt(f)
        ts = d["timestamp"]
        file_rows.append({"file": f.name, "n_points": len(d),
                          "start": ts.min() if len(d) else pd.NaT,
                          "end": ts.max() if len(d) else pd.NaT})
        if len(d):
            parts.append(d.assign(file=f.name))
    cols = ["lat", "lon", "timestamp", "file"]
    points = pd.concat(parts, ignore_index=True)[cols] if parts else pd.DataFrame(columns=cols)
    points["file"] = points["file"].astype("category")
    files = pd.DataFrame(file_rows, columns=["file", "n_points", "start", "end"])
    for c in ("start", "end"):
        files[c] = pd.to_datetime(files[c], utc=True)
    interim.save_table(points, "points", u)
    interim.save_table(files, "files", u)
    lf = udir / "labels.txt"
    if lf.exists():
        interim.save_table(read_labels(lf), "labels", u)
    return len(points)


def main() -> None:
    ap = argparse.ArgumentParser(description="Chuyển dữ liệu thô GeoLife sang data/interim (một lần).")
    ap.add_argument("--users", nargs="*", help="chỉ chuyển đổi các user này, ví dụ --users 000 163")
    ap.add_argument("--force", action="store_true", help="chuyển đổi lại cả user đã có")
    args = ap.parse_args()
    udirs = sorted(p for p in interim.RAW_DIR.iterdir() if (p / "Trajectory").is_dir())
    if args.users:
        udirs = [p for p in udirs if p.name in set(args.users)]
    done = set(interim.list_users())
    print(f"Định dạng: {interim.FORMAT}" + ("" if interim.FORMAT == "parquet" else
          " (cài pyarrow để dùng parquet: pip install pyarrow)"))
    t0 = time.time()
    for i, udir in enumerate(udirs, 1):
        if udir.name in done and not args.force:
            continue
        n = convert_user(udir)
        print(f"[{i}/{len(udirs)}] {udir.name}: {n:,} điểm ({time.time() - t0:.0f} giây)")
    print("Xong:", interim.INTERIM_DIR)


if __name__ == "__main__":
    main()
