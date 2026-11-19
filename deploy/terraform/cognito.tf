# Đăng nhập cho API bằng Amazon Cognito.
#
#   - User Pool "home-office-users": đăng nhập bằng email + mật khẩu (>= 8 ký tự, có chữ thường và số).
#     Chỉ admin tạo tài khoản (không cho tự đăng ký), vì user_id là mã GeoLife do dự án gán, không có người dùng thật.
#   - Thuộc tính riêng custom:geolife_id: mã user GeoLife (ví dụ "002") mà tài khoản được xem.
#     App client không có quyền ghi thuộc tính này, nên người dùng không tự đổi được; chỉ admin (AWS CLI) đặt.
#   - Nhóm "admin": xem được kết quả của mọi user_id.
#   - App client "home-office-app": không có secret (app chạy trên máy người dùng không giữ được secret), token sống 60 phút.
#     Hai cách đăng nhập:
#       a) OAuth 2.0 Authorization Code + PKCE qua trang đăng nhập của Cognito (Hosted UI, domain bên dưới):
#          app chuyển người dùng sang trang Cognito, Cognito trả "code" về callback_urls, app đổi code lấy token.
#          Mock app đặt xe (demo_ui/serve.py) dùng cách này.
#       b) USER_PASSWORD_AUTH (gửi thẳng email + mật khẩu): chỉ cho script thử (api\test.ps1, get_token.ps1).
#   - API Gateway gắn JWT authorizer vào route /v1/users/{user_id}/home-office; /health vẫn mở.
#     Token gửi lên là ID token (có claim custom:geolife_id và cognito:groups; access token không có custom:geolife_id).
#     API Gateway tự kiểm chữ ký, hạn, issuer và audience (= client id); sai thì trả 401, Lambda không chạy.
#     Lambda (api/lookup_handler.py, AUTH_MODE=jwt) so custom:geolife_id với {user_id}: khác và không phải admin thì 403.
#
# Chi phí: gói LITE, miễn phí 10.000 người dùng hoạt động mỗi tháng. Không gửi email (tài khoản tạo bằng
# deploy\cognito_users.ps1 với --message-action SUPPRESS), nên không tốn SES.
# Tắt đăng nhập (quay về như trước): auth_enabled = false trong terraform.tfvars rồi apply. User Pool vẫn giữ.

variable "app_urls" {
  description = "Địa chỉ của app được Cognito chuyển về sau đăng nhập / đăng xuất (http chỉ được dùng cho localhost)."
  type        = list(string)
  default     = ["http://localhost:8080"]
}

variable "auth_enabled" {
  description = "true: route tra cứu cần token Cognito (JWT authorizer + AUTH_MODE=jwt). false: mở như trước."
  type        = bool
  default     = true
}

resource "aws_cognito_user_pool" "main" {
  name           = "home-office-users"
  user_pool_tier = "LITE" # gói miễn phí; không ghi thì AWS có thể chọn gói Essentials

  username_attributes = ["email"] # tên đăng nhập là email
  deletion_protection = "INACTIVE"

  password_policy {
    minimum_length                   = 8
    require_lowercase                = true
    require_numbers                  = true
    require_uppercase                = false
    require_symbols                  = false
    temporary_password_validity_days = 7
  }

  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  # Quên mật khẩu: chỉ admin đặt lại (không gửi email/SMS).
  account_recovery_setting {
    recovery_mechanism {
      name     = "admin_only"
      priority = 1
    }
  }

  # Mã user GeoLife mà tài khoản được xem. Trong token là claim "custom:geolife_id".
  # Lưu ý: Cognito không cho sửa hay xoá thuộc tính đã tạo; muốn đổi thì phải tạo User Pool mới.
  schema {
    name                     = "geolife_id"
    attribute_data_type      = "String"
    mutable                  = true
    developer_only_attribute = false
    string_attribute_constraints {
      min_length = 1
      max_length = 64
    }
  }
}

# Domain của trang đăng nhập Cognito: https://home-office-<account>.auth.ap-southeast-1.amazoncognito.com
# (prefix phải duy nhất trong vùng, nên gắn số tài khoản). managed_login_version = 1: trang đăng nhập cổ điển,
# có sẵn ở gói LITE, không cần tạo giao diện riêng.
resource "aws_cognito_user_pool_domain" "main" {
  domain                = "home-office-${var.account_id}"
  user_pool_id          = aws_cognito_user_pool.main.id
  managed_login_version = 1
}

resource "aws_cognito_user_group" "admin" {
  name         = "admin"
  user_pool_id = aws_cognito_user_pool.main.id
  description  = "Xem được kết quả home/office của mọi user_id"
}

resource "aws_cognito_user_pool_client" "app" {
  name         = "home-office-app"
  user_pool_id = aws_cognito_user_pool.main.id

  generate_secret               = false
  explicit_auth_flows           = ["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]
  prevent_user_existence_errors = "ENABLED" # sai email hay sai mật khẩu đều báo giống nhau
  enable_token_revocation       = true

  id_token_validity      = 60
  access_token_validity  = 60
  refresh_token_validity = 1
  token_validity_units {
    id_token      = "minutes"
    access_token  = "minutes"
    refresh_token = "days"
  }

  # OAuth 2.0: chỉ luồng Authorization Code (app dùng PKCE), đăng nhập bằng tài khoản trong User Pool.
  # Scope openid: ID token chứa mọi thuộc tính client được đọc (gồm custom:geolife_id) và cognito:groups.
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  # profile: đăng nhập qua Hosted UI thì ID token chỉ có thuộc tính custom (custom:geolife_id) khi xin scope profile.
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = ["COGNITO"]
  callback_urls                        = [for u in var.app_urls : "${u}/auth/callback"]
  logout_urls                          = [for u in var.app_urls : "${u}/"]

  # Đọc được geolife_id; KHÔNG cho ghi (người dùng không tự đổi mình thành user khác).
  read_attributes  = ["email", "email_verified", "custom:geolife_id"]
  write_attributes = ["email"]
}

# Bộ kiểm tra JWT của API Gateway. Token phải do User Pool trên cấp, cho đúng app client.
resource "aws_apigatewayv2_authorizer" "cognito" {
  api_id           = aws_apigatewayv2_api.main.id
  name             = "cognito"
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]

  jwt_configuration {
    audience = [aws_cognito_user_pool_client.app.id]
    issuer   = "https://${aws_cognito_user_pool.main.endpoint}"
  }
}

output "cognito_user_pool_id" {
  description = "User Pool chứa tài khoản demo (deploy\\cognito_users.ps1 tạo tài khoản)."
  value       = aws_cognito_user_pool.main.id
}

output "cognito_client_id" {
  description = "App client id: dùng để lấy token (api\\get_token.ps1 đọc bản chép ở api\\cognito_client_id.txt)."
  value       = aws_cognito_user_pool_client.app.id
}

output "cognito_domain" {
  description = "Địa chỉ trang đăng nhập Cognito (demo_ui\\serve.py đọc bản chép ở api\\cognito_domain.txt)."
  value       = "https://${aws_cognito_user_pool_domain.main.domain}.auth.${var.region}.amazoncognito.com"
}

output "auth_enabled" {
  description = "Route tra cứu có cần token không."
  value       = var.auth_enabled
}
