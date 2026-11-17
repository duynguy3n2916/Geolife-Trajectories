# Phiên bản Terraform, provider, và cách kết nối AWS.
# "provider" là phần bổ trợ giúp Terraform nói chuyện với một dịch vụ (ở đây là AWS).
# `terraform init` tải provider về thư mục .terraform/ và ghi phiên bản đã chọn vào .terraform.lock.hcl.

terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    archive = {
      source  = "hashicorp/archive" # nén deploy/lookup/handler.py thành file zip cho Lambda tra cứu
      version = "~> 2.4"
    }
  }

  # State (sổ ghi Terraform đang quản lý những gì) nằm ở file terraform.tfstate trong thư mục này.
  # Không đưa file đó lên git (xem .gitignore). Xem README.md mục "State".
}

provider "aws" {
  region  = var.region
  profile = var.aws_profile

  # Chốt an toàn: nếu đang đăng nhập nhầm tài khoản khác (ví dụ tài khoản management),
  # Terraform dừng ngay, không đọc hay sửa gì.
  allowed_account_ids = [var.account_id]

  # Gắn nhãn cho mọi tài nguyên Terraform quản lý, để nhìn trên console là biết.
  default_tags {
    tags = {
      Project   = "home-office"
      ManagedBy = "terraform"
    }
  }
}
