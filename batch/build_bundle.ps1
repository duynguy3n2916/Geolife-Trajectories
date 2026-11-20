# Bước 3a của quy trình: đóng gói mã nguồn của Lambda batch và đưa lên S3 để CloudShell lấy về build image.
# Vì sao build ở CloudShell: image nặng vài trăm MB, đẩy từ máy nhà lên ECR quá chậm; CloudShell nằm sẵn trong AWS.
# Chạy lại mỗi khi sửa batch\batch_handler.py hoặc src\ (code nằm trong image). Đổi params thì KHÔNG cần.
# Cách chạy (từ thư mục Home_Office):  .\batch\build_bundle.ps1
# Tạo ra: s3://<bucket>/build/batch_bundle.tar.gz, và in lệnh để dán vào CloudShell (bước 3b).
. "$PSScriptRoot\..\deploy\common.ps1"

Write-Step "Kho ECR $Repo"
Aws ecr describe-repositories --repository-names $Repo 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Aws ecr create-repository --repository-name $Repo | Out-Null
    Assert-Ok "tạo kho ECR $Repo"
    Write-Host "Đã tạo kho"
}

Write-Step "Đóng gói"
$bundle = Join-Path $env:TEMP "batch_bundle.tar.gz"
if (Test-Path $bundle) { Remove-Item $bundle }
# Chỉ gói những gì Dockerfile cần: src\ (bỏ src\eda) và các file trong batch\.
tar.exe -czf $bundle --exclude=__pycache__ --exclude=*.pyc --exclude=src/eda `
    src batch/Dockerfile batch/Dockerfile.dockerignore batch/requirements.txt `
    batch/batch_handler.py batch/cloudshell_build.sh
Assert-Ok "đóng gói bằng tar"
Write-Host ("Gói {0:N0} KB" -f ((Get-Item $bundle).Length / 1KB))

Write-Step "Đưa gói lên S3"
Aws s3 cp $bundle "s3://$Bucket/build/batch_bundle.tar.gz" --only-show-errors
Assert-Ok "đưa gói lên S3"

Write-Host ""
Write-Host "Bước 3b: mở CloudShell (vùng Singapore) và dán NGUYÊN dòng dưới đây:" -ForegroundColor Green
Write-Host "cd ~ && rm -rf ho && mkdir ho && cd ho && aws s3 cp s3://$Bucket/build/batch_bundle.tar.gz - --region $Region | tar xz && bash batch/cloudshell_build.sh"
Write-Host ""
Write-Host "Khi CloudShell in 'Xong', đưa image mới lên Lambda:  cd deploy\terraform; terraform apply"
