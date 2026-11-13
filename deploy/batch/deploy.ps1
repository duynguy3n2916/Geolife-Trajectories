# Bước 4 của quy trình: tạo (hoặc cập nhật) role và Lambda batch dùng image đã đẩy lên ECR.
# Cần có trước: image $Image trong ECR (bước 3: build_bundle.ps1 rồi lệnh build trong CloudShell) và bucket (bước 1).
# Cách chạy (từ thư mục Home_Office):  .\deploy\batch\deploy.ps1
# Chạy lại an toàn: role và quyền được ghi đè, function có sẵn thì chỉ cập nhật sang image mới.
. "$PSScriptRoot\..\common.ps1"

Write-Step "Kiểm tra image $Image"
Aws ecr describe-images --repository-name $Repo --image-ids imageTag=v1 2>$null | Out-Null
Assert-Ok "chưa có image $Image trong ECR. Làm bước 3 (deploy\batch\build_bundle.ps1) trước"

Write-Step "Role $BatchRole"
if (New-LambdaRole $BatchRole) { Write-Host "Đã tạo role"; Start-Sleep 15 }   # role mới cần vài giây mới dùng được
# Quyền S3 tối thiểu: đọc GPS và params, ghi kết quả. ListBucket để liệt kê file .plt của một user.
$policy = '{"Version":"2012-10-17","Statement":[' +
  '{"Effect":"Allow","Action":"s3:GetObject","Resource":["arn:aws:s3:::' + $Bucket + '/geolife/*","arn:aws:s3:::' + $Bucket + '/models/*"]},' +
  '{"Effect":"Allow","Action":"s3:ListBucket","Resource":"arn:aws:s3:::' + $Bucket + '","Condition":{"StringLike":{"s3:prefix":"geolife/*"}}},' +
  '{"Effect":"Allow","Action":"s3:PutObject","Resource":"arn:aws:s3:::' + $Bucket + '/results/*"}]}'
Aws iam put-role-policy --role-name $BatchRole --policy-name batch-s3 --policy-document ("file://" + (New-TempJson "ho-batch-s3.json" $policy))
Assert-Ok "gắn quyền S3 cho $BatchRole"

Write-Step "Function $BatchFn (2048 MB, tối đa 15 phút)"
Aws lambda get-function --function-name $BatchFn 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    $created = $false
    for ($i = 1; $i -le 3 -and -not $created; $i++) {
        Aws lambda create-function --function-name $BatchFn --package-type Image --code "ImageUri=$Image" `
            --role "arn:aws:iam::${Acct}:role/$BatchRole" --memory-size 2048 --timeout 900 `
            --environment "Variables={BUCKET=$Bucket}" | Out-Null
        if ($LASTEXITCODE -eq 0) { $created = $true } else { Write-Host "Thử lại sau 15 s (role có thể chưa sẵn sàng)"; Start-Sleep 15 }
    }
    if (-not $created) { throw "Lỗi: tạo function $BatchFn" }
    Write-Host "Đã tạo function"
} else {
    Aws lambda update-function-code --function-name $BatchFn --image-uri $Image | Out-Null
    Assert-Ok "cập nhật image cho $BatchFn"
    Write-Host "Đã cập nhật function sang image mới"
}
Aws lambda wait function-active-v2 --function-name $BatchFn
Aws lambda wait function-updated-v2 --function-name $BatchFn
Write-Host "Xong: $BatchFn. Bước tiếp: .\deploy\batch\setup_async.ps1 (một lần), rồi .\deploy\batch\run_batch.ps1"
