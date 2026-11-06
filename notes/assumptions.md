# Giả định và ngưỡng (bản hiện hành)

Mỗi giả định có mã (A1, A2, ...); code và notebook tham chiếu theo mã này. Mã A8 đã bỏ, không dùng lại.
"EDA mục N" là mục trong `notebooks/eda/` (bảng ở README). Quyết định lựa chọn: `notes/decisions.md`.

Số liệu ghi theo lần chạy cuối. Các số có ghi "182 user" tính trước khi chia dev/test (D17); cần xác nhận lại sau khi chạy lại EDA trên nhóm dev.

## Tóm tắt

| Mã | Nội dung | Giá trị | Trạng thái |
|---|---|---|---|
| A1 | Timestamp trong .plt và labels.txt là UTC | UTC | chốt |
| A2 | Điểm lỗi dữ liệu | tọa độ ngoài phạm vi; thời gian ngoài [2007-04-01, 2012-09-01) | chốt |
| A3 | Timestamp trùng | gộp về dòng đầu; xóa cả nhóm nếu lệch > 83 m | chốt |
| A4 | Khoảng lấy mẫu điển hình | 5 giây | chốt (mô tả) |
| A5 | Tốc độ nghi là outlier | > 300 km/h | chốt |
| A6 | Chuỗi outlier bị xóa | k ≤ 5 điểm | chốt |
| A7 | Khoảng trống (máy tắt, mất tín hiệu) | > 30 phút | chốt |
| A9 | Giờ địa phương | múi giờ IANA (`timezonefinder`, ô 0,5°) + `zoneinfo` | chốt, chưa kiểm trên dữ liệu thật |
| A10 | Khung giờ home / office | đêm 20–7h; ngày làm việc T2–T6 8:30–18h liền (lõi 10–17h, 18–20h vùng xám) | chốt (D18) |
| A11 | Dữ liệu tối thiểu để suy ra home/office | 7 phiếu: dưới mức này có kết quả nhưng không có confidence, cờ `few_nights` / `few_workdays` | quy ước (notebook 10, mục 29, 30) |
| A12 | Gap-stay: khoảng trống khi đứng yên tính vào stay | khoảng trống ≤ 24 giờ, hai đầu trong bán kính stay | chốt |
| A13 | Không có nhãn home/office chuẩn | không đánh giá thủ công (mentor, 06/11); chỉ đo độ ổn định | chốt |
| A14 | Tham số stay point | D = 200 m, T = 30 phút | chốt |
| A15 | Bán kính gom địa điểm (v1) | 200 m | chốt |

## Chi tiết

### A1. Timestamp là UTC
Theo User Guide GeoLife 1.3. Kiểm chứng: với điểm trong Trung Quốc, theo UTC giờ ít dữ liệu nhất là 19–21h (vô lý), theo UTC+8 là 3–5h sáng (EDA mục 10); tốc độ trung vị của nhãn `walk` 4,2 km/h (EDA mục 7). Mọi phép tính khoảng thời gian dùng UTC; giờ địa phương chỉ dùng cho phân tích theo giờ trong ngày.

### A2. Điểm lỗi dữ liệu (xóa)
Xóa điểm có lat ngoài [-90, 90], lon ngoài [-180, 180], timestamp không đọc được, hoặc ngoài [2007-04-01, 2012-09-01) (User Guide: thu thập 04/2007 đến 08/2012). Lỗi rất ít (EDA mục 1, 3): 1 điểm sai tọa độ, 3 điểm sai thời gian. Làm đầu tiên vì một timestamp sai làm sai mọi tốc độ quanh nó.

### A3. Timestamp trùng (gộp / xóa)
Với mỗi nhóm dòng cùng timestamp, so với dòng đầu nhóm:
- giống hệt, chỉ khác độ cao, hoặc mọi dòng cách dòng đầu ≤ 83 m: gộp, giữ dòng đầu (`n_dup`);
- có dòng cách dòng đầu > 83 m (`DUP_MAX_DIST_M` = 300 km/h × 1 giây): xóa cả nhóm (`n_dup_conflict`), vì không biết dòng nào đúng.

Căn cứ (EDA notebook 01, mục 3.1–3.8, 182 user): 698.900 dòng thừa (2,81%) ở 74 user, 3 user (065, 141, 165) chiếm 89%; 99,4% nhóm chỉ khác lat/lon lệch ≤ 10 m; nhóm lệch > 83 m có 161 nhóm, 458 dòng. Phải làm trước khi tính tốc độ (dt = 0).
Chưa xử lý: file giống hệt giữa các user (khoảng 6% dữ liệu, mục 3.7).

