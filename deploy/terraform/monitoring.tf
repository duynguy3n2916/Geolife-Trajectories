# Theo dõi và kiểm soát chi phí (bước A4 của kế hoạch CP2).
#   - 3 alarm CloudWatch: Lambda tra cứu lỗi, Lambda batch lỗi, API trả nhiều lỗi 5xx.
#   - 1 hàng thông báo SNS: alarm kêu thì gửi email (nếu có địa chỉ).
#   - 1 ngân sách AWS Budgets 5 USD/tháng: gửi email khi chi phí thật vượt 80% hoặc dự báo vượt 100%.
# Email lấy từ biến alert_email (không ghi cứng trong code). Để trống thì vẫn tạo alarm, chỉ không gửi email
# và không tạo ngân sách. Ghi vào file terraform.tfvars (đã .gitignore) một dòng: alert_email = "email-cua-ban"
# Sau lần apply đầu có email, AWS gửi thư "AWS Notification - Subscription Confirmation": bấm Confirm thì mới nhận được báo động.

variable "alert_email" {
  description = "Email nhận báo động và cảnh báo chi phí. Để trống: không gửi email, không tạo ngân sách."
  type        = string
  default     = ""
}

variable "monthly_budget_usd" {
  description = "Ngân sách chi phí mỗi tháng (USD)."
  type        = number
  default     = 5
}

locals {
  has_email = var.alert_email != ""
}

# ---- Nơi nhận báo động ----
resource "aws_sns_topic" "alerts" {
  name = "home-office-alerts"
}

resource "aws_sns_topic_subscription" "alerts_email" {
  count     = local.has_email ? 1 : 0
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# ---- Alarm ----
# Lambda tra cứu báo lỗi (mã chạy hỏng, hết thời gian) ít nhất 1 lần trong 5 phút.
# Lỗi nghiệp vụ như 404, 422 không tính là lỗi Lambda. Alarm này cũng dùng để quyết định rollback khi demo canary.
resource "aws_cloudwatch_metric_alarm" "lookup_errors" {
  alarm_name          = "home-office-lookup-errors"
  alarm_description   = "Lambda tra cứu có lỗi trong 5 phút gần nhất"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.lookup.function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching" # không ai gọi thì không có số liệu, coi là bình thường
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}

# Lambda batch báo lỗi.
resource "aws_cloudwatch_metric_alarm" "batch_errors" {
  alarm_name          = "home-office-batch-errors"
  alarm_description   = "Lambda batch có lỗi trong 5 phút gần nhất"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.batch.function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

# API trả từ 5 lỗi 5xx trở lên trong 5 phút (Lambda hỏng, S3 không đọc được, quá tải).
resource "aws_cloudwatch_metric_alarm" "api_5xx" {
  alarm_name          = "home-office-api-5xx"
  alarm_description   = "API Gateway trả nhiều lỗi 5xx"
  namespace           = "AWS/ApiGateway"
  metric_name         = "5xx"
  dimensions          = { ApiId = aws_apigatewayv2_api.main.id, Stage = aws_apigatewayv2_stage.default.name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 5
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

# ---- Ngân sách ----
resource "aws_budgets_budget" "monthly" {
  count        = local.has_email ? 1 : 0
  name         = "home-office-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}
