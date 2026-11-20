# Bước 8 của quy trình: gọi thử API (địa chỉ trong api\api_url.txt, bước 5) và so mã HTTP với mong đợi.
# Có đăng nhập Cognito (deploy/terraform/cognito.tf): script đăng nhập 2 tài khoản demo (deploy\cognito_users.ps1)
# rồi thử: không token -> 401, token giả -> 401, đúng user -> 200, user khác -> 403, admin -> 200 với mọi user.
# Dùng Invoke-WebRequest của PowerShell thay cho curl.exe: trên một số máy Windows, curl.exe kẹt ở bước kiểm tra
# thu hồi chứng chỉ (schannel) và trả mã 000 dù API vẫn chạy.
# Cách chạy (từ thư mục Home_Office):
#   .\api\test.ps1            có đăng nhập (hỏi mật khẩu demo, hoặc đặt trước $env:HO_DEMO_PASSWORD)
#   .\api\test.ps1 -NoAuth    khi đã tắt đăng nhập (auth_enabled = false)
param([switch]$NoAuth)
$url = (Get-Content "$PSScriptRoot\api_url.txt" -Raw).Trim()
. "$PSScriptRoot\auth.ps1"

# Gọi GET và trả (mã HTTP, nội dung). Mã 4xx/5xx làm Invoke-WebRequest ném lỗi: lấy mã và nội dung từ lỗi đó.
function Get-Http([string]$Path, [string]$Token = "") {
    $h = @{}
    if ($Token) { $h["Authorization"] = "Bearer $Token" }
    try {
        $r = Invoke-WebRequest -Uri "$url$Path" -Headers $h -UseBasicParsing -TimeoutSec 30
        return @([int]$r.StatusCode, $r.Content)
    } catch {
        $resp = $_.Exception.Response
        if (-not $resp) { return @(0, $_.Exception.Message) }
        $body = (New-Object IO.StreamReader($resp.GetResponseStream())).ReadToEnd()
        return @([int]$resp.StatusCode, $body)
    }
}

if ($NoAuth) {
    $t153 = ""; $tAdmin = ""
    $cases = @(
        @{ Path = "/health";                                           Want = 200 },
        @{ Path = "/v1/users/153/home-office";                         Want = 200 },
        @{ Path = "/v1/users/153/home-office?model_version=dbscan-v2"; Want = 200 },
        @{ Path = "/v1/users/153/home-office?model_version=nope";      Want = 422 },
        @{ Path = "/v1/users/999/home-office";                         Want = 404 }
    )
} else {
    $pw = Read-DemoPassword
    $t153 = Get-IdToken "user153@example.com" $pw
    $tAdmin = Get-IdToken "admin@example.com" $pw
    $cases = @(
        @{ Who = "không token"; Path = "/health";                                           Want = 200 },
        @{ Who = "không token"; Path = "/v1/users/153/home-office";                         Want = 401 },
        @{ Who = "token giả";   Path = "/v1/users/153/home-office";                         Want = 401; Token = "abc.def.ghi" },
        @{ Who = "user153";     Path = "/v1/users/153/home-office";                         Want = 200; Token = $t153 },
        @{ Who = "user153";     Path = "/v1/users/153/home-office?model_version=dbscan-v2"; Want = 200; Token = $t153 },
        @{ Who = "user153";     Path = "/v1/users/153/home-office?model_version=nope";      Want = 422; Token = $t153 },
        @{ Who = "user153";     Path = "/v1/users/002/home-office";                         Want = 403; Token = $t153 },
        @{ Who = "user153";     Path = "/v1/users/999/home-office";                         Want = 403; Token = $t153 },
        @{ Who = "admin";       Path = "/v1/users/002/home-office";                         Want = 200; Token = $tAdmin },
        @{ Who = "admin";       Path = "/v1/users/999/home-office";                         Want = 404; Token = $tAdmin }
    )
}
foreach ($c in $cases) {
    $code, $body = Get-Http $c.Path $c.Token
    $mark = if ($code -eq $c.Want) { "đúng" } else { "SAI (cần $($c.Want)): $body" }
    "{0,-12} {1,-52} HTTP {2}  {3}" -f $c.Who, $c.Path, $code, $mark
}
Write-Host "`nNội dung trả về cho user 153:"
(Get-Http "/v1/users/153/home-office" $t153)[1]
