"""Lambda batch: tính home / office cho MỘT user với MỘT version model, rồi ghi kết quả lên S3.

Mỗi lần gọi:
    1. đọc tham số của model:   s3://BUCKET/models/<model>/params.json
    2. tải GPS thô của user:     s3://BUCKET/geolife/Data/<user>/Trajectory/*.plt   (về /tmp)
    3. lọc điểm lỗi -> stay point -> gom địa điểm -> bỏ phiếu (src/params.run_pipeline)
    4. ghi kết quả:              s3://BUCKET/results/<model>/<user>.json

Event (JSON):
    {"user": "153", "model": "dbscan-v2"}      model mặc định dbscan-v2
    tuỳ chọn: "dry_run": true       chạy nhưng không ghi S3
              "write_empty": true   vẫn ghi file khi không ra home lẫn office (mặc định bỏ qua -> API trả 404)
              "params_uri": "s3://..."  dùng file tham số khác
Biến môi trường: BUCKET (bắt buộc), PREFIX (mặc định geolife/Data)
Trả về: tóm tắt (số điểm, số stay, có home / office không, thời gian từng bước, RAM đỉnh) để run_batch.ps1 ghi log.

Các import nặng (pandas, src/) đặt ở đầu file: chỉ nạp một lần khi container khởi động (cold start),
các lần gọi sau trong cùng container dùng lại.
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

import boto3                                                     # noqa: E402
import pandas as pd                                              # noqa: E402
import infer                                                     # noqa: E402
import params as hparams                                         # noqa: E402
from preprocess.clean_trajectory import filter_track, read_plt  # noqa: E402

S3 = boto3.client("s3")
BUCKET = os.environ["BUCKET"]
PREFIX = os.environ.get("PREFIX", "geolife/Data")
DOWNLOAD_THREADS = 32
_cold = True                   # True ở lần gọi đầu tiên của container
_params_cache: dict = {}       # params đã đọc, theo uri (sống cùng container)


def load_params(uri: str) -> dict:
    """Đọc params.json một lần cho mỗi container."""
    if uri not in _params_cache:
        _params_cache[uri] = hparams.load(uri)
    return _params_cache[uri]


def download_user(user: str, dest: Path) -> list[Path]:
    """Tải mọi file .plt của user về `dest`. Có file <PREFIX>/<user>.tar.gz (cách thử nghiệm cũ) thì tải file đó."""
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
        files = []
        with tarfile.open(tgz, "r:gz") as tf:
            for m in tf:
                if m.isfile() and m.name.endswith(".plt"):
                    p = dest / Path(m.name).name          # bỏ thư mục con: không tin đường dẫn bên trong file nén
                    with tf.extractfile(m) as src, open(p, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    files.append(p)
        tgz.unlink()
        if not files:
            raise FileNotFoundError(f"không có .plt trong s3://{BUCKET}/{archive_key}")
        return sorted(files)

    prefix = f"{PREFIX}/{user}/Trajectory/"
    keys = []
    for page in S3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=prefix):   # mỗi trang tối đa 1000 key
        keys += [o["Key"] for o in page.get("Contents", []) if o["Key"].endswith(".plt")]
    if not keys:
        raise FileNotFoundError(f"không có .plt dưới s3://{BUCKET}/{prefix}")

    def get(key: str) -> Path:
        p = dest / Path(key).name
        S3.download_file(BUCKET, key, str(p))
        return p

    with ThreadPoolExecutor(max_workers=DOWNLOAD_THREADS) as ex:
        return sorted(ex.map(get, keys))


def build_result(user: str, model: str, clean, stays, places, res) -> dict:
    """Nội dung file kết quả. Cách tính home / office / flags giống src/infer.py."""
    if stays.empty:
        return {"user_id": user, "model_version": model, "home": None, "office": None, "flags": ["no_stays"]}
    flags = [f for f in str(res.get("flags") or "").split(";") if f]
    if clean["tz_name"].astype(str).nunique() > 1:
        flags.append("multi_timezone")
    return {"user_id": user, "model_version": model,
            "home": infer.location(places, res, "home"), "office": infer.location(places, res, "office"),
            "flags": flags}


def lambda_handler(event, context):
    """Điểm vào: Lambda gọi hàm này cho mỗi lần gọi."""
    global _cold
    cold, _cold = _cold, False
    user = str(event["user"])
    model = event.get("model", "dbscan-v2")
    params_uri = event.get("params_uri") or f"s3://{BUCKET}/models/{model}/params.json"
    tmp = Path("/tmp") / user
    t = {"start": time.perf_counter()}

    params = load_params(params_uri)
    t["params"] = time.perf_counter()
    files = download_user(user, tmp)
    t["download"] = time.perf_counter()
    raw = (pd.concat([read_plt(f) for f in files], ignore_index=True)
           .sort_values("timestamp", kind="stable").reset_index(drop=True))
    t["read"] = time.perf_counter()
    clean, _ = filter_track(raw, time_min=infer.TIME_MIN, time_max=infer.TIME_MAX)
    t["filter"] = time.perf_counter()
    stays, places, res = hparams.run_pipeline(clean, user, params)
    t["pipeline"] = time.perf_counter()
    shutil.rmtree(tmp, ignore_errors=True)          # /tmp được giữ giữa các lần gọi: dọn để không đầy

    result = build_result(user, model, clean, stays, places, res)
    found = result["home"] is not None or result["office"] is not None
    key = f"results/{model}/{user}.json"
    wrote = False
    if (found or event.get("write_empty")) and not event.get("dry_run"):
        result["computed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        body = json.dumps(result, allow_nan=False, ensure_ascii=False).encode("utf-8")   # NaN lọt vào thì báo lỗi, không ghi JSON hỏng
        S3.put_object(Bucket=BUCKET, Key=key, ContentType="application/json", Body=body)
        wrote = True
    t["write"] = time.perf_counter()

    steps = ["start", "params", "download", "read", "filter", "pipeline", "write"]
    return {"user": user, "model": model, "cold_start": cold, "n_files": len(files),
            "n_points": int(len(raw)), "n_clean": int(len(clean)), "n_stays": int(len(stays)),
            "home": result["home"] is not None, "office": result["office"] is not None, "flags": result["flags"],
            "wrote": wrote, "result_key": key if wrote else None,
            "seconds": {b: round(t[b] - t[a], 2) for a, b in zip(steps, steps[1:])},
            "total_s": round(t["write"] - t["start"], 2),
            "peak_ram_mb_process": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)}
