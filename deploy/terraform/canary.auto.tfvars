# Điều khiển canary model theo người dùng (xem canary.tf và README.md mục Canary).
# Sửa các dòng dưới rồi chạy: terraform plan, terraform apply.

# Chia vai: registry (bản Approved) = model NỀN cho người dùng không thuộc nhóm canary;
# canary_model = bản ỨNG VIÊN đang thử (phải có trong registry, thường đang Pending).
# Thăng cấp: duyệt bản ứng viên trong SageMaker Studio, rồi tắt canary.

# Để "" (model nền lấy từ registry). Chỉ ghim khi khẩn cấp: ghim thì đổi registry không còn tác dụng.
lookup_pinned_version = ""

# canary_percent % người dùng (cố định theo user_id) nhận canary_model.
# Ví dụ registry duyệt heuristic-v1: canary_model = "dbscan-v2", canary_percent = 10.
# Tắt (rollback): canary_model = "", canary_percent = 0.
canary_model   = "dbscan-v2"
canary_percent = 10

# true = nhóm canary bị lỗi 500 (giả lập model mới hỏng, chỉ để demo alarm + rollback).
canary_simulate_error = false

# Muối băm cùng user_id. "" = dùng tên canary_model (mỗi model mới rút một nhóm user khác).
# Chỉ đặt khi muốn chạy lại cùng model với một nhóm khác, ví dụ canary_salt = "dbscan-v2-dot2".
canary_salt = ""
