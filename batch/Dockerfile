# Image của Lambda batch: Python 3.12 của AWS Lambda + thư viện + src/ + batch_handler.py.
# Build từ thư mục gốc dự án (Home_Office), không phải từ batch:
#   docker build --platform linux/amd64 --provenance=false -f batch/Dockerfile -t home-office-lambda .
# Thường không build tay: dùng batch/build_bundle.ps1 rồi batch/cloudshell_build.sh.
FROM public.ecr.aws/lambda/python:3.12

# Cài thư viện trước khi chép code: Docker giữ cache từng lớp, sửa code không phải cài lại thư viện.
COPY batch/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ${LAMBDA_TASK_ROOT}/src/
COPY batch/batch_handler.py ${LAMBDA_TASK_ROOT}/

# Lambda chạy bằng user không phải root: file chép từ thư mục Windows / OneDrive có thể chỉ chủ sở hữu đọc được.
RUN chmod -R a+rX ${LAMBDA_TASK_ROOT}

# Mỗi lần được gọi, Lambda chạy hàm lambda_handler trong batch_handler.py.
CMD ["batch_handler.lambda_handler"]
