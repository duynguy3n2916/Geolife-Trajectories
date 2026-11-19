# Demo canary model theo người dùng (deploy/terraform/canary.tf): gọi cả 182 user (000..181) 2 vòng, đếm bao nhiêu user
# nhận mỗi model (header X-Model-Version, X-Canary), và kiểm tra mỗi user ở vòng 2 có giữ nguyên model không (phải là 0 user đổi).
# Nếu deploy/terraform/canary.auto.tfvars có canary_users (api/pick_canary_users.py), script so nhóm canary thật với danh sách đó.
# Chạy lại sau mỗi lần đổi canary_percent / canary_users. Khi bật canary_simulate_error: user canary trả 500, script liệt kê các user lỗi.
# Cách chạy (từ thư mục Home_Office):
#   .\api\canary_check.ps1
#   .\api\canary_check.ps1 -NoAuth   khi đã tắt đăng nhập (auth_enabled = false)
# Đọc địa chỉ API trong api\api_url.txt. Có đăng nhập: lấy token tài khoản admin một lần (api\auth.ps1), vì gọi user
# của người khác; hỏi mật khẩu demo nếu chưa đặt $env:HO_DEMO_PASSWORD. Token sống 60 phút, đủ cho một lần chạy.
param([switch]$NoAuth, [string]$Email = "admin@example.com", [int]$Users = 182)
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
# So với canary_users trong tfvars (nếu có). Lưu ý: tfvars là file trên máy, chỉ đúng với Lambda khi đã terraform apply.
$tfvars = Join-Path $PSScriptRoot "..\deploy\terraform\canary.auto.tfvars"
$m = if (Test-Path $tfvars) { Select-String -Path $tfvars -Pattern '^\s*canary_users\s*=\s*\[(.*)\]' | Select-Object -First 1 } else { $null }
$listed = if ($m) { @([regex]::Matches($m.Matches[0].Groups[1].Value, '"([^"]+)"') | ForEach-Object { $_.Groups[1].Value }) } else { @() }
if ($listed.Count) {
    $missing = @($listed | Where-Object { $_ -notin $canaryUsers })
    $extra = @($canaryUsers | Where-Object { $_ -notin $listed })
    Write-Host ("So với canary_users trong tfvars ({0} user): thiếu {1} {2}; thừa {3} {4}" -f $listed.Count,
        $missing.Count, ($missing -join " "), $extra.Count, ($extra -join " ")) `
        -ForegroundColor $(if ($missing.Count -or $extra.Count) { "Red" } else { "Green" })
}
Write-Host ("Đổi model giữa vòng 1 và vòng 2: {0} user {1}" -f $changed.Count, ($changed -join " ")) `
    -ForegroundColor $(if ($changed.Count) { "Red" } else { "Green" })
$fail = @(($r1 + $r2) | Where-Object { $_.Status -notin 200, 404 })
$failUsers = @($fail | Select-Object -ExpandProperty User -Unique)
$codes = ($fail | Group-Object Status | ForEach-Object { "$($_.Name)×$($_.Count)" }) -join ", "
Write-Host ("Lỗi (khác 200/404): {0}/{1} {2}" -f $fail.Count, (2 * $ids.Count), $codes) `
    -ForegroundColor $(if ($fail.Count) { "Red" } else { "Green" })
if ($failUsers.Count) { Write-Host ("User bị lỗi ({0}): {1}" -f $failUsers.Count, ($failUsers -join " ")) -ForegroundColor Red }
