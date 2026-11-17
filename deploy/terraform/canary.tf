# Deploy strategy: canary cho Lambda tra cứu bằng alias có trọng số.
#
# Cách hoạt động:
#   - Lambda tra cứu bật publish: mỗi lần đổi code hoặc cấu hình sinh một bản cố định (version 1, 2, 3...).
#   - Alias "live" trỏ tới một bản chính (stable) và, khi chạy canary, gửi thêm một phần traffic sang bản mới nhất.
#   - API Gateway gọi alias "live", nên người dùng không biết đang có 2 bản.
#   - Mỗi response có header X-Lambda-Version (bản nào trả lời) và X-Model-Version (version model nào).
#
# Điều khiển bằng file canary.auto.tfvars (Terraform tự đọc), sửa file rồi chạy terraform apply:
#   lookup_pinned_version : version model mà bản Lambda MỚI dùng làm mặc định ("" = theo registry / _default.json)
#   stable_version        : số bản chính ("" = luôn dùng bản mới nhất, tức không chạy canary)
#   canary_weight         : phần traffic gửi sang bản mới nhất, từ 0 đến 1 (0.1 = 10%)
#   lookup_simulate_error : true = bản mới cố ý lỗi, chỉ để demo rollback
# Kịch bản từng bước: deploy/terraform/README.md, mục Canary.

variable "lookup_pinned_version" {
  description = "Version model ghim cho bản Lambda mới (\"\" = theo version được duyệt trong registry)."
  type        = string
  default     = ""
}

variable "lookup_simulate_error" {
  description = "true: bản Lambda mới cố ý lỗi ở route tra cứu (chỉ để demo rollback)."
  type        = bool
  default     = false
}

variable "stable_version" {
  description = "Số bản Lambda chính mà alias live trỏ tới. \"\" = bản mới nhất (không chạy canary)."
  type        = string
  default     = ""
}

variable "canary_weight" {
  description = "Phần traffic gửi sang bản mới nhất khi chạy canary (0 đến 1)."
  type        = number
  default     = 0

  validation {
    condition     = var.canary_weight >= 0 && var.canary_weight < 1
    error_message = "canary_weight phải từ 0 đến dưới 1. Muốn chuyển 100% thì đặt stable_version = \"\"."
  }
}

locals {
  latest_version = aws_lambda_function.lookup.version
  primary        = var.stable_version != "" ? var.stable_version : local.latest_version
  # Chỉ chia traffic khi có bản chính cố định, trọng số > 0, và bản mới nhất khác bản chính.
  canary_on = var.stable_version != "" && var.canary_weight > 0 && var.stable_version != local.latest_version
}

resource "aws_lambda_alias" "live" {
  name             = "live"
  description      = "Bản đang phục vụ người dùng (API Gateway gọi alias này)"
  function_name    = aws_lambda_function.lookup.function_name
  function_version = local.primary

  dynamic "routing_config" {
    for_each = local.canary_on ? [1] : []
    content {
      additional_version_weights = { (local.latest_version) = var.canary_weight }
    }
  }
}

# Quyền cho API Gateway gọi alias live (API chỉ gọi qua alias, không gọi thẳng function).
resource "aws_lambda_permission" "apigw_live" {
  statement_id  = "apigw-invoke-live"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.lookup.function_name
  qualifier     = aws_lambda_alias.live.name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}

output "lookup_latest_version" {
  description = "Số bản Lambda tra cứu mới nhất."
  value       = local.latest_version
}

output "lookup_live_routing" {
  description = "Alias live đang chia traffic thế nào."
  value       = local.canary_on ? "bản ${local.primary}: ${100 - var.canary_weight * 100}%, bản ${local.latest_version}: ${var.canary_weight * 100}%" : "bản ${local.primary}: 100%"
}
