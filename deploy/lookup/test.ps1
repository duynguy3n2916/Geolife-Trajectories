# Gọi thử API sau khi chạy deploy\lookup\deploy.ps1 (đọc địa chỉ trong deploy\lookup\api_url.txt) và in mã HTTP.
# Cách chạy (từ thư mục Home_Office):  .\deploy\lookup\test.ps1
$url = (Get-Content "$PSScriptRoot\api_url.txt" -Raw).Trim()
$cases = @(
    @{ Path = "/health";                                           Want = "200" },
    @{ Path = "/v1/users/153/home-office";                         Want = "200" },
    @{ Path = "/v1/users/153/home-office?model_version=dbscan-v2"; Want = "200" },
    @{ Path = "/v1/users/153/home-office?model_version=nope";      Want = "422" },
    @{ Path = "/v1/users/999/home-office";                         Want = "404" }
)
foreach ($c in $cases) {
    $code = & curl.exe -s -o NUL -w "%{http_code}" "$url$($c.Path)"
    $mark = if ($code -eq $c.Want) { "đúng" } else { "SAI (cần $($c.Want))" }
    "{0,-55} HTTP {1}  {2}" -f $c.Path, $code, $mark
}
Write-Host "`nNội dung trả về cho user 153:"
& curl.exe -s -i "$url/v1/users/153/home-office"
Write-Host ""
