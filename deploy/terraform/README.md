# deploy/terraform: hạ tầng AWS của Home/Office bằng Terraform

Toàn bộ hạ tầng AWS của dự án (bước 4 trong `deploy\README.md`).

| File | Nội dung |
|---|---|
| `versions.tf` | phiên bản Terraform, provider, đăng nhập AWS, chốt đúng một tài khoản, nhãn chung |
| `variables.tf` | RAM, timeout của 2 Lambda, giới hạn request API, tag image |
| `main.tf` | bucket và ECR (chỉ đọc), Lambda batch + role + hàng đợi lỗi, Lambda tra cứu + role, API Gateway |
| `canary.tf`, `canary.auto.tfvars` | alias `live` và điều khiển canary |
| `monitoring.tf`, `terraform.tfvars` | alarm, email báo động, ngân sách (email chỉ để trên máy) |
| `outputs.tf` | giá trị in ra sau apply |

Tài khoản duy nhất: Blank Canvas `451071929893`, vùng `ap-southeast-1`, profile `home-office`.

## Cài đặt (một lần)

Terraform đã cài bằng winget. Mở cửa sổ PowerShell **mới** để lệnh `terraform` có trong PATH, rồi kiểm tra:

```powershell
terraform version
```

Thư mục này đã được `terraform init` sẵn. Nếu cần init lại (ví dụ sau khi xoá `.terraform\`):

```powershell
cd C:\Users\Acer\OneDrive\Desktop\Home_Office\deploy\terraform
terraform init
```

## Mỗi lần làm việc

```powershell
aws login --profile home-office --region ap-southeast-1
cd C:\Users\Acer\OneDrive\Desktop\Home_Office\deploy\terraform
terraform plan
```

Đọc plan, nhìn số `to destroy` trước tiên. Đồng ý thì:

```powershell
terraform apply
```

Terraform in lại plan và hỏi; gõ `yes` mới thực hiện.

## Việc hay làm

| Muốn | Làm |
|---|---|
| Đổi RAM, timeout, giới hạn request | sửa `variables.tf`, rồi `plan`, `apply` |
| Đưa code mới của `api\handler.py` lên | `plan`, `apply` (Terraform tự nén lại) |
| Đưa image batch mới lên | build trong CloudShell như cũ (bước 3a, 3b), rồi `plan`, `apply` |
| Xem địa chỉ API | `terraform output -raw api_url` |
| Ghi địa chỉ API cho `test.ps1`, `canary_check.ps1` | `terraform output -raw api_url \| Set-Content -Encoding ascii ..\..\api\api_url.txt` |
| Xem Terraform đang quản lý gì | `terraform state list` |
| Ghi app client id cho `get_token.ps1`, `test.ps1`, demo UI | `terraform output -raw cognito_client_id \| Set-Content -Encoding ascii ..\..\api\cognito_client_id.txt` |

## Báo động và ngân sách (`monitoring.tf`)

3 alarm (Lambda tra cứu lỗi, Lambda batch lỗi, API nhiều lỗi 5xx) gửi email qua SNS, và ngân sách 5 USD/tháng.
Email đặt trong file `terraform.tfvars` (không đưa lên git), Terraform tự đọc mỗi lần chạy:

```powershell
Set-Content -Encoding ascii terraform.tfvars 'alert_email = "email-cua-ban@gmail.com"'
```

Sau lần apply đầu, mở hộp thư, bấm **Confirm subscription** trong thư của AWS thì mới nhận được báo động.
Xem trạng thái alarm: console CloudWatch → Alarms, hoặc `aws cloudwatch describe-alarms --alarm-name-prefix home-office --profile home-office --region ap-southeast-1`.

## Canary cho Lambda tra cứu (`canary.tf`, `canary.auto.tfvars`)

Alias `live` chọn bản Lambda nào phục vụ người dùng và chia traffic giữa bản cũ và bản mới nhất.
Điều khiển bằng cách sửa `canary.auto.tfvars` rồi `terraform plan`, `terraform apply`.
Sau mỗi bước, đo tỉ lệ thật (từ thư mục `Home_Office`): `.\api\canary_check.ps1 -N 200`.

| Bước | `lookup_pinned_version` | `stable_version` | `canary_weight` | `lookup_simulate_error` | Kết quả mong đợi |
|---|---|---|---|---|---|
| 0. Bật alias (một lần) | `""` | `""` | `0` | `false` | tạo bản 1; 100% bản 1, model `heuristic-v1` |
| 1. Canary 10% | `"dbscan-v2"` | `"1"` | `0.1` | `false` | tạo bản 2; khoảng 90% bản 1, 10% bản 2 (`dbscan-v2`) |
| 2. Canary 50% | `"dbscan-v2"` | `"1"` | `0.5` | `false` | khoảng 50/50 |
| 3. Chuyển hẳn | `"dbscan-v2"` | `""` | `0` | `false` | 100% bản 2 |
| 4. Bản lỗi ở 10% | `"dbscan-v2"` | `"2"` | `0.1` | `true` | tạo bản 3 lỗi; khoảng 10% lỗi 500; alarm `home-office-lookup-errors` kêu sau vài phút |
| 5. Rollback | `"dbscan-v2"` | `"2"` | `0` | `true` | 100% bản 2, 0 lỗi |
| 6. Dọn sau demo | `""` | `""` | `0` | `false` | tạo bản mới theo registry; 100% bản đó |

Số bản (1, 2, 3) là số thật Lambda cấp, xem bằng `terraform output lookup_latest_version`; nếu khác bảng thì dùng số thật.
Blue-green là trường hợp đặc biệt: chuyển thẳng từ bước 0 sang bước 3, giữ bản cũ để quay lại tức thì.
Sau khi chuyển hẳn sang `dbscan-v2`, nên chạy `python deploy/registry/register_models.py set-default dbscan-v2` để registry khớp.

## Đăng nhập Cognito (`cognito.tf`)

Route `GET /v1/users/{user_id}/home-office` cần ID token của Cognito User Pool `home-office-users`; `/health` vẫn mở.
API Gateway (JWT authorizer) chặn token thiếu / sai / hết hạn bằng 401. Lambda tra cứu (`AUTH_MODE=jwt`) so claim
`custom:geolife_id` với `user_id`: khác thì 403, trừ tài khoản nhóm `admin`. Gói LITE, miễn phí đến 10.000 người dùng/tháng.

Bật lần đầu (từ thư mục `Home_Office`, sau `aws login`):

```powershell
cd deploy\terraform
terraform plan
terraform apply
terraform output -raw cognito_client_id | Set-Content -Encoding ascii ..\..\api\cognito_client_id.txt
cd ..\..
.\deploy\cognito_users.ps1
.\api\test.ps1
```

`cognito_users.ps1` tạo 3 tài khoản demo cùng một mật khẩu: `user002@example.com` (user 002), `user153@example.com` (user 153),
`admin@example.com` (nhóm admin). Đặt `$env:HO_DEMO_PASSWORD = "..."` trước thì các script không hỏi lại mật khẩu.
Lấy token để gọi tay: `.\api\get_token.ps1 user153@example.com`.

Tắt đăng nhập: thêm dòng `auth_enabled = false` vào `terraform.tfvars`, `plan`, `apply`; thử bằng `.\api\test.ps1 -NoAuth`.
User Pool và tài khoản vẫn giữ. Bật hay tắt đều tạo một bản Lambda tra cứu mới (đổi biến `AUTH_MODE`); alias `live` theo bản đó
nếu đang không chạy canary. Khi đang canary (`stable_version` khác `""`), bản chính cũ vẫn giữ `AUTH_MODE` cũ: đừng đổi đăng nhập giữa lúc canary.

## State

`terraform.tfstate` là sổ ghi Terraform đang quản lý gì. Không sửa tay, không xoá, không đưa lên git.
Sao lưu sau mỗi lần apply, ví dụ:

```powershell
Copy-Item terraform.tfstate "terraform.tfstate.$(Get-Date -Format yyyyMMdd_HHmm).bak"
```

## Lịch sử

Hạ tầng ban đầu tạo bằng script PowerShell, chuyển sang Terraform ngày 13/11/2026 bằng khối `import` (nhận 17 tài nguyên có sẵn, 0 xoá).
Sau đó đã xoá các script hạ tầng cũ và file `imports.tf` (vẫn xem lại được trong lịch sử git).
`terraform destroy` xoá mọi tài nguyên trong thư mục này nhưng **không** đụng bucket và ECR. Đừng chạy nếu không chắc.

## Lỗi hay gặp

| Lỗi | Cách xử lý |
|---|---|
| `terraform is not recognized` | mở cửa sổ PowerShell mới |
| `No valid credential sources` / `expired` | `aws login --profile home-office --region ap-southeast-1` |
| `AWS account ID not allowed` | đang đăng nhập nhầm tài khoản; đăng nhập lại profile `home-office` |
| `terraform init` lỗi `connection was forcibly closed` khi tải provider | mạng chặn tải file lớn; chạy lại, hoặc nhờ Claude tải provider bằng curl |
