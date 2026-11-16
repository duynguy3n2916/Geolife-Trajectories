# deploy/terraform: hạ tầng AWS của Home/Office bằng Terraform

Thay cho `deploy\batch\deploy.ps1`, `deploy\batch\setup_async.ps1` và phần hạ tầng của `deploy\lookup\deploy.ps1`.
Mới dùng Terraform: đọc `HOC_TERRAFORM.md` trước.

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
| Đưa code mới của `deploy\lookup\handler.py` lên | `plan`, `apply` (Terraform tự nén lại) |
| Đưa image batch mới lên | build trong CloudShell như cũ (bước 3a, 3b), rồi `plan`, `apply` |
| Xem địa chỉ API | `terraform output -raw api_url` |
| Ghi địa chỉ API cho `test.ps1` | `terraform output -raw api_url \| Set-Content -Encoding ascii ..\lookup\api_url.txt` |
| Xem Terraform đang quản lý gì | `terraform state list` |

## Báo động và ngân sách (`monitoring.tf`)

3 alarm (Lambda tra cứu lỗi, Lambda batch lỗi, API nhiều lỗi 5xx) gửi email qua SNS, và ngân sách 5 USD/tháng.
Email đặt trong file `terraform.tfvars` (không đưa lên git), Terraform tự đọc mỗi lần chạy:

```powershell
Set-Content -Encoding ascii terraform.tfvars 'alert_email = "email-cua-ban@gmail.com"'
```

Sau lần apply đầu, mở hộp thư, bấm **Confirm subscription** trong thư của AWS thì mới nhận được báo động.
Xem trạng thái alarm: console CloudWatch → Alarms, hoặc `aws cloudwatch describe-alarms --alarm-name-prefix home-office --profile home-office --region ap-southeast-1`.

## Lần apply đầu tiên (import)

`imports.tf` nhận về 17 tài nguyên đã tạo bằng script. Plan lần đầu phải là:
`17 to import, 0 to add, 7 to change, 0 to destroy`. Bảy thay đổi là gắn nhãn, ghi image theo mã băm,
và tải lại zip của Lambda tra cứu (cùng nội dung). Sau apply, chạy `.\deploy\lookup\test.ps1` (từ thư mục `Home_Office`) để kiểm tra.

## State

`terraform.tfstate` là sổ ghi Terraform đang quản lý gì. Không sửa tay, không xoá, không đưa lên git.
Sao lưu sau mỗi lần apply, ví dụ:

```powershell
Copy-Item terraform.tfstate "terraform.tfstate.$(Get-Date -Format yyyyMMdd_HHmm).bak"
```

## Sau khi chuyển sang Terraform

Đã apply ngày 13/11/2026 (`terraform plan` sau đó: No changes; `test.ps1` qua cả 5 phép thử). Vì vậy đã xoá:
`batch\deploy.ps1`, `batch\setup_async.ps1`, `lookup\deploy.ps1`, `cleanup.ps1`, `lambda-trust.json`
(vẫn xem lại được trong lịch sử git).

- Đặt version mặc định của API: `.\deploy\data\set_default_version.ps1 dbscan-v2` (thay cho `lookup\deploy.ps1 -DefaultVersion`).
- Xoá hạ tầng: `terraform destroy` (xoá 17 resource, **không** đụng bucket và ECR). Đừng chạy nếu không chắc.
- Vẫn dùng như cũ: `upload_data.ps1`, `upload_params.ps1`, `build_bundle.ps1` + CloudShell, `run_batch.ps1`, `test.ps1`.
- `imports.tf` đã hết tác dụng sau lần apply đầu; giữ lại cũng vô hại.

## Lỗi hay gặp

| Lỗi | Cách xử lý |
|---|---|
| `terraform is not recognized` | mở cửa sổ PowerShell mới |
| `No valid credential sources` / `expired` | `aws login --profile home-office --region ap-southeast-1` |
| `AWS account ID not allowed` | đang đăng nhập nhầm tài khoản; đăng nhập lại profile `home-office` |
| `terraform init` lỗi `connection was forcibly closed` khi tải provider | mạng chặn tải file lớn; chạy lại, hoặc nhờ Claude tải provider bằng curl |
| `couldn't find resource` khi import | tài nguyên đã bị xoá hoặc đổi mã; xem lại `imports.tf` |
