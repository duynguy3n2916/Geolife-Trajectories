# Bước 8 của quy trình: gọi thử API (địa chỉ trong deploy\lookup\api_url.txt, bước 5) và so mã HTTP với mong đợi.
# Dùng Invoke-WebRequest của PowerShell thay cho curl.exe: trên một số máy Windows, curl.exe kẹt ở bước kiểm tra
# thu hồi chứng chỉ (schannel) và trả mã 000 dù API vẫn chạy.
# Cách chạy (từ thư mục Home_Office):  .\deploy\lookup\test.ps1
$url = (Get-Content "$PSScriptRoot\api_url.txt" -Raw).Trim()
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# Gọi GET và trả (mã HTTP, nội dung). Mã 4xx/5xx làm Invoke-WebRequest ném lỗi: lấy mã và nội dung từ lỗi đó.
function Get-Http([string]$Path) {
    try {
        $r = Invoke-WebRequest -Uri "$url$Path" -UseBasicParsing -TimeoutSec 30
        return @([int]$r.StatusCode, $r.Content)
    } catch {
        $resp = $_.Exception.Response
        if (-not $resp) { return @(0, $_.Exception.Message) }
        $body = (New-Object IO.StreamReader($resp.GetResponseStream())).ReadToEnd()
        return @([int]$resp.StatusCode, $body)
    }
}

$cases = @(
    @{ Path = "/health";                                           Want = 200 },
    @{ Path = "/v1/users/153/home-office";                         Want = 200 },
    @{ Path = "/v1/users/153/home-office?model_version=dbscan-v2"; Want = 200 },
    @{ Path = "/v1/users/153/home-office?model_version=nope";      Want = 422 },
    @{ Path = "/v1/users/999/home-office";                         Want = 404 }
)
foreach ($c in $cases) {
    $code, $body = Get-Http $c.Path
    $mark = if ($code -eq $c.Want) { "đúng" } else { "SAI (cần $($c.Want)): $body" }
    "{0,-55} HTTP {1}  {2}" -f $c.Path, $code, $mark
}
Write-Host "`nNội dung trả về cho user 153:"
(Get-Http "/v1/users/153/home-office")[1]
