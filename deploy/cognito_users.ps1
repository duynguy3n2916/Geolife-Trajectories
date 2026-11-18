# Tạo (hoặc cập nhật) 3 tài khoản demo trong Cognito User Pool home-office-users (deploy/terraform/cognito.tf):
#   user002@example.com  -> chỉ xem user 002          (custom:geolife_id = 002)
#   user153@example.com  -> chỉ xem user 153          (custom:geolife_id = 153)
#   admin@example.com    -> nhóm admin, xem mọi user
# @example.com là tên miền dành riêng cho ví dụ: không ai nhận thư, và Cognito không gửi thư (--message-action SUPPRESS).
# Cả 3 tài khoản dùng chung một mật khẩu (>= 8 ký tự, có chữ thường và số), đặt luôn là mật khẩu chính thức.
# Mật khẩu: tham số -Password, hoặc biến $env:HO_DEMO_PASSWORD, không có thì script hỏi (không hiện lên màn hình).
# Tránh dấu nháy " và ' trong mật khẩu (PowerShell 5.1 truyền sai sang aws.exe).
# Chạy lại được: tài khoản đã có thì chỉ đặt lại thuộc tính, mật khẩu và nhóm.
# Cách chạy (từ thư mục Home_Office, sau terraform apply):  .\deploy\cognito_users.ps1
param([string]$Password = $env:HO_DEMO_PASSWORD)
. "$PSScriptRoot\common.ps1"

$PoolId = Aws cognito-idp list-user-pools --max-results 60 --query "UserPools[?Name=='home-office-users'].Id | [0]" --output text
Assert-Ok "tìm User Pool"
if (-not $PoolId -or $PoolId -eq "None") { throw "Chưa có User Pool home-office-users. Chạy terraform apply trong deploy\terraform trước." }
Write-Host "User Pool: $PoolId"

if (-not $Password) {
    $s = Read-Host "Mật khẩu cho 3 tài khoản demo (>= 8 ký tự, có chữ thường và số)" -AsSecureString
    $Password = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
}

$accounts = @(
    @{ Email = "user002@example.com"; GeoLife = "002"; Admin = $false },
    @{ Email = "user153@example.com"; GeoLife = "153"; Admin = $false },
    @{ Email = "admin@example.com";   GeoLife = "";    Admin = $true }
)
foreach ($a in $accounts) {
    Write-Step $a.Email
    $attrs = @("Name=email,Value=$($a.Email)", "Name=email_verified,Value=true")
    if ($a.GeoLife) { $attrs += "Name=custom:geolife_id,Value=$($a.GeoLife)" }

    Aws cognito-idp admin-get-user --user-pool-id $PoolId --username $a.Email 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Aws cognito-idp admin-update-user-attributes --user-pool-id $PoolId --username $a.Email --user-attributes @attrs
        Assert-Ok "cập nhật thuộc tính $($a.Email)"
        Write-Host "  đã có, cập nhật thuộc tính"
    } else {
        Aws cognito-idp admin-create-user --user-pool-id $PoolId --username $a.Email --user-attributes @attrs --message-action SUPPRESS | Out-Null
        Assert-Ok "tạo tài khoản $($a.Email)"
        Write-Host "  đã tạo"
    }

    Aws cognito-idp admin-set-user-password --user-pool-id $PoolId --username $a.Email --password $Password --permanent
    Assert-Ok "đặt mật khẩu $($a.Email) (mật khẩu cần >= 8 ký tự, có chữ thường và số)"

    if ($a.Admin) {
        Aws cognito-idp admin-add-user-to-group --user-pool-id $PoolId --username $a.Email --group-name admin
        Assert-Ok "thêm $($a.Email) vào nhóm admin"
        Write-Host "  trong nhóm admin"
    }
}
Write-Host "`nXong. Thử API: .\api\test.ps1" -ForegroundColor Green
