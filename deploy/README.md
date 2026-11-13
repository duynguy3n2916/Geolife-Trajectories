# deploy/: đưa Home/Office lên AWS

Tài liệu này giải thích quy trình deploy, thứ tự các bước, và mỗi file làm gì.
Mọi script chạy trong **PowerShell, từ thư mục `Home_Office`** (trừ một lệnh chạy trong CloudShell).

**Hạ tầng (role, 2 Lambda, hàng đợi lỗi, API Gateway) do Terraform quản lý**, trong `deploy\terraform\`
(xem `terraform\README.md`; mới dùng Terraform thì đọc `terraform\HOC_TERRAFORM.md`).
Các script `.ps1` còn lại chỉ làm việc với **dữ liệu và image**: đưa GPS, params lên S3, build image, chạy batch, thử API.
Đừng sửa hạ tầng bằng console hay AWS CLI nữa: lần `terraform plan` sau sẽ thấy khác và đề nghị sửa ngược lại.
Vùng: Singapore (`ap-southeast-1`). Profile AWS CLI: `home-office` (đăng nhập bằng `aws login --profile home-office --region ap-southeast-1`).

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
```

Hai version model: `heuristic-v1` (gom địa điểm greedy 200 m) và `dbscan-v2` (DBSCAN eps 200 m).
Version mặc định của API nằm trong `s3://<bucket>/results/_default.json`.

## Quy trình (lần đầu), và vì sao theo thứ tự này

Mỗi bước tạo ra thứ mà bước sau cần.

| Bước | Lệnh | Tạo ra | Vì sao ở vị trí này |
|---|---|---|---|
| 0 | `aws login --profile home-office --region ap-southeast-1` | phiên đăng nhập | mọi bước sau đều gọi AWS |
| 1 | `.\deploy\data\upload_data.ps1` | bucket, GPS thô trên S3 | Lambda chỉ đọc dữ liệu từ S3; role cần tên bucket |
| 2 | `python -m src.params write`, `python -m src.params check`, `.\deploy\data\upload_params.ps1` | `models/<version>/params.json` | Lambda batch đọc file này đầu tiên |
| 3a | `.\deploy\batch\build_bundle.ps1` | kho ECR, gói mã nguồn trên S3, lệnh cho CloudShell | CloudShell cần gói này để build |
| 3b | dán lệnh mà 3a in ra vào **CloudShell** | image `home-office-lambda:v1` trong ECR | Lambda kiểu image cần image có sẵn trong ECR |
| 4 | trong `deploy\terraform`: `terraform plan`, rồi `terraform apply` | 2 role, 2 Lambda, hàng đợi lỗi, cấu hình thử lại, API Gateway | cần image (3b) và bucket (1) |
| 5 | `terraform output -raw api_url \| Set-Content -Encoding ascii ..\lookup\api_url.txt` | `deploy\lookup\api_url.txt` | `test.ps1` đọc địa chỉ API từ file này |
| 6 | `.\deploy\batch\run_batch.ps1` | `results/<version>/<user>.json` | cần đủ dữ liệu, params, function, quyền ghi |
| 7 | `.\deploy\data\set_default_version.ps1 heuristic-v1` (lần đầu), rồi `.\deploy\lookup\test.ps1` | `results/_default.json` | API trả kết quả của bước 6 |

Chạy thử trước khi chạy hết: `.\deploy\batch\run_batch.ps1 -OnlyUsers 153,128 -DryRun`.
Tập test chỉ chạy **một lần** (D19): `.\deploy\batch\run_batch.ps1 -Group test` (script hỏi xác nhận).

## Khi sửa một thứ thì làm lại từ bước nào

