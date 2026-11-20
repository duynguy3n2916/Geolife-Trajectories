"""Tham số (siêu tham số) của từng version model, lưu thành file params.json để Lambda batch đọc từ S3.

Tham số ở đây KHÔNG phải weight (không có gì được học): đó là ngưỡng và cấu hình chọn qua tuning trên validation
(D, T, max gap, khung giờ đêm / làm việc, số phiếu tối thiểu, bán kính / eps gom địa điểm). Nguồn gốc vẫn là code
trong src/ (hằng số) và `models.MODELS[...].params`; file params.json là bản sao của `params` đó, để:
  - registry (Model Package) trỏ tới file này, đọc được từ bên ngoài code;
  - batch đọc ngưỡng từ file thay vì hằng số trong code (đổi ngưỡng không phải build lại image).

Dùng:
    python -m src.params write [--out params]      # ghi params/<version>.json cho mọi version trong models.MODELS
    python -m src.params check [--dir params]      # file khớp params trong code và khớp giá trị mặc định của các hàm

Trong Lambda batch (batch/batch_handler.py):
    p = params.load("s3://<bucket>/models/dbscan-v2/params.json")
    stays, places, res = params.run_pipeline(clean, user, p)

Các hàm thuần (parse, to_kwargs) không import pandas nên chạy được ở mọi nơi; hàm cần pipeline thì import muộn.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Các khoá bắt buộc trong params.json
REQUIRED = ("D_m", "T_min", "max_gap_h", "stay_method", "night", "work", "min_votes")


def _span(text: str) -> tuple[float, float]:
    a, b = text.split("-")
    return float(a), float(b)


def night_from_str(text: str) -> tuple[float, float]:
    """"20-7" -> (20.0, 31.0): đêm bắt đầu 20h, kết thúc 7h hôm sau (31 = 7 + 24), giống hằng số NIGHT."""
    a, b = _span(text)
    return a, b + 24 if b <= a else b


def work_from_str(text: str) -> list[tuple[float, float]]:
    """"9-18" -> [(9.0, 18.0)], giống hằng số WORK."""
    return [_span(text)]


def validate(params: dict) -> None:
    """Báo lỗi nếu params thiếu khoá bắt buộc."""
    missing = [k for k in REQUIRED if k not in params]
    if missing:
        raise ValueError(f"params thiếu khoá: {', '.join(missing)}")
    if "eps_m" not in params and "place_radius_m" not in params:
        raise ValueError("params cần eps_m (dbscan) hoặc place_radius_m (greedy)")


def to_kwargs(params: dict) -> dict:
    """Đổi params.json thành đối số cho từng bước: {"stays": {...}, "places": {...}, "votes": {...}}."""
    validate(params)
    stays = {"dist_m": float(params["D_m"]), "time_s": float(params["T_min"]) * 60,
             "max_gap_s": float(params["max_gap_h"]) * 3600, "method": str(params["stay_method"])}
    if "eps_m" in params:
        places = {"eps_m": float(params["eps_m"]), "min_samples": int(params.get("min_samples", 1))}
    else:
        places = {"radius_m": float(params["place_radius_m"])}
    votes = {"NIGHT": night_from_str(params["night"]), "WORK": work_from_str(params["work"]),
             "N_MIN_NIGHTS": int(params["min_votes"]), "N_MIN_WORKDAYS": int(params["min_votes"])}
    return {"stays": stays, "places": places, "votes": votes}


def load(source: str) -> dict:
    """Đọc params.json từ đường dẫn trên máy hoặc s3://bucket/key, rồi kiểm tra."""
    if source.startswith("s3://"):
        import boto3
        bucket, key = source[5:].split("/", 1)
        body = boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()
        params = json.loads(body)
    else:
        params = json.loads(Path(source).read_text(encoding="utf-8"))
    validate(params)
    return params


def run_pipeline(clean, user: str, params: dict):
    """Chạy stay point -> gom địa điểm -> bỏ phiếu trên bảng điểm đã lọc (sau filter_track) với tham số từ params.
    Trả về (stays, places, kết quả bỏ phiếu). Đặt NIGHT / WORK / số phiếu tối thiểu trong home_office_conf trước mỗi lần chạy."""
    from places import cluster_v1, cluster_v2, home_office_conf as hoc
    from stays.detect import stays_for_user
    kw = to_kwargs(params)
    for name, value in kw["votes"].items():
        setattr(hoc, name, value)
    stays = stays_for_user(clean, user, **kw["stays"])
    cluster = cluster_v2 if "eps_m" in params else cluster_v1
    places, s = cluster.places_for_user(stays, user, **kw["places"])
    return stays, places, hoc.infer_user(s)


def build() -> dict[str, dict]:
    """params của mọi version đang có trong code: {"heuristic-v1": {...}, "dbscan-v2": {...}}."""
    import models
    return {v: dict(m.params) for v, m in models.MODELS.items()}


def check(directory: Path) -> int:
    """So các file trong `directory` với code. Trả về số lỗi."""
    import inspect
    from places import cluster_v1, cluster_v2, home_office_conf as hoc
    from stays.detect import stays_for_user
    errors = 0
    sd = {k: p.default for k, p in inspect.signature(stays_for_user).parameters.items()}
    for version, expected in build().items():
        path = directory / f"{version}.json"
        if not path.exists():
            print(f"THIẾU  {path}"); errors += 1; continue
        got = load(str(path))
        if got != expected:
            print(f"KHÁC   {path}: file {got} <> code {expected}"); errors += 1; continue
        kw = to_kwargs(got)
        fn = cluster_v2.places_for_user if "eps_m" in got else cluster_v1.places_for_user
        pd_ = {k: p.default for k, p in inspect.signature(fn).parameters.items()}
        bad = [f"stays.{k}: {v} <> {sd.get(k)}" for k, v in kw["stays"].items() if sd.get(k) != v]
        bad += [f"places.{k}: {v} <> {pd_.get(k)}" for k, v in kw["places"].items() if pd_.get(k) != v]
        bad += [f"votes.{k}: {v} <> {getattr(hoc, k)}" for k, v in kw["votes"].items() if getattr(hoc, k) != v]
        if bad:
            print(f"LỆCH   {version}: " + "; ".join(bad)); errors += 1
        else:
            print(f"OK     {version}: file, code và giá trị mặc định khớp nhau")
    return errors


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("write"); w.add_argument("--out", default="params")
    c = sub.add_parser("check"); c.add_argument("--dir", default="params")
    a = ap.parse_args()
    if a.cmd == "write":
        out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
        for version, p in build().items():
            (out / f"{version}.json").write_text(json.dumps(p, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"Đã ghi {out / (version + '.json')}")
    else:
        sys.exit(1 if check(Path(a.dir)) else 0)


if __name__ == "__main__":
    main()
