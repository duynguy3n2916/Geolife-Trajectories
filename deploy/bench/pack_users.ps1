# Thử nghiệm cũ: nén thư mục Trajectory của vài user thành MỘT file .tar.gz rồi đưa lên S3 (ít request hơn hàng nghìn file nhỏ).
# Lambda batch tự dùng file nén nếu có (s3://<bucket>/geolife/Data/<user>.tar.gz). Quy trình chính không cần bước này.
# Cách chạy (từ thư mục Home_Office):  .\deploy\bench\pack_users.ps1 167 017 153
param([Parameter(ValueFromRemainingArguments = $true)] [string[]]$PackUsers)
. "$PSScriptRoot\..\common.ps1"
if (-not $PackUsers) { throw "Cho mã user, ví dụ: 167 017 153" }
New-Item -ItemType Directory -Force "deploy/bench/pack" | Out-Null
foreach ($u in $PackUsers) {
    $tgz = "deploy/bench/pack/$u.tar.gz"
    Write-Step "user ${u}: nén"
    tar.exe -czf $tgz -C "data\raw\geolife\Data\$u\Trajectory" .
    Assert-Ok "nén user $u"
    Write-Host ("{0:N1} MB, đang đưa lên" -f ((Get-Item $tgz).Length / 1MB))
    $sw = [Diagnostics.Stopwatch]::StartNew()
    Aws s3 cp $tgz "s3://$Bucket/geolife/Data/$u.tar.gz" --only-show-errors
    Assert-Ok "đưa user $u lên"
    Write-Host ("Đã đưa lên sau {0:N0} s" -f $sw.Elapsed.TotalSeconds)
}
