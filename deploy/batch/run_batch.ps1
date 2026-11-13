# Bước 6 của quy trình: gọi Lambda batch cho mọi cặp (user, model) và theo dõi kết quả.
# Mỗi lần gọi Lambda xử lý một user với một model và ghi s3://<bucket>/results/<model>/<user>.json.
#
# Hai cách gọi:
#   - Đồng bộ (mặc định): máy bạn mở tối đa -Concurrency lần gọi cùng lúc và chờ từng lần trả lời,
#     nên biết ngay lần nào lỗi (thử lại một lần). Phải để cửa sổ mở đến khi xong.
#   - Bất đồng bộ (-Async): chỉ gửi yêu cầu (mỗi yêu cầu dưới 1 giây) rồi Lambda tự chạy; lỗi thì Lambda tự thử lại,
#     lỗi hẳn thì vào hàng đợi $Dlq. Tắt máy cũng được. Hàng đợi và cấu hình thử lại do Terraform tạo (deploy\terraform).
#     Ở cách này mọi user đều có file (kể cả không ra home/office) để đếm được đủ số user.
#
# Cách chạy (từ thư mục Home_Office):
#   .\deploy\batch\run_batch.ps1 -OnlyUsers 153,128 -DryRun     thử 2 user, không ghi S3
#   .\deploy\batch\run_batch.ps1                                115 user validation × 2 model
#   .\deploy\batch\run_batch.ps1 -Async                         như trên, gọi bất đồng bộ
#   .\deploy\batch\run_batch.ps1 -Model dbscan-v2               chỉ một model
#   .\deploy\batch\run_batch.ps1 -Group test                    tập test: chỉ chạy MỘT lần (D19), script hỏi xác nhận
# Log: deploy\batch\runs\run_<giờ>\runs.csv (mỗi lần gọi một dòng) và các file payload / phản hồi.
param(
    [string[]]$Model = @("heuristic-v1", "dbscan-v2"),
    [ValidateSet("validation", "test", "all")][string]$Group = "validation",
    [int]$Concurrency = 50,
    [string[]]$OnlyUsers,
    [switch]$DryRun,        # chạy pipeline nhưng không ghi S3
    [switch]$WriteEmpty,    # ghi cả file cho user không ra home/office (mặc định bỏ qua, API trả 404)
    [switch]$Async          # gọi bất đồng bộ; tự bật -WriteEmpty
)
. "$PSScriptRoot\..\common.ps1"
if ($Async) { $WriteEmpty = [switch]$true }

# ---- Chọn user từ data\split\users.csv (bỏ user bị loại) ----
$rows = Import-Csv "data/split/users.csv" | Where-Object { $_.excluded -ne "True" }
if ($Group -eq "validation") { $rows = $rows | Where-Object { $_.group -eq "val" } }
elseif ($Group -eq "test")   { $rows = $rows | Where-Object { $_.group -eq "test" } }
$users = @($rows | ForEach-Object { $_.user })
if ($OnlyUsers) {
    $want = $OnlyUsers | ForEach-Object { $_ -split "," } | Where-Object { $_ }
    $users = @($users | Where-Object { $want -contains $_ })
}
if (-not $users) { throw "Không có user nào khớp" }
if ($Group -ne "validation" -and -not $DryRun) {
    Write-Host "CẢNH BÁO: nhóm '$Group' có user TEST. Chạy tập test được tính là lần test duy nhất (D19)." -ForegroundColor Yellow
    if ((Read-Host "Gõ YES để tiếp tục") -ne "YES") { return }
}

# ---- Hàng đợi việc: user nhiều file chạy trước để việc dài bắt đầu sớm ----
$size = @{}; foreach ($r in $rows) { $size[$r.user] = [int]$r.n_files }
$users = @($users | Sort-Object { -$size[$_] })
$queue = New-Object System.Collections.Generic.Queue[object]
foreach ($m in $Model) { foreach ($u in $users) { $queue.Enqueue([pscustomobject]@{ User = $u; Model = $m; Try = 1 }) } }
$total = $queue.Count
$startUtc = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss")
Write-Host "Nhóm=$Group  user=$($users.Count)  model=$($Model -join ',')  lần gọi=$total  đồng thời=$Concurrency  dry_run=$DryRun  async=$Async"

$dir = "deploy/batch/runs/run_" + (Get-Date -Format "yyyyMMdd_HHmmss")
New-Item -ItemType Directory -Force $dir | Out-Null
$log = "$dir/runs.csv"
"user,model,try,status,wrote,home,office,n_points,total_s,peak_mb,error" | Out-File $log -Encoding ascii

