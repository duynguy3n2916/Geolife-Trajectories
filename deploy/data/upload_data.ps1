# Bước 1 của quy trình: tạo bucket S3 (nếu chưa có) và đưa GPS thô (.plt) của mọi user lên S3, rồi so số file hai phía.
# Chạy lại an toàn: "aws s3 sync" chỉ gửi file còn thiếu hoặc đã đổi.
# Cách chạy (từ thư mục Home_Office):
#   .\deploy\data\upload_data.ps1                      mọi user
#   .\deploy\data\upload_data.ps1 -OnlyUsers 000,001   chỉ vài user
# Tạo ra: s3://<bucket>/geolife/Data/<user>/Trajectory/*.plt
param([string[]]$OnlyUsers)
. "$PSScriptRoot\..\common.ps1"
$Root = "data\raw\geolife\Data"
aws.exe configure set default.s3.max_concurrent_requests 50 --profile $Profile

Write-Step "Bucket $Bucket"
Aws s3api head-bucket --bucket $Bucket 2>$null
if ($LASTEXITCODE -ne 0) {
    Aws s3 mb "s3://$Bucket"
    Assert-Ok "tạo bucket $Bucket"
    Write-Host "Đã tạo bucket"
} else {
    Write-Host "Bucket đã có"
}
# Chặn mọi truy cập công khai: đây là dữ liệu vị trí.
Aws s3api put-public-access-block --bucket $Bucket --public-access-block-configuration "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
Assert-Ok "chặn truy cập công khai"

Write-Step "Danh sách user"
$users = Get-ChildItem $Root -Directory | Where-Object { Test-Path (Join-Path $_.FullName "Trajectory") } | ForEach-Object { $_.Name } | Sort-Object
if ($OnlyUsers) {
    $want = $OnlyUsers | ForEach-Object { $_ -split "," } | Where-Object { $_ }
    $users = @($users | Where-Object { $want -contains $_ })
}
Write-Host ("{0} user sẽ đưa lên s3://{1}/geolife/Data/" -f $users.Count, $Bucket)

Write-Step "Đưa file .plt lên (một user lỗi không dừng các user khác)"
$failed = @()
$total = [Diagnostics.Stopwatch]::StartNew()
$i = 0
foreach ($u in $users) {
    $i++
    $sw = [Diagnostics.Stopwatch]::StartNew()
    Aws s3 sync "$Root\$u\Trajectory" "s3://$Bucket/geolife/Data/$u/Trajectory" --exclude "*" --include "*.plt" --only-show-errors
    if ($LASTEXITCODE -ne 0) { $failed += $u; Write-Host "!! user $u lỗi" -ForegroundColor Red }
    Write-Host ("[{0}/{1}] user {2}: {3:N0} s (tổng {4:N0} s)" -f $i, $users.Count, $u, $sw.Elapsed.TotalSeconds, $total.Elapsed.TotalSeconds)
}

Write-Step "So số file .plt: máy và S3"
$remote = @{}
foreach ($line in (Aws s3 ls "s3://$Bucket/geolife/Data/" --recursive)) {
    $key = (($line -split "\s+", 4)[3])
    if ($key -match '^geolife/Data/([^/]+)/Trajectory/[^/]+\.plt$') { $remote[$Matches[1]] = 1 + [int]$remote[$Matches[1]] }
}
$mismatch = @()
foreach ($u in $users) {
    $local = (Get-ChildItem "$Root\$u\Trajectory" -Filter *.plt -File).Count
    if ($local -ne [int]$remote[$u]) { $mismatch += $u; Write-Host ("LỆCH user {0}: máy={1} S3={2}" -f $u, $local, [int]$remote[$u]) -ForegroundColor Yellow }
}
Write-Host ("Xong sau {0:N0} s. User: {1}, lỗi gửi: {2}, lệch số file: {3}" -f $total.Elapsed.TotalSeconds, $users.Count, $failed.Count, $mismatch.Count)
if ($failed.Count -or $mismatch.Count) { Write-Host "Chạy lại script: nó chỉ gửi phần còn thiếu." }
