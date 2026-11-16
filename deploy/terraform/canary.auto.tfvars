# Điều khiển canary của Lambda tra cứu (xem canary.tf và README.md mục Canary).
# Sửa các dòng dưới rồi chạy: terraform plan, terraform apply.

lookup_pinned_version = ""    # "" = theo registry; "dbscan-v2" = bản mới ghim dbscan-v2
lookup_simulate_error = false # true = bản mới cố ý lỗi (chỉ để demo rollback)
stable_version        = ""    # "" = 100% bản mới nhất; "1" = bản chính là bản số 1
canary_weight         = 0     # 0.1 = 10% traffic sang bản mới nhất
