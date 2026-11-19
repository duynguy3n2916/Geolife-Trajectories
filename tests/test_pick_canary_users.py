"""Test api/pick_canary_users.py (không gọi S3): đúng số lượng, lặp lại được, nhóm nhỏ nằm trong nhóm lớn, ghi tfvars."""
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "api" / "pick_canary_users.py"
spec = importlib.util.spec_from_file_location("pick_canary_users", SCRIPT)
pc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pc)

USERS = [f"{i:03d}" for i in range(182) if i not in (108, 149)]  # giả lập vài user không có kết quả


def test_exact_count():
    assert len(pc.pick(USERS, 10, "dbscan-v2")) == 18      # ceil(180 * 10%) = 18
    assert len(pc.pick(USERS, 50, "dbscan-v2")) == 90
    assert pc.pick(USERS, 0, "dbscan-v2") == []
    assert pc.pick(USERS, 100, "dbscan-v2") == sorted(USERS)
    assert len(pc.pick(USERS[:5], 1, "x")) == 1


def test_only_users_with_results():
    assert not {"108", "149"} & set(pc.pick(USERS, 100, "dbscan-v2"))


def test_repeatable_and_seed_changes_group():
    a = pc.pick(USERS, 10, "dbscan-v2")
    assert a == pc.pick(list(reversed(USERS)), 10, "dbscan-v2")
    assert a != pc.pick(USERS, 10, "dbscan-v2-dot2")


def test_small_group_inside_big_group():
    small, big = set(pc.pick(USERS, 10, "s")), set(pc.pick(USERS, 50, "s"))
    assert small <= big


def test_write_tfvars(tmp_path, monkeypatch):
    f = tmp_path / "canary.auto.tfvars"
    f.write_text('canary_model = "dbscan-v2"\ncanary_users = []\ncanary_salt = ""\n', encoding="utf-8")
    monkeypatch.setattr(pc, "TFVARS", f)
    pc.write_tfvars(pc.tfvars_line(["003", "153"]))
    assert f.read_text(encoding="utf-8") == 'canary_model = "dbscan-v2"\ncanary_users = ["003", "153"]\ncanary_salt = ""\n'
    pc.write_tfvars(pc.tfvars_line([]))
    assert 'canary_users = []\n' in f.read_text(encoding="utf-8")
