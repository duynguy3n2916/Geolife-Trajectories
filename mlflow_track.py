"""Ghi MLflow cho hai version model (heuristic-v1, dbscan-v2) và đăng ký vào model registry `home_office`.

Mỗi version một run trong experiment "home-office":
    params    tham số thật lấy từ src/models.py (D, T, max gap, khung giờ, min votes, bán kính v1 / eps + min_samples v2)
    metrics   chỉ số KHÔNG cần nhãn, tính từ outputs/home_office_<v>_<group>.csv (tỉ lệ có home / office, confidence...).
              Dự án không có nhãn home / office thật (A13), nên KHÔNG có accuracy / F1. Đừng thêm số giả.
    artifacts outputs/home_office_<v>_<group>.csv, outputs/place_stats_<v>.csv,
              và results/<user>.json nếu chạy với --user (suy luận thật trên file .plt gốc của user đó)
    model     pyfunc bọc src/infer.py: predict(DataFrame lat, lon, timestamp) -> kết quả home / office

Registry: model `home_office`, mỗi run một version. Alias champion = models.DEFAULT_MODEL (heuristic-v1),
challenger = version còn lại (dbscan-v2). Đổi bằng --champion.

Chạy (trong thư mục Home_Office):
    pip install mlflow
    python mlflow_track.py                      # cả hai version, nhóm validation, đăng ký + gắn alias
    python mlflow_track.py --user 170           # thêm results/170.json (suy luận thật cho user 170)
    python mlflow_track.py --versions dbscan-v2 --no-register
    mlflow ui --backend-store-uri sqlite:///mlflow.db     # mở http://127.0.0.1:5000

Nơi lưu: mặc định sqlite:///mlflow.db (cùng file mà `mlflow ui` tạo) và artifact trong ./mlruns.
Databricks (chưa xác nhận workspace): KHÔNG ghi token vào code. Đặt biến môi trường rồi chạy lại:
    $env:DATABRICKS_HOST="https://<workspace>"; $env:DATABRICKS_TOKEN="<token>"
    $env:MLFLOW_TRACKING_URI="databricks"; $env:MLFLOW_REGISTRY_URI="databricks"
    python mlflow_track.py --experiment /Users/<email>/home-office
(Unity Catalog: MLFLOW_REGISTRY_URI="databricks-uc" và --model-name <catalog>.<schema>.home_office)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import mlflow
import pandas as pd
from mlflow.tracking import MlflowClient

ROOT = Path(__file__).resolve().parent                   # thư mục Home_Office
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
import models                                            # noqa: E402

RAW = ROOT / "data" / "raw" / "geolife" / "Data"
EXPERIMENT = "home-office"
MODEL_NAME = "home_office"


# ---------------------------------------------------------------- pyfunc
class HomeOfficeModel(mlflow.pyfunc.PythonModel):
    """Bọc src/infer.py. Code src/ được đóng gói theo model (code_paths), nên load ở máy khác vẫn chạy."""

    def __init__(self, model_version: str):
        self.model_version = model_version

    def load_context(self, context):
        for p in map(Path, list(sys.path)):
            if (p / "src" / "infer.py").exists():         # MLflow thêm thư mục code/ của model vào sys.path
                sys.path.insert(0, str(p / "src"))
                break

    def predict(self, context, model_input, params=None):
        import infer
        df = model_input if isinstance(model_input, pd.DataFrame) else pd.DataFrame(model_input)
        return [infer.infer(df, model_version=self.model_version)]


def log_pyfunc(model_version: str, register: bool, model_name: str):
    kw = dict(python_model=HomeOfficeModel(model_version), code_paths=[str(SRC)],
              pip_requirements=str(ROOT / "requirements-api.txt"),
              registered_model_name=model_name if register else None)
    try:
        return mlflow.pyfunc.log_model(name="model", **kw)          # MLflow 3
    except TypeError:
        return mlflow.pyfunc.log_model(artifact_path="model", **kw)  # MLflow 2


# ---------------------------------------------------------------- metrics (không nhãn)
def unlabeled_metrics(df: pd.DataFrame) -> dict:
    n = len(df)
    flags = df["flags"].fillna("")
    out = {"n_users": n,
           "home_found_rate": df["home"].notna().mean(),
           "office_found_rate": df["office"].notna().mean(),
           "home_conf_rate": df["conf_home"].notna().mean(),        # đủ phiếu để có confidence
           "office_conf_rate": df["conf_office"].notna().mean(),
           "no_flag_rate": (flags == "").mean()}
    for kind in ("home", "office"):
        c = df[f"conf_{kind}"].dropna()
        if len(c):
            out[f"conf_{kind}_median"] = float(c.median())
            out[f"conf_{kind}_ge90_rate"] = float((c >= 90).mean())
    for f in sorted(set(";".join(flags).split(";")) - {""}):
        out[f"flag_rate_{f}"] = float(flags.str.split(";").apply(lambda xs: f in xs).mean())
    return {k: float(v) for k, v in out.items()}


def user_result(user: str, model_version: str) -> tuple[dict, float]:
    """Suy luận thật cho một user từ các file .plt gốc (giống src/eda/bench_user.py)."""
    import infer
    from preprocess.clean_trajectory import read_plt
    files = sorted((RAW / user / "Trajectory").glob("*.plt"))
    if not files:
        raise FileNotFoundError(f"không thấy file .plt trong {RAW / user / 'Trajectory'}")
    t0 = time.perf_counter()
    points = pd.concat([read_plt(f) for f in files], ignore_index=True)
    res = infer.infer(points, model_version=model_version, user=user)
    return res, time.perf_counter() - t0


def git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


# ---------------------------------------------------------------- main
def setup(experiment: str):
    if not os.environ.get("MLFLOW_TRACKING_URI"):
        mlflow.set_tracking_uri(f"sqlite:///{(ROOT / 'mlflow.db').as_posix()}")
    if mlflow.get_experiment_by_name(experiment) is None and mlflow.get_tracking_uri().startswith("sqlite"):
        mlflow.create_experiment(experiment, artifact_location=(ROOT / "mlruns").as_uri())
    mlflow.set_experiment(experiment)


def run_one(version: str, group: str, users: list[str], register: bool, model_name: str):
    m = models.get_model(version)
    csv = ROOT / "outputs" / f"home_office_{m.key}_{group}.csv"
    stats = ROOT / "outputs" / f"place_stats_{m.key}.csv"
    with mlflow.start_run(run_name=version) as run:
        mlflow.set_tags({"model_version": version, "method": m.method, "group": group,
                         "metrics_type": "unlabeled (không có nhãn home/office thật)",
                         **({"git_commit": c} if (c := git_commit()) else {})})
        mlflow.log_params({"model_version": version, "method": m.method, "group": group, **m.params})

        if csv.exists():
            mlflow.set_tag("results_csv_mtime",
                           datetime.fromtimestamp(csv.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
            mlflow.log_metrics(unlabeled_metrics(pd.read_csv(csv, dtype={"user": str})))
            mlflow.log_artifact(str(csv), artifact_path="outputs")
        else:
            print(f"  [!] chưa có {csv.relative_to(ROOT)}: chạy python -m src.places.home_office_conf --version {m.key}"
                  f"{' --test' if group == 'test' else ''}. Run này không có metric.")
        if stats.exists():
            mlflow.log_artifact(str(stats), artifact_path="outputs")

        for u in users:
            res, secs = user_result(u, version)
            out = ROOT / "results" / version / f"{u}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
            mlflow.log_artifact(str(out), artifact_path="results")
            mlflow.log_metric(f"infer_seconds_user_{u}", secs)
            print(f"  user {u}: home={res['home'] and res['home']['place_id']} "
                  f"office={res['office'] and res['office']['place_id']} ({secs:.1f}s) -> {out.relative_to(ROOT)}")

        info = log_pyfunc(version, register, model_name)
        mv = getattr(info, "registered_model_version", None)
        print(f"  run {run.info.run_id} ({version})" + (f" -> {model_name} v{mv}" if mv else ""))
        return mv


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--versions", nargs="+", default=list(models.MODELS), choices=list(models.MODELS))
    ap.add_argument("--group", default="val", choices=["val", "test"],
                    help="file kết quả để tính metric; mặc định validation (test chỉ dùng một lần, D19)")
    ap.add_argument("--user", nargs="*", default=[], help="suy luận thật cho các user này, lưu results/<version>/<user>.json")
    ap.add_argument("--no-register", action="store_true", help="chỉ ghi run, không đăng ký registry")
    ap.add_argument("--champion", default=models.DEFAULT_MODEL, choices=list(models.MODELS))
    ap.add_argument("--experiment", default=os.environ.get("MLFLOW_EXPERIMENT_NAME", EXPERIMENT))
    ap.add_argument("--model-name", default=MODEL_NAME)
    a = ap.parse_args()

    setup(a.experiment)
    print(f"tracking: {mlflow.get_tracking_uri()}  experiment: {a.experiment}")
    registered = {v: run_one(v, a.group, a.user, not a.no_register, a.model_name) for v in a.versions}

    client = MlflowClient()
    for v, mv in registered.items():
        if mv:
            alias = "champion" if v == a.champion else "challenger"
            client.set_registered_model_alias(a.model_name, alias, mv)
            print(f"  alias {alias} -> {a.model_name} v{mv} ({v})")
    if any(registered.values()):
        print(f"\nDùng lại: mlflow.pyfunc.load_model('models:/{a.model_name}@champion').predict(df_lat_lon_timestamp)")


if __name__ == "__main__":
    main()
