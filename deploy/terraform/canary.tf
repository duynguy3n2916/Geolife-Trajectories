# Deploy strategy: canary MODEL theo người dùng cho Lambda tra cứu.
#
# Cách hoạt động (code ở api/lookup_handler.py, hàm choose_version):
#   - Handler băm chuỗi "<muối>:<user_id>" bằng sha256 ra một số 0..99 cố định cho mỗi người dùng.
#   - Người dùng có số < canary_percent luôn nhận canary_model (bản ỨNG VIÊN); người dùng còn lại nhận model NỀN
#     = bản Approved trong registry (results/_default.json; lookup_pinned_version chỉ để ghi đè khi khẩn cấp).
#   - canary_model phải có trong registry (danh sách "registered" trong results/_default.json, do registry_sync.tf ghi);
#     không có thì Lambda tắt canary và log canary_model_not_registered. Đọc S3 lỗi thì không chặn, API không lỗi theo.
#   - Thăng cấp: duyệt bản ứng viên trong SageMaker Studio (registry_sync.tf tự cập nhật API), rồi tắt canary.
#   - Cùng một người dùng luôn thấy cùng một model; tăng 10 -> 50 -> 100 thì nhóm cũ vẫn nằm trong nhóm canary.
#   - Muối = canary_salt, để "" thì dùng tên canary_model: mỗi model mới rút một nhóm người dùng khác.
#   - Response có header X-Model-Version (model nào) và X-Canary (true / false).
#   - Rollback: canary_percent = 0 (hoặc canary_model = ""), terraform apply, mọi người dùng về model mặc định.
#
# Điều khiển bằng file canary.auto.tfvars (Terraform tự đọc), sửa file rồi chạy terraform apply.
# Mỗi lần đổi các biến này thì cấu hình Lambda đổi, Lambda cập nhật trong khoảng vài giây.
# Kịch bản từng bước: deploy/terraform/README.md, mục Canary.

variable "lookup_pinned_version" {
  description = "Ghi đè model nền khi khẩn cấp (\"\" = bình thường: model nền là bản Approved trong registry)."
  type        = string
  default     = ""
}

variable "canary_model" {
  description = "Model mới cho nhóm canary (\"\" = tắt canary)."
  type        = string
  default     = ""

  validation {
    condition     = contains(["", "heuristic-v1", "dbscan-v2"], var.canary_model)
    error_message = "canary_model phải là \"\", \"heuristic-v1\" hoặc \"dbscan-v2\"."
  }
}

variable "canary_percent" {
  description = "Phần trăm người dùng (0 đến 100, số nguyên) nhận canary_model."
  type        = number
  default     = 0

  validation {
    condition     = var.canary_percent >= 0 && var.canary_percent <= 100 && floor(var.canary_percent) == var.canary_percent
    error_message = "canary_percent phải là số nguyên từ 0 đến 100."
  }
}

variable "canary_salt" {
  description = "Muối băm cùng user_id (\"\" = dùng tên canary_model). Đổi muối = rút nhóm người dùng khác."
  type        = string
  default     = ""
}

variable "canary_simulate_error" {
  description = "true: người dùng thuộc nhóm canary bị lỗi 500 (giả lập model mới hỏng, chỉ để demo alarm + rollback)."
  type        = bool
  default     = false
}

locals {
  # Canary bật khi có model và phần trăm > 0 (main.tf đưa vào biến môi trường Lambda).
  model_canary_on = var.canary_model != "" && var.canary_percent > 0
}

output "lookup_model_canary" {
  description = "Canary model theo người dùng đang bật thế nào."
  value       = local.model_canary_on ? "${var.canary_percent}% user (sha256 của \"${var.canary_salt != "" ? var.canary_salt : var.canary_model}:user_id\") nhận ${var.canary_model}${var.canary_simulate_error ? " (ĐANG GIẢ LẬP LỖI)" : ""}, còn lại nhận model mặc định" : "tắt (mọi user nhận model mặc định)"
}
