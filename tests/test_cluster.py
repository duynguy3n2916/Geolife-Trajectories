import numpy as np
import pytest

from geo import haversine_m
from places import cluster_v1, cluster_v2


def _line(n, step_m):
    return 39.9 + np.arange(n) * step_m / 111_195.0, np.full(n, 116.3)


def test_v1_radius_around_longest_stay():
    lat, lon = _line(5, 150)                              # 0, 150, 300, 450, 600 m
    dur = np.array([10, 99, 10, 10, 10.0])                # tâm là stay số 1
    labels = cluster_v1.cluster_v1(lat, lon, dur, 200.0)
    assert labels[1] == labels[0] == labels[2]            # trong 200 m quanh stay số 1
    assert labels[3] != labels[1]


def test_v2_chains_where_v1_splits():
    lat, lon = _line(10, 150)                             # mỗi cặp liền kề cách 150 m, cả chuỗi dài 1,35 km
    assert len(set(cluster_v2.cluster_v2(lat, lon, 200.0))) == 1
    assert len(set(cluster_v2.cluster_v2(lat, lon, 100.0))) == 10
    assert len(set(cluster_v1.cluster_v1(lat, lon, np.ones(10), 200.0))) > 1


def test_v2_does_not_depend_on_order():
    rng = np.random.default_rng(0)
    lat = 39.9 + rng.normal(0, 0.004, 80)
    lon = 116.3 + rng.normal(0, 0.004, 80)
    a = cluster_v2.cluster_v2(lat, lon, 200.0)
    perm = rng.permutation(80)
    b = cluster_v2.cluster_v2(lat[perm], lon[perm], 200.0)
    assert len(set(zip(a[perm], b))) == len(set(a)) == len(set(b))


def test_v2_min_samples_marks_noise():
    lat = np.r_[39.9 + np.arange(5) * 0.0005, 39.95]       # 5 stay sát nhau và một stay lẻ
    lon = np.full(6, 116.3)
    labels = cluster_v2.cluster_v2(lat, lon, 200.0, min_samples=3)
    assert labels[-1] == -1 and (labels[:5] == 0).all()
    assert (cluster_v2.cluster_v2(lat, lon, 200.0, min_samples=1) >= 0).all()


@pytest.mark.parametrize("eps,ms", [(100, 1), (200, 1), (300, 2), (200, 3)])
def test_v2_matches_sklearn(eps, ms):
    DBSCAN = pytest.importorskip("sklearn.cluster").DBSCAN
    rng = np.random.default_rng(3)
    centers = rng.uniform(0, 0.1, (8, 2)) + [39.9, 116.3]
    pts = np.vstack([c + rng.normal(0, 0.0012, (rng.integers(1, 50), 2)) for c in centers])
    mine = cluster_v2.cluster_v2(pts[:, 0], pts[:, 1], eps, ms)
    m = DBSCAN(eps=eps / 6371008.8, min_samples=ms, metric="haversine", algorithm="ball_tree").fit(np.radians(pts))
    core = np.zeros(len(pts), bool)
    core[m.core_sample_indices_] = True
    assert ((mine == -1) == (m.labels_ == -1)).all()                         # cùng tập nhiễu
    assert len(set(zip(mine[core], m.labels_[core]))) == len(set(mine[core])) == len(set(m.labels_[core]))


def test_haversine_known_distance():
    assert haversine_m(0, 0, 0, 1) == pytest.approx(111_195, rel=1e-3)
