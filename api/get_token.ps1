# In ID token của một tài khoản demo, để gọi API bằng tay, dán vào Swagger Editor / Postman, hoặc xem trên jwt.io.
# Cách chạy (từ thư mục Home_Office):
#   .\api\get_token.ps1 user153@example.com
#   $t = .\api\get_token.ps1 user153@example.com
#   $api = (Get-Content api\api_url.txt -Raw).Trim()
#   Invoke-RestMethod "$api/v1/users/153/home-office" -Headers @{ Authorization = "Bearer $t" }
param([Parameter(Mandatory = $true)][string]$Email)
. "$PSScriptRoot\auth.ps1"
Get-IdToken $Email (Read-DemoPassword)
