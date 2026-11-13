# Bước 7 của quy trình: tạo (hoặc cập nhật) Lambda tra cứu và API Gateway HTTP API đứng trước nó.
# Cần có trước: bucket và kết quả batch trong results/ (bước 6).
# Cách chạy (từ thư mục Home_Office):
#   .\deploy\lookup\deploy.ps1                              version mặc định heuristic-v1 (chỉ đặt khi chưa có)
#   .\deploy\lookup\deploy.ps1 -DefaultVersion dbscan-v2    đặt version mặc định (ghi đè results/_default.json)
# Tạo ra: role, function, API có 2 route (GET /health, GET /v1/users/{user_id}/home-office), địa chỉ API ở deploy\lookup\api_url.txt
# Chạy lại an toàn. Sửa deploy\lookup\handler.py rồi chạy lại là code mới được đưa lên (Lambda này dùng file zip, không cần image).
param([string]$DefaultVersion)
. "$PSScriptRoot\..\common.ps1"

Write-Step "Role $LookupRole"
if (New-LambdaRole $LookupRole) { Write-Host "Đã tạo role"; Start-Sleep 15 }
# Chỉ đọc results/. ListBucket để file không tồn tại trả 404 thay vì AccessDenied.
$policy = '{"Version":"2012-10-17","Statement":[' +
  '{"Effect":"Allow","Action":"s3:GetObject","Resource":"arn:aws:s3:::' + $Bucket + '/results/*"},' +
  '{"Effect":"Allow","Action":"s3:ListBucket","Resource":"arn:aws:s3:::' + $Bucket + '","Condition":{"StringLike":{"s3:prefix":"results/*"}}}]}'
Aws iam put-role-policy --role-name $LookupRole --policy-name results-read --policy-document ("file://" + (New-TempJson "ho-lookup-read.json" $policy))
Assert-Ok "gắn quyền đọc results/ cho $LookupRole"

Write-Step "Version mặc định (results/_default.json)"
Aws s3api head-object --bucket $Bucket --key results/_default.json 2>$null | Out-Null
$exists = ($LASTEXITCODE -eq 0)
if ($DefaultVersion -or -not $exists) {
    if (-not $DefaultVersion) { $DefaultVersion = "heuristic-v1" }
    $df = New-TempJson "ho-default.json" ('{"default_model_version":"' + $DefaultVersion + '"}')
    Aws s3 cp $df "s3://$Bucket/results/_default.json" --content-type application/json --only-show-errors
    Assert-Ok "ghi results/_default.json"
    Write-Host "Mặc định = $DefaultVersion (Lambda đọc lại sau tối đa 60 giây)"
} else {
    Write-Host "Giữ nguyên: $(Aws s3 cp "s3://$Bucket/results/_default.json" -)"
}

Write-Step "Function $LookupFn (Python 3.12, 256 MB, tối đa 10 giây)"
$zip = Join-Path $env:TEMP "ho-lookup.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path "deploy/lookup/handler.py" -DestinationPath $zip    # handler.py nằm ở gốc file zip
Aws lambda get-function --function-name $LookupFn 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    $created = $false
    for ($i = 1; $i -le 3 -and -not $created; $i++) {
        Aws lambda create-function --function-name $LookupFn --runtime python3.12 --handler handler.lambda_handler `
            --role "arn:aws:iam::${Acct}:role/$LookupRole" --zip-file "fileb://$zip" --memory-size 256 --timeout 10 `
            --environment "Variables={BUCKET=$Bucket}" | Out-Null
        if ($LASTEXITCODE -eq 0) { $created = $true } else { Write-Host "Thử lại sau 15 s (role có thể chưa sẵn sàng)"; Start-Sleep 15 }
    }
    if (-not $created) { throw "Lỗi: tạo function $LookupFn" }
    Write-Host "Đã tạo function"
} else {
    Aws lambda update-function-code --function-name $LookupFn --zip-file "fileb://$zip" | Out-Null
    Assert-Ok "cập nhật code cho $LookupFn"
    Aws lambda wait function-updated-v2 --function-name $LookupFn
    # Bản nháp trước dùng tên file lookup_handler.py: đặt lại điểm vào cho đúng handler.py.
    Aws lambda update-function-configuration --function-name $LookupFn --handler handler.lambda_handler | Out-Null
    Assert-Ok "đặt handler cho $LookupFn"
    Write-Host "Đã cập nhật code"
}
Aws lambda wait function-active-v2 --function-name $LookupFn
Aws lambda wait function-updated-v2 --function-name $LookupFn
$fnArn = "arn:aws:lambda:${Region}:${Acct}:function:$LookupFn"

Write-Step "API Gateway $ApiName"
$apiId = Aws apigatewayv2 get-apis --query "Items[?Name=='$ApiName'].ApiId | [0]" --output text
if (-not $apiId -or $apiId -eq "None") {
    $apiId = Aws apigatewayv2 create-api --name $ApiName --protocol-type HTTP --query ApiId --output text
    Assert-Ok "tạo API"
    # Một integration (gọi Lambda, payload 2.0) dùng chung cho cả hai route.
    $intId = Aws apigatewayv2 create-integration --api-id $apiId --integration-type AWS_PROXY --integration-uri $fnArn `
        --payload-format-version 2.0 --query IntegrationId --output text
    Assert-Ok "tạo integration"
    Aws apigatewayv2 create-route --api-id $apiId --route-key "GET /health" --target "integrations/$intId" | Out-Null
    Assert-Ok "tạo route /health"
    Aws apigatewayv2 create-route --api-id $apiId --route-key "GET /v1/users/{user_id}/home-office" --target "integrations/$intId" | Out-Null
    Assert-Ok "tạo route home-office"
    # Stage $default tự deploy mỗi khi đổi route; giới hạn 20 request/giây (dồn tối đa 50) để tránh bị gọi tràn.
    Aws apigatewayv2 create-stage --api-id $apiId --stage-name '$default' --auto-deploy `
        --default-route-settings "ThrottlingBurstLimit=50,ThrottlingRateLimit=20" | Out-Null
    Assert-Ok "tạo stage"
    Write-Host "Đã tạo API $apiId"
} else {
    Write-Host "API $apiId đã có (giữ nguyên route)"
}

Write-Step "Cho API Gateway quyền gọi $LookupFn"
Aws lambda add-permission --function-name $LookupFn --statement-id apigw-invoke --action lambda:InvokeFunction `
    --principal apigateway.amazonaws.com --source-arn "arn:aws:execute-api:${Region}:${Acct}:${apiId}/*/*" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Host "Quyền đã có từ lần trước" }

$url = "https://$apiId.execute-api.$Region.amazonaws.com"
Set-Content -Path "deploy/lookup/api_url.txt" -Value $url -Encoding ascii
Write-Host "Xong. Địa chỉ API: $url" -ForegroundColor Green
Write-Host "Thử: .\deploy\lookup\test.ps1"