### A4. Khoảng lấy mẫu
dt có p50 = 2 giây, p90 = p95 = 5 giây (EDA mục 4). User có trung vị dt > 5 giây xếp vào nhóm "ghi thưa" khi kiểm tra ngưỡng outlier (notebook 03).

### A5. Ngưỡng tốc độ outlier: 300 km/h
Một bước nhanh hơn 300 km/h (dt ≤ 30 phút) là bước nghi vấn. Căn cứ (EDA mục 5): phân phối tốc độ có vùng trũng 250–300 km/h; không đổi theo dt tối đa; tàu hỏa p99,9 = 237 km/h (dưới 300) nhưng máy bay có trung vị 668 km/h (trên 300), nên không thể chỉ dựa vào tốc độ mà cần thêm điều kiện "đi ra rồi quay về" (A6). Không chọn 150–180 km/h vì cắt vào phân phối thật của tàu.

### A6. Chuỗi outlier bị xóa: k ≤ 5 điểm
Chuỗi `A → X1..Xk → B`: bước vào và bước ra đều nhanh hơn 300 km/h (dt ≤ 30 phút, cùng file), còn A → B không vượt 300 km/h. Xóa X1..Xk khi k ≤ 5 (đếm điểm, không thêm điều kiện thời gian). Pipeline tìm bước quay về trong 5 bước sau bước vào; EDA (notebook 03) tìm không giới hạn. Cả hai dừng ở khoảng trống > 30 phút hoặc hết file.

Căn cứ (notebook 03): đếm điểm không phụ thuộc tần suất ghi (cách đếm giây T = 30 giây xóa 0 chuỗi ở nhóm ghi thưa); chuỗi chỉ bị đếm điểm bắt có dấu hiệu lỗi rõ (tới 444.347 km/h, cách A tới 621 km rồi quay về); k = 5 nằm giữa vùng phẳng của lưới. Pipeline xóa 455 điểm trên 182 user.
Hạn chế: 2 chuỗi trong đoạn nhãn máy bay bị xóa, chưa xem chi tiết; chuỗi dài hơn 5 điểm được giữ. Số 507 chuỗi và 455 điểm cần xác nhận đã chạy lại với phạm vi tìm hiện hành.

### A7. Khoảng trống: 30 phút
Bước có dt > 30 phút là khoảng trống, không phải bước di chuyển; không xóa điểm. Dùng ở hai chỗ: không dò outlier qua khoảng trống; stay có khoảng trống là gap-stay (A12). Căn cứ (EDA mục 6, 13): số khoảng trống giảm nhanh tới mốc 30 phút; dưới 30 phút hai đầu gần nhau (trung vị khoảng 30 m), từ 30 phút trở lên khoảng cách hai đầu tăng rõ (trung vị 92 m rồi 126 m).

### A9. Giờ địa phương
Tra tên múi giờ IANA từ tọa độ bằng `timezonefinder` theo ô lưới 0,5° (tra tại tâm ô, có cache), đổi giờ bằng `zoneinfo` (có giờ mùa hè theo ngày). Điểm không tra được dùng `Etc/GMT`. Thêm cột `tz_name`, `tz_offset_h` (số thực). Căn cứ: 97,6% điểm nằm trong Trung Quốc (80,5% ở Bắc Kinh), 12 user có điểm ngoài Trung Quốc (EDA mục 9, 10).
**Chưa kiểm chứng trên dữ liệu thật:** chạy `src/preprocess/check_timezone.py` để đo tỷ lệ điểm khác cách cũ, số điểm ra `Asia/Urumqi` (IANA ghi UTC+6, giờ chính thức là Bắc Kinh) và sai số ô lưới. Không lọc theo Bắc Kinh (27 user có dưới 50% điểm ở Bắc Kinh).

### A10. Khung giờ home / office
Đêm (home): 20–7h mọi ngày. Ngày làm việc (office): T2–T6 (với user ở Trung Quốc bỏ ngày lễ, thêm ngày làm bù), 8:30–18:00 liền, không loại giờ trưa (người ăn trưa ở công ty vẫn ở office); lõi 10–17h, 18–20h là vùng xám. Bỏ phiếu theo số phút chồng lên khung, giờ địa phương (D18).
Căn cứ (EDA mục 24–26, 114 user có stay, 70 user đủ cặp): dời mốc đêm ±1 giờ đổi home của 2–5 user, thu hẹp đổi 11–19 user; tỉ lệ ở nơi làm việc ngày thường 0,39 (8h), 0,65 (9h), 0,78–0,85 (10–17h), 0,68 (18h), 0,46 (20h); giờ trưa không có chỗ lõm rõ, nên không có căn cứ để loại.
Hạn chế: 8:30 là nội suy, cuối tuần chỉ thấp hơn chứ chưa sạch, cặp nhà/văn phòng chọn bằng khung 10–16h nên đường cong có phần tự khẳng định.

