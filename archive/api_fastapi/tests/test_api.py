"""Test API (api/app.py) bằng TestClient của FastAPI. Store GeoLife là bản giả lập nhỏ, ghi vào thư mục tạm."""
import gzip
import io
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))     # để import được gói api
from fastapi.testclient import TestClient                          # noqa: E402

from conftest import HOME, OFFICE, make_points                     # noqa: E402
from geo import haversine_m                                        # noqa: E402

KEY = "test-key"
H = {"X-API-Key": KEY}


def _fake_store(path: Path) -> None:
    from api.build_store import RESULT_COLS, write
    base = {c: np.nan for c in RESULT_COLS}
    rows, places = [], []
    for v in ("heuristic-v1", "dbscan-v2"):
        rows.append({**base, "user": "001", "n_stays": 50, "home": 0, "office": 1, "n_night_votes": 30,
                     "n_work_votes": 20, "conf_home": 99.0, "conf_office": 95.5, "flags": np.nan,
                     "h_share": .9, "h_margin": .8, "h_gps": .1, "h_stable": 1.0,
                     "o_share": .7, "o_margin": .5, "o_gps": .05, "o_stable": 1.0, "model_version": v})
        rows.append({**base, "user": "002", "n_stays": 5, "home": 0, "n_night_votes": 3, "n_work_votes": 0,
                     "flags": "few_nights;no_workday", "h_share": 1.0, "h_margin": 1.0, "h_gps": .2, "h_stable": 1.0,
                     "model_version": v})
        rows.append({**base, "user": "003", "n_stays": 0, "flags": "no_stays", "model_version": v})
        for u, n in (("001", 3), ("002", 1)):
            for pid in range(n):
                places.append({"user": u, "place_id": pid, "lat": 39.99 + pid * 0.01, "lon": 116.3, "n_stays": 10 - pid,
                               "total_hours": 100.0 - pid, "gap_hours": 80.0, "model_version": v})
    write(path, pd.DataFrame(rows), pd.DataFrame(places))


@pytest.fixture(scope="module")
def client(tmp_path_factory, monkeypatch_module):
    store = tmp_path_factory.mktemp("store") / "geolife.sqlite"
    _fake_store(store)
    monkeypatch_module.setenv("API_KEYS", f"other,{KEY}")
    monkeypatch_module.setenv("GIT_COMMIT", "abc1234")
    from api import app as appmod
    monkeypatch_module.setattr(appmod, "STORE_PATH", store)
    appmod.get_store.cache_clear()
    with TestClient(appmod.app) as c:
        yield c
    appmod.get_store.cache_clear()


@pytest.fixture(scope="module")
def monkeypatch_module():
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


# ------------------------------------------------------------------ meta, auth, spec
def test_health_needs_no_key(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok", "default_model_version": "heuristic-v1"}


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "sai"}])
def test_key_required(client, headers):
    r = client.get("/v1/models", headers=headers)
    assert r.status_code == 401 and r.json()["code"] == "unauthorized"


def test_no_keys_means_open(client, monkeypatch):
    monkeypatch.delenv("API_KEYS")
    assert client.get("/v1/models").status_code == 200


def test_models(client):
    r = client.get("/v1/models", headers=H).json()
    assert r["default"] == "heuristic-v1"
    assert [i["model_version"] for i in r["items"]] == ["heuristic-v1", "dbscan-v2"]
    assert all(i["created_at"] and i["git_commit"] == "abc1234" for i in r["items"])


def test_openapi_is_the_handwritten_spec(client):
    s = client.get("/openapi.json").json()
    assert s["info"]["version"].startswith("0.2.0")
    assert s["components"]["parameters"]["ModelVersion"]["schema"]["enum"] == ["heuristic-v1", "dbscan-v2"]


def test_unknown_model_version(client):
    r = client.get("/v1/geolife/users", params={"model_version": "v9"}, headers=H)
    assert r.status_code == 422 and r.json()["code"] == "unknown_model_version"


# ------------------------------------------------------------------ inference
def _check_result(r, version):
    assert r.status_code == 200, r.text
    assert r.headers["X-Model-Version"] == version
    b = r.json()
    assert b["model_version"] == version
    assert haversine_m(*HOME, b["home"]["lat"], b["home"]["lon"]) < 100
    assert haversine_m(*OFFICE, b["office"]["lat"], b["office"]["lon"]) < 100


@pytest.mark.parametrize("version", ["heuristic-v1", "dbscan-v2"])
def test_infer_json(client, points, version):
    r = client.post("/v1/infer", params={"model_version": version}, headers=H,
                    json={"points": points.to_dict("records")})
    _check_result(r, version)


def test_infer_default_version(client, points):
    r = client.post("/v1/infer", headers=H, json={"points": points.to_dict("records")})
    _check_result(r, "heuristic-v1")


