# Hạ tầng AWS của Home/Office, viết bằng Terraform.
# Thay cho deploy/batch/deploy.ps1, deploy/batch/setup_async.ps1 và phần hạ tầng của deploy/lookup/deploy.ps1.
#
# Terraform KHÔNG quản lý (chỉ đọc, hoặc để ngoài hẳn):
#   - bucket S3 (dữ liệu GPS, params, kết quả): chỉ đọc bằng "data", nên Terraform không thể xoá hay tạo lại;
#   - kho ECR và image: build trong CloudShell (deploy/batch/build_bundle.ps1 + cloudshell_build.sh);
#   - dữ liệu trên S3 (upload_data.ps1, upload_params.ps1, results/_default.json, kết quả batch).

locals {
  bucket_name = "home-office-lambda-sg-${var.account_id}"
  repo_name   = "home-office-lambda"

  # Quyền ghi log CloudWatch, gắn cho cả hai role.
  basic_exec_policy = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"

  # Cho phép dịch vụ Lambda "đóng vai" role (giống deploy/lambda-trust.json).
  lambda_trust = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# =====================================================================
# 1. Thứ đã có sẵn, chỉ ĐỌC (data source): Terraform không bao giờ sửa hay xoá
# =====================================================================

data "aws_s3_bucket" "main" {
  bucket = local.bucket_name
}

data "aws_ecr_repository" "lambda" {
  name = local.repo_name
}

# Image hiện tại của tag v1. Dùng mã băm (digest) của image thay cho tag:
# build lại image trong CloudShell rồi chạy `terraform apply` là Lambda tự chuyển sang image mới.
# Nếu chưa có image, bước plan báo lỗi ngay (giống kiểm tra đầu deploy/batch/deploy.ps1).
data "aws_ecr_image" "batch" {
  repository_name = data.aws_ecr_repository.lambda.name
  image_tag       = var.image_tag
}

# =====================================================================
# 2. Lambda batch: chạy model cho một user
# =====================================================================

resource "aws_iam_role" "batch" {
  name               = "home-office-batch-role"
  assume_role_policy = local.lambda_trust
}

resource "aws_iam_role_policy_attachment" "batch_logs" {
  role       = aws_iam_role.batch.name
  policy_arn = local.basic_exec_policy
}

# Quyền S3 tối thiểu: đọc GPS và params, liệt kê file .plt, ghi kết quả.
resource "aws_iam_role_policy" "batch_s3" {
  name = "batch-s3"
  role = aws_iam_role.batch.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = ["${data.aws_s3_bucket.main.arn}/geolife/*", "${data.aws_s3_bucket.main.arn}/models/*"]
      },
      {
        Effect    = "Allow"
        Action    = "s3:ListBucket"
        Resource  = data.aws_s3_bucket.main.arn
        Condition = { StringLike = { "s3:prefix" = "geolife/*" } }
      },
      {
        Effect   = "Allow"
        Action   = "s3:PutObject"
        Resource = "${data.aws_s3_bucket.main.arn}/results/*"
      },
    ]
  })
}

# Hàng đợi nhận các lần gọi bất đồng bộ bị lỗi hẳn (sau 2 lần thử lại), giữ 14 ngày.
resource "aws_sqs_queue" "batch_dlq" {
  name                      = "home-office-batch-dlq"
  message_retention_seconds = 1209600
  max_message_size          = 1048576 # 1 MB, giống hàng đợi đang có (mặc định của Terraform là 256 KB)
  sqs_managed_sse_enabled   = true
}

resource "aws_iam_role_policy" "batch_dlq_send" {
  name = "dlq-send"
  role = aws_iam_role.batch.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sqs:SendMessage", Resource = aws_sqs_queue.batch_dlq.arn }]
  })
}

resource "aws_lambda_function" "batch" {
  function_name = "home-office-batch"
  package_type  = "Image"
  image_uri     = "${data.aws_ecr_repository.lambda.repository_url}@${data.aws_ecr_image.batch.image_digest}"
  role          = aws_iam_role.batch.arn
  memory_size   = var.batch_memory_mb
  timeout       = var.batch_timeout_s

  environment {
    variables = { BUCKET = data.aws_s3_bucket.main.id }
  }

  # Role phải có quyền S3 trước khi function chạy.
  depends_on = [aws_iam_role_policy_attachment.batch_logs, aws_iam_role_policy.batch_s3]
}

# Gọi bất đồng bộ: thử lại 2 lần, giữ lần gọi chờ tối đa 1 giờ, lỗi hẳn thì gửi vào hàng đợi.
resource "aws_lambda_function_event_invoke_config" "batch" {
  function_name                = aws_lambda_function.batch.function_name
  maximum_retry_attempts       = 2
  maximum_event_age_in_seconds = 3600

  destination_config {
    on_failure {
      destination = aws_sqs_queue.batch_dlq.arn
    }
  }

  depends_on = [aws_iam_role_policy.batch_dlq_send]
}

