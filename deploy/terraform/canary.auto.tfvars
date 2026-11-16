# Điều khiển canary của Lambda tra cứu (xem canary.tf và README.md mục Canary).
# Sửa các dòng dưới rồi chạy: terraform plan, terraform apply.

lookup_pinned_version = ""
lookup_simulate_error = false
stable_version        = ""
canary_weight         = 0