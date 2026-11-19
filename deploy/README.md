# deploy/: đưa Home/Office lên AWS

Tài liệu này giải thích quy trình deploy, thứ tự các bước, và mỗi file làm gì.
Mọi lệnh chạy trong **PowerShell, từ thư mục `Home_Office`** (trừ một lệnh chạy trong CloudShell và các lệnh `terraform` chạy trong `deploy\terraform`).
Vùng: Singapore (`ap-southeast-1`). Profile AWS CLI: `home-office` (đăng nhập bằng `aws login --profile home-office --region ap-southeast-1`).

Chia việc:
- **Hạ tầng** (2 Lambda, role, hàng đợi lỗi, API Gateway, canary model theo user, alarm, ngân sách): Terraform, trong `terraform\`
  (xem `terraform\README.md`).
  Đừng sửa hạ tầng bằng console hay AWS CLI: lần `terraform plan` sau sẽ thấy khác và đề nghị sửa ngược lại.
- **Dữ liệu**: `data\` trong thư mục này (đưa GPS, ngưỡng lên S3).
- **Lambda batch** (code, image, chạy batch): thư mục `..\batch\`. **API** (code Lambda tra cứu, spec, script thử): thư mục `..\api\`.
- **Version model**: SageMaker Model Registry, script `registry\register_models.py`.

## Kiến trúc

```
GPS thô (.plt)   ──►  S3  geolife/Data/<user>/Trajectory/
params (ngưỡng)  ──►  S3  models/<version>/params.json
                          │
   run_batch.ps1 ──►  Lambda batch  home-office-batch  (image trong ECR, 2048 MB, tối đa 15 phút)
                          │   đọc params + GPS, lọc → stay point → gom địa điểm → bỏ phiếu
                          ▼
                     S3  results/<version>/<user>.json
                          ▲
App ──► API Gateway home-office-api ──► Lambda tra cứu home-office-lookup (zip, 256 MB)
        GET /health
        GET /v1/users/{user_id}/home-office[?model_version=...]

