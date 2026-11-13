# Đưa GPS của các user dùng để đo ($Users trong bench_common.ps1) lên S3. Chỉ là lối tắt cho upload_data.ps1 -OnlyUsers.
# Cách chạy (từ thư mục Home_Office):  .\deploy\bench\upload_users.ps1
$Users = "170", "155", "028", "167", "017", "153"
& "$PSScriptRoot\..\data\upload_data.ps1" -OnlyUsers $Users
