# Giả định và ngưỡng (bản hiện hành)

Mã A1, A2, ... giữ nguyên để code và notebook tham chiếu; mã A8 đã bỏ, không dùng lại.

**Trạng thái (2026-11-07, Duy yêu cầu làm lại từ đầu):** tất cả ngưỡng đã chốt (A3, A5, A6, A7 ở tuning 05–08; A10, A12, A14 ở tuning 09–12; A11, A15 là quy ước, A11 kiểm lại ở tuning/13).
 mọi ngưỡng được chọn trước ngày này (và các số liệu căn cứ) đã bị xoá khỏi tài liệu, vì chúng được chọn trên bản chia dữ liệu cũ (có rò rỉ, D17) hoặc trên toàn bộ 182 user. Các ngưỡng sẽ được đo lại ở `notebooks/tuning/` (chỉ nhóm validation) rồi mới ghi vào đây cùng số liệu chạy lại.
Các hằng số trong code (`MAX_GAP_S`, `DIST_M`, `TIME_S`, `DUP_MAX_DIST_M`, `MIN_VOTE_MIN`, `N_MIN_NIGHTS`...) hiện là **giá trị tạm để pipeline chạy được, chưa phải giá trị đã chọn**; sửa lại khi tuning xong.
"Mục N" (đánh số riêng trong từng notebook, ghi kèm tên notebook) là mục trong `notebooks/survey/` (khảo sát toàn bộ dữ liệu, chỉ mô tả), `notebooks/tuning/` (chọn ngưỡng, chỉ nhóm validation) hoặc `notebooks/test/` (bảng ở README). Quyết định: `notes/decisions.md`.

## Tóm tắt

| Mã | Nội dung | Giá trị | Trạng thái |
|---|---|---|---|
| A1 | Timestamp trong .plt và labels.txt là UTC | UTC (User Guide GeoLife 1.3) | dữ kiện tài liệu |
| A2 | Điểm lỗi dữ liệu | tọa độ ngoài phạm vi; thời gian ngoài thời gian thu thập theo User Guide (04/2007–08/2012) | dữ kiện tài liệu |
| A3 | Timestamp trùng | giữ dòng đầu; xóa cả nhóm nếu có dòng lệch > 83 m | chốt 2026-11-07 (tuning/05) |
| A4 | Khoảng lấy mẫu điển hình | mô tả | đo lại ở survey/02 |
| A5 | Tốc độ nghi là outlier | > 300 km/h | chốt 2026-11-07 (tuning/06) |
| A6 | Chuỗi outlier bị xóa | k ≤ 5 điểm (đếm điểm, N = 5) | chốt 2026-11-07 (tuning/07) |
| A7 | Khoảng trống (máy tắt, mất tín hiệu) | > 30 phút | chốt 2026-11-07 (tuning/06, 08) |
| A9 | Giờ địa phương | múi giờ IANA (`timezonefinder`, ô 0,5°) + `zoneinfo` | cách làm (thư viện chuẩn), không phải ngưỡng |
| A10 | Khung giờ home / office | đêm 20–7h, làm việc 9–18h (T2–T6) | chốt 2026-11-07 (tuning/12) |
| A11 | Dữ liệu tối thiểu để suy ra home/office | 7 đêm / 7 ngày làm việc; 60 phút/ngày trong khung | chốt 2026-11-07 như quy ước; kiểm lại ở tuning/13 |
| A12 | Gap-stay: khoảng trống khi đứng yên tính vào stay | max gap | giả định giữ; max gap 24 giờ, chốt 2026-11-07 (tuning/11) |
| A13 | Không có nhãn home/office chuẩn | không đánh giá thủ công (mentor, 06/11); chỉ đo độ ổn định | giữ |
| A14 | Tham số stay point | D = 200 m, T = 30 phút | chốt 2026-11-07 (tuning/09) |
| A15 | Bán kính gom địa điểm (v1) | 200 m (bằng D) | chốt 2026-11-07 như quy ước |
| A16 | Gom địa điểm v2 (DBSCAN) | `eps` 200 m, `min_samples` 1 | chốt 2026-11-09 như quy ước (tuning/14) |

## Chi tiết

### A1. Timestamp là UTC
Theo User Guide GeoLife 1.3. Kiểm chứng ở `survey/03` mục 2 (số điểm theo giờ) và `survey/02` mục 2 (tốc độ nhãn `walk`); chạy lại để lấy số. Mọi phép tính khoảng thời gian dùng UTC; giờ địa phương chỉ dùng cho phân tích theo giờ trong ngày.