# Bắt đầu một lần gọi: ghi payload ra file rồi chạy aws.exe ở tiến trình nền.
function Start-Invoke($job) {
    $name = "$($job.Model)_$($job.User)_$($job.Try)"
    $body = @{ user = $job.User; model = $job.Model }
    if ($DryRun) { $body.dry_run = $true }
    if ($WriteEmpty) { $body.write_empty = $true }
    $payload = Join-Path $PWD "$dir/$name.payload.json"
    [IO.File]::WriteAllText($payload, ($body | ConvertTo-Json -Compress))
    $resp = Join-Path $PWD "$dir/$name.resp.json"
    $cli = @("lambda", "invoke", "--function-name", $BatchFn, "--payload", "fileb://$payload", "--cli-read-timeout", "900",
             "--region", $Region, "--profile", $Profile)
    if ($Async) { $cli += @("--invocation-type", "Event") }
    $cli += $resp
    $p = Start-Process -FilePath "aws.exe" -ArgumentList $cli -NoNewWindow -PassThru `
        -RedirectStandardOutput "$dir/$name.out.txt" -RedirectStandardError "$dir/$name.err.txt"
    $null = $p.Handle    # giữ handle để đọc được ExitCode sau khi tiến trình kết thúc
    return [pscustomobject]@{ Job = $job; Proc = $p; Name = $name; Resp = $resp }
}

# Ghi nhận một lần gọi đã xong: ghi log, lỗi thì xếp lại để thử thêm một lần.
function Complete-Invoke($x) {
    $job = $x.Job; $r = $null; $err = ""
    $out = Get-Content "$dir/$($x.Name).out.txt" -Raw -ErrorAction SilentlyContinue
    if ($x.Proc.ExitCode -ne 0) { $err = ((Get-Content "$dir/$($x.Name).err.txt" -Raw) -replace "[\r\n,]+", " ").Trim() }
    elseif ($Async) { if ($out -notmatch '"StatusCode":\s*202') { $err = "AWS không nhận yêu cầu" } }
    else {
        try { $r = Get-Content $x.Resp -Raw | ConvertFrom-Json } catch { }
        if (-not $r) { $err = "không có phản hồi" }
        elseif ($r.errorMessage) { $err = (($r.errorType + ": " + $r.errorMessage) -replace "[\r\n,]+", " ") }
    }
    $script:done++
    if ($err) {
        "$($job.User),$($job.Model),$($job.Try),FAIL,,,,,,,$err" | Add-Content $log -Encoding ascii
        if ($job.Try -lt 2) { $queue.Enqueue([pscustomobject]@{ User = $job.User; Model = $job.Model; Try = 2 }); $script:total++ }
        else { $script:failed++ }
        $status = "LỖI $err"
    } elseif ($Async) {
        "$($job.User),$($job.Model),$($job.Try),queued,,,,,,," | Add-Content $log -Encoding ascii
        $status = "đã gửi"
    } else {
        "$($job.User),$($job.Model),$($job.Try),ok,$($r.wrote),$($r.home),$($r.office),$($r.n_points),$($r.total_s),$($r.peak_ram_mb_process)," | Add-Content $log -Encoding ascii
        $status = "ok"
    }
    Write-Host ("[{0}/{1}] {2} {3}: {4}" -f $script:done, $script:total, $job.Model, $job.User, $status)
}

# Đếm file kết quả được ghi từ lúc bắt đầu lần chạy này (không đếm file cũ).
function Get-NewResultCount([string]$M) {
    $n = Aws s3api list-objects-v2 --bucket $Bucket --prefix "results/$M/" --query "length(Contents[?LastModified>='$startUtc'] || ``[]``)" --output text
    if ($LASTEXITCODE -ne 0 -or -not $n -or $n -eq "None") { return 0 }
    return [int]$n
}

# ---- Vòng chính: luôn giữ tối đa $Concurrency lần gọi đang chạy ----
$running = @(); $done = 0; $failed = 0
while ($queue.Count -gt 0 -or $running.Count -gt 0) {
    while ($queue.Count -gt 0 -and $running.Count -lt $Concurrency) { $running += Start-Invoke ($queue.Dequeue()) }
    Start-Sleep -Seconds 2
    $still = @()
    foreach ($x in $running) { if ($x.Proc.HasExited) { Complete-Invoke $x } else { $still += $x } }
    $running = $still
}
Write-Host "Đã gửi xong. Lỗi sau khi thử lại: $failed. Log: $log"
if ($DryRun) { return }

# ---- Bất đồng bộ: chờ Lambda ghi đủ file (tối đa 20 phút; đóng cửa sổ cũng không sao) ----
if ($Async) {
    Write-Step "Chờ kết quả (mỗi 15 giây)"
    $dlqUrl = Aws sqs get-queue-url --queue-name $Dlq --query QueueUrl --output text 2>$null
    for ($i = 0; $i -lt 80; $i++) {
        $parts = @(); $all = $true
        foreach ($m in $Model) {
            $n = Get-NewResultCount $m
            $parts += "$m=$n/$($users.Count)"
            if ($n -lt $users.Count) { $all = $false }
        }
        $dlqText = ""
        if ($dlqUrl) { $dlqText = "  lỗi trong DLQ=" + (Aws sqs get-queue-attributes --queue-url $dlqUrl --attribute-names ApproximateNumberOfMessages --query Attributes.ApproximateNumberOfMessages --output text) }
        Write-Host ((Get-Date -Format "HH:mm:ss") + "  " + ($parts -join "  ") + $dlqText)
        if ($all) { break }
        Start-Sleep -Seconds 15
    }
}

# ---- Tổng kết và lưu biên bản lần chạy lên S3 ----
Write-Step "Tổng kết"
$counts = @{}
foreach ($m in $Model) {
    $counts[$m] = Get-NewResultCount $m
    Write-Host "results/$m/: $($counts[$m]) file được ghi trong lần chạy này (user không ra home/office không có file, trừ khi -WriteEmpty)"
}
$manifest = [ordered]@{ run_at = $startUtc + "Z"; group = $Group; users = $users.Count; models = $Model; async = [bool]$Async; written = $counts; failed = $failed }
$mf = Join-Path $PWD "$dir/manifest.json"
[IO.File]::WriteAllText($mf, ($manifest | ConvertTo-Json -Compress))
Aws s3 cp $mf "s3://$Bucket/results/_runs/$(Split-Path $dir -Leaf).json" --only-show-errors
