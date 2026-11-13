# Đặt version model mặc định mà API trả về khi không truyền ?model_version=...
# Ghi s3://<bucket>/results/_default.json. Lambda tra cứu đọc lại sau tối đa 60 giây (không cần deploy lại).
# Đây là dữ liệu trên S3, không phải hạ tầng, nên nằm ngoài Terraform.
# Cách chạy (từ thư mục Home_Office):
#   .\deploy\data\set_default_version.ps1                    xem version mặc định hiện tại
#   .\deploy\data\set_default_version.ps1 dbscan-v2          đặt mặc định = dbscan-v2
param([ValidateSet("heuristic-v1", "dbscan-v2")][string]$Version)
. "$PSScriptRoot\..\common.ps1"

if (-not $Version) {
    Write-Host "Hiện tại: $(Aws s3 cp "s3://$Bucket/results/_default.json" -)"
    return
}
$df = New-TempJson "ho-default.json" ('{"default_model_version":"' + $Version + '"}')
Aws s3 cp $df "s3://$Bucket/results/_default.json" --content-type application/json --only-show-errors
Assert-Ok "ghi results/_default.json"
Write-Host "Mặc định = $Version (Lambda đọc lại sau tối đa 60 giây)" -ForegroundColor Green