### A2. Điểm lỗi dữ liệu (xóa)
Xóa điểm có lat ngoài [-90, 90], lon ngoài [-180, 180], timestamp không đọc được, hoặc ngoài thời gian thu thập theo User Guide (04/2007 đến 08/2012). Làm đầu tiên vì một timestamp sai làm sai mọi tốc độ quanh nó. Số điểm lỗi: `survey/01`, mục 1, 3.

### A3. Timestamp trùng
Nhóm dòng cùng timestamp trong cùng file. **Chốt 2026-11-07 (Duy):** giữ dòng đầu của nhóm; nếu có dòng cách dòng đầu hơn 83 m (`DUP_MAX_DIST_M` = 300 km/h × 1 giây) thì bỏ cả nhóm. Phải xử lý trước khi tính tốc độ (dt = 0).
Căn cứ (`tuning/05`, validation 115 user, 13.107.562 dòng thô): 60.998 nhóm trùng, 114.592 dòng thừa (0,87%); 99,1% dòng khác tọa độ lệch ≤ 10 m so với dòng đầu; lấy tâm nhóm thay dòng đầu chỉ dời 0–0,54 m ở 3 user nhiều trùng nhất nên không đổi gì; nhóm lệch > 83 m chỉ 129 nhóm, 362 dòng, 11 user (0,0028% dữ liệu); ở nhóm đó dòng đầu khớp quỹ đạo chỉ 41,1% số nhóm (không biết dòng nào sai nên bỏ cả nhóm, D4). So với chỉ giữ dòng đầu, bỏ nhóm lệch xa bỏ thêm 129 dòng. Mốc 83 m phụ thuộc A5. Không dùng stay point để chọn quy tắc này (D, T chưa chọn ở bước này, Duy chỉ ra 2026-11-07); nếu muốn kiểm độ nhạy của stay point theo cách giữ dòng thì làm bây giờ khi D, T đã chốt (`tuning/09`), chỉ như kiểm tra, không để chọn.
Chưa xử lý: file giống hệt giữa các user (mô tả ở `survey/01` mục 3.4, dùng để chia nhóm, D17).

### A4. Khoảng lấy mẫu
Mô tả phân phối dt (`survey/02`, mục 1). Nhóm "ghi thưa" dùng khi kiểm tra ngưỡng outlier (tuning/07); mốc phân nhóm đọc từ phân phối đó.

### A5. Ngưỡng tốc độ outlier
**Chốt 2026-11-07 (Duy): 300 km/h.** Mốc vật lý, không phải điểm gãy của dữ liệu. Căn cứ: tàu có p99,9 = 237 km/h (`survey/02`, mục 2), máy bay trung vị 668 km/h, nên 300 nằm giữa hai nhóm. `tuning/06` (mục 1, validation 115 user): số bước (dt ≤ 10 s) vượt 250 / 300 / 350 km/h là 12.203 / 11.567 / 11.071, giảm chậm, **không có vùng trũng rõ**, nên chọn trong khoảng 250–350 không đổi nhiều (chênh khoảng 9%). Không thể chỉ dựa vào tốc độ vì máy bay vượt mọi ngưỡng, nên cần thêm điều kiện "đi ra rồi quay về" (A6).

### A6. Chuỗi outlier bị xóa
Chuỗi `A → X1..Xk → B`: bước vào và bước ra đều nhanh hơn ngưỡng A5, và A → B không vượt ngưỡng đó. **Chốt 2026-11-07 (Duy): xoá chuỗi có k ≤ 5 điểm (đếm điểm, N = 5, không thêm điều kiện thời gian).** Căn cứ (`tuning/07`, validation 115 user): tìm được 572 chuỗi (152.035 điểm) ở 53 user; quy tắc điểm gập chọn N = 3, nhưng vùng N = 3–10 khá phẳng (tăng thêm 27 / 17 điểm mỗi mức N), và bước 7: N = 3 xoá 331 chuỗi / 354 điểm, N = 5 xoá thêm 11 chuỗi / 50 điểm; trong 11 chuỗi thêm đó 10 là lỗi (tốc độ 323–40.504 km/h, không phải máy bay; tàu tối đa 237 km/h) và 1 là máy bay thật (user 128). Đếm điểm không phụ thuộc tần suất ghi: lọc theo T (30 giây) gần như không bắt chuỗi nào ở nhóm ghi thưa.
Hạn chế đã biết: N = 5 xoá 2 chuỗi trong đoạn nhãn máy bay (N = 3 xoá 1), cả hai ở user 128; chuỗi dài hơn 5 điểm được giữ.

