# Home/Office Inference trên GeoLife (Track MLE B1)

Suy ra vị trí **home** và **office** của mỗi user từ dữ liệu GPS GeoLife 1.3, rồi phục vụ kết quả qua API.

Trạng thái: **Checkpoint 1** (location model cơ bản + API spec).

## Cấu trúc

```
Home_Office/
├── README.md
├── requirements.txt
├── .gitignore
├── api/                     openapi.yaml: bản nháp OpenAPI spec, review với mentor trước khi code
├── docs/
│   └── cp1_slides.html      slide tổng kết Checkpoint 1 (mở bằng trình duyệt; ← → chuyển slide, Ctrl+P xuất PDF)
├── notes/
│   ├── assumptions.md       ngưỡng và giả định, kèm căn cứ
│   └── decisions.md         các quyết định thiết kế, theo ngày
├── data/                    không commit
│   ├── raw/geolife/         dữ liệu gốc GeoLife 1.3 (Data/<user>/Trajectory/*.plt, labels.txt)
│   ├── interim/             bản sao nguyên vẹn của dữ liệu gốc ở định dạng nhị phân (convert_raw.py)
│   │   ├── points/          mỗi user một file: lat, lon, timestamp, file
│   │   ├── files/           mỗi user một file: danh sách file .plt
│   │   └── labels/          nhãn phương tiện (user có labels.txt)
│   └── processed/
│       ├── clean/           quỹ đạo đã lọc, mỗi user một parquet (timestamp UTC, local_time, tz_offset_h)
│       ├── stays/           stay point, mỗi user một parquet
│       └── places_v1/       địa điểm (v1) và stay kèm place_id, mỗi user hai parquet
├── notebooks/
│   └── eda/                 EDA, đánh số mục 1–29 theo thứ tự pipeline (01–05 mô tả dữ liệu thô trước bước lọc, không gắn ngưỡng hay khung giờ)
│       ├── 01_data_quality.ipynb        mục 1–3: chất lượng, quy mô dữ liệu theo user
│       ├── 02_speed_and_gaps.ipynb      mục 4–7: khoảng lấy mẫu, tốc độ, khoảng trống, nhãn phương tiện
│       ├── 03_outlier_thresholds.ipynb  mục 8: chuỗi đi ra rồi quay về, chọn ngưỡng outlier (N hay T)
│       ├── 04_space_and_time.ipynb      mục 9, 10, 11: phân bố không gian, kiểm chứng múi giờ, theo tháng/năm
│       ├── 05_coverage.ipynb            mục 12, 13: độ phủ theo giờ, khoảng trống theo giờ
│       ├── 06_staypoint_thresholds.ipynb mục 14–17: kiểm chứng D, T của stay point bằng nhãn phương tiện
│       ├── 07_stay_anchor.ipynb          mục 18–21: cách đặt điểm neo của stay point, `li` so với `h1_mean`
│       ├── 08_gap_stay.ipynb             mục 22–23: gap-stay, hai đầu xa nhau là gì, chọn max gap
│       ├── 09_home_office_windows.ipynb  mục 24–26: thời gian có mặt theo giờ, giờ đến/đi, độ nhạy khung home/office; 26.1–26.5 đọc khung giờ làm việc từ dữ liệu (A10)
│       ├── 10_gap_home_office.ipynb      mục 27–29: gap trong giờ đêm / giờ hành chính, gap có ở home/office không, số đêm / ngày tối thiểu để bỏ phiếu
├── src/
│   ├── preprocess/
│   │   ├── check_raw_format.py   kiểm tra định dạng file .plt
│   │   ├── convert_raw.py        chuyển .plt sang data/interim (một lần)
│   │   ├── interim.py            đọc/ghi data/interim (parquet, hoặc pickle nếu thiếu pyarrow)
│   │   ├── clean_trajectory.py   lọc tọa độ/thời gian/trùng/outlier, thêm giờ địa phương
│   │   └── local_time.py         đổi UTC sang giờ địa phương (dùng chung cho EDA và pipeline)
│   ├── stays/
│   │   └── detect.py             bước 5: stay point (Li et al., 2008, neo h1_mean D13), kể cả gap-stay
│   ├── places/
│   │   ├── cluster_v1.py         bước 6 (v1): gom stay thành địa điểm quanh điểm neo, bán kính 200 m
│   │   └── home_office_conf.py   bước 7: home/office bằng bỏ phiếu theo ngày + confidence (D18)
│   └── eda/
│       ├── stay_scan.py          chạy stay point trong các đoạn có nhãn cho notebook 06, lưu tạm ở data/interim/eda_stays_labels
│       ├── stay_anchor.py        li và h1_mean, đo tách stay, nhận nhầm, địa điểm đứng đầu, gap-stay (notebook 07, 08), lưu tạm ở data/interim/eda_stay_anchor_mean
│       ├── stay_anchor_plots.py  biểu đồ cho notebook 07, 08, 10
│       ├── split.py              chia user dev/test (D17), chạy đầu tiên trước mọi EDA; notebook 01–10 chỉ đọc nhóm dev; kết quả data/split/users.csv
│       ├── work_window.py        đọc khung giờ làm việc từ tỷ lệ office/(office+home) theo giờ, notebook 09 mục 26.1–26.5
│       ├── presence.py           tách stay thành phần GPS / khoảng trống theo giờ cho notebook 09, lưu tạm ở data/interim/eda_presence
│       ├── gap_evidence.py       giờ GPS / gap của home, office, gap có ở home/office không (notebook 10)
│       ├── min_days.py           số đêm / ngày làm việc tối thiểu để bỏ phiếu ổn định (notebook 10, mục 29)
│       ├── duplicates.py         dòng trùng timestamp, file trùng giữa các user (notebook 01)
│       ├── config.py             dữ kiện tài liệu, giả thuyết, mốc mô tả dùng chung cho các notebook EDA
│       ├── scan.py               quét data/interim, tính số liệu theo chủ đề cho từng notebook
│       └── utils.py              hàm nhỏ (phân vị từ histogram, định dạng nhãn)
└── reports/
    └── filter_stats.csv     số liệu lọc theo user
```

