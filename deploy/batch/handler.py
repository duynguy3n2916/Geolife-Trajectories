"""Lambda batch Home/Office cho MOT user: doc .plt tu S3 + params.json tu S3 -> chay pipeline -> ghi ket qua len S3.

Event:  {"user": "153", "model": "dbscan-v2"}            (model mac dinh dbscan-v2)
        tuy chon: "dry_run": true      chay nhung khong ghi S3
                  "write_empty": true  van ghi file khi khong tim ra home lan office (mac dinh: bo qua -> API tra 404)
                  "params_uri": "s3://..."  doi file params (mac dinh s3://BUCKET/models/<model>/params.json)
Env:    BUCKET (bat buoc), PREFIX (mac dinh geolife/Data)
Ghi:    s3://BUCKET/results/<model>/<user>.json  (home / office theo schema Location, flags)
Tra ve: ket qua tom tat + thoi gian tung buoc + RAM (giu cac truong cu de so voi lan do truoc).
Cac import nang dat o muc module de Init Duration (cold start) tinh ca thoi gian nap pandas va src/.
"""
import json
import os
import resource
import shutil
import sys
import tarfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"
sys.path.insert(0, str(SRC))

import boto3                                            # noqa: E402
import pandas as pd                                     # noqa: E402
import infer                                            # noqa: E402
import params as hparams                                # noqa: E402
from preprocess.clean_trajectory import filter_track, read_plt   # noqa: E402

S3 = boto3.client("s3")
BUCKET = os.environ["BUCKET"]
PREFIX = os.environ.get("PREFIX", "geolife/Data")
COLD = True                                             # True chi o lan goi dau cua container
_PARAMS: dict[str, dict] = {}                           # params da doc, theo uri (cache trong container)


def _params(uri: str) -> dict:
    if uri not in _PARAMS:
        _PARAMS[uri] = hparams.load(uri)
    return _PARAMS[uri]


def _download(user: str, dest: Path) -> list[Path]:
    """Uu tien mot file geolife/Data/<user>.tar.gz; neu khong co thi tai tung file .plt."""
    dest.mkdir(parents=True, exist_ok=True)
    archive_key = f"{PREFIX}/{user}.tar.gz"
    try:
        S3.head_object(Bucket=BUCKET, Key=archive_key)
        has_archive = True
    except Exception:
        has_archive = False
    if has_archive:
        tgz = Path("/tmp") / f"{user}.tar.gz"
        S3.download_file(BUCKET, archive_key, str(tgz))
        out = []
        with tarfile.open(tgz, "r:gz") as tf:
            for m in tf:
                if m.isfile() and m.name.endswith(".plt"):
                    p = dest / Path(m.name).name          # lam phang; khong tin duong dan trong archive
                    with tf.extractfile(m) as src, open(p, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    out.append(p)
        tgz.unlink()
        if not out:
            raise FileNotFoundError(f"no .plt in s3://{BUCKET}/{archive_key}")
        return sorted(out)

    prefix = f"{PREFIX}/{user}/Trajectory/"
    keys = []
    for page in S3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=prefix):
        keys += [o["Key"] for o in page.get("Contents", []) if o["Key"].endswith(".plt")]
    if not keys:
        raise FileNotFoundError(f"no .plt under s3://{BUCKET}/{prefix} and no s3://{BUCKET}/{archive_key}")

    def get(key: str) -> Path:
        p = dest / Path(key).name
        S3.download_file(BUCKET, key, str(p))
        return p

    with ThreadPoolExecutor(max_workers=32) as ex:
        return sorted(ex.map(get, keys))


def _result(user: str, model: str, clean, stays, places, res) -> dict:
    """Ket qua cho API tra cuu: cung cach tinh home/office/flags voi src/infer.py."""
    if stays.empty:
        return {"user_id": user, "model_version": model, "home": None, "office": None, "flags": ["no_stays"]}
    flags = [f for f in str(res.get("flags") or "").split(";") if f]
    if clean["tz_name"].astype(str).nunique() > 1:
        flags.append("multi_timezone")
    return {"user_id": user, "model_version": model,
            "home": infer.location(places, res, "home"), "office": infer.location(places, res, "office"),
            "flags": flags}


def lambda_handler(event, context):
    global COLD
    cold, COLD = COLD, False
    user = str(event["user"])
    model = event.get("model", "dbscan-v2")
    uri = event.get("params_uri") or f"s3://{BUCKET}/models/{model}/params.json"
    tmp = Path("/tmp") / user
    t = {"start": time.perf_counter()}

    params = _params(uri)
    t["params"] = time.perf_counter()
    files = _download(user, tmp)
    t["download"] = time.perf_counter()
    raw = pd.concat([read_plt(f) for f in files], ignore_index=True).sort_values("timestamp", kind="stable").reset_index(drop=True)
    t["read"] = time.perf_counter()
    clean, _ = filter_track(raw, time_min=infer.TIME_MIN, time_max=infer.TIME_MAX)
    t["filter"] = time.perf_counter()
    stays, places, res = hparams.run_pipeline(clean, user, params)
    t["pipeline"] = time.perf_counter()
    shutil.rmtree(tmp, ignore_errors=True)

    out = _result(user, model, clean, stays, places, res)
    found = out["home"] is not None or out["office"] is not None
    key = f"results/{model}/{user}.json"
    wrote = False
    if (found or event.get("write_empty")) and not event.get("dry_run"):
        out["computed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        S3.put_object(Bucket=BUCKET, Key=key, ContentType="application/json",
                      Body=json.dumps(out, allow_nan=False, ensure_ascii=False).encode("utf-8"))
        wrote = True
    t["write"] = time.perf_counter()

    order = ["start", "params", "download", "read", "filter", "pipeline", "write"]
    seconds = {b: round(t[b] - t[a], 2) for a, b in zip(order, order[1:])}
    return {"user": user, "model": model, "cold_start": cold, "n_files": len(files),
            "n_points": int(len(raw)), "n_clean": int(len(clean)), "n_stays": int(len(stays)),
            "home": out["home"] is not None, "office": out["office"] is not None, "flags": out["flags"],
            "wrote": wrote, "result_key": key if wrote else None,
            "seconds": seconds, "total_s": round(t["write"] - t["start"], 2),
            "peak_ram_mb_process": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)}