### A7. Khoảng trống
Bước có dt lớn hơn ngưỡng là khoảng trống, không phải bước di chuyển; không xóa điểm. Dùng để không dò outlier qua khoảng trống và để nhận ra gap-stay (A12). **Chốt 2026-11-07 (Duy): 30 phút.** Căn cứ (`tuning/08`, validation 115 user): khoảng cách trung vị giữa hai đầu khoảng trống tăng từ 29,3 m (10–30 phút) lên 87,5 m (30–60 phút), bước nhảy rõ nhất giữa các mốc; tỉ lệ hai đầu cách ≤ 200 m giảm từ 74,8% xuống 62,1%. Không có điểm gãy sắc, và 30 phút cũng là mốc của bài gốc stay point (A14). Số khoảng trống mỗi ngày có dữ liệu (trung vị) > 30 phút là 2,0 (`tuning/06`, mục 2).

### A9. Giờ địa phương
Tra tên múi giờ IANA từ tọa độ bằng `timezonefinder` theo ô lưới 0,5° (tra tại tâm ô, có cache), đổi giờ bằng `zoneinfo`. Điểm không tra được dùng `Etc/GMT`. Thêm cột `tz_name`, `tz_offset_h`. Ranh giới múi giờ và giờ mùa hè lấy từ thư viện chuẩn, không kiểm thêm (Duy chốt 2026-11-06). Phần xấp xỉ của mình chỉ là ô 0,5° (ô vắt qua biên giới có thể sai múi giờ cho vài điểm). Hạn chế đã biết: điểm ở Tân Cương ra `Asia/Urumqi` (UTC+6, giờ chính thức là Bắc Kinh). Phân bố điểm theo vùng: `survey/03`.

