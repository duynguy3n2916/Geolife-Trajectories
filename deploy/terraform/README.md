# deploy/terraform: hạ tầng AWS của Home/Office bằng Terraform

Toàn bộ hạ tầng AWS của dự án (bước 4 trong `deploy\README.md`).

| File | Nội dung |
|---|---|
| `versions.tf` | phiên bản Terraform, provider, đăng nhập AWS, chốt đúng một tài khoản, nhãn chung |
| `variables.tf` | RAM, timeout của 2 Lambda, giới hạn request API, tag image |
| `main.tf` | bucket và ECR (chỉ đọc), Lambda batch + role + hàng đợi lỗi, Lambda tra cứu + role, API Gateway |
| `canary.tf`, `canary.auto.tfvars` | điều khiển canary model theo người dùng |
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
| Ghi địa chỉ trang đăng nhập Cognito cho demo UI | `terraform output -raw cognito_domain \| Set-Content -Encoding ascii ..\..\api\cognito_domain.txt` |

## Báo động và ngân sách (`monitoring.tf`)

3 alarm (Lambda tra cứu lỗi, Lambda batch lỗi, API nhiều lỗi 5xx) gửi email qua SNS, và ngân sách 5 USD/tháng.
Email đặt trong file `terraform.tfvars` (không đưa lên git), Terraform tự đọc mỗi lần chạy:

```powershell
Set-Content -Encoding ascii terraform.tfvars 'alert_email = "email-cua-ban@gmail.com"'
```

Sau lần apply đầu, mở hộp thư, bấm **Confirm subscription** trong thư của AWS thì mới nhận được báo động.
Xem trạng thái alarm: console CloudWatch → Alarms, hoặc `aws cloudwatch describe-alarms --alarm-name-prefix home-office --profile home-office --region ap-southeast-1`.

## Canary model theo người dùng (`canary.tf`, `canary.auto.tfvars`)

Đưa model mới ra dần cho một phần **người dùng** (không phải một phần request):

- `api/handler.py` băm chuỗi `"<muối>:<user_id>"` bằng sha256, lấy 8 ký tự hex đầu, chia lấy dư 100, ra số 0..99 cố định
  cho mỗi user (không dùng `hash()` của Python vì giá trị đổi mỗi lần Lambda khởi động). Số 0..99 là "ô phần trăm",
  không phải mã user: 182 user rải vào 100 ô.
- User có số `< canary_percent` nhận `canary_model`; user còn lại nhận model mặc định (registry, hoặc `lookup_pinned_version`).
- Cùng một user luôn nhận cùng một model. Tăng 10 → 50 → 100 thì user đã ở nhóm canary vẫn ở đó, chỉ thêm user mới.
- Muối = `canary_salt`, để `""` thì dùng tên `canary_model`. Giống cách LaunchDarkly, Unleash băm `tên flag + user`: mỗi đợt
  canary rút một nhóm khác, không user nào lần nào cũng vào canary trước. Trong một đợt (cùng muối) nhóm vẫn cố định.
  Đổi muối giữa đợt thì nhóm bị rút lại, nên chỉ đổi khi bắt đầu đợt mới.
- Response có header `X-Canary: true/false` (cả trên 404 `user_not_found`). Truyền `?model_version=` thì bỏ qua canary.
- API Gateway gọi thẳng function (không có alias). Đổi các biến trên chỉ đổi biến môi trường của Lambda, cập nhật trong vài giây.

Đo sau mỗi bước (từ thư mục `Home_Office`, cần tài khoản admin): `.\api\canary_check.ps1`.
Script gọi cả 182 user 2 vòng, in số user mỗi model, danh sách user canary, số user đổi model giữa 2 vòng (phải là 0)
và danh sách user bị lỗi.

Registry đang duyệt `dbscan-v2`, nên để demo "đưa model mới ra dần" thì ghim model cũ làm mặc định rồi canary model mới:

