# Largest user with dbscan-v2 at several memory sizes (cold call, then warm call) to see how duration depends on memory.
. "$PSScriptRoot\..\common.ps1"
$big = $Users[-1]
foreach ($mem in 1024, 2048, 3008) {
    Write-Host "=== memory $mem MB ==="
    Set-Cold $mem ("mem{0}-{1}" -f $mem, (Get-Date -Format "HHmmss"))
    Invoke-Fn $big "dbscan-v2"
    Invoke-Fn $big "dbscan-v2"
}
Set-Cold 2048 "reset"
Write-Host "Done. Results: $Csv"
