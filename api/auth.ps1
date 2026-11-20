# Hàm lấy token Cognito, dùng chung cho api\get_token.ps1, api\test.ps1, api\canary_check.ps1. Không chạy trực tiếp.
# Gọi thẳng API công khai của Cognito (InitiateAuth, USER_PASSWORD_AUTH): không cần AWS CLI hay đăng nhập AWS,
# giống app thật đăng nhập bằng email + mật khẩu.
# Client id đọc từ api\cognito_client_id.txt, ghi sau terraform apply (trong deploy\terraform):
#   terraform output -raw cognito_client_id | Set-Content -Encoding ascii ..\..\api\cognito_client_id.txt
$CognitoRegion = "ap-southeast-1"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Test-AuthConfigured { Test-Path "$PSScriptRoot\cognito_client_id.txt" }

function Get-ClientId {
    $f = "$PSScriptRoot\cognito_client_id.txt"
    if (-not (Test-Path $f)) {
        throw "Chưa có api\cognito_client_id.txt. Trong deploy\terraform chạy: terraform output -raw cognito_client_id | Set-Content -Encoding ascii ..\..\api\cognito_client_id.txt"
    }
    (Get-Content $f -Raw).Trim()
}

# Mật khẩu tài khoản demo: $env:HO_DEMO_PASSWORD nếu có, không thì hỏi (không hiện lên màn hình).
function Read-DemoPassword {
    if ($env:HO_DEMO_PASSWORD) { return $env:HO_DEMO_PASSWORD }
    $s = Read-Host "Mật khẩu tài khoản demo" -AsSecureString
    [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
}

# Đăng nhập, trả ID token (gửi lên API: Authorization: Bearer <token>). Token sống 60 phút.
# Dùng ID token vì chỉ ID token có claim custom:geolife_id (user GeoLife mà tài khoản được xem).
function Get-IdToken([string]$Email, [string]$Password) {
    $body = @{
        AuthFlow       = "USER_PASSWORD_AUTH"
        ClientId       = (Get-ClientId)
        AuthParameters = @{ USERNAME = $Email; PASSWORD = $Password }
    } | ConvertTo-Json -Depth 4
    try {
        $r = Invoke-WebRequest -Method Post -Uri "https://cognito-idp.$CognitoRegion.amazonaws.com/" -UseBasicParsing -TimeoutSec 30 `
            -ContentType "application/x-amz-json-1.1" -Body $body `
            -Headers @{ "X-Amz-Target" = "AWSCognitoIdentityProviderService.InitiateAuth" }
    } catch {
        $resp = $_.Exception.Response
        $msg = if ($resp) { (New-Object IO.StreamReader($resp.GetResponseStream())).ReadToEnd() } else { $_.Exception.Message }
        throw "Đăng nhập $Email thất bại: $msg"
    }
    # PowerShell 5.1 trả nội dung dạng byte khi không nhận ra loại nội dung (application/x-amz-json-1.1)
    $text = if ($r.Content -is [byte[]]) { [Text.Encoding]::UTF8.GetString($r.Content) } else { $r.Content }
    $res = ($text | ConvertFrom-Json)
    if (-not $res.AuthenticationResult) {
        throw "Đăng nhập $Email chưa xong (Cognito yêu cầu $($res.ChallengeName)). Chạy lại .\deploy\cognito_users.ps1 để đặt mật khẩu chính thức."
    }
    $res.AuthenticationResult.IdToken
}
