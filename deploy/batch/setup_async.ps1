# One-time setup for asynchronous batch runs: a dead-letter queue (SQS) for failed events, plus retry settings on the function.
# Run from the Home_Office folder:  .\deploy\batch\setup_async.ps1
. "$PSScriptRoot\..\common.ps1"
$Dlq = "home-office-batch-dlq"

# 1. Queue (14 days retention). create-queue is idempotent when the attributes are the same.
$url = Aws sqs create-queue --queue-name $Dlq --attributes MessageRetentionPeriod=1209600 --query QueueUrl --output text
if ($LASTEXITCODE -ne 0 -or -not $url) { throw "Cannot create the SQS queue" }
$arn = "arn:aws:sqs:${Region}:${Acct}:$Dlq"

# 2. Role may send to this queue only
$pf = Join-Path $env:TEMP "ho-dlq-send.json"
$policy = '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"sqs:SendMessage","Resource":"' + $arn + '"}]}'
[IO.File]::WriteAllText($pf, $policy)
Aws iam put-role-policy --role-name $Role --policy-name dlq-send --policy-document "file://$pf"
if ($LASTEXITCODE -ne 0) { throw "Cannot add the dlq-send policy" }
Start-Sleep 10

# 3. Async settings: retry twice (Lambda default), keep an event up to 1 h (throttled events are retried inside that time), failed events go to the queue
$dc = '{"OnFailure":{"Destination":"' + $arn + '"}}'
$cf = Join-Path $env:TEMP "ho-async-dest.json"
[IO.File]::WriteAllText($cf, $dc)
Aws lambda put-function-event-invoke-config --function-name $Fn --maximum-retry-attempts 2 --maximum-event-age-in-seconds 3600 --destination-config "file://$cf" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Cannot set the event invoke config" }
Write-Host "Done. Failed async events go to $url"
