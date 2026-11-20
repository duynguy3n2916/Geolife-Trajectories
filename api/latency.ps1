# Đo độ trễ API tra cứu (có đăng nhập Cognito + JWT authorizer), từ máy anh tới AWS Singapore.
# Đo 2 thứ:
#   1. Phía client: thời gian Invoke-WebRequest (tính cả mạng VN -> Singapore, API Gateway kiểm JWT, Lambda, S3).
#   2. Trong Lambda: số "Duration" trong log REPORT của Lambda home-office-lookup (cần aws login, profile home-office).
# Cách chạy (thư mục Home_Office):
#   $env:AWS_PROFILE = "home-office"
#   .\api\latency.ps1                 20 lần /health + 20 lần tra cứu user 153 (token admin)
#   .\api\latency.ps1 -N 50 -User 002
# Lần gọi đầu bỏ ra (làm ấm Lambda), không tính vào kết quả.
param([int]$N = 20, [string]$User = "153", [string]$Email = "admin@example.com")
. "$PSScriptRoot\auth.ps1"
$base = (Get-Content "$PSScriptRoot\api_url.txt" -Raw).Trim()
$token = Get-IdToken $Email (Read-DemoPassword)
$h = @{ Authorization = "Bearer $token" }

function Measure-Calls([string]$url, [hashtable]$headers) {
    $ms = @()
    for ($i = 0; $i -le $N; $i++) {
        $sw = [Diagnostics.Stopwatch]::StartNew()
        try { $r = Invoke-WebRequest -Uri $url -Headers $headers -UseBasicParsing -TimeoutSec 30; $code = [int]$r.StatusCode }
        catch { $code = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 0 } }
        $sw.Stop()
        if ($i -gt 0) { $ms += $sw.Elapsed.TotalMilliseconds }   # bỏ lần đầu (làm ấm)
        if ($code -ne 200) { Write-Host "  lần $i trả $code" -ForegroundColor Yellow }
    }
    return ,$ms
}

function Summary([string]$name, [double[]]$ms) {
    $s = $ms | Sort-Object
    $p = { param($q) $s[[math]::Min($s.Count - 1, [math]::Floor($q * $s.Count))] }
    "{0,-34} n={1,3}  min {2,6:N0} ms  trung vị {3,6:N0} ms  p95 {4,6:N0} ms  max {5,6:N0} ms" -f $name, $s.Count, $s[0], (& $p 0.5), (& $p 0.95), $s[-1]
}

$start = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
Write-Host "Đo $N lần mỗi loại (bỏ lần đầu)..."
$health = Measure-Calls "$base/health" @{}
$lookup = Measure-Calls "$base/v1/users/$User/home-office" $h
Write-Host ""
Write-Host "Phía client (VN -> Singapore, tính cả mạng):" -ForegroundColor Cyan
Summary "/health (không token)" $health
Summary "/v1/users/$User (JWT, admin)" $lookup

Write-Host ""
Write-Host "Trong Lambda (log REPORT, đợi 15 giây cho log về CloudWatch)..." -ForegroundColor Cyan
Start-Sleep -Seconds 15
try {
    $raw = aws logs filter-log-events --log-group-name /aws/lambda/home-office-lookup --start-time $start `
        --filter-pattern "REPORT" --region ap-southeast-1 --query "events[].message" --output json 2>&1
    $msgs = $raw | Out-String | ConvertFrom-Json
    $dur = @($msgs | ForEach-Object { if ($_ -match 'Duration: ([\d.]+) ms') { [double]$Matches[1] } })
    $init = @($msgs | Where-Object { $_ -match 'Init Duration' }).Count
    if ($dur.Count) { Summary "Lambda Duration (mọi request)" $dur; Write-Host "Cold start trong lượt đo: $init" }
    else { Write-Host "Không đọc được log (đã aws login và đặt AWS_PROFILE chưa?)" -ForegroundColor Yellow }
} catch { Write-Host "Không đọc được log: $($_.Exception.Message)" -ForegroundColor Yellow }
