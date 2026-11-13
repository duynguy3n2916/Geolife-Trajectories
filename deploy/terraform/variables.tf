# Các giá trị có thể đổi. Mỗi biến có giá trị mặc định đúng với hạ tầng hiện tại,
# nên chạy `terraform plan` không cần truyền gì thêm.
# Muốn đổi khi chạy: terraform plan -var "batch_memory_mb=3008"

variable "account_id" {
  description = "Tài khoản AWS duy nhất được phép đụng tới (Blank Canvas)."
  type        = string
  default     = "451071929893"
}

variable "region" {
  description = "Vùng AWS (Singapore)."
  type        = string
  default     = "ap-southeast-1"
}

variable "aws_profile" {
  description = "Profile AWS CLI, đăng nhập bằng: aws login --profile home-office --region ap-southeast-1"
  type        = string
  default     = "home-office"
}

variable "image_tag" {
  description = "Tag của image Lambda batch trong ECR (image build trong CloudShell, ngoài Terraform)."
  type        = string
  default     = "v1"
}

variable "batch_memory_mb" {
  description = "RAM của Lambda batch (MB)."
  type        = number
  default     = 2048
}

variable "batch_timeout_s" {
  description = "Thời gian chạy tối đa của Lambda batch (giây). 900 = 15 phút, mức tối đa của Lambda."
  type        = number
  default     = 900
}

variable "lookup_memory_mb" {
  description = "RAM của Lambda tra cứu (MB)."
  type        = number
  default     = 256
}

variable "lookup_timeout_s" {
  description = "Thời gian chạy tối đa của Lambda tra cứu (giây)."
  type        = number
  default     = 10
}

variable "api_rate_limit" {
  description = "Số request mỗi giây tối đa vào API."
  type        = number
  default     = 20
}

variable "api_burst_limit" {
  description = "Số request dồn cùng lúc tối đa vào API."
  type        = number
  default     = 50
}
