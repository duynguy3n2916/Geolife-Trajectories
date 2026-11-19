"""Chọn ngẫu nhiên ĐÚNG N% người dùng cho nhóm canary, rồi in (hoặc ghi) dòng canary_users cho canary.auto.tfvars.

Chỉ chọn trong số user CÓ KẾT QUẢ của canary_model (có file s3://<bucket>/results/<model>/<user>.json), nên các user
không có nhà/công ty (404) không chiếm chỗ trong nhóm canary.

Ngẫu nhiên nhưng lặp lại được: trộn danh sách user bằng random.Random(seed), lấy N user đầu. Seed mặc định = tên model.
    - Cùng seed, chạy lại ra cùng nhóm (để demo và kiểm lại).
    - Cùng seed, tăng 10 -> 50 -> 100: nhóm 10% nằm trọn trong nhóm 50% (người đã nhận model mới không bị lấy lại).
    - Đổi seed = rút nhóm khác.

Cách chạy (thư mục Home_Office, đã aws login và đặt $env:AWS_PROFILE = "home-office"):
    python api/pick_canary_users.py --percent 10              in dòng canary_users để xem
    python api/pick_canary_users.py --percent 10 --write      ghi luôn vào deploy/terraform/canary.auto.tfvars
    python api/pick_canary_users.py --percent 0 --write       xoá danh sách (quay về cách băm theo canary_percent)
Sau đó: cd deploy/terraform, terraform plan, terraform apply.
"""
import argparse
import math
import random
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TFVARS = ROOT / "deploy" / "terraform" / "canary.auto.tfvars"
DEFAULT_BUCKET = "home-office-lambda-sg-451071929893"
REGION = "ap-southeast-1"
LINE_RE = re.compile(r"^canary_users\s*=.*$", re.M)


def users_with_results(bucket: str, model: str) -> list[str]:
    """Các user_id có file kết quả của model trên S3 (bỏ _default.json và file lạ)."""
    import boto3
    s3 = boto3.client("s3", region_name=REGION)
    users = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=f"results/{model}/"):
        for obj in page.get("Contents", []):
            name = obj["Key"].rsplit("/", 1)[-1]
            if name.endswith(".json") and not name.startswith("_"):
                users.append(name[:-5])
    return sorted(users)


def pick(users: list[str], percent: int, seed: str) -> list[str]:
    """N = làm tròn lên percent% số user (percent > 0 thì ít nhất 1 user). Trả danh sách đã sắp xếp."""
    if percent <= 0 or not users:
        return []
    n = min(len(users), math.ceil(len(users) * percent / 100))
    order = sorted(users)
    random.Random(seed).shuffle(order)
    return sorted(order[:n])


def tfvars_line(chosen: list[str]) -> str:
    return "canary_users = [" + ", ".join(f'"{u}"' for u in chosen) + "]"


def write_tfvars(line: str) -> None:
    text = TFVARS.read_text(encoding="utf-8")
    if LINE_RE.search(text):
        text = LINE_RE.sub(line, text, count=1)
    else:
        text = text.rstrip("\n") + "\n\n# Danh sách user canary (api/pick_canary_users.py). Có danh sách thì bỏ qua canary_percent.\n" + line + "\n"
    TFVARS.write_text(text, encoding="utf-8", newline="\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="Chọn ngẫu nhiên đúng N% user cho canary")
    ap.add_argument("--percent", type=int, required=True, help="0 đến 100")
    ap.add_argument("--model", default="dbscan-v2", help="canary_model (chọn trong user có kết quả của model này)")
    ap.add_argument("--seed", default=None, help="mặc định = tên model")
    ap.add_argument("--bucket", default=DEFAULT_BUCKET)
    ap.add_argument("--write", action="store_true", help="ghi vào deploy/terraform/canary.auto.tfvars")
    a = ap.parse_args()
    if not 0 <= a.percent <= 100:
        ap.error("--percent phải từ 0 đến 100")

    users = users_with_results(a.bucket, a.model) if a.percent > 0 else []
    if a.percent > 0 and not users:
        raise SystemExit(f"Không thấy file nào ở s3://{a.bucket}/results/{a.model}/ (đã aws login và đặt AWS_PROFILE chưa?)")
    chosen = pick(users, a.percent, a.seed or a.model)
    line = tfvars_line(chosen)
    if a.percent > 0:
        print(f"{len(users)} user có kết quả {a.model}; chọn {len(chosen)} user ({a.percent}%), seed = {a.seed or a.model}")
    print(line)
    if a.write:
        write_tfvars(line)
        print(f"Đã ghi vào {TFVARS.relative_to(ROOT)}. Tiếp theo: cd deploy/terraform; terraform plan; terraform apply")


if __name__ == "__main__":
    main()
