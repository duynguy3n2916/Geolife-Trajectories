"""Các version model (cách gom địa điểm) mà dịch vụ phục vụ. Mầm của model registry (CP2).

Mỗi version khác nhau ở bước 6 (gom stay thành địa điểm); stay point (bước 5) và bỏ phiếu home / office (bước 7)
dùng chung. Thêm version mới: viết hàm `places_for_user(stays, user)` rồi đăng ký vào MODELS.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

SRC = Path(__file__).resolve().parent                    # thư mục src
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
from places import cluster_v1, cluster_v2, home_office_conf as hoc   # noqa: E402
from stays import detect                                # noqa: E402


class UnknownModelVersion(ValueError):
    code = "unknown_model_version"


@dataclass(frozen=True)
class Model:
    version: str
    method: str                              # tên cách gom, khớp ModelInfo.method trong api/openapi.yaml
    places_for_user: Callable                # (stays, user) -> (bảng địa điểm, bảng stay kèm place_id)
    params: dict = field(default_factory=dict)
    key: str = ""                            # hậu tố file kết quả: places_<key>, home_office_<key>_*.csv
    created_at: str = ""                     # ngày chốt cấu hình của bản này (notes/decisions.md)


def _shared_params() -> dict:
    return {"D_m": detect.DIST_M, "T_min": detect.TIME_S / 60, "max_gap_h": detect.MAX_GAP_S / 3600,
            "stay_method": detect.METHOD, "night": f"{hoc.NIGHT[0]:g}-{hoc.NIGHT[1] - 24:g}",
            "work": "-".join(f"{x:g}" for x in hoc.WORK[0]), "min_votes": hoc.N_MIN_NIGHTS}


MODELS: dict[str, Model] = {
    "heuristic-v1": Model("heuristic-v1", "greedy_200m",
                          lambda stays, user: cluster_v1.places_for_user(stays, user),
                          {**_shared_params(), "place_radius_m": cluster_v1.RADIUS_M},
                          key="v1", created_at="2026-11-07T00:00:00Z"),
    "dbscan-v2": Model("dbscan-v2", "dbscan",
                       lambda stays, user: cluster_v2.places_for_user(stays, user),
                       {**_shared_params(), "eps_m": cluster_v2.EPS_M, "min_samples": cluster_v2.MIN_SAMPLES},
                       key="v2", created_at="2026-11-09T00:00:00Z"),
}
DEFAULT_MODEL = "heuristic-v1"


def get_model(version: str | None = None) -> Model:
    version = version or DEFAULT_MODEL
    if version not in MODELS:
        raise UnknownModelVersion(f"Không có version '{version}'. Có: {', '.join(MODELS)}")
    return MODELS[version]


def describe(git_commit: str | None = None) -> dict:
    """Nội dung cho GET /v1/models. git_commit do nơi build (Docker, CI) truyền vào; không có thì bỏ trống."""
    items = []
    for m in MODELS.values():
        item = {"model_version": m.version, "method": m.method, "created_at": m.created_at, "params": m.params}
        if git_commit:
            item["git_commit"] = git_commit
        items.append(item)
    return {"default": DEFAULT_MODEL, "items": items}
