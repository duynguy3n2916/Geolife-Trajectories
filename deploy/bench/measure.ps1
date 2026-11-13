# Đo heuristic-v1 và dbscan-v2 cho các user trong $Users (nhỏ đến lớn) ở 2048 MB. Không ghi kết quả home/office.
# Cách chạy (từ thư mục Home_Office):  .\deploy\bench\measure.ps1      Kết quả: deploy\bench\results\results.csv
. "$PSScriptRoot\bench_common.ps1"
foreach ($model in "heuristic-v1", "dbscan-v2") {
    Write-Step "$model (container mới: lần gọi đầu là cold start)"
    Set-Cold 2048 ("{0}-{1}" -f $model, (Get-Date -Format "HHmmss"))
    foreach ($u in $Users) { Invoke-Fn $u $model }
    Invoke-Fn $Users[-1] $model          # gọi lại user lớn nhất khi container đã ấm
}
Write-Host "Xong. Kết quả: $Csv"
