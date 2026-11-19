# Demo canary (sau bước 8): gọi API nhiều lần rồi đếm mỗi bản Lambda (header X-Lambda-Version) trả lời bao nhiêu % và có bao nhiêu lỗi.
# Dùng khi demo canary (deploy/terraform/canary.tf): sau mỗi lần đổi canary_weight thì chạy lại để xem tỉ lệ thật.
# Cách chạy (từ thư mục Home_Office):
#   .\api\canary_check.ps1              100 lần, user 153
#   .\api\canary_check.ps1 -N 200 -User 128
#   .\api\canary_check.ps1 -NoAuth   khi đã tắt đăng nhập (auth_enabled = false)
#   .\api\canary_check.ps1 -AllUsers   canary MODEL theo user: gọi cả 182 user (000..181) 2 vòng, đếm bao nhiêu user
#                                     nhận model canary (header X-Canary) và kiểm tra mỗi user vòng 2 có giữ nguyên model không.
#                                     Cần token admin (mặc định admin@example.com) vì gọi user của người khác.
# Đọc địa chỉ API trong api\api_url.txt. Có đăng nhập: lấy token tài khoản admin một lần (api\auth.ps1),
# hỏi mật khẩu demo nếu chưa đặt $env:HO_DEMO_PASSWORD. Token sống 60 phút, đủ cho một lần chạy.
param([int]$N = 100, [string]$User = "153", [switch]$NoAuth, [string]$Email = "admin@example.com",
      [switch]$AllUsers, [int]$Users = 182)
. "$PSScriptRoot\auth.ps1"
$headers = @{}
if (-not $NoAuth) { $headers["Authorization"] = "Bearer " + (Get-IdToken $Email (Read-DemoPassword)) }

$base = (Get-Content "$PSScriptRoot\api_url.txt" -Raw).Trim()

# Đọc một header từ response lỗi (PowerShell 5.1 và 7 trả kiểu khác nhau).
function Get-ErrHeader($resp, [string]$name) {
    try { $v = $resp.Headers[$name]; if ($v) { return [string]$v } } catch {}
    try { return (@($resp.Headers.GetValues($name)) -join ",") } catch { return "?" }
}

# Gọi 1 user, trả status, model, canary. 404 = user không có nhà/công ty (16 user), không tính là lỗi.
function Invoke-One([string]$u) {
    $o = [pscustomobject]@{ User = $u; Status = 0; Model = "?"; Canary = "?" }
    try {
        $r = Invoke-WebRequest -Uri "$base/v1/users/$u/home-office" -Headers $headers -UseBasicParsing -TimeoutSec 30
        $o.Status = [int]$r.StatusCode; $o.Model = [string]$r.Headers["X-Model-Version"]; $o.Canary = [string]$r.Headers["X-Canary"]
    } catch {
        $resp = $_.Exception.Response
        if ($resp) {
            $o.Status = [int]$resp.StatusCode
            $o.Model = Get-ErrHeader $resp "X-Model-Version"; $o.Canary = Get-ErrHeader $resp "X-Canary"
        }
    }
    return $o
}

if ($AllUsers) {
    $ids = 0..($Users - 1) | ForEach-Object { "{0:D3}" -f $_ }
    $round = @{}
    foreach ($k in 1, 2) {
        Write-Host "Vòng ${k}: gọi $($ids.Count) user..."
        $round[$k] = @($ids | ForEach-Object { Invoke-One $_ })
    }
    $r1 = $round[1]; $r2 = $round[2]
    $ok = @($r1 | Where-Object { $_.Status -in 200, 404 })
    Write-Host ""
    Write-Host "Vòng 1, theo model (200 = có kết quả, 404 = user không có nhà/công ty):" -ForegroundColor Cyan
    $ok | Group-Object Model, Canary | Sort-Object Name | ForEach-Object {
        $g = $_.Group
        "{0,-14} X-Canary={1,-5} {2,4} user ({3,5:P0})   200: {4}  404: {5}" -f $g[0].Model, $g[0].Canary, $g.Count,
            ($g.Count / $ids.Count), @($g | Where-Object Status -eq 200).Count, @($g | Where-Object Status -eq 404).Count
    }
    $changed = @(for ($i = 0; $i -lt $ids.Count; $i++) {
        if ($r1[$i].Model -ne $r2[$i].Model -or $r1[$i].Canary -ne $r2[$i].Canary) { $r1[$i].User }
    })
    $canaryUsers = @($r1 | Where-Object Canary -eq "true" | Select-Object -ExpandProperty User)
    Write-Host ("User canary ({0}): {1}" -f $canaryUsers.Count, ($canaryUsers -join " "))
    Write-Host ("Đổi model giữa vòng 1 và vòng 2: {0} user {1}" -f $changed.Count, ($changed -join " ")) `
        -ForegroundColor $(if ($changed.Count) { "Red" } else { "Green" })
    $fail = @(($r1 + $r2) | Where-Object { $_.Status -notin 200, 404 })
    $codes = ($fail | Group-Object Status | ForEach-Object { "$($_.Name)×$($_.Count)" }) -join ", "
    Write-Host ("Lỗi (khác 200/404): {0}/{1} {2}" -f $fail.Count, (2 * $ids.Count), $codes) `
        -ForegroundColor $(if ($fail.Count) { "Red" } else { "Green" })
    return
}

$url = "$base/v1/users/$User/home-office"
$rows = @()
Write-Host "Gọi $N lần: $url"
for ($i = 1; $i -le $N; $i++) {
    $status = 0; $lv = "?"; $mv = "?"
    try {
        $r = Invoke-WebRequest -Uri $url -Headers $headers -UseBasicParsing -TimeoutSec 30
        $status = [int]$r.StatusCode
        $lv = $r.Headers["X-Lambda-Version"]; $mv = $r.Headers["X-Model-Version"]
    } catch {
        $resp = $_.Exception.Response
        if ($resp) {
            $status = [int]$resp.StatusCode
            if ($resp.Headers["X-Lambda-Version"]) { $lv = $resp.Headers["X-Lambda-Version"] }
        }
    }
    $rows += [pscustomobject]@{ LambdaVersion = $lv; ModelVersion = $mv; Ok = ($status -eq 200); Status = $status }
    if ($i % 20 -eq 0) { Write-Host "  đã gọi $i/$N" }
}

Write-Host ""
Write-Host "Theo bản Lambda trả lời (bản '?' là lỗi xảy ra trước khi Lambda kịp trả header):" -ForegroundColor Cyan
$rows | Group-Object LambdaVersion | Sort-Object Name | ForEach-Object {
    $ok = @($_.Group | Where-Object Ok).Count
    $models = (($_.Group | Where-Object Ok | Select-Object -ExpandProperty ModelVersion -Unique) -join ",")
    "{0,-8} {1,4} lần  ({2,5:P0})   thành công {3,4}   model: {4}" -f ("bản " + $_.Name), $_.Count, ($_.Count / $N), $ok, $models
}
$fail = @($rows | Where-Object { -not $_.Ok })
$codes = ($fail | Group-Object Status | ForEach-Object { "$($_.Name)×$($_.Count)" }) -join ", "
Write-Host ("Lỗi: {0}/{1} ({2:P0}) {3}" -f $fail.Count, $N, ($fail.Count / $N), $codes) -ForegroundColor $(if ($fail.Count) { "Red" } else { "Green" })
