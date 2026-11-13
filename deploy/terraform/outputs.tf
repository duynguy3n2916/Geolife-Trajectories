# Giá trị in ra sau `terraform apply`. Xem lại bất cứ lúc nào: terraform output
# Lấy một giá trị dạng chữ trơn:            terraform output -raw api_url

output "api_url" {
  description = "Địa chỉ API (thay cho deploy/lookup/api_url.txt)."
  value       = trimsuffix(aws_apigatewayv2_stage.default.invoke_url, "/") # bỏ "/" cuối để test.ps1 ghép đường dẫn đúng
}

output "bucket" {
  description = "Bucket dữ liệu (chỉ đọc, Terraform không quản lý)."
  value       = data.aws_s3_bucket.main.id
}

output "batch_function" {
  value = aws_lambda_function.batch.function_name
}

output "batch_image" {
  description = "Image Lambda batch đang dùng (theo mã băm)."
  value       = aws_lambda_function.batch.image_uri
}

output "lookup_function" {
  value = aws_lambda_function.lookup.function_name
}

output "dlq_url" {
  description = "Hàng đợi chứa các lần gọi batch bất đồng bộ bị lỗi hẳn."
  value       = aws_sqs_queue.batch_dlq.url
}