def test_infer_csv_gz(client, points):
    data = gzip.compress(points.to_csv(index=False).encode())
    r = client.post("/v1/infer", headers=H, files={"file": ("gps.csv.gz", data, "application/gzip")})
    _check_result(r, "heuristic-v1")


def test_infer_plt_zip(client, points):
    ts = pd.to_datetime(points["timestamp"], utc=True)
    plt = pd.DataFrame({"lat": points["lat"], "lon": points["lon"], "z": 0, "alt": 0, "days": 0.0,
                        "date": ts.dt.strftime("%Y-%m-%d"), "time": ts.dt.strftime("%H:%M:%S")})
    text = "Geolife trajectory\nWGS 84\nAltitude is in Feet\nReserved 3\n0,2,255,My Track,0,0,2,8421376\n0\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("Trajectory/a.plt", text + plt.to_csv(index=False, header=False))
    r = client.post("/v1/infer", headers=H, files={"file": ("gps.zip", buf.getvalue(), "application/zip")},
                    data={"format": "plt_zip"})
    _check_result(r, "heuristic-v1")


@pytest.mark.parametrize("kwargs, status, code", [
    ({"json": {"points": [{"lat": 1, "lon": 2, "timestamp": "2024-01-01T00:00:00Z"}]}}, 422, "validation_error"),
    ({"json": {"nope": []}}, 422, "validation_error"),
    ({"json": {"points": [{"lat": 1, "lon": 2, "timestamp": "2024-01-01 00:00:00"}] * 3}}, 400, "bad_timestamp"),
    ({"json": {"points": [{"lat": 1, "lon": 2}] * 3}}, 400, "missing_column"),
    ({"files": {"file": ("a.txt", b"x", "text/plain")}}, 415, "unsupported_format"),
    ({"files": {"file": ("a.zip", b"not a zip", "application/zip")}}, 400, "bad_archive"),
    ({"content": b"lat,lon", "headers": {"Content-Type": "text/csv"}}, 415, "unsupported_format"),
])
def test_infer_bad_input(client, kwargs, status, code):
    headers = {**H, **kwargs.pop("headers", {})}
    r = client.post("/v1/infer", headers=headers, **kwargs)
    assert r.status_code == status, r.text
    assert r.json()["code"] == code


def test_infer_too_large(client):
    r = client.post("/v1/infer", headers={**H, "Content-Type": "application/json",
                                          "Content-Length": str(60 * 1024 * 1024)}, content=b"{}")
    assert r.status_code == 413 and r.json()["code"] == "payload_too_large"


# ------------------------------------------------------------------ GeoLife
def test_geolife_users_and_filters(client):
    r = client.get("/v1/geolife/users", headers=H).json()
    assert r["total"] == 3 and [i["user_id"] for i in r["items"]] == ["001", "002", "003"]
    r = client.get("/v1/geolife/users", params={"has_office": True}, headers=H).json()
    assert r["total"] == 1 and r["items"][0]["user_id"] == "001"
    r = client.get("/v1/geolife/users", params={"limit": 1, "offset": 1}, headers=H).json()
    assert r["total"] == 3 and [i["user_id"] for i in r["items"]] == ["002"]
    assert client.get("/v1/geolife/users", params={"limit": 500}, headers=H).status_code == 422


def test_geolife_locations(client):
    r = client.get("/v1/geolife/users/001/locations", params={"model_version": "dbscan-v2"}, headers=H)
    assert r.status_code == 200 and r.headers["X-Model-Version"] == "dbscan-v2"
    b = r.json()
    assert b["home"]["place_id"] == 0 and b["home"]["confidence"] == 99.0 and b["office"]["place_id"] == 1
    b = client.get("/v1/geolife/users/002/locations", headers=H).json()
    assert b["home"]["confidence"] is None and b["office"] is None and b["flags"] == ["few_nights", "no_workday"]
    b = client.get("/v1/geolife/users/003/locations", headers=H).json()
    assert b["home"] is None and b["flags"] == ["no_stays"]


def test_geolife_places(client):
    b = client.get("/v1/geolife/users/001/places", params={"limit": 2}, headers=H).json()
    assert [(p["place_id"], p["role"]) for p in b["items"]] == [(0, "home"), (1, "office")]
    assert client.get("/v1/geolife/users/003/places", headers=H).json()["items"] == []


@pytest.mark.parametrize("path, status, code", [("/v1/geolife/users/999/locations", 404, "user_not_found"),
                                                ("/v1/geolife/users/12/places", 422, "validation_error")])
def test_geolife_bad_user(client, path, status, code):
    r = client.get(path, headers=H)
    assert r.status_code == status and r.json()["code"] == code
