# Registry điều khiển API: duyệt (Approved) một version trong SageMaker Model Registry thì API tự dùng version đó.
#
#   SageMaker (Studio / CLI / register_models.py set-default) đổi trạng thái duyệt của một Model Package
#     -> sự kiện "SageMaker Model Package State Change" trên EventBridge (bus mặc định, AWS tự phát)
#     -> rule bên dưới, chỉ bắt group home-office
#     -> Lambda home-office-registry-sync (registry_sync/registry_sync_handler.py)
#     -> ghi s3://<bucket>/results/_default.json -> Lambda tra cứu đọc lại sau tối đa 60 giây.
#
# Quy tắc khi có nhiều version Approved, hoặc không có version nào: xem đầu file registry_sync_handler.py
# (bản đổi gần nhất thắng; không có bản nào thì giữ nguyên _default.json).
# Quyền tối thiểu: đọc Model Package của đúng group này, đọc + ghi đúng một file results/_default.json.

locals {
  registry_group = "home-office" # tên group trong deploy/registry/register_models.py (GROUP)
}

resource "aws_iam_role" "registry_sync" {
  name               = "home-office-registry-sync-role"
  assume_role_policy = local.lambda_trust
}

resource "aws_iam_role_policy_attachment" "registry_sync_logs" {
  role       = aws_iam_role.registry_sync.name
  policy_arn = local.basic_exec_policy
}

resource "aws_iam_role_policy" "registry_sync" {
  name = "registry-read-default-write"
  role = aws_iam_role.registry_sync.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # ListModelPackages không giới hạn được theo tài nguyên (AWS chỉ cho "*"), chỉ liệt kê, không đọc nội dung.
        Effect   = "Allow"
        Action   = "sagemaker:ListModelPackages"
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = "sagemaker:DescribeModelPackage"
        Resource = "arn:aws:sagemaker:${var.region}:${var.account_id}:model-package/${local.registry_group}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject"]
        Resource = "${data.aws_s3_bucket.main.arn}/results/_default.json"
      },
    ]
  })
}

data "archive_file" "registry_sync" {
  type        = "zip"
  source_file = "${path.module}/../../registry_sync/registry_sync_handler.py"
  output_path = "${path.module}/build/registry_sync.zip"
}

resource "aws_lambda_function" "registry_sync" {
  function_name    = "home-office-registry-sync"
  runtime          = "python3.12"
  handler          = "registry_sync_handler.lambda_handler"
  filename         = data.archive_file.registry_sync.output_path
  source_code_hash = data.archive_file.registry_sync.output_base64sha256
  role             = aws_iam_role.registry_sync.arn
  memory_size      = 128
  timeout          = 30

  environment {
    variables = {
      BUCKET   = data.aws_s3_bucket.main.id
      GROUP    = local.registry_group
      VERSIONS = "heuristic-v1,dbscan-v2"
    }
  }

  depends_on = [aws_iam_role_policy_attachment.registry_sync_logs, aws_iam_role_policy.registry_sync]
}

# Bắt mọi lần đổi trạng thái (tạo version, Approved, Pending, Rejected) của group home-office.
# Bắt cả lần bỏ duyệt để Lambda tính lại; Lambda chỉ ghi khi version được chọn thực sự đổi.
resource "aws_cloudwatch_event_rule" "registry_change" {
  name        = "home-office-registry-change"
  description = "SageMaker Model Registry (group home-office) đổi trạng thái duyệt -> cập nhật results/_default.json"
  event_pattern = jsonencode({
    source        = ["aws.sagemaker"]
    "detail-type" = ["SageMaker Model Package State Change"]
    detail        = { ModelPackageGroupName = [local.registry_group] }
  })
}

resource "aws_cloudwatch_event_target" "registry_sync" {
  rule = aws_cloudwatch_event_rule.registry_change.name
  arn  = aws_lambda_function.registry_sync.arn
}

resource "aws_lambda_permission" "events_registry_sync" {
  statement_id  = "events-invoke-registry-sync"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.registry_sync.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.registry_change.arn
}

# Lambda đồng bộ lỗi (ví dụ thiếu quyền) thì báo email như các alarm khác (monitoring.tf).
resource "aws_cloudwatch_metric_alarm" "registry_sync_errors" {
  alarm_name          = "home-office-registry-sync-errors"
  alarm_description   = "Lambda đồng bộ registry -> _default.json bị lỗi; API có thể vẫn dùng version cũ"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.registry_sync.function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

output "registry_sync_function" {
  description = "Lambda ghi results/_default.json khi duyệt version trên registry. Log: /aws/lambda/home-office-registry-sync"
  value       = aws_lambda_function.registry_sync.function_name
}
