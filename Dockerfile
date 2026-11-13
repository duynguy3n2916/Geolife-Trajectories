# Image chạy API Home/Office (api/app.py). Chỉ chứa src/ và api/ (kèm store GeoLife), không có data/.
#
# Build (từ thư mục Home_Office, sau khi đã chạy python api/build_store.py):
#   docker build -t home-office-api --build-arg GIT_COMMIT=$(git rev-parse --short HEAD) .
# Chạy:
#   docker run --rm -p 8000:8000 home-office-api                        # không kiểm tra key, chỉ để thử ở máy
#   docker run --rm -p 8000:8000 -e API_KEYS=dev-key home-office-api    # bật API key (bắt buộc khi deploy)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Cài thư viện trước để Docker dùng lại lớp này khi chỉ sửa code
COPY requirements-api.txt .
RUN pip install -r requirements-api.txt

COPY src/ src/
COPY api/ api/
RUN test -f api/store/geolife.sqlite \
    || (echo "Thiếu api/store/geolife.sqlite: chạy python api/build_store.py trước khi build" && exit 1)

# Commit của bản build, hiện ở GET /v1/models (registry)
ARG GIT_COMMIT=""
ENV GIT_COMMIT=${GIT_COMMIT}

# Không chạy bằng root
RUN useradd --system --uid 10001 app
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

# Một tiến trình; khi cần chạy nhiều thì tăng số container (ECS) thay vì số worker
CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
