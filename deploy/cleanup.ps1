# Delete everything created for the test (function, ECR repo, role, both buckets, log group).
. "$PSScriptRoot\common.ps1"
$old = "home-office-lambda-$Acct"
$ans = Read-Host "Delete function $Fn, ECR repo $Repo, role $Role, bucket $Bucket and old bucket $old (us-east-1)? Type yes"
if ($ans -ne "yes") { Write-Host "Cancelled"; return }
Aws lambda delete-function --function-name $Fn
Aws ecr delete-repository --repository-name $Repo --force | Out-Null
Aws iam detach-role-policy --role-name $Role --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
Aws iam detach-role-policy --role-name $Role --policy-arn arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess
Aws iam delete-role --role-name $Role
Aws s3 rb "s3://$Bucket" --force
aws s3 rb "s3://$old" --force --region us-east-1 --profile $Profile
Aws logs delete-log-group --log-group-name "/aws/lambda/$Fn"
Write-Host "Cleanup finished. Check: aws s3 ls --profile $Profile ; aws lambda list-functions --profile $Profile --region $Region"
