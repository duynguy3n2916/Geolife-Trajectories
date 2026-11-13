# Upload the Trajectory folders of the measured users to the S3 bucket (safe to re-run: sync skips files already uploaded).
. "$PSScriptRoot\..\common.ps1"
aws configure set default.s3.max_concurrent_requests 50 --profile $Profile
Aws s3api head-bucket --bucket $Bucket 2>$null
if ($LASTEXITCODE -ne 0) {
    Aws s3 mb "s3://$Bucket"
    if ($LASTEXITCODE -ne 0) { throw "Cannot create bucket $Bucket (check the region policy)" }
}
foreach ($u in $Users) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    Write-Host "== user $u"
    Aws s3 sync "data\raw\geolife\Data\$u\Trajectory" "s3://$Bucket/geolife/Data/$u/Trajectory"
    Write-Host ("   done in {0:N0} s" -f $sw.Elapsed.TotalSeconds)
}
Write-Host "== file counts in the bucket"
foreach ($u in $Users) {
    $n = (Aws s3 ls "s3://$Bucket/geolife/Data/$u/Trajectory/" --summarize | Select-Object -Last 2) -join " | "
    Write-Host "user ${u}: $n"
}
