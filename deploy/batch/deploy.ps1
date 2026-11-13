param([switch]$SkipImage)
# Build the image, push it to ECR, create the role and the Lambda function (safe to re-run: updates the code if it exists).
. "$PSScriptRoot\..\common.ps1"
Write-Host "Account $Acct, region $Region"

# ECR repository
Aws ecr describe-repositories --repository-names $Repo 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Aws ecr create-repository --repository-name $Repo | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Cannot create the ECR repository" }
}

if (-not $SkipImage) {
# Build and push (run from the Home_Office folder; Docker Desktop must be running)
docker build --platform linux/amd64 --provenance=false -f deploy/batch/Dockerfile -t $Repo .
if ($LASTEXITCODE -ne 0) { throw "docker build failed" }
# Docker Desktop credential helper fails with ECR tokens ("stub received bad data"):
# run docker login/push with a copy of docker.exe and a PATH that has no credential helper, so the token goes to config.json
$pw = Aws ecr get-login-password
if ($LASTEXITCODE -ne 0 -or -not $pw) { throw "Cannot get the ECR password" }
$dc = Join-Path $env:TEMP "docker-cfg-ho"
New-Item -ItemType Directory -Force -Path "$dc\bin" | Out-Null
Set-Content -Path (Join-Path $dc "config.json") -Value "{}" -Encoding ASCII
Copy-Item (Get-Command docker -CommandType Application | Select-Object -First 1).Source "$dc\bin\docker.exe" -Force
$oldPath = $env:PATH; $oldCfg = $env:DOCKER_CONFIG
$env:DOCKER_CONFIG = $dc
$env:PATH = "$dc\bin;$env:SystemRoot\System32;$env:SystemRoot"
try {
    $pw | & "$dc\bin\docker.exe" login --username AWS --password-stdin "$Acct.dkr.ecr.$Region.amazonaws.com"
    if ($LASTEXITCODE -ne 0) { throw "docker login failed" }
    & "$dc\bin\docker.exe" tag $Repo $Image
    & "$dc\bin\docker.exe" push $Image
    if ($LASTEXITCODE -ne 0) { throw "docker push failed" }
} finally { $env:PATH = $oldPath; $env:DOCKER_CONFIG = $oldCfg }
}

# Execution role
Aws iam get-role --role-name $Role 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Aws iam create-role --role-name $Role --assume-role-policy-document file://deploy/batch/trust.json | Out-Null
    Aws iam attach-role-policy --role-name $Role --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
    Aws iam attach-role-policy --role-name $Role --policy-arn arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess
    Start-Sleep 15
}

# Permission to write results (idempotent): only s3://<bucket>/results/*, nothing else
$pf = Join-Path $env:TEMP "ho-results-write.json"
$policy = '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"s3:PutObject","Resource":"arn:aws:s3:::' + $Bucket + '/results/*"}]}'
[IO.File]::WriteAllText($pf, $policy)
Aws iam put-role-policy --role-name $Role --policy-name results-write --policy-document "file://$pf"
if ($LASTEXITCODE -ne 0) { throw "Cannot add the results-write policy to the role" }

# Lambda function: 2048 MB, 15 minutes
Aws lambda get-function --function-name $Fn 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    $created = $false
    for ($i = 1; $i -le 3 -and -not $created; $i++) {
        Aws lambda create-function --function-name $Fn --package-type Image --code "ImageUri=$Image" --role "arn:aws:iam::${Acct}:role/$Role" --memory-size 2048 --timeout 900 --environment "Variables={BUCKET=$Bucket}" | Out-Null
        if ($LASTEXITCODE -eq 0) { $created = $true } else { Write-Host "retry in 15 s (the role may not be ready yet)"; Start-Sleep 15 }
    }
    if (-not $created) { throw "create-function failed" }
} else {
    Aws lambda update-function-code --function-name $Fn --image-uri $Image | Out-Null
}
Aws lambda wait function-active-v2 --function-name $Fn
Aws lambda wait function-updated-v2 --function-name $Fn
Write-Host "Deployed: $Fn"
