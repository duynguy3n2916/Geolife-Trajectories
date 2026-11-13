# Measure heuristic-v1 and dbscan-v2 for every user (ascending size) at 2048 MB. Results go to deploy/bench/results/results.csv.
. "$PSScriptRoot\..\common.ps1"
foreach ($model in "heuristic-v1", "dbscan-v2") {
    Write-Host "=== $model (new container = cold start on the first call) ==="
    Set-Cold 2048 ("{0}-{1}" -f $model, (Get-Date -Format "HHmmss"))
    foreach ($u in $Users) { Invoke-Fn $u $model }
    Invoke-Fn $Users[-1] $model
}
Write-Host "Done. Results: $Csv"
