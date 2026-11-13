# Bước 2 của quy trình: đưa tham số (ngưỡng) của mỗi version model lên S3 để Lambda batch đọc.
# Cần có trước: params\<version>.json, tạo bằng  python -m src.params write  rồi kiểm bằng  python -m src.params check
# Cách chạy (từ thư mục Home_Office):  .\deploy\data\upload_params.ps1
# Tạo ra: s3://<bucket>/models/<version>/params.json
# Đổi ngưỡng chỉ cần chạy lại bước này rồi chạy batch, không phải build lại image.
. "$PSScriptRoot\..\common.ps1"
$files = Get-ChildItem "params" -Filter *.json -ErrorAction SilentlyContinue
if (-not $files) { throw "Chưa có params\*.json. Chạy: python -m src.params write" }

Write-Step "Đưa params lên s3://$Bucket/models/"
foreach ($f in $files) {
    $dest = "s3://$Bucket/models/$($f.BaseName)/params.json"
    Aws s3 cp $f.FullName $dest --only-show-errors
    Assert-Ok "đưa $($f.Name) lên"
    Write-Host "Đã đưa $dest"
}
Write-Step "Kiểm tra"
Aws s3 ls "s3://$Bucket/models/" --recursive
