"""Đường dẫn gốc của dự án. Một chỗ duy nhất; các module khác import từ đây."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]      # thư mục Home_Office (cha của src)
