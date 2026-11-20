# Tạo (hoặc cập nhật) tài khoản trong Cognito User Pool home-office-users (deploy/terraform/cognito.tf):
#   user000@example.com ... user181@example.com  -> mỗi tài khoản chỉ xem user GeoLife của mình (custom:geolife_id = 000 ... 181)
#   admin@example.com                            -> nhóm admin, xem mọi user
# Danh sách user lấy từ các thư mục trong data\raw\geolife\Data (không có thư mục đó thì dùng 000 đến 181).
# @example.com là tên miền dành riêng cho ví dụ: không ai nhận thư, và Cognito không gửi thư (--message-action SUPPRESS).
# Mọi tài khoản dùng chung một mật khẩu (>= 8 ký tự, có chữ thường và số), đặt luôn là mật khẩu chính thức.
# Mật khẩu: tham số -Password, hoặc biến $env:HO_DEMO_PASSWORD, không có thì script hỏi (không hiện lên màn hình).
# Tránh dấu nháy " và ' trong mật khẩu (PowerShell 5.1 truyền sai sang aws.exe).
# Chạy lại được: tài khoản đã có thì chỉ đặt lại thuộc tính và mật khẩu. Tạo hết 183 tài khoản mất khoảng 10 phút
# (mỗi tài khoản 2 lệnh aws). Chạy lại sau khi đứt giữa chừng là tạo tiếp phần còn thiếu.
# Cách chạy (từ thư mục Home_Office, sau terraform apply):
#   .\deploy\cognito_users.ps1                       mọi user + admin
#   .\deploy\cognito_users.ps1 -Users 002,153        chỉ vài user (+ admin)
param([string]$Password = $env:HO_DEMO_PASSWORD, [string[]]$Users = @())
. "$PSScriptRoot\common.ps1"

$PoolId = Aws cognito-idp list-user-pools --max-results 60 --query "UserPools[?Name=='home-office-users'].Id | [0]" --output text
Assert-Ok "tìm User Pool"
if (-not $PoolId -or $PoolId -eq "None") { throw "Chưa có User Pool home-office-users. Chạy terraform apply trong deploy\terraform trước." }
Write-Host "User Pool: $PoolId"

if (-not $Password) {
    $s = Read-Host "Mật khẩu chung cho các tài khoản (>= 8 ký tự, có chữ thường và số)" -AsSecureString
    $Password = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
}

# Danh sách user GeoLife
if (-not $Users -or $Users.Count -eq 0) {
    $root = "data\raw\geolife\Data"
    if (Test-Path $root) { $Users = @(Get-ChildItem $root -Directory | Select-Object -ExpandProperty Name | Sort-Object) }
    else { $Users = @(0..181 | ForEach-Object { "{0:D3}" -f $_ }) }
}
$accounts = @($Users | ForEach-Object { @{ Email = "user$_@example.com"; GeoLife = "$_"; Admin = $false } })
$accounts += @{ Email = "admin@example.com"; GeoLife = ""; Admin = $true }

# Email các tài khoản đã có (một lần gọi, AWS CLI tự lật trang), để khỏi hỏi từng tài khoản.
$existing = @{}
foreach ($e in @(Aws cognito-idp list-users --user-pool-id $PoolId --query "Users[].Attributes[?Name=='email'].Value[]" --output text)) {
    foreach ($x in ($e -split "\s+")) { if ($x) { $existing[$x] = $true } }
}
Assert-Ok "liệt kê tài khoản"
Write-Host ("Đã có {0} tài khoản; sẽ xử lý {1} tài khoản." -f $existing.Count, $accounts.Count)

$i = 0; $fail = @()
foreach ($a in $accounts) {
    $i++
    $attrs = @("Name=email,Value=$($a.Email)", "Name=email_verified,Value=true")
    if ($a.GeoLife) { $attrs += "Name=custom:geolife_id,Value=$($a.GeoLife)" }

    if ($existing.ContainsKey($a.Email)) {
        Aws cognito-idp admin-update-user-attributes --user-pool-id $PoolId --username $a.Email --user-attributes @attrs
        $what = "cập nhật"
    } else {
        Aws cognito-idp admin-create-user --user-pool-id $PoolId --username $a.Email --user-attributes @attrs --message-action SUPPRESS | Out-Null
        $what = "tạo mới"
    }
    if ($LASTEXITCODE -ne 0) { $fail += $a.Email; Write-Host "  LỖI $($a.Email) ($what)" -ForegroundColor Red; continue }

    Aws cognito-idp admin-set-user-password --user-pool-id $PoolId --username $a.Email --password $Password --permanent
    if ($LASTEXITCODE -ne 0) {
        $fail += $a.Email
        Write-Host "  LỖI đặt mật khẩu $($a.Email) (mật khẩu cần >= 8 ký tự, có chữ thường và số)" -ForegroundColor Red
        continue
    }
    if ($a.Admin) {
        Aws cognito-idp admin-add-user-to-group --user-pool-id $PoolId --username $a.Email --group-name admin
        if ($LASTEXITCODE -ne 0) { $fail += $a.Email; Write-Host "  LỖI thêm $($a.Email) vào nhóm admin" -ForegroundColor Red; continue }
    }
    Write-Host ("[{0}/{1}] {2}: {3}" -f $i, $accounts.Count, $a.Email, $what)
}

if ($fail.Count) {
    Write-Host ("`n{0} tài khoản lỗi: {1}. Chạy lại script để thử lại." -f $fail.Count, ($fail -join ", ")) -ForegroundColor Red
} else {
    Write-Host "`nXong $($accounts.Count) tài khoản. Thử API: .\api\test.ps1" -ForegroundColor Green
}
