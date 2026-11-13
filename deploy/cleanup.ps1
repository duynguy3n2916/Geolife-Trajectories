# Xoá các tài nguyên AWS của dự án. Mặc định GIỮ bucket (dữ liệu GPS, params, kết quả) và kho ECR.
# Cách chạy (từ thư mục Home_Office):
#   .\deploy\cleanup.ps1 -Legacy        chỉ xoá đồ của bản thử cũ: function home-office-test và role home-office-lambda-role
#   .\deploy\cleanup.ps1                xoá API, 2 function, 2 role, hàng đợi lỗi, log (giữ bucket và ECR)
#   .\deploy\cleanup.ps1 -All           xoá thêm kho ECR và bucket (mất hết dữ liệu trên S3: phải upload lại từ đầu)
# Script hỏi xác nhận trước khi xoá. Tài nguyên không tồn tại thì bỏ qua.
param([switch]$Legacy, [switch]$All)
. "$PSScriptRoot\common.ps1"

# Xoá một role: phải gỡ hết policy (gắn sẵn và viết trong role) trước thì mới xoá được role.
function Remove-Role([string]$Name) {
    Aws iam get-role --role-name $Name 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { return }
    foreach ($p in (Aws iam list-role-policies --role-name $Name --query "PolicyNames[]" --output text) -split "\s+" | Where-Object { $_ }) {
        Aws iam delete-role-policy --role-name $Name --policy-name $p
    }
    foreach ($a in (Aws iam list-attached-role-policies --role-name $Name --query "AttachedPolicies[].PolicyArn" --output text) -split "\s+" | Where-Object { $_ }) {
        Aws iam detach-role-policy --role-name $Name --policy-arn $a
    }
    Aws iam delete-role --role-name $Name
    Write-Host "Đã xoá role $Name"
}

# Xoá một function và nhóm log của nó.
function Remove-Function([string]$Name) {
    Aws lambda get-function --function-name $Name 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { Aws lambda delete-function --function-name $Name; Write-Host "Đã xoá function $Name" }
    Aws logs delete-log-group --log-group-name "/aws/lambda/$Name" 2>$null
}

if ($Legacy) {
    if ((Read-Host "Xoá function home-office-test và role home-office-lambda-role? Gõ yes") -ne "yes") { Write-Host "Đã huỷ"; return }
    Remove-Function "home-office-test"
    Remove-Role "home-office-lambda-role"
    Write-Host "Xong."
    return
}

$what = "API $ApiName, function $BatchFn và $LookupFn, role $BatchRole và $LookupRole, hàng đợi $Dlq, log"
if ($All) { $what += ", KHO ECR $Repo và BUCKET $Bucket (mất hết dữ liệu)" }
if ((Read-Host "Xoá $what? Gõ yes") -ne "yes") { Write-Host "Đã huỷ"; return }

$apiId = Aws apigatewayv2 get-apis --query "Items[?Name=='$ApiName'].ApiId | [0]" --output text
if ($apiId -and $apiId -ne "None") { Aws apigatewayv2 delete-api --api-id $apiId; Write-Host "Đã xoá API $apiId" }
Remove-Function $BatchFn
Remove-Function $LookupFn
Remove-Function "home-office-test"
Remove-Role $BatchRole
Remove-Role $LookupRole
Remove-Role "home-office-lambda-role"
$q = Aws sqs get-queue-url --queue-name $Dlq --query QueueUrl --output text 2>$null
if ($LASTEXITCODE -eq 0 -and $q) { Aws sqs delete-queue --queue-url $q; Write-Host "Đã xoá hàng đợi $Dlq" }
if ($All) {
    Aws ecr delete-repository --repository-name $Repo --force 2>$null | Out-Null
    Aws s3 rb "s3://$Bucket" --force
    Write-Host "Đã xoá kho ECR và bucket"
}
Write-Host "Xong. Kiểm tra: aws lambda list-functions --profile $Profile --region $Region"
