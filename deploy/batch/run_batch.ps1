param(
    [string[]]$Model = @("heuristic-v1", "dbscan-v2"),
    [ValidateSet("validation", "test", "all")][string]$Group = "validation",
    [int]$Concurrency = 10,
    [switch]$DryRun,        # run the pipeline but do not write results to S3
    [switch]$WriteEmpty,    # also write a file for users with no home/office
    [switch]$Async,         # fire-and-forget (invocation-type Event): Lambda runs on its own, you can close this window. Implies -WriteEmpty
    [string[]]$OnlyUsers    # run only these users (e.g. -OnlyUsers 153,128)
)
# Run the batch Lambda for every user x model, at most $Concurrency invocations at a time (account limit is 10).
# Run from the Home_Office folder:  .\deploy\batch\run_batch.ps1 -Group validation
. "$PSScriptRoot\..\common.ps1"

if ($Async) { $WriteEmpty = [switch]$true }
$rows = Import-Csv "data/split/users.csv" | Where-Object { $_.excluded -ne "True" }
if ($Group -eq "validation") { $rows = $rows | Where-Object { $_.group -eq "val" } }
elseif ($Group -eq "test")   { $rows = $rows | Where-Object { $_.group -eq "test" } }
$users = @($rows | ForEach-Object { $_.user })
if ($OnlyUsers) { $users = @($users | Where-Object { $OnlyUsers -contains $_ }) }

if ($Group -ne "validation" -and -not $DryRun) {
    Write-Host "WARNING: group '$Group' includes TEST users. Results on the test group count as the single test run (D19)." -ForegroundColor Yellow
    if ((Read-Host "Type YES to continue") -ne "YES") { return }
}

# Largest users first so the long jobs start early
$size = @{}
foreach ($r in $rows) { $size[$r.user] = [int]$r.n_files }
$users = @($users | Sort-Object { -$size[$_] })
$jobs = New-Object System.Collections.Generic.Queue[object]
foreach ($m in $Model) { foreach ($u in $users) { $jobs.Enqueue([pscustomobject]@{ User = $u; Model = $m; Try = 1 }) } }
$total = $jobs.Count
Write-Host "Group=$Group  users=$($users.Count)  models=$($Model -join ',')  invocations=$total  concurrency=$Concurrency  dry_run=$DryRun"

$dir = "deploy/batch/runs/run_" + (Get-Date -Format "yyyyMMdd_HHmmss")
New-Item -ItemType Directory -Force $dir | Out-Null
$log = "$dir/runs.csv"
"user,model,try,status,wrote,home,office,n_points,total_s,peak_mb,error" | Out-File $log -Encoding ascii

$running = @()
$done = 0; $failed = 0
function Start-Job1($j) {
    $name = "$($j.Model)_$($j.User)_$($j.Try)"
    $pl = Join-Path $PWD "$dir/$name.payload.json"
    $ev = '{"user":"' + $j.User + '","model":"' + $j.Model + '"'
    if ($DryRun) { $ev += ',"dry_run":true' }
    if ($WriteEmpty) { $ev += ',"write_empty":true' }
    [IO.File]::WriteAllText($pl, $ev + '}')
    $resp = Join-Path $PWD "$dir/$name.resp.json"
    $al = @("lambda", "invoke", "--function-name", $Fn, "--payload", "fileb://$pl", "--cli-read-timeout", "900",
            "--region", $Region, "--profile", $Profile)
    if ($Async) { $al += @("--invocation-type", "Event") }
    $al += $resp
    $p = Start-Process -FilePath "aws.exe" -ArgumentList $al -NoNewWindow -PassThru -RedirectStandardOutput "$dir/$name.out.txt" -RedirectStandardError "$dir/$name.err.txt"
    $null = $p.Handle   # keep the handle so ExitCode is available after exit
    return [pscustomobject]@{ Job = $j; Proc = $p; Resp = $resp; Err = "$dir/$name.err.txt"; Name = $name }
}

