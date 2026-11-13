# Đo user lớn nhất với dbscan-v2 ở nhiều mức RAM (một lần cold, một lần ấm) để xem thời gian phụ thuộc RAM thế nào.
# Cách chạy (từ thư mục Home_Office):  .\deploy\bench\mem_sweep.ps1    Cuối script đặt lại 2048 MB.
. "$PSScriptRoot\bench_common.ps1"
$big = $Users[-1]
foreach ($mem in 1024, 2048, 3008) {
    Write-Step "RAM $mem MB"
    Set-Cold $mem ("mem{0}-{1}" -f $mem, (Get-Date -Format "HHmmss"))
    Invoke-Fn $big "dbscan-v2"
    Invoke-Fn $big "dbscan-v2"
}
Set-Cold 2048 "reset"
Write-Host "Xong. Kết quả: $Csv"
