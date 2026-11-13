# Image Lambda thử pipeline Home/Office. Build từ thư mục Home_Office (không phải từ deploy/batch):
#   docker build --platform linux/amd64 --provenance=false -f deploy/batch/Dockerfile -t home-office-lambda .
FROM public.ecr.aws/lambda/python:3.12

COPY deploy/batch/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ${LAMBDA_TASK_ROOT}/src/
COPY deploy/batch/handler.py ${LAMBDA_TASK_ROOT}/

# Lambda runs as a non-root user: files copied from a Windows/OneDrive folder can arrive owner-only (rwx------)
RUN chmod -R a+rX ${LAMBDA_TASK_ROOT}

CMD ["handler.lambda_handler"]
