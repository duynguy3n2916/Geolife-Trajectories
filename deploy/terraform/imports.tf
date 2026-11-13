# NHẬN VỀ (import) các tài nguyên đã được script PowerShell tạo từ trước.
# Mỗi khối import nói: "tài nguyên có sẵn trên AWS với mã X chính là resource Y trong main.tf".
# Nhờ đó Terraform ghi chúng vào state thay vì tạo mới (tạo mới sẽ lỗi vì trùng tên) hay xoá đi.
#
# Mã của API, integration và route lấy bằng AWS CLI ngày 13/11/2026:
#   aws apigatewayv2 get-apis / get-integrations / get-routes --profile home-office --region ap-southeast-1
#
# Khối import chỉ có tác dụng ở lần `terraform apply` đầu tiên. Sau khi apply xong,
# file này có thể xoá (giữ lại cũng vô hại: tài nguyên đã có trong state thì Terraform bỏ qua).

locals {
  imp_api_id         = "2ri5mspocd"
  imp_integration_id = "po4dzqa"
  imp_route_health   = "8snwnkp"
  imp_route_user     = "6dxfs4n"
}

# ---- Lambda batch ----
import {
  to = aws_iam_role.batch
  id = "home-office-batch-role"
}
import {
  to = aws_iam_role_policy_attachment.batch_logs
  id = "home-office-batch-role/arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}
import {
  to = aws_iam_role_policy.batch_s3
  id = "home-office-batch-role:batch-s3"
}
import {
  to = aws_iam_role_policy.batch_dlq_send
  id = "home-office-batch-role:dlq-send"
}
import {
  to = aws_sqs_queue.batch_dlq
  id = "https://sqs.${var.region}.amazonaws.com/${var.account_id}/home-office-batch-dlq"
}
import {
  to = aws_lambda_function.batch
  id = "home-office-batch"
}
import {
  to = aws_lambda_function_event_invoke_config.batch
  id = "home-office-batch"
}

# ---- Lambda tra cứu ----
import {
  to = aws_iam_role.lookup
  id = "home-office-lookup-role"
}
import {
  to = aws_iam_role_policy_attachment.lookup_logs
  id = "home-office-lookup-role/arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}
import {
  to = aws_iam_role_policy.lookup_read
  id = "home-office-lookup-role:results-read"
}
import {
  to = aws_lambda_function.lookup
  id = "home-office-lookup"
}

# ---- API Gateway ----
import {
  to = aws_apigatewayv2_api.main
  id = local.imp_api_id
}
import {
  to = aws_apigatewayv2_integration.lookup
  id = "${local.imp_api_id}/${local.imp_integration_id}"
}
import {
  to = aws_apigatewayv2_route.health
  id = "${local.imp_api_id}/${local.imp_route_health}"
}
import {
  to = aws_apigatewayv2_route.home_office
  id = "${local.imp_api_id}/${local.imp_route_user}"
}
import {
  to = aws_apigatewayv2_stage.default
  id = "${local.imp_api_id}/$default"
}
import {
  to = aws_lambda_permission.apigw
  id = "home-office-lookup/apigw-invoke"
}