### A11. Dữ liệu tối thiểu
Mốc 7 phiếu (`N_MIN_NIGHTS`, `N_MIN_WORKDAYS`, quy ước): dưới mức này vẫn trả home / office nhưng confidence để trống và bật cờ `few_nights` / `few_workdays` (D18). Mục 29 (hai nhóm rời nhau): 7 phiếu mỗi nhóm trùng nhau 63% (home) và 58% (office), 14 phiếu 77% và 75%, chưa mức nào đạt 81%; chỉ user có từ 14 phiếu (35% home, 28% office) nằm trong phép đo, nên có thể lạc quan cho user ít phiếu. Kết quả bỏ phiếu hiện tại trên dev: trung vị 7 đêm và 5,5 ngày làm việc có phiếu; chỉ 43 user đủ 14 đêm và 24 user đủ 14 ngày làm việc.

### A12. Gap-stay: khoảng trống khi đứng yên được tính vào stay
Nếu máy ngừng ghi rồi ghi lại ở cùng một chỗ (hai đầu khoảng trống trong bán kính stay so với điểm neo), coi như người dùng ở yên suốt khoảng trống. Stay chạy liền qua các file của cùng user, chỉ ngắt ở khoảng trống > 24 giờ (`MAX_GAP_S`, D16). Stay có khoảng trống > 30 phút có `source = "gap"` và `gap_min`.
Căn cứ (EDA mục 13): khoảng trống 6–12 giờ có 43,4% trường hợp hai đầu cách ≤ 200 m, khoảng 5–30 phút có 75–83%; khoảng trống > 24 giờ chỉ 10,3% hai đầu cách ≤ 100 m. Khoảng 90% giờ stay đến từ khoảng trống (người dùng thường tắt máy khi đứng yên).
Hạn chế: không phân biệt "ở yên, máy tắt" với "đi đâu đó rồi về đúng chỗ cũ".

### A13. Không có nhãn chuẩn
GeoLife không có nhãn home/office. Mọi kết quả chỉ có độ nhạy và độ ổn định, chưa có độ đúng. Không làm đánh giá thủ công (mentor chốt 2026-11-06); kết quả chỉ báo độ ổn định, kiểm trên nhóm test (D19). `confidence` là độ chắc của quy tắc, không phải xác suất đã hiệu chuẩn.

### A14. Tham số stay point: D = 200 m, T = 30 phút
Nguồn: Li et al. (2008), *Mining user similarity based on location history*, ACM SIGSPATIAL GIS, thuật toán ở Figure 2, tham số ở mục 5.1.2 ("timeThreh 30 minutes, distThreh 200 meters"). Thuật toán điểm neo trong `src/stays/detect.py`; điểm neo dùng `h1_mean` (D13).
Kiểm chứng bằng nhãn phương tiện (notebook 06, nhóm dev): chạy stay point trong các đoạn có nhãn đang di chuyển và đo thời gian bị nhận nhầm là stay. Ở D = 200 m, T = 30 phút: 10,08% (giảm khi T tăng, tăng khi D tăng; T = 30 phút cho ít nhất trong lưới T = 10/20/30). Phần lớn stay giả là đi loanh quanh trong một khu nhỏ (nhãn `walk`), không phải lỗi ngưỡng; nhận nhầm khi đang chạy xe thật rất nhỏ.
Giữ 200 m: D = 100 m nhận nhầm ít hơn nhưng làm mất khoảng một phần ba số đêm ở nhà (nối gap-stay: 27,7% so với 43,4%).
Giới hạn: chỉ đo nhận nhầm, không đo bỏ sót; chỉ 69/182 user có nhãn.

### A15. Bán kính địa điểm (v1): 200 m
Gom tham lam quanh stay neo dài nhất, bán kính 200 m (`src/places/cluster_v1.py`), bằng bán kính stay. Hạn chế: hai nơi gần nhau dưới 200 m bị gộp, địa điểm rộng hơn 200 m bị tách, kết quả phụ thuộc thứ tự neo. Nghi ngờ chưa kiểm: một nơi bị cắt đôi làm chênh lệch phiếu giữa hai nơi dẫn đầu thấp giả tạo; v2 dùng DBSCAN (CP2).
