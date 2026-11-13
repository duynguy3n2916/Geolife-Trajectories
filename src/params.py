"""Tham so (sieu tham so) cua tung version model, luu thanh file params.json de doc tu S3.

Tham so o day KHONG phai weight (khong co gi duoc hoc): la nguong va cau hinh do ban chon qua tuning tren validation
(D, T, max gap, khung gio dem / lam viec, so phieu toi thieu, ban kinh / eps gom dia diem). Nguon su that van la code
trong src/ (hang so) va `models.MODELS[...].params`; file params.json la ban sao cua `params` do, de:
  - ghi vao registry (Model Package tro toi file nay) va doc duoc tu ben ngoai code;
  - batch doc nguong tu file thay vi hang so trong code (doi nguong = tao version moi, khong build lai image).

Dung:
    python -m src.params write [--out params]      # ghi params/<version>.json cho moi version trong models.MODELS
    python -m src.params check [--dir params]      # file khop params trong code, va khop gia tri mac dinh cua ham

Trong batch (Lambda):
    p = params.load("s3://<bucket>/models/dbscan-v2/params.json")
    stays, places, res = params.run_pipeline(clean, user, p)

Cac ham thuan (parse, to_kwargs) khong import pandas, nen chay duoc o moi noi; ham can pipeline import tre.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Cac khoa bat buoc trong params.json
REQUIRED = ("D_m", "T_min", "max_gap_h", "stay_method", "night", "work", "min_votes")


def _span(text: str) -> tuple[float, float]:
    a, b = text.split("-")
    return float(a), float(b)


def night_from_str(text: str) -> tuple[float, float]:
    """"20-7" -> (20.0, 31.0): dem bat dau luc 20h, ket thuc 7h hom sau (31 = 7 + 24), nhu hang so NIGHT."""
    a, b = _span(text)
    return a, b + 24 if b <= a else b


def work_from_str(text: str) -> list[tuple[float, float]]:
    """"9-18" -> [(9.0, 18.0)], nhu hang so WORK."""
    return [_span(text)]


def validate(params: dict) -> None:
    missing = [k for k in REQUIRED if k not in params]
    if missing:
        raise ValueError(f"params thieu khoa: {', '.join(missing)}")
    if "eps_m" not in params and "place_radius_m" not in params:
        raise ValueError("params can eps_m (dbscan) hoac place_radius_m (greedy)")


def to_kwargs(params: dict) -> dict:
    """Doi params.json thanh doi so cho tung buoc: {"stays": {...}, "places": {...}, "votes": {...}}."""
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
    """Doc params.json tu duong dan local hoac s3://bucket/key."""
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
    """Chay stay -> dia diem -> bo phieu tren bang diem da loc (sau filter_track) voi tham so lay tu params.
    Tra ve (stays, places, ket qua bo phieu). Dat NIGHT / WORK / so phieu toi thieu trong home_office_conf truoc moi lan chay."""
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
    """params cua moi version dang co trong code: {"heuristic-v1": {...}, "dbscan-v2": {...}}."""
    import models
    return {v: dict(m.params) for v, m in models.MODELS.items()}


def check(directory: Path) -> int:
    """So file trong `directory` voi code. Tra ve so loi."""
    import inspect
    from places import cluster_v1, cluster_v2, home_office_conf as hoc
    from stays.detect import stays_for_user
    errors = 0
    sd = {k: p.default for k, p in inspect.signature(stays_for_user).parameters.items()}
    for version, expected in build().items():
        path = directory / f"{version}.json"
        if not path.exists():
            print(f"THIEU  {path}"); errors += 1; continue
        got = load(str(path))
        if got != expected:
            print(f"KHAC   {path}: file {got} <> code {expected}"); errors += 1; continue
        kw = to_kwargs(got)
        fn = cluster_v2.places_for_user if "eps_m" in got else cluster_v1.places_for_user
        pd_ = {k: p.default for k, p in inspect.signature(fn).parameters.items()}
        bad = [f"stays.{k}: {v} <> {sd.get(k)}" for k, v in kw["stays"].items() if sd.get(k) != v]
        bad += [f"places.{k}: {v} <> {pd_.get(k)}" for k, v in kw["places"].items() if pd_.get(k) != v]
        bad += [f"votes.{k}: {v} <> {getattr(hoc, k)}" for k, v in kw["votes"].items() if getattr(hoc, k) != v]
        if bad:
            print(f"LECH   {version}: " + "; ".join(bad)); errors += 1
        else:
            print(f"OK     {version}: file, code va gia tri mac dinh khop nhau")
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
            print(f"da ghi {out / (version + '.json')}")
    else:
        sys.exit(1 if check(Path(a.dir)) else 0)


if __name__ == "__main__":
    main()
