import json

import pandas as pd
import pytest

import infer
import models
from conftest import HOME, OFFICE, make_points
from geo import haversine_m


@pytest.mark.parametrize("version", ["heuristic-v1", "dbscan-v2"])
def test_finds_home_and_office(points, version):
    r = infer.infer(points, version)
    assert r["model_version"] == version
    assert haversine_m(*HOME, r["home"]["lat"], r["home"]["lon"]) < 100
    assert haversine_m(*OFFICE, r["office"]["lat"], r["office"]["lon"]) < 100
    assert r["home"]["confidence"] is not None and r["office"]["confidence"] is not None
    assert r["flags"] == []
    assert r["input"]["timezones"] == ["Asia/Shanghai"] and r["input"]["n_points"] == len(points)
    roles = {p["role"] for p in r["places"]}
    assert {"home", "office"} <= roles
    json.dumps(r)                                          # kết quả phải serialize được


def test_default_model_is_used(points):
    assert infer.infer(points)["model_version"] == models.DEFAULT_MODEL


def test_few_days_gives_result_without_confidence():
    r = infer.infer(make_points(days=3))
    assert r["home"] is not None and r["home"]["confidence"] is None
    assert "few_nights" in r["flags"]


def test_working_from_home_flags_home_eq_office():
    r = infer.infer(make_points(wfh=True))
    assert r["office"] is None and "home_eq_office" in r["flags"]


def test_input_order_and_time_format_do_not_matter(points):
    base = infer.infer(points)
    shuffled = points.sample(frac=1.0, random_state=0).reset_index(drop=True)
    assert infer.infer(shuffled)["home"] == base["home"]
    epoch = points.assign(timestamp=pd.to_datetime(points["timestamp"], utc=True).map(lambda t: int(t.timestamp())))
    assert infer.infer(epoch)["home"] == base["home"]


def test_old_dates_outside_geolife_period_are_kept(points):
    assert infer.infer(points)["input"]["n_points_clean"] > 0.9 * len(points)     # 2024, ngoài 2007–2012


@pytest.mark.parametrize("drop,code", [("lat", "missing_column"), ("timestamp", "missing_column")])
def test_missing_column(points, drop, code):
    with pytest.raises(infer.InferError) as e:
        infer.infer(points.drop(columns=drop))
    assert e.value.code == code


def test_timestamp_without_timezone_is_rejected(points):
    naive = points.assign(timestamp=points["timestamp"].str.replace("Z", "", regex=False))
    with pytest.raises(infer.InferError) as e:
        infer.infer(naive)
    assert e.value.code == "bad_timestamp"
    with pytest.raises(infer.InferError):
        infer.infer(points.assign(timestamp=pd.to_datetime(naive["timestamp"])))


def test_too_few_points():
    two = pd.DataFrame({"lat": [39.9, 39.9], "lon": [116.3, 116.3], "timestamp": ["2024-03-04T00:00:00Z"] * 2})
    with pytest.raises(infer.InferError) as e:
        infer.infer(two)
    assert e.value.code == "too_few_points"


def test_payload_too_large(points, monkeypatch):
    monkeypatch.setattr(infer, "MAX_POINTS", 10)
    with pytest.raises(infer.InferError) as e:
        infer.infer(points)
    assert e.value.code == "payload_too_large"


def test_unknown_model_version(points):
    with pytest.raises(models.UnknownModelVersion):
        infer.infer(points, "nope")
