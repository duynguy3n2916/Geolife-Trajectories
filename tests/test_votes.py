import numpy as np
import pandas as pd

from places import home_office_conf as hoc


def _stays(places, days=14, start="2024-03-04"):
    """Mỗi ngày: đêm 21h–7h hôm sau ở nơi 0; T2–T6 9h–18h ở nơi `places` cho biết (0 hoặc 1)."""
    rows = []
    for d in range(days):
        day = pd.Timestamp(start) + pd.Timedelta(days=d)
        rows.append((day + pd.Timedelta(hours=21), day + pd.Timedelta(hours=31), 0, 0.8))
        if day.weekday() < 5:
            rows.append((day + pd.Timedelta(hours=9), day + pd.Timedelta(hours=18), places, 0.0))
    df = pd.DataFrame(rows, columns=["arrive_local", "leave_local", "place_id", "g"])
    df["duration_min"] = (df["leave_local"] - df["arrive_local"]).dt.total_seconds() / 60
    df["gap_min"] = df["duration_min"] * df["g"]
    df["lat"], df["lon"], df["user"] = 39.9, 116.3, "t"
    return df.drop(columns="g")


def test_home_and_office_are_voted():
    r = hoc.infer_user(_stays(places=1), workday_fn=hoc.workday_default)
    assert (r["home"], r["office"]) == (0, 1) and r["flags"] == ""
    assert r["conf_home"] == 100.0 and r["conf_office"] == 100.0


def test_office_equal_home_is_flagged_and_emptied():
    r = hoc.infer_user(_stays(places=0), workday_fn=hoc.workday_default)
    assert r["home"] == 0 and r["office"] is None and "home_eq_office" in r["flags"]


def test_few_votes_keep_the_result_but_drop_confidence():
    r = hoc.infer_user(_stays(places=1, days=5), workday_fn=hoc.workday_default)
    assert r["home"] == 0 and np.isnan(r["conf_home"]) and "few_nights" in r["flags"]


def test_noise_stays_do_not_vote():
    s = _stays(places=1)
    s.loc[s["place_id"] == 1, "place_id"] = -1               # nơi làm việc bị coi là nhiễu
    r = hoc.infer_user(s, workday_fn=hoc.workday_default)
    assert r["office"] is None and "no_workday" in r["flags"]


def test_result_is_repeatable():
    s = _stays(places=1)
    assert hoc.infer_user(s, hoc.workday_default) == hoc.infer_user(s, hoc.workday_default)
