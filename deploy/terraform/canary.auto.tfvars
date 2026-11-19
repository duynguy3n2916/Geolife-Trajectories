# Điều khiển canary của Lambda tra cứu (xem canary.tf và README.md mục Canary).
# Sửa các dòng dưới rồi chạy: terraform plan, terraform apply.

# (A) Canary CODE theo request: alias live chia ngẫu nhiên giữa 2 bản Lambda.

lookup_pinned_version = ""
lookup_simulate_error = false
stable_version        = ""
canary_weight         = 0
# (B) Canary MODEL theo user: canary_percent % user (cố định theo user_id) nhận canary_model.
#     Ví dụ: canary_model = "heuristic-v1", canary_percent = 10. Tắt: canary_model = "", canary_percent = 0.
#     Khi bật (B) thì giữ stable_version = "" ở trên.
canary_model   = ""
canary_percent = 0
# Muối băm cùng user_id. "" = dùng tên canary_model (mỗi model mới rút một nhóm user khác).
# Chỉ đặt khi muốn chạy lại cùng model với một nhóm khác, ví dụ canary_salt = "dbscan-v2-dot2".
canary_salt    = ""
