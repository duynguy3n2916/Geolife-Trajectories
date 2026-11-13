# Hàm dùng chung cho các script đo thời gian và RAM của Lambda batch (thử nghiệm ngày 12/11, không thuộc quy trình deploy).
# Không chạy trực tiếp: measure.ps1 và mem_sweep.ps1 nạp file này.
# Kết quả đo ghi vào deploy\bench\results\results.csv.
. "$PSScriptRoot\..\common.ps1"

# User dùng để đo, xếp theo dung lượng GPS từ nhỏ đến lớn (đều thuộc tập validation; 153 lớn nhất).
$Users = "170", "155", "028", "167", "017", "153"

$Out = "deploy/bench/results"
New-Item -ItemType Directory -Force $Out | Out-Null
$Csv = "$Out/results.csv"
if (-not (Test-Path $Csv)) {
    "run,user,model,cold,n_points,n_stays,total_s,download_s,proc_peak_mb,duration_ms,billed_ms,mem_size_mb,max_mem_mb,init_ms,error" | Out-File $Csv -Encoding ascii
}
$global:RunNo = 0

# Lấy số đầu tiên khớp mẫu regex trong một dòng log.
function Get-Num($Text, $Pattern) { if ($Text -match $Pattern) { return $Matches[1] } else { return "" } }

# Buộc Lambda dùng container mới (lần gọi sau là cold start) và đặt dung lượng RAM.
function Set-Cold($Memory, $Tag) {
    Aws lambda update-function-configuration --function-name $BatchFn --memory-size $Memory `
        --environment "Variables={BUCKET=$Bucket,COLD_TAG=$Tag}" | Out-Null
    Assert-Ok "update-function-configuration"
    Aws lambda wait function-updated-v2 --function-name $BatchFn
}

# Gọi đồng bộ một lần (dry_run: không ghi kết quả), in một dòng tóm tắt và thêm một dòng vào results.csv.
function Invoke-Fn($User, $Model) {
    $global:RunNo++
    $payload = "$Out/payload.json"
    [IO.File]::WriteAllText((Join-Path $PWD $payload), ('{"user":"' + $User + '","model":"' + $Model + '","dry_run":true}'))
    $resp = "$Out/resp_${User}_${Model}_$($global:RunNo).json"
    $b64 = Aws lambda invoke --function-name $BatchFn --payload "fileb://$payload" --cli-read-timeout 900 --log-type Tail --query LogResult --output text $resp
    $log = ""
    try { $log = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String(($b64 -join ""))) } catch { }
    $rep = ($log -split "`n" | Where-Object { $_ -match "^REPORT" } | Select-Object -Last 1)   # dòng REPORT: thời gian, RAM, cold start
    $dur    = Get-Num $rep '\tDuration: ([\d.]+) ms'
    $billed = Get-Num $rep 'Billed Duration: (\d+) ms'
    $msize  = Get-Num $rep 'Memory Size: (\d+) MB'
    $mmax   = Get-Num $rep 'Max Memory Used: (\d+) MB'
    $init   = Get-Num $rep 'Init Duration: ([\d.]+) ms'
    $r = $null; $err = ""
    try { $r = Get-Content $resp -Raw | ConvertFrom-Json } catch { $err = "không đọc được phản hồi" }
    if ($r -and $r.errorMessage) { $err = (($r.errorType + ": " + $r.errorMessage) -replace ",", ";") }
    $row = @($global:RunNo, $User, $Model, $r.cold_start, $r.n_points, $r.n_stays, $r.total_s, $r.seconds.download, $r.peak_ram_mb_process, $dur, $billed, $msize, $mmax, $init, $err) -join ","
    Add-Content $Csv $row -Encoding ascii
    Write-Host ("user {0} {1}: điểm={2} thời gian={3} ms RAM={4} MB init={5} ms {6}" -f $User, $Model, $r.n_points, $dur, $mmax, $init, $err)
    if ($err) { Write-Host $rep }
}
