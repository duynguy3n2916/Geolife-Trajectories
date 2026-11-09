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
├── notebooks/               đánh số 01–14 theo thứ tự làm; mục đánh số riêng trong từng notebook
│   ├── survey/              KHẢO SÁT, trước khi chia: toàn bộ 182 user, chỉ mô tả, không chọn ngưỡng
│   │   ├── 01_data_quality.ipynb         mục 1–3 (3.1–3.4): chất lượng, quy mô theo user, dòng trùng, file trùng giữa các user
│   │   ├── 02_sampling_and_labels.ipynb  mục 1, 2: khoảng lấy mẫu, nhãn phương tiện
│   │   ├── 03_space_and_time.ipynb       mục 1, 2, 3: phân bố không gian, kiểm chứng múi giờ, theo tháng/năm
│   │   └── 04_coverage_by_hour.ipynb     mục 1: độ phủ theo thứ và giờ
│   ├── tuning/              TUNING, sau khi chia: chỉ nhóm validation, chọn ngưỡng
│   │   ├── 05_duplicate_rules.ipynb      mục 1 (1.1–1.3): quy tắc xử lý dòng trùng timestamp (R3, R4, 83 m)
│   │   ├── 06_speed_and_gaps.ipynb       mục 1, 2: tốc độ giữa hai điểm, khoảng trống thời gian
│   │   ├── 07_outlier_thresholds.ipynb   các bước 1–7: chuỗi đi ra rồi quay về, chọn ngưỡng outlier (N hay T)
│   │   ├── 08_gap_ends.ipynb             mục 1: khoảng trống xảy ra lúc nào, hai đầu có gần nhau không
│   │   ├── 09_staypoint_thresholds.ipynb mục 1–4: kiểm chứng D, T của stay point bằng nhãn phương tiện
│   │   ├── 10_stay_anchor.ipynb          mục 1–4: cách đặt điểm neo của stay point, `li` so với `h1_mean`
│   │   ├── 11_gap_stay.ipynb             mục 1–2: gap-stay, hai đầu xa nhau là gì, chọn max gap
│   │   ├── 12_home_office_windows.ipynb  mục 1–4: thời gian có mặt theo giờ, giờ đến/đi, độ nhạy khung home/office; 4.1–4.5 đọc khung giờ làm việc từ dữ liệu
│   │   ├── 13_gap_home_office.ipynb      mục 1–5: gap trong giờ đêm / giờ hành chính, số đêm / ngày tối thiểu, confidence, xem CSV
│   │   └── 14_place_eps.ipynb            mục 1–4: chọn `eps` của cluster_v2 (D20, A16), quét `min_samples`, so với v1
│   └── test/                TEST, chạy một lần (D19)
│       └── 15_test.ipynb
├── src/
│   ├── paths.py                  PROJECT_ROOT, đường dẫn gốc dùng chung
│   ├── geo.py                    haversine_m
│   ├── models.py                 các version model (heuristic-v1, dbscan-v2), mầm của registry
│   ├── infer.py                  infer(points, model_version): chuỗi GPS trong bộ nhớ -> home/office (lõi của POST /v1/infer)
│   ├── preprocess/
│   │   ├── check_raw_format.py   kiểm tra định dạng file .plt
│   │   ├── convert_raw.py        chuyển .plt sang data/interim (một lần)
│   │   ├── interim.py            đọc/ghi data/interim (parquet, hoặc pickle nếu thiếu pyarrow)
│   │   ├── clean_trajectory.py   lọc tọa độ/thời gian/trùng/outlier, thêm giờ địa phương
│   │   └── local_time.py         đổi UTC sang giờ địa phương (dùng chung cho EDA và pipeline)
│   ├── stays/
│   │   └── detect.py             bước 5: stay point (Li et al., 2008, neo h1_mean D13), kể cả gap-stay
│   ├── places/
│   │   ├── common.py             phần dùng chung của hai cách gom (bảng địa điểm, dòng lệnh, places_dir(version))
│   │   ├── cluster_v1.py         bước 6 (v1): gom stay thành địa điểm quanh điểm neo
│   │   ├── cluster_v2.py         bước 6 (v2): DBSCAN, eps 200 m, min_samples 1 (D20)
│   │   └── home_office_conf.py   bước 7: home/office bằng bỏ phiếu theo ngày + confidence (D18)
│   └── eda/
│       ├── place_eps.py          quét eps / min_samples của cluster_v2 và so với v1 (notebook 14), cache ở data/interim/eda_place_eps
│       ├── stay_scan.py          chạy stay point trong các đoạn có nhãn cho notebook 09, lưu tạm ở data/interim/eda_stays_labels
│       ├── stay_anchor.py        li và h1_mean, đo tách stay, nhận nhầm, địa điểm đứng đầu, gap-stay (notebook 10, 11), lưu tạm ở data/interim/eda_stay_anchor_mean
│       ├── stay_anchor_plots.py  biểu đồ cho notebook 10, 11, 13
│       ├── split.py              chia user validation/test (D17), chạy sau khảo sát và trước tuning; notebook tuning chỉ đọc nhóm validation; kết quả data/split/users.csv
│       ├── work_window.py        đọc khung giờ làm việc từ tỷ lệ office/(office+home) theo giờ, notebook 12 mục 4.1–4.5
│       ├── presence.py           tách stay thành phần GPS / khoảng trống theo giờ cho notebook 12, lưu tạm ở data/interim/eda_presence
│       ├── gap_evidence.py       giờ GPS / gap của home, office, gap có ở home/office không (notebook 13)
│       ├── min_days.py           số đêm / ngày làm việc tối thiểu để bỏ phiếu ổn định (notebook 13, mục 3)
│       ├── duplicates.py         dòng trùng timestamp, file trùng giữa các user (notebook 01 và 05)
│       ├── config.py             dữ kiện tài liệu, giả thuyết, mốc mô tả dùng chung cho các notebook EDA
│       ├── scan.py               quét data/interim, tính số liệu theo chủ đề cho từng notebook
│       └── utils.py              hàm nhỏ (phân vị từ histogram, định dạng nhãn)
├── tests/                   pytest: gom cụm, bỏ phiếu, infer (python -m pytest tests)
└── reports/
    ├── cp1_slides.html      slide tổng kết Checkpoint 1; slide đều để ở reports/ (mở bằng trình duyệt; ← → chuyển slide, Ctrl+P xuất PDF)
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

