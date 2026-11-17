# Demo canary (sau bước 8): gọi API nhiều lần rồi đếm mỗi bản Lambda (header X-Lambda-Version) trả lời bao nhiêu % và có bao nhiêu lỗi.
# Dùng khi demo canary (deploy/terraform/canary.tf): sau mỗi lần đổi canary_weight thì chạy lại để xem tỉ lệ thật.
# Cách chạy (từ thư mục Home_Office):
#   .\api\canary_check.ps1              100 lần, user 153
#   .\api\canary_check.ps1 -N 200 -User 128
# Đọc địa chỉ API trong api\api_url.txt.
param([int]$N = 100, [string]$User = "153")

$url = (Get-Content "$PSScriptRoot\api_url.txt" -Raw).Trim() + "/v1/users/$User/home-office"
$rows = @()
Write-Host "Gọi $N lần: $url"
for ($i = 1; $i -le $N; $i++) {
    $status = 0; $lv = "?"; $mv = "?"
    try {
        $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 30
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