| Bước | `lookup_pinned_version` | `canary_model` | `canary_percent` | `canary_simulate_error` | Kết quả mong đợi (`canary_check.ps1`) |
|---|---|---|---|---|---|
| 0. Mọi user dùng model cũ | `"heuristic-v1"` | `""` | `0` | `false` | 182 user `heuristic-v1`, `X-Canary=false` |
| 1. Canary 10% user | `"heuristic-v1"` | `"dbscan-v2"` | `10` | `false` | 19 user `dbscan-v2` (`X-Canary=true`), 0 user đổi model giữa 2 vòng |
| 2. Canary 50% user | `"heuristic-v1"` | `"dbscan-v2"` | `50` | `false` | 85 user; mọi user canary ở bước 1 vẫn có trong danh sách |
| 3. Chuyển hẳn | `""` | `""` | `0` | `false` | registry đã duyệt `dbscan-v2` nên mọi user nhận `dbscan-v2` |
| 4. Model mới hỏng ở 10% | `"heuristic-v1"` | `"dbscan-v2"` | `10` | `true` | 19 user canary trả 500, user khác 200; alarm `home-office-lookup-errors` gửi email sau vài phút |
| 5. Rollback | `"heuristic-v1"` | `""` | `0` | `false` | mọi user về `heuristic-v1`, 0 lỗi |
| 6. Dọn sau demo | `""` | `""` | `0` | `false` | mọi user theo registry |

Số user (19, 85) là đếm thật với muối mặc định `dbscan-v2`, lệch khỏi đúng 10%, 50% vì 182 user còn ít;
con số đang bật in trong `terraform output lookup_model_canary`.
`canary_simulate_error` chỉ có tác dụng khi canary đang bật, và chỉ để demo: nó giả lập "model mới hỏng" để thấy
lỗi chỉ trúng nhóm canary, alarm kêu, rồi rollback bằng `canary_percent = 0`.
Rollback ở đây là tắt canary (Lambda cập nhật cấu hình, khoảng vài giây đến 1 phút cho `apply`), không phải lùi về bản cũ.
Blue-green tương ứng: nhảy thẳng từ bước 0 sang bước 3 (đổi model mặc định một lần cho mọi người dùng).
Sau khi chuyển hẳn, nếu registry chưa duyệt model mới thì chạy `python deploy/registry/register_models.py set-default dbscan-v2`.
Trước 19/11/2026 canary làm bằng Lambda alias `live` chia traffic theo request (đã bỏ vì cùng user lúc thấy model này lúc
model kia); xem lại trong lịch sử git nếu cần.

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
terraform output -raw cognito_domain | Set-Content -Encoding ascii ..\..\api\cognito_domain.txt
cd ..\..
.\deploy\cognito_users.ps1
.\api\test.ps1
```

`cognito_users.ps1` tạo mỗi user GeoLife một tài khoản `userNNN@example.com` (`user000` đến `user181`, chỉ xem user của mình)
và `admin@example.com` (nhóm admin), cùng một mật khẩu; khoảng 10 phút. Chỉ vài user: `.\deploy\cognito_users.ps1 -Users 002,153`. Đặt `$env:HO_DEMO_PASSWORD = "..."` trước thì các script không hỏi lại mật khẩu.
Lấy token để gọi tay: `.\api\get_token.ps1 user153@example.com`.

Mock app đặt xe (`demo_ui\serve.py`) đăng nhập bằng OAuth 2.0 Authorization Code + PKCE: chuyển sang trang đăng nhập
của Cognito (`terraform output cognito_domain`), Cognito trả code về `http://localhost:8080/auth/callback`, server đổi code lấy token.
Chạy demo ở địa chỉ khác (cổng khác, máy khác): thêm địa chỉ đó vào `app_urls` trong `terraform.tfvars` rồi apply,
và đặt `$env:APP_URL` trước khi chạy `serve.py`. Script thử (`test.ps1`, `get_token.ps1`) vẫn dùng `USER_PASSWORD_AUTH`.

Tắt đăng nhập: thêm dòng `auth_enabled = false` vào `terraform.tfvars`, `plan`, `apply`; thử bằng `.\api\test.ps1 -NoAuth`.
User Pool và tài khoản vẫn giữ. Bật hay tắt chỉ đổi biến `AUTH_MODE` của Lambda tra cứu.

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