## Cài đặt

```
python -m venv .venv
.venv\Scripts\activate          # Windows; Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

Tải GeoLife 1.3 và giải nén sao cho có `data/raw/geolife/Data/000/Trajectory/*.plt`.

## Chạy

Mọi lệnh chạy từ thư mục gốc `Home_Office`.

```
# 1. Kiểm tra định dạng file .plt
python src/preprocess/check_raw_format.py

# 2. Chuyển dữ liệu thô sang data/interim (MỘT LẦN, khoảng 10 phút)
#    Chỉ đổi định dạng, không lọc. Chạy lại khi đổi cách đọc file .plt (read_plt).
python src/preprocess/convert_raw.py

# 2b. Chia user thành nhóm dev / test (D17) TRƯỚC KHI chạy bất kỳ EDA nào.
#    Chạy một lần; không ghi đè nếu đã có data/split/users.csv.
python src/eda/split.py

# 3. EDA: mở từng notebook trong notebooks/eda/ và Run All (mỗi notebook khoảng 1–2 phút)
#    Chỉ đọc nhóm dev.
#    Kết quả dùng để chọn ngưỡng lọc (xem notes/assumptions.md).

# 4. Lọc với các ngưỡng đã chọn (đọc từ data/interim)
python src/preprocess/clean_trajectory.py --save-clean data/processed/clean
#    -> reports/filter_stats.csv (CSV) và data/processed/clean/*.parquet
#    đọc lại: from clean_trajectory import load_clean; load_clean("060")

# 5. Stay point (đọc data/processed/clean)
python src/stays/detect.py
#    -> data/processed/stays/<user>.parquet và reports/stay_stats.csv

# 6. Gom stay thành địa điểm, phiên bản v1 (đọc data/processed/stays)
python src/places/cluster_v1.py
#    -> data/processed/places_v1/<user>_places.parquet, <user>_stays.parquet (kèm place_id)
#       và reports/place_stats_v1.csv


```

## Pipeline Checkpoint 1

| # | Bước | Trạng thái | Code |
|---|---|---|---|
| 1 | Đọc, kiểm tra định dạng | xong | `src/preprocess/check_raw_format.py` |
| 2 | Chuyển dữ liệu thô sang data/interim | xong | `src/preprocess/convert_raw.py` |
| 2b | Chia user dev / test (D17) | xong | `src/eda/split.py` |
| 3 | EDA trên dữ liệu thô (nhóm dev), chọn ngưỡng | xong (chạy lại trên dev) | `notebooks/eda/01`–`05` |
| 4 | Lọc tọa độ, thời gian, trùng, chuỗi outlier (k ≤ 5); thêm giờ địa phương (không cắt segment, D10) | xong | `src/preprocess/clean_trajectory.py` |
| 5 | Stay point (Li et al., 2008, neo h1_mean; D = 200 m, T = 30 phút; gap-stay ≤ 24 giờ) | xong (chạy lại sau D13, đổi sang h1_mean 2026-11-06) | `src/stays/detect.py` |
| 6 | Gom cụm địa điểm: v1 tham lam quanh điểm neo (200 m); v2 DBSCAN (CP2) | v1 xong | `src/places/cluster_v1.py` |
| 7 | Gán home/office (bỏ phiếu), confidence % bootstrap, cờ | xong (v1); test chạy một lần (D19) | `src/places/home_office_conf.py`, `notebooks/eda/11_test.ipynb` |
| – | OpenAPI spec (làm song song, review với mentor trước khi code API) | bản nháp, chờ review | `api/openapi.yaml` |

Ngưỡng và giả định: xem `notes/assumptions.md`. Các tham chiếu "EDA mục N" trong đó ứng với notebook:

| Mục | Notebook |
|---|---|
| 1, 2, 3 | `01_data_quality` |
| 4, 5, 6, 7 | `02_speed_and_gaps` |
| 8 | `03_outlier_thresholds` |
| 9, 10, 11 | `04_space_and_time` |
| 12, 13 | `05_coverage` |
| 14, 15, 16, 17 | `06_staypoint_thresholds` |
| 18, 19, 20, 21 | `07_stay_anchor` |
| 22, 23 | `08_gap_stay` |
| 24, 25, 26 (26.1–26.5) | `09_home_office_windows` |
| 27, 28, 29 | `10_gap_home_office` |