SageMaker Model Registry (group home-office): version Approved = version mặc định, ghi xuống S3 results/_default.json
```

Hai version model: `heuristic-v1` (gom địa điểm tham lam 200 m) và `dbscan-v2` (DBSCAN eps 200 m).

## Quy trình (lần đầu), và vì sao theo thứ tự này

Mỗi bước tạo ra thứ mà bước sau cần.

| Bước | Lệnh | Tạo ra | Vì sao ở vị trí này |
|---|---|---|---|
| 0 | `aws login --profile home-office --region ap-southeast-1` | phiên đăng nhập | mọi bước sau đều gọi AWS |
| 1 | `.\deploy\data\upload_data.ps1` | bucket, GPS thô trên S3 | Lambda chỉ đọc dữ liệu từ S3; role cần tên bucket |
| 2 | `python -m src.params write`, `python -m src.params check`, `.\deploy\data\upload_params.ps1` | `models/<version>/params.json` | Lambda batch đọc file này đầu tiên |
| 3a | `.\batch\build_bundle.ps1` | kho ECR, gói mã nguồn trên S3, lệnh cho CloudShell | CloudShell cần gói này để build |
| 3b | dán lệnh mà 3a in ra vào **CloudShell** | image `home-office-lambda:v1` trong ECR | Lambda kiểu image cần image có sẵn trong ECR |
| 4 | trong `deploy\terraform`: `terraform plan`, rồi `terraform apply` | toàn bộ hạ tầng | cần image (3b) và bucket (1) |
| 5 | trong `deploy\terraform`: `terraform output -raw api_url \| Set-Content -Encoding ascii ..\..\api\api_url.txt` | `api\api_url.txt` | `test.ps1`, `canary_check.ps1` đọc địa chỉ API từ file này |
| 6 | `.\batch\run_batch.ps1` | `results/<version>/<user>.json` | cần đủ dữ liệu, params, function, quyền ghi |
| 7 | `python deploy/registry/register_models.py register`, rồi `set-default dbscan-v2` | Version 1 = heuristic-v1, Version 2 = dbscan-v2 (Approved), `results/_default.json` | API cần biết version mặc định |
| 7b | trong `deploy\terraform`: `terraform output -raw cognito_client_id \| Set-Content -Encoding ascii ..\..\api\cognito_client_id.txt`, rồi `.\deploy\cognito_users.ps1` | `api\cognito_client_id.txt`, 183 tài khoản trong Cognito | route tra cứu cần token; `test.ps1` đăng nhập bằng các tài khoản này |
| 8 | `.\api\test.ps1` | | kiểm API trả đúng mã HTTP, gồm 401 (không token), 403 (user khác), 200 (đúng user, admin) |

Chạy thử trước khi chạy hết: `.\batch\run_batch.ps1 -OnlyUsers 153,128 -DryRun`.
Batch trên AWS là để **phục vụ**, nên chạy cho mọi user (182), không chia validation / test và không bỏ user bị loại.
Chia tập (`data\split\users.csv`, D19) chỉ dùng cho đánh giá trong notebooks.

## Khi sửa một thứ thì làm lại từ bước nào

| Sửa | Làm lại |
|---|---|
| ngưỡng (`params\*.json` hoặc hằng số trong `src\`) | 2 rồi 6 (không build lại image nếu chỉ đổi file params) |
| `..\batch\batch_handler.py` hoặc code trong `src\` | 3a, 3b, 4, 6 |
| `api\lookup_handler.py` | 4 (`terraform apply` tự nén lại code và tạo bản Lambda mới) |
| thêm GPS | 1 rồi 6 (cho user có dữ liệu mới) |
| đổi version mặc định của API | `python deploy/registry/register_models.py set-default dbscan-v2` |
| thêm version model mới | `params\<version>.json`, 2, 6, rồi `register_models.py register` |
| RAM, timeout, giới hạn request | `deploy\terraform\variables.tf`, rồi 4 |
| bật / tắt đăng nhập | `auth_enabled` trong `deploy\terraform\terraform.tfvars`, rồi 4 (xem `terraform\README.md`, mục Đăng nhập Cognito) |
| đưa model mới ra dần cho một phần người dùng (canary model theo user) | sửa `canary_model`, `canary_percent` trong `deploy\terraform\canary.auto.tfvars`, rồi 4 (xem `terraform\README.md`, mục Canary model theo người dùng) |

## File nào làm gì

| File | Vai trò |
|---|---|
| `common.ps1` | Cấu hình chung: vùng, profile, tên bucket, kho ECR, function batch, hàng đợi. Hàm `Aws` (gọi AWS CLI kèm vùng, profile), `Assert-Ok` (dừng khi lệnh lỗi), `Write-Step`. Mọi script `.ps1` nạp file này. |
| `data\upload_data.ps1` | Bước 1: tạo bucket, chặn truy cập công khai, `aws s3 sync` file `.plt`, so số file máy và S3. |
| `data\upload_params.ps1` | Bước 2: đưa `params\<version>.json` lên `models/<version>/params.json`. |
| `..\batch\build_bundle.ps1` | Bước 3a: tạo kho ECR nếu chưa có, nén `src\` và các file build, đưa lên `build/batch_bundle.tar.gz`, in lệnh cho CloudShell. |
| `..\batch\cloudshell_build.sh` | Bước 3b (chạy trong CloudShell): `docker build`, đăng nhập ECR, `docker push`. |
| `..\batch\Dockerfile`, `Dockerfile.dockerignore`, `requirements.txt` | Công thức image của Lambda batch: Python 3.12 của Lambda, thư viện, `src\`, `batch_handler.py`. |
| `terraform\` | Bước 4: toàn bộ hạ tầng. Bucket và ECR chỉ đọc, nên `terraform destroy` không đụng tới dữ liệu. |
| `..\batch\batch_handler.py` | Code chạy trong Lambda batch. `lambda_handler` (điểm vào), `load_params` (đọc params, nhớ trong container), `download_user` (tải `.plt` song song), `build_result` (nội dung file kết quả). |
| `..\batch\run_batch.ps1` | Bước 6: gọi Lambda batch cho mọi cặp (user, model), đồng bộ hoặc `-Async`, ghi log `batch\runs\`, đếm file mới, lưu biên bản `results/_runs/`. |
| `cognito_users.ps1` | Bước 7b: tạo hoặc cập nhật tài khoản Cognito cho mọi user GeoLife (`userNNN@example.com`, 182 tài khoản) và `admin@example.com`, đặt mật khẩu chính thức, thêm admin vào nhóm `admin`. |
| `registry\register_models.py` | Bước 7: đăng ký version vào SageMaker Model Registry (`register`, `list`, `default`), duyệt version mặc định và ghi `results/_default.json` (`set-default`). |
| `..\api\lookup_handler.py` | Code của Lambda tra cứu: route, kiểm tra `user_id` / `model_version`, đọc `results/`, trả lỗi theo `api\openapi.yaml`, kiểm quyền khi `AUTH_MODE=jwt` (claim `custom:geolife_id`, nhóm `admin`), `PINNED_VERSION` (model mặc định ghim), `CANARY_MODEL` + `CANARY_PERCENT` (+ `CANARY_SALT`, `CANARY_SIMULATE_ERROR`) cho canary model theo user (băm sha256 của `muối:user_id`, header `X-Canary`). |
| `..\api\test.ps1` | Bước 8: đăng nhập tài khoản demo, gọi thử API và so mã HTTP với mong đợi (`-NoAuth` khi tắt đăng nhập). |
| `..\api\auth.ps1` | Hàm `Get-IdToken` (đăng nhập Cognito bằng email + mật khẩu, trả ID token), `Read-DemoPassword`. Các script trong `api\` nạp file này. |
| `..\api\get_token.ps1` | In ID token của một tài khoản, để gọi API bằng tay. |
| `..\api\canary_check.ps1` | Demo canary: gọi cả 182 user 2 vòng, đếm user mỗi model, kiểm tra không user nào đổi model, liệt kê user lỗi. |
| `bench\results\` | Kết quả thử nghiệm đo thời gian và RAM ngày 12/11 (chỉ trên máy, không có trong git; script đo đã xoá, xem lịch sử git nếu cần đo lại). |

Hàm trong `src\params.py` (dùng bởi Lambda batch): `load` (đọc params từ máy hoặc S3), `validate`, `to_kwargs` (chia params cho từng bước), `run_pipeline` (stay point, gom địa điểm, bỏ phiếu), `build` và CLI `write` (sinh `params\*.json`), `check` (đối chiếu file với code).

## Quy ước trong thư mục này

- Comment, docstring và thông báo in ra: tiếng Việt có dấu. File `.ps1` lưu UTF-8 **có BOM** để Windows PowerShell 5.1 đọc đúng dấu.
- Đầu mỗi file: làm gì, bước mấy của quy trình, cần gì trước, cách chạy, tạo ra gì.
- Tên tài nguyên AWS bắt đầu bằng `home-office-`. Script PowerShell lấy tên từ `common.ps1`; Terraform khai báo trong `deploy\terraform`;
  `cloudshell_build.sh` và `register_models.py` lặp lại vì không đọc được file PowerShell.
- Script chạy lại an toàn: tạo nếu chưa có, cập nhật nếu đã có.

## Lỗi hay gặp

| Lỗi | Cách xử lý |
|---|---|
| `... .ps1 is not recognized` | `cd C:\Users\Acer\OneDrive\Desktop\Home_Office` |
| `Chưa đăng nhập AWS` / `NoCredentials` / `No valid credential sources` | `aws login --profile home-office --region ap-southeast-1` |
| `MissingDependencyException ... botocore[crt]` (script Python) | `python -m pip install "botocore[crt]"` |
| `charmap codec can't encode` khi in tiếng Việt | `$env:PYTHONIOENCODING = "utf-8"` |
| `failed to connect to the docker API` | lệnh `docker` chỉ chạy trong CloudShell |
| CloudShell `cookie has changed` | đóng bớt tab AWS, tải lại trang (F5) |
| `PermissionError ... /var/task/...` | đã xử lý trong Dockerfile (`chmod`); build lại image |
| `terraform plan` muốn sửa thứ bạn không đổi | có người sửa bằng console hoặc CLI; xem kỹ trước khi apply |
| `TooManyRequestsException` | giảm `-Concurrency` hoặc dùng `-Async` |
