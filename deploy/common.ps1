# Cấu hình và hàm dùng chung cho mọi script trong deploy\.
# Không chạy trực tiếp: các script khác nạp file này bằng  . "$PSScriptRoot\..\common.ps1"  (trong batch\: ..\deploy\common.ps1)
# Mọi script phải chạy từ thư mục Home_Office (đường dẫn tương đối tính từ đó).

# ---- Tài khoản và vùng ----
$Region  = "ap-southeast-1"          # Singapore
$Profile = "home-office"             # profile AWS CLI, đăng nhập bằng: aws login --profile home-office --region ap-southeast-1
$Acct    = (aws.exe sts get-caller-identity --profile $Profile --query Account --output text 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $Acct) { throw "Chưa đăng nhập AWS. Chạy: aws login --profile $Profile --region $Region" }

# ---- Tên tài nguyên mà các script còn dùng (mọi tên bắt đầu bằng home-office) ----
# Role, function, hàng đợi, API do Terraform tạo và quản lý: xem deploy/terraform/main.tf.
$Bucket     = "home-office-lambda-sg-$Acct"     # S3: geolife/ (GPS thô), models/ (params), results/ (kết quả), build/ (gói build)
$Repo       = "home-office-lambda"              # ECR chứa image của Lambda batch (giữ tên cũ vì image đã đẩy)
$BatchFn    = "home-office-batch"               # Lambda chạy model cho một user
$Dlq        = "home-office-batch-dlq"           # hàng đợi SQS nhận các lần gọi bất đồng bộ bị lỗi

# ---- Hàm tiện ích ----
# Gọi AWS CLI kèm vùng và profile. Gọi aws.exe (không phải aws) vì PowerShell không phân biệt hoa thường:
# "aws" bên trong hàm "Aws" sẽ gọi lại chính hàm này và lặp vô hạn.
function Aws { & aws.exe @args --region $Region --profile $Profile }

# Dừng script nếu lệnh ngoài vừa chạy báo lỗi.
function Assert-Ok([string]$What) { if ($LASTEXITCODE -ne 0) { throw "Lỗi: $What" } }

# In tiêu đề một bước.
function Write-Step([string]$Text) { Write-Host "== $Text" -ForegroundColor Cyan }