| Sửa | Làm lại |
|---|---|
| ngưỡng (`params\*.json` hoặc hằng số trong `src\`) | 2 rồi 6 (không build lại image nếu chỉ đổi file params) |
| `deploy\batch\handler.py` hoặc code trong `src\` | 3a, 3b, 4, 6 |
| `deploy\lookup\handler.py` | 4 (`terraform apply` tự nén lại code) |
| thêm GPS | 1 rồi 6 (cho user có dữ liệu mới) |
| đổi version mặc định của API | `.\deploy\data\set_default_version.ps1 dbscan-v2` |
| RAM, timeout, giới hạn request | `deploy\terraform\variables.tf`, rồi 4 |

## File nào làm gì

| File | Vai trò |
|---|---|
| `common.ps1` | Cấu hình chung: vùng, profile, tên bucket, kho ECR, function batch, hàng đợi. Hàm `Aws` (gọi AWS CLI kèm vùng, profile), `Assert-Ok` (dừng khi lệnh lỗi), `Write-Step`, `New-TempJson` (file JSON tạm cho AWS CLI). Mọi script nạp file này. |
| `data\upload_data.ps1` | Bước 1: tạo bucket, chặn truy cập công khai, `aws s3 sync` file `.plt`, so số file máy và S3. |
| `terraform\` | Bước 4: toàn bộ hạ tầng (2 role với quyền S3 tối thiểu, 2 Lambda, hàng đợi lỗi và thử lại 2 lần, API Gateway 2 route giới hạn 20 request/giây). Bucket và ECR chỉ đọc. `terraform destroy` thay cho `cleanup.ps1` cũ (không đụng bucket, ECR). |
| `data\set_default_version.ps1` | Đặt version mặc định của API (`results/_default.json`). |
| `data\upload_params.ps1` | Bước 2: đưa `params\<version>.json` lên `models/<version>/params.json`. |
| `batch\build_bundle.ps1` | Bước 3a: tạo kho ECR nếu chưa có, nén `src\` và các file build, đưa lên `build/batch_bundle.tar.gz`, in lệnh cho CloudShell. |
| `batch\cloudshell_build.sh` | Bước 3b (chạy trong CloudShell): `docker build`, đăng nhập ECR, `docker push`. |
| `batch\Dockerfile`, `Dockerfile.dockerignore`, `requirements.txt` | Công thức image của Lambda batch: Python 3.12 của Lambda, thư viện, `src\`, `handler.py`. |
| `batch\handler.py` | Code chạy trong Lambda batch. `lambda_handler` (điểm vào), `load_params` (đọc params, nhớ trong container), `download_user` (tải `.plt` song song), `build_result` (nội dung file kết quả). |
| `batch\run_batch.ps1` | Bước 6: gọi Lambda batch cho mọi cặp (user, model), đồng bộ hoặc `-Async`, ghi log `batch\runs\`, đếm file mới, lưu biên bản `results/_runs/`. |
| `lookup\handler.py` | Code của Lambda tra cứu: route, kiểm tra `user_id` / `model_version`, đọc `results/`, trả lỗi theo `api\openapi.yaml`, công tắc đăng nhập `AUTH_MODE`. |
| `lookup\test.ps1` | Gọi thử API và so mã HTTP với mong đợi. |
| `registry\register_models.py` | Đăng ký 2 version vào SageMaker Model Registry (chưa chạy). |
| `bench\results\` | Kết quả thử nghiệm đo thời gian và RAM ngày 12/11 (chỉ trên máy, không có trong git; script đo đã xoá, xem lịch sử git nếu cần đo lại). |

Hàm trong `src\params.py` (dùng bởi Lambda batch): `load` (đọc params từ máy hoặc S3), `validate`, `to_kwargs` (chia params cho từng bước), `run_pipeline` (stay point, gom địa điểm, bỏ phiếu), `build` / `check` / CLI `write`, `check` (đối chiếu file với code).

## Quy ước trong thư mục này

- Comment, docstring và thông báo in ra: tiếng Việt có dấu. File `.ps1` lưu UTF-8 **có BOM** để Windows PowerShell 5.1 đọc đúng dấu.
- Đầu mỗi file: làm gì, bước mấy của quy trình, cần gì trước, cách chạy, tạo ra gì.
- Tên tài nguyên AWS bắt đầu bằng `home-office-` và chỉ khai báo trong `common.ps1` (riêng `cloudshell_build.sh` và `register_models.py` lặp lại vì không đọc được file PowerShell).
- Script chạy lại an toàn: tạo nếu chưa có, cập nhật nếu đã có.

## Lỗi hay gặp

| Lỗi | Cách xử lý |
|---|---|
| `... .ps1 is not recognized` | `cd C:\Users\Acer\OneDrive\Desktop\Home_Office` |
| `Chưa đăng nhập AWS` / `NoCredentials` | `aws login --profile home-office --region ap-southeast-1` |
| `failed to connect to the docker API` | lệnh `docker` chỉ chạy trong CloudShell |
| CloudShell `cookie has changed` | đóng bớt tab AWS, tải lại trang (F5) |
| `PermissionError ... /var/task/...` | đã xử lý trong Dockerfile (`chmod`); build lại image |
| `terraform plan` muốn sửa thứ bạn không đổi | có người sửa bằng console hoặc CLI; xem kỹ trước khi apply |
| `TooManyRequestsException` | giảm `-Concurrency` hoặc dùng `-Async` |
