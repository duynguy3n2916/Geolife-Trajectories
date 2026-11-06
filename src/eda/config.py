"""Cấu hình dùng chung cho các notebook EDA.

Tách rõ bốn loại:
- Dữ kiện từ tài liệu (User Guide GeoLife 1.3), không suy ra từ dữ liệu.
- Giả thuyết, được kiểm chứng trong notebook.
- Công cụ xấp xỉ cho thống kê (không dùng để lọc).
- Mốc mô tả: chỉ để đọc phân phối, không phải ngưỡng.
"""
import numpy as np
import pandas as pd

# ---- Dữ kiện từ tài liệu (User Guide GeoLife 1.3)
# - Timestamp trong file .plt và trong labels.txt là GMT (UTC).
# - Dữ liệu thu thập "from April 2007 to August 2012".
TIME_MIN = pd.Timestamp("2007-04-01", tz="UTC")
TIME_MAX = pd.Timestamp("2012-09-01", tz="UTC")   # không bao gồm

# ---- Giả thuyết, được kiểm chứng trong notebook
# - Giờ địa phương: UTC+8 trong Trung Quốc, ngoài Trung Quốc xấp xỉ round(lon / 15)
#   (local_offset_h trong src/preprocess/local_time.py). Kiểm chứng ở notebook 04, mục 10.

# ---- Công cụ xấp xỉ cho thống kê (không dùng để lọc): lat_min, lat_max, lon_min, lon_max
BJ_BOX = (39.44, 41.06, 115.42, 117.51)   # Bắc Kinh
# CN_BOX (Trung Quốc) nằm trong src/preprocess/local_time.py

# ---- Mốc mô tả
SPEED_MARKS = [50, 100, 150, 200, 250, 300, 350, 400, 500, 700, 1000, 2000]   # km/h
GAP_MARKS_MIN = [5, 10, 30, 60, 180, 360, 720, 1440]                         # phút
DT_CUTS_S = [10, 60, 300, 1800, 7200, np.inf]   # các mức dt tối đa để xem phân phối tốc độ (mục 5)
QUANTILES = [0.5, 0.9, 0.95, 0.99, 0.999]
DT_BINS = np.logspace(0, 9, 181)          # giây
SPEED_BINS = np.logspace(-2, 4, 121)      # km/h
WORLD_LAT = np.arange(-90, 91, 1.0)
WORLD_LON = np.arange(-180, 181, 1.0)
BJ_RES = 0.01                             # độ, khoảng 1 km
BJ_LAT = np.arange(BJ_BOX[0], BJ_BOX[1] + BJ_RES / 2, BJ_RES)
BJ_LON = np.arange(BJ_BOX[2], BJ_BOX[3] + BJ_RES / 2, BJ_RES)
EPOCH = pd.Timestamp("1970-01-01", tz="UTC")
WEEKDAYS = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]

# ---- Mục 8 (notebook 03): dò "chuỗi đi ra rồi quay về" với điều kiện RỘNG, để dữ liệu tự cho thấy ranh giới
EXC_SPEED_KMH = 300     # tốc độ vô lý với phương tiện mặt đất (vùng trũng mục 5); giống ngưỡng bộ lọc
EXC_STEP_DT_S = 1800    # khoảng trống (A7): chuỗi không vắt qua bước dài hơn mức này; giống bộ lọc
# Không giới hạn số điểm hay thời lượng của chuỗi: dò tới khoảng trống, hết file, hoặc hết dữ liệu (D11).