# 3. KHẢO SÁT (trước khi chia): notebooks/survey/ gồm 01–04. Run All, chạy trên TOÀN BỘ 182 user.
#    Chỉ mô tả dữ liệu, không chọn ngưỡng. Mỗi notebook khoảng 1–2 phút (01 lần đầu khoảng 10 phút).

# 3b. Chia user thành nhóm validation / test (D17) sau khi khảo sát và TRƯỚC KHI chọn ngưỡng.
#    Chỉ đọc tên file và md5 file .plt; user có file giống hệt nhau vào cùng một nhóm (cụm).
#    Chạy một lần; không ghi đè nếu đã có data/split/users.csv (lần đầu quét md5 khoảng 1–2 phút).
python src/eda/split.py

# 3c. TUNING (sau khi chia): notebooks/tuning/ gồm 05–14, chỉ nhóm validation.
#    Kết quả dùng để chọn ngưỡng (xem notes/assumptions.md). Notebook 05–08 chạy trước bước 4–6 bên dưới; notebook 09–14 chạy sau đó
#    (làm sạch, stay, gom địa điểm), notebook 13 sau bước 7, notebook 14 sau bước 6; test (notebook 15) cuối cùng.

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

# 6b. Phiên bản v2 (DBSCAN, eps 200 m); chạy bước 7 cho v2 bằng --version v2
python src/places/cluster_v2.py
python src/places/home_office_conf.py --version v2      # mặc định v1; ghi reports/home_office_<version>_val.csv

# Test (cần: pip install -r requirements-dev.txt)
python -m pytest tests


```

## Pipeline Checkpoint 1

| # | Bước | Trạng thái | Code |
|---|---|---|---|
| 1 | Đọc, kiểm tra định dạng | xong | `src/preprocess/check_raw_format.py` |
| 2 | Chuyển dữ liệu thô sang data/interim | xong | `src/preprocess/convert_raw.py` |
| 3 | Khảo sát toàn bộ dữ liệu (chỉ mô tả, chưa chọn ngưỡng) | xong 2026-11-07 (bản chia mới) | `notebooks/survey/` |
| 3b | Chia validation / test, gom user trùng file (D17) | xong 2026-11-07 | `src/eda/split.py` |
| 3c | Chọn ngưỡng, chỉ nhóm validation | 05–13 xong 2026-11-07; 14 xong 2026-11-09; 13 chưa chạy lại trên kết quả bước 7 mới | `notebooks/tuning/` |
| 4 | Lọc tọa độ, thời gian, trùng, chuỗi outlier (A3, A5, A6 đã chốt); thêm giờ địa phương (không cắt segment, D10) | xong 2026-11-07 | `src/preprocess/clean_trajectory.py` |
| 5 | Stay point (Li et al., 2008; D = 200 m, T = 30 phút, max gap 24 giờ, neo h1_mean đã chốt) | xong 2026-11-07 | `src/stays/detect.py` |
| 6 | Gom cụm địa điểm: v1 tham lam quanh điểm neo (bán kính 200 m); v2 DBSCAN `eps` 200 m (D20) | v1 và v2 xong 2026-11-09 (mọi user, `eps` 200 m) | `src/places/cluster_v1.py`, `src/places/cluster_v2.py` |
| 7 | Gán home/office (bỏ phiếu), confidence % bootstrap, cờ | xong 2026-11-09 cho v1 và v2, gồm test chạy một lần (D19) | `src/places/home_office_conf.py`, `notebooks/test/15_test.ipynb` |
| – | OpenAPI spec (làm song song, review với mentor trước khi code API) | bản nháp, chờ review | `api/openapi.yaml` |

Ngưỡng và giả định: xem `notes/assumptions.md` (tất cả đã chốt 2026-11-07; A11 và A15 là quy ước, A11 kiểm lại ở `notebooks/tuning/13`). Mục ("mục N") đánh số riêng trong từng notebook; tham chiếu từ file khác ghi kèm tên notebook, ví dụ "mục 2.1 (notebook 11)". Mục của từng notebook: xem cây thư mục ở đầu file.
