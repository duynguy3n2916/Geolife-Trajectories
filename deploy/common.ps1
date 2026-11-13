# Cấu hình và hàm dùng chung cho mọi script trong deploy\.
# Không chạy trực tiếp: các script khác nạp file này bằng  . "$PSScriptRoot\..\common.ps1"
# Mọi script phải chạy từ thư mục Home_Office (đường dẫn tương đối tính từ đó).

# ---- Tài khoản và vùng ----
$Region  = "ap-southeast-1"          # Singapore
$Profile = "home-office"             # profile AWS CLI, đăng nhập bằng: aws login --profile home-office --region ap-southeast-1
$Acct    = (aws.exe sts get-caller-identity --profile $Profile --query Account --output text 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $Acct) { throw "Chưa đăng nhập AWS. Chạy: aws login --profile $Profile --region $Region" }

# ---- Tên tài nguyên (mọi tên bắt đầu bằng home-office) ----
$Bucket     = "home-office-lambda-sg-$Acct"     # S3: geolife/ (GPS thô), models/ (params), results/ (kết quả), build/ (gói build)
$Repo       = "home-office-lambda"              # ECR chứa image của Lambda batch (giữ tên cũ vì image đã đẩy)
$Image      = "$Acct.dkr.ecr.$Region.amazonaws.com/${Repo}:v1"
$BatchFn    = "home-office-batch"               # Lambda chạy model cho một user
$BatchRole  = "home-office-batch-role"
$Dlq        = "home-office-batch-dlq"           # hàng đợi SQS nhận các lần gọi bất đồng bộ bị lỗi
$LookupFn   = "home-office-lookup"              # Lambda tra cứu kết quả cho API
$LookupRole = "home-office-lookup-role"
$ApiName    = "home-office-api"                 # API Gateway HTTP API
$TrustFile  = "deploy/lambda-trust.json"        # cho phép dịch vụ Lambda dùng role

# ---- Hàm tiện ích ----
# Gọi AWS CLI kèm vùng và profile. Gọi aws.exe (không phải aws) vì PowerShell không phân biệt hoa thường:
# "aws" bên trong hàm "Aws" sẽ gọi lại chính hàm này và lặp vô hạn.
function Aws { & aws.exe @args --region $Region --profile $Profile }

# Dừng script nếu lệnh ngoài vừa chạy báo lỗi.
function Assert-Ok([string]$What) { if ($LASTEXITCODE -ne 0) { throw "Lỗi: $What" } }

# In tiêu đề một bước.
function Write-Step([string]$Text) { Write-Host "== $Text" -ForegroundColor Cyan }

# Ghi một chuỗi JSON ra file tạm (không BOM) và trả đường dẫn, để truyền cho AWS CLI bằng file://...
function New-TempJson([string]$Name, [string]$Json) {
    $path = Join-Path $env:TEMP $Name
    [IO.File]::WriteAllText($path, $Json)
    return $path
}

# Tạo role cho Lambda nếu chưa có (kèm quyền ghi log CloudWatch). Trả $true nếu vừa tạo.
function New-LambdaRole([string]$Name) {
    Aws iam get-role --role-name $Name 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { return $false }
    Aws iam create-role --role-name $Name --assume-role-policy-document "file://$TrustFile" | Out-Null
    Assert-Ok "tạo role $Name"
    Aws iam attach-role-policy --role-name $Name --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
    Assert-Ok "gắn quyền ghi log cho $Name"
    return $true
}
