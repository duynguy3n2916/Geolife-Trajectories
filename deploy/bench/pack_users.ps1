# Pack each user's Trajectory folder into ONE .tar.gz and upload it (far fewer requests than thousands of small files).
# Usage (from the Home_Office folder):  powershell -ExecutionPolicy Bypass -File deploy\bench\pack_users.ps1 167 017 153
param([Parameter(ValueFromRemainingArguments = $true)] [string[]]$PackUsers)
. "$PSScriptRoot\..\common.ps1"
if (-not $PackUsers) { throw "Give the user ids, e.g. 167 017 153" }
New-Item -ItemType Directory -Force "deploy/bench/pack" | Out-Null
foreach ($u in $PackUsers) {
    $tgz = "deploy/bench/pack/$u.tar.gz"
    Write-Host "== user ${u}: packing"
    tar -czf $tgz -C "data\raw\geolife\Data\$u\Trajectory" .
    if ($LASTEXITCODE -ne 0) { throw "tar failed for $u" }
    Write-Host ("   {0:N1} MB; uploading" -f ((Get-Item $tgz).Length / 1MB))
    $sw = [Diagnostics.Stopwatch]::StartNew()
    Aws s3 cp $tgz "s3://$Bucket/geolife/Data/$u.tar.gz"
    Write-Host ("   uploaded in {0:N0} s" -f $sw.Elapsed.TotalSeconds)
}