# =====================================================================
# 3. Lambda tra cứu: đọc kết quả có sẵn trong results/ cho API
# =====================================================================

resource "aws_iam_role" "lookup" {
  name               = "home-office-lookup-role"
  assume_role_policy = local.lambda_trust
}

resource "aws_iam_role_policy_attachment" "lookup_logs" {
  role       = aws_iam_role.lookup.name
  policy_arn = local.basic_exec_policy
}

# Chỉ đọc results/. ListBucket để file không tồn tại trả 404 thay vì AccessDenied.
resource "aws_iam_role_policy" "lookup_read" {
  name = "results-read"
  role = aws_iam_role.lookup.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = "${data.aws_s3_bucket.main.arn}/results/*"
      },
      {
        Effect    = "Allow"
        Action    = "s3:ListBucket"
        Resource  = data.aws_s3_bucket.main.arn
        Condition = { StringLike = { "s3:prefix" = "results/*" } }
      },
    ]
  })
}

# Nén handler.py thành zip (handler.py nằm ở gốc file zip). Sửa handler.py rồi `terraform apply` là code mới được đưa lên.
data "archive_file" "lookup" {
  type        = "zip"
  source_file = "${path.module}/../lookup/handler.py"
  output_path = "${path.module}/build/lookup.zip"
}

resource "aws_lambda_function" "lookup" {
  function_name    = "home-office-lookup"
  runtime          = "python3.12"
  handler          = "handler.lambda_handler"
  filename         = data.archive_file.lookup.output_path
  source_code_hash = data.archive_file.lookup.output_base64sha256
  role             = aws_iam_role.lookup.arn
  memory_size      = var.lookup_memory_mb
  timeout          = var.lookup_timeout_s

  environment {
    variables = { BUCKET = data.aws_s3_bucket.main.id }
  }

  depends_on = [aws_iam_role_policy_attachment.lookup_logs, aws_iam_role_policy.lookup_read]
}

# =====================================================================
# 4. API Gateway (HTTP API) đứng trước Lambda tra cứu
# =====================================================================

resource "aws_apigatewayv2_api" "main" {
  name          = "home-office-api"
  protocol_type = "HTTP"
}

# Một integration (gọi Lambda, payload 2.0) dùng chung cho cả hai route.
resource "aws_apigatewayv2_integration" "lookup" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_method     = "POST"
  integration_uri        = aws_lambda_function.lookup.arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "health" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "GET /health"
  target    = "integrations/${aws_apigatewayv2_integration.lookup.id}"
}

resource "aws_apigatewayv2_route" "home_office" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "GET /v1/users/{user_id}/home-office"
  target    = "integrations/${aws_apigatewayv2_integration.lookup.id}"
}

# Stage $default tự deploy mỗi khi đổi route; giới hạn số request để tránh bị gọi tràn.
resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.main.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_rate_limit  = var.api_rate_limit
    throttling_burst_limit = var.api_burst_limit
  }
}

# Cho API Gateway quyền gọi Lambda tra cứu.
resource "aws_lambda_permission" "apigw" {
  statement_id  = "apigw-invoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.lookup.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}

# =====================================================================
# 5. EventBridge: gọi Lambda tra cứu mỗi 5 phút để nó luôn "ấm"
# =====================================================================
# Lambda để lâu không ai gọi thì AWS tắt container; lần gọi sau phải khởi động lại (chậm hơn 1-2 giây).
# Lần gọi định kỳ này giả làm request GET /health (handler trả lời ngay, không đọc kết quả của user nào).
# Chi phí: khoảng 8 640 lần gọi mỗi tháng, nằm trong mức miễn phí của Lambda và EventBridge.

resource "aws_cloudwatch_event_rule" "lookup_warm" {
  name                = "home-office-lookup-warm"
  description         = "Gọi Lambda tra cứu mỗi 5 phút để tránh khởi động chậm"
  schedule_expression = "rate(5 minutes)"
}

resource "aws_cloudwatch_event_target" "lookup_warm" {
  rule  = aws_cloudwatch_event_rule.lookup_warm.name
  arn   = aws_lambda_function.lookup.arn
  input = jsonencode({ routeKey = "GET /health" })
}

# Cho EventBridge quyền gọi Lambda tra cứu (chỉ từ đúng rule này).
resource "aws_lambda_permission" "eventbridge_warm" {
  statement_id  = "eventbridge-warm"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.lookup.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.lookup_warm.arn
}