function Finish-Job($x) {
    $j = $x.Job; $r = $null; $err = ""
    try { $r = Get-Content $x.Resp -Raw | ConvertFrom-Json } catch { }
    if ($Async -and $x.Proc.ExitCode -eq 0 -and ((Get-Content "$dir/$($x.Name).out.txt" -Raw) -match '"StatusCode":\s*202')) {
        "$($j.User),$($j.Model),$($j.Try),QUEUED,,,,,,," | Add-Content $log -Encoding ascii
        $script:done++
        Write-Host ("[{0}/{1}] {2} {3}: queued" -f $script:done, $total, $j.Model, $j.User)
        return
    }
    if ($x.Proc.ExitCode -ne 0) { $err = ((Get-Content $x.Err -Raw) -replace "[\r\n,]+", " ").Trim() }
    elseif (-not $r) { $err = "no response" }
    elseif ($r.errorMessage) { $err = (($r.errorType + ": " + $r.errorMessage) -replace "[\r\n,]+", " ") }
    $ok = ($err -eq "")
    if ($ok) {
        "$($j.User),$($j.Model),$($j.Try),ok,$($r.wrote),$($r.home),$($r.office),$($r.n_points),$($r.total_s),$($r.peak_ram_mb_process)," | Add-Content $log -Encoding ascii
    } else {
        "$($j.User),$($j.Model),$($j.Try),FAIL,,,,,,,$err" | Add-Content $log -Encoding ascii
        if ($j.Try -lt 2) { $jobs.Enqueue([pscustomobject]@{ User = $j.User; Model = $j.Model; Try = $j.Try + 1 }) }   # retry once (e.g. throttled)
        else { $script:failed++ }
    }
    $script:done++
    Write-Host ("[{0}/{1}] {2} {3}: {4}" -f $script:done, $total, $j.Model, $j.User, $(if ($ok) { "ok" } else { "FAIL " + $err }))
}

while ($jobs.Count -gt 0 -or $running.Count -gt 0) {
    while ($jobs.Count -gt 0 -and $running.Count -lt $Concurrency) { $running += Start-Job1 ($jobs.Dequeue()) }
    Start-Sleep -Seconds 2
    $still = @()
    foreach ($x in $running) {
        if ($x.Proc.HasExited) { Finish-Job $x } else { $still += $x }
    }
    $running = $still
}

Write-Host "Finished sending. Failed after retry: $failed. Log: $log"
if ($Async -and -not $DryRun) {
    Write-Host "Lambda is now running on its own. Waiting for results (you may close this window; re-check later with the s3 ls command in the instructions)."
    $dlq = (Aws sqs get-queue-url --queue-name home-office-batch-dlq --query QueueUrl --output text 2>$null)
    for ($i = 0; $i -lt 80; $i++) {
        $line = @()
        $all = $true
        foreach ($m in $Model) {
            $n = (Aws s3 ls "s3://$Bucket/results/$m/" | Measure-Object).Count
            $line += "$m=$n/$($users.Count)"
            if ($n -lt $users.Count) { $all = $false }
        }
        $dn = ""
        if ($dlq) { $dn = " DLQ=" + (Aws sqs get-queue-attributes --queue-url $dlq --attribute-names ApproximateNumberOfMessages --query Attributes.ApproximateNumberOfMessages --output text) }
        Write-Host ((Get-Date -Format "HH:mm:ss") + "  " + ($line -join "  ") + $dn)
        if ($all) { break }
        Start-Sleep -Seconds 15
    }
}
if (-not $DryRun) {
    foreach ($m in $Model) {
        $n = (Aws s3 ls "s3://$Bucket/results/$m/" | Measure-Object).Count
        Write-Host "results/$m/ has $n files (users with no home/office are skipped unless -WriteEmpty)"
    }
    $mf = '{"run_at":"' + (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ") + '","group":"' + $Group + '","users":' + $users.Count + ',"models":["' + ($Model -join '","') + '"]}'
    $mp = Join-Path $dir "_manifest.json"; [IO.File]::WriteAllText((Join-Path $PWD $mp), $mf)
    Aws s3 cp $mp "s3://$Bucket/results/_manifest.json" --only-show-errors
}
