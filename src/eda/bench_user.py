"""Đo thời gian và RAM đỉnh của pipeline cho một user (kiểm tra giới hạn Lambda: 15 phút, RAM).

    python -m src.eda.bench_user 153 128                    # mặc định: dbscan-v2, 3 lần mỗi user
    python -m src.eda.bench_user 153 --model heuristic-v1 --runs 1

Mỗi lần đo chạy trong một tiến trình riêng (RAM đỉnh không lẫn giữa các lần). Đọc thẳng file .plt gốc (data/raw/geolife/Data/<user>),
rồi chạy đúng các bước của src/infer.py: filter_track -> stays_for_user -> places_for_user -> infer_user.
Chỉ in thời gian và RAM, không in và không lưu kết quả home / office. Nên đo user thuộc nhóm validation (xem data/split/users.csv).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]
ROOT = SRC.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
RAW = ROOT / "data" / "raw" / "geolife" / "Data"


def _peak_mb() -> float:
    import psutil
    mi = psutil.Process().memory_info()
    peak = getattr(mi, "peak_wset", None)                 # Windows
    if peak is None:
        import resource                                   # Linux (KB)
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    return peak / 2**20


def child(user: str, model_version: str) -> dict:
    import pandas as pd
    import models
    from places import home_office_conf as hoc
    from preprocess.clean_trajectory import filter_track, read_plt
    from stays.detect import stays_for_user
    t = {}
    t0 = time.perf_counter()
    files = sorted((RAW / user / "Trajectory").glob("*.plt"))
    raw = pd.concat([read_plt(f) for f in files], ignore_index=True).sort_values("timestamp", kind="stable").reset_index(drop=True)
    t["read"] = time.perf_counter(); t["start"] = t0
    clean, _ = filter_track(raw, time_min=pd.Timestamp("2000-01-01", tz="UTC"), time_max=pd.Timestamp("2100-01-01", tz="UTC"))
    t["filter"] = time.perf_counter()
    stays = stays_for_user(clean, user)
    t["stays"] = time.perf_counter()
    model = models.get_model(model_version)
    places, s = model.places_for_user(stays, user)
    t["places"] = time.perf_counter()
    hoc.infer_user(s)
    t["infer"] = time.perf_counter()
    order = ["start", "read", "filter", "stays", "places", "infer"]
    steps = {b: round(t[b] - t[a], 2) for a, b in zip(order, order[1:])}
    return {"user": user, "model": model_version, "n_files": len(files), "n_points": int(len(raw)),
            "n_clean": int(len(clean)), "n_stays": int(len(stays)), "seconds": steps,
            "total_s": round(t["infer"] - t0, 2), "peak_ram_mb": round(_peak_mb())}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("users", nargs="+")
    ap.add_argument("--model", default="dbscan-v2")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.child:
        print("RESULT " + json.dumps(child(a.users[0], a.model)))
        return
    for u in a.users:
        runs = []
        for i in range(a.runs):
            p = subprocess.run([sys.executable, "-m", "src.eda.bench_user", u, "--model", a.model, "--child"],
                               cwd=ROOT, capture_output=True, text=True)
            line = next((l for l in p.stdout.splitlines() if l.startswith("RESULT ")), None)
            if line is None:
                print(f"user {u} lần {i + 1}: lỗi\n{p.stderr[-800:]}")
                break
            r = json.loads(line[7:]); runs.append(r)
            print(f"user {u} lần {i + 1}: {r['total_s']} s, RAM đỉnh {r['peak_ram_mb']} MB, từng bước {r['seconds']}")
        if runs:
            r = runs[0]
            print(f"==> user {u} ({a.model}): {r['n_files']} file, {r['n_points']:,} điểm ({r['n_clean']:,} sau lọc), {r['n_stays']} stay | "
                  f"lớn nhất: {max(x['total_s'] for x in runs)} s, {max(x['peak_ram_mb'] for x in runs)} MB")


if __name__ == "__main__":
    main()