### A10. Khung giờ home / office
**Chốt 2026-11-07 (Duy): đêm 20–7h, làm việc 9–18h.** Căn cứ `tuning/12` (validation 108 user có stay): các khung đêm lân cận đổi home ở 0–4 user (20–7h: 0 user đổi so với khung gốc, 19–7h: 4, 21–7h: 4); khung làm việc 9–18h cho 0 user đổi home và 0 user đổi office, trong khi 8–19h đổi office 6 user, 10–19h đổi 9 user. Hạn chế: cặp home/office dùng để đọc khung giờ có phần tự khẳng định (A13).
 Cách làm đã định (D18): đêm cho home, ngày làm việc T2–T6 cho office, bỏ phiếu theo số phút chồng lên khung, giờ địa phương. Mốc giờ cụ thể chọn ở `tuning/12` (mục 1–3). Căn cứ ngoài dữ liệu có thể dùng khi chọn: Quy định của Quốc vụ viện về giờ làm của người lao động (1995), Điều 3 (8 giờ/ngày, 40 giờ/tuần) và Điều 7 (nghỉ thứ Bảy, Chủ nhật) (https://lehmanlaw.com/resource-centre/laws-and-regulations/labor/state-council-regulations-on-working-hours-of-employees-1995.html); khảo sát sử dụng thời gian Bắc Kinh của Cục Thống kê (đi lại khoảng 1 giờ 29 phút/ngày) (https://yicaiglobal.com/news/beijingers-work-longer-office-hours-than-a-decade-ago-nbs-survey-finds). Hạn chế phải ghi khi chọn: cặp nhà/văn phòng dùng để đọc khung giờ có phần tự khẳng định.

### A11. Dữ liệu tối thiểu
**Chốt 2026-11-07 (Duy): 7 phiếu (đêm hoặc ngày làm việc), và 60 phút/ngày trong khung mới có phiếu; là quy ước.** Ở `tuning/12`, 30 / 59 / 73 / 83 trên 108 user có dưới 3 / 7 / 14 / 30 đêm, nên 7 phiếu gắn cờ khoảng 55% user. `tuning/13` (mục 3, validation 115 user): không có điểm gãy; hai nửa phiếu chọn cùng nơi home 58,4% ở k = 7 và 71% ở k = 14 (không đạt 81%), office 65% ở k = 7; nên 7 vẫn là quy ước. Cách dùng: đủ 7 đêm thì home có confidence, đủ 7 ngày làm việc thì office có confidence; thiếu thì vẫn trả nơi thắng nhưng không có confidence và gắn cờ `few_nights` / `few_workdays`. Trên validation: 59 user có confidence home, 33 có confidence office. Confidence nửa đầu từ 90% giữ nguyên nơi ở nửa sau 66,7% (home, 40 user), dưới 70% là 20%; tương quan hạng 0,40; không phải xác suất đúng (A13).
 Cách làm đã định (D18): ít phiếu hơn mức tối thiểu thì vẫn trả home / office nhưng confidence để trống và bật cờ `few_nights` / `few_workdays`, vì với rất ít phiếu bốc lại luôn ra 100%. Mức tối thiểu chọn ở `tuning/13` (mục 3); nếu không có điểm gãy thì ghi rõ là quy ước.

### A12. Gap-stay
Nếu máy ngừng ghi rồi ghi lại ở cùng một chỗ (hai đầu khoảng trống trong bán kính stay so với điểm neo), coi như người dùng ở yên suốt khoảng trống. Stay chạy liền qua các file của cùng user, chỉ ngắt ở khoảng trống dài hơn max gap (`MAX_GAP_S` = 24 giờ, chốt 2026-11-07, D16). Stay có khoảng trống có `source = "gap"` và `gap_min`. Phần giờ stay đến từ khoảng trống và mức hai đầu gần nhau: đo ở `tuning/08` (mục 1) và `tuning/11` (mục 1, 2).
Hạn chế: không phân biệt "ở yên, máy tắt" với "đi đâu đó rồi về đúng chỗ cũ".

### A13. Không có nhãn chuẩn
GeoLife không có nhãn home/office. Mọi kết quả chỉ có độ nhạy và độ ổn định, chưa có độ đúng. Không làm đánh giá thủ công (mentor chốt 2026-11-06); kết quả chỉ báo độ ổn định, kiểm trên nhóm test (D19). `confidence` là độ chắc của quy tắc, không phải xác suất đã hiệu chuẩn.

### A14. Tham số stay point: D, T
**Chốt 2026-11-07 (Duy): D = 200 m, T = 30 phút.** Căn cứ `tuning/09` (42 user có nhãn): nhận nhầm di chuyển là stay 10,4% thời gian ở D = 200 m, T = 30 phút (D = 100: 6,3%; D = 300: 13,9%); T = 10 phút lên 23,5%, T = 20 phút 15,0%. Trùng giá trị bài gốc, nằm giữa các mức đã thử. Giới hạn: chỉ đo nhận nhầm, không đo bỏ sót. Giá trị khởi điểm của bài gốc: Li et al. (2008), *Mining user similarity based on location history*, ACM SIGSPATIAL GIS, Figure 2 và mục 5.1.2 (distThreh 200 m, timeThreh 30 phút); bài nêu giá trị nhưng không giải thích vì sao chọn. Kiểm bằng nhãn phương tiện ở `tuning/09`: chạy stay point trong các đoạn có nhãn đang di chuyển và đo thời gian bị nhận nhầm là stay. Giới hạn: chỉ đo nhận nhầm, không đo bỏ sót; chỉ một phần user có nhãn. Thuật toán điểm neo ở `src/stays/detect.py` (neo `h1_mean`, chốt 2026-11-07, D13).

### A15. Bán kính địa điểm (v1)
**Chốt 2026-11-07 (Duy): 200 m, bằng D, là quy ước, chưa có số đo riêng.**
Chưa chọn. Gom tham lam quanh stay neo dài nhất (`src/places/cluster_v1.py`). Hạn chế: hai nơi gần nhau dưới bán kính bị gộp, địa điểm rộng hơn bị tách, kết quả phụ thuộc thứ tự neo; nghi ngờ chưa kiểm: một nơi bị cắt đôi làm chênh lệch phiếu giữa hai nơi dẫn đầu thấp giả tạo. v2 dùng DBSCAN (CP2).

### A16. Tham số gom địa điểm (v2)
**Chốt 2026-11-09 (Duy): `eps` = 200 m, `min_samples` = 1, là quy ước trong vùng ổn định (150–200 m), chưa có số đo cho thấy hơn 150 m.** `src/places/cluster_v2.py` (`DBSCAN`, viết bằng numpy). Căn cứ và hạn chế: D20 (`tuning/14`). `min_samples` = 1 vì mỗi stay đã ≥ 30 phút (A14); ngưỡng phiếu ở A11. Đã quét 2, 3, 5 (D20): mất home / office ở nhiều user hơn và gộp mới không giảm, nên giữ 1. Cắt đôi một nơi (nghi ngờ ở A15) chưa có chỉ số riêng; chaining (gộp home với office) là rủi ro chính của v2.
