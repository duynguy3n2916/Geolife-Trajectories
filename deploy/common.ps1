# Shared settings and helpers for the deploy scripts. Run the scripts from the Home_Office folder.
$Region  = "ap-southeast-1"
$Profile = "home-office"
$Acct    = (aws sts get-caller-identity --profile $Profile --query Account --output text)
if ($LASTEXITCODE -ne 0 -or -not $Acct) { throw "Not logged in. Run: aws login --profile $Profile --region $Region" }
$Bucket  = "home-office-lambda-sg-$Acct"
$Repo    = "home-office-lambda"
$Image   = "$Acct.dkr.ecr.$Region.amazonaws.com/${Repo}:v1"
$Fn      = "home-office-test"
$Role    = "home-office-lambda-role"
# Users to measure, ordered by raw size (small -> large). All are in the validation group.
$Users   = "170", "155", "028", "167", "017", "153"

function Aws { & aws.exe @args --region $Region --profile $Profile }

$Out = "deploy/bench/results"
New-Item -ItemType Directory -Force $Out | Out-Null
$Csv = "$Out/results.csv"
if (-not (Test-Path $Csv)) {
    "run,user,model,cold,n_points,n_stays,total_s,download_s,proc_peak_mb,duration_ms,billed_ms,mem_size_mb,max_mem_mb,init_ms,error" | Out-File $Csv -Encoding ascii
}
$global:RunNo = 0

function Get-Num($text, $pattern) {
    if ($text -match $pattern) { return $Matches[1] } else { return "" }
}

# Force a new Lambda container (cold start) and set the memory size.
function Set-Cold($memory, $tag) {
    Aws lambda update-function-configuration --function-name $Fn --memory-size $memory --environment "Variables={BUCKET=$Bucket,COLD_TAG=$tag}" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "update-function-configuration failed" }
    Aws lambda wait function-updated-v2 --function-name $Fn
}

# One synchronous invocation. Prints a summary line and appends a row to results.csv.
function Invoke-Fn($user, $model) {
    $global:RunNo++
    $payload = "$Out/payload.json"
    [IO.File]::WriteAllText((Join-Path $PWD $payload), ('{"user":"' + $user + '","model":"' + $model + '"}'))
    $resp = "$Out/resp_${user}_${model}_$($global:RunNo).json"
    $b64 = Aws lambda invoke --function-name $Fn --payload "fileb://$payload" --cli-read-timeout 900 --log-type Tail --query LogResult --output text $resp
    $log = ""
    try { $log = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String(($b64 -join ""))) } catch { }
    $rep = ($log -split "`n" | Where-Object { $_ -match "^REPORT" } | Select-Object -Last 1)
    $dur    = Get-Num $rep '\tDuration: ([\d.]+) ms'
    $billed = Get-Num $rep 'Billed Duration: (\d+) ms'
    $msize  = Get-Num $rep 'Memory Size: (\d+) MB'
    $mmax   = Get-Num $rep 'Max Memory Used: (\d+) MB'
    $init   = Get-Num $rep 'Init Duration: ([\d.]+) ms'
    $r = $null; $err = ""
    try { $r = Get-Content $resp -Raw | ConvertFrom-Json } catch { $err = "cannot read response" }
    if ($r -and $r.errorMessage) { $err = (($r.errorType + ": " + $r.errorMessage) -replace ",", ";") }
    $row = @($global:RunNo, $user, $model, $r.cold_start, $r.n_points, $r.n_stays, $r.total_s, $r.seconds.download, $r.peak_ram_mb_process, $dur, $billed, $msize, $mmax, $init, $err) -join ","
    Add-Content $Csv $row -Encoding ascii
    Write-Host ("user {0} {1}: points={2} duration={3} ms max_mem={4} MB init={5} ms {6}" -f $user, $model, $r.n_points, $dur, $mmax, $init, $err)
    if ($err) { Write-Host $rep }
}
