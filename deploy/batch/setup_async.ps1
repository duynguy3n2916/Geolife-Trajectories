# Bước 5 của quy trình (một lần, sau deploy.ps1): chuẩn bị cho cách gọi bất đồng bộ (run_batch.ps1 -Async).
#   - hàng đợi SQS $Dlq nhận các lần gọi lỗi hẳn (sau khi Lambda tự thử lại), giữ 14 ngày;
#   - cho role của batch quyền gửi vào hàng đợi đó;
#   - đặt cho function: thử lại 2 lần, giữ một lần gọi chờ chạy tối đa 1 giờ, lỗi hẳn thì gửi vào hàng đợi.
# Cách chạy (từ thư mục Home_Office):  .\deploy\batch\setup_async.ps1      (chạy lại an toàn)
. "$PSScriptRoot\..\common.ps1"

Write-Step "Hàng đợi lỗi $Dlq"
$url = Aws sqs create-queue --queue-name $Dlq --attributes MessageRetentionPeriod=1209600 --query QueueUrl --output text
Assert-Ok "tạo hàng đợi $Dlq"
$arn = "arn:aws:sqs:${Region}:${Acct}:$Dlq"

Write-Step "Quyền gửi vào hàng đợi cho $BatchRole"
$policy = '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"sqs:SendMessage","Resource":"' + $arn + '"}]}'
Aws iam put-role-policy --role-name $BatchRole --policy-name dlq-send --policy-document ("file://" + (New-TempJson "ho-dlq-send.json" $policy))
Assert-Ok "gắn quyền dlq-send"
Start-Sleep 10    # quyền mới cần vài giây mới có hiệu lực

Write-Step "Cấu hình thử lại cho $BatchFn"
$dest = New-TempJson "ho-async-dest.json" ('{"OnFailure":{"Destination":"' + $arn + '"}}')
Aws lambda put-function-event-invoke-config --function-name $BatchFn --maximum-retry-attempts 2 `
    --maximum-event-age-in-seconds 3600 --destination-config "file://$dest" | Out-Null
Assert-Ok "đặt cấu hình gọi bất đồng bộ"
Write-Host "Xong. Lần gọi lỗi hẳn sẽ nằm ở $url"
