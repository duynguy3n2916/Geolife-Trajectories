# Nhật ký quyết định (bản hiện hành)

**2026-11-07 :** mọi ngưỡng đã chọn trước ngày này và số liệu căn cứ (D5, D9, D13, D16, D18, D19, v.v.) đã bị xoá khỏi tài liệu, vì chúng được chọn trên bản chia cũ (có rò rỉ, D17) hoặc trên toàn bộ 182 user. Ngưỡng chọn lại ở `notebooks/tuning/` (chỉ nhóm validation), ghi vào đây và `assumptions.md` sau khi chạy. Các giá trị hằng số trong code hiện là **giá trị tạm để pipeline chạy**, chưa phải giá trị đã chọn. Chỉ giữ ở đây: quy trình, cách làm, và các lựa chọn không phải ngưỡng.

Mã D1, D2, ... giữ nguyên; mã đã bỏ (D6, D10, D11, D15) không dùng lại. Ngưỡng và giả định: `notes/assumptions.md`.

## Quy trình

### D2. Khảo sát mô tả tách khỏi bước chọn ngưỡng
Thứ tự: (1) khảo sát mô tả trên toàn bộ 182 user (`notebooks/survey/` 01–04), không chọn ngưỡng; (2) chia validation / test (D17); (3) chọn ngưỡng chỉ trên validation (`notebooks/tuning/` 05–13); (4) test chạy một lần (`notebooks/test/15_test`, D19). Ngưỡng chọn xong ghi ở `assumptions.md`, mỗi ngưỡng dẫn về mục EDA làm căn cứ.

### D1. Chuyển dữ liệu thô sang `data/interim` một lần
Đọc mọi file `.plt` bằng `read_plt`, ghi ra định dạng nhị phân; EDA và các bước lọc đều đọc từ đây. `data/interim` chỉ đổi định dạng, không lọc.

## Dữ liệu và làm sạch

### D3. Thứ tự các bước lọc, xử lý từng file `.plt`
(1) xóa lỗi dữ liệu (A2), (2) xử lý timestamp trùng (A3), (3) xóa outlier (A5, A6), (4) thêm giờ địa phương (A9). Không cắt segment: khoảng trống và cú nhảy không quay về được để nguyên, bước sau tự ngắt ở khoảng trống (A7) khi cần tính tốc độ hay quãng đường.

### D4. Chỉ xóa khi biết chắc điểm nào sai
Xóa chỉ với lỗi dữ liệu, bản trùng, và chuỗi đi ra rồi quay về (hai điểm A, B hai bên khớp nhau nên biết X sai). Cú nhảy một chiều không biết bên nào sai nên không xóa.

### D5. Lọc outlier theo chuỗi `A → X1..Xk → B`
**Chốt 2026-11-07:** xoá theo số điểm của chuỗi (N), k ≤ 5, không theo thời gian: đếm điểm không phụ thuộc tần suất ghi. Căn cứ và hạn chế: A6. Có chọn N = 3 hay 5 sau khi chạy lại tuning/07 trên bản chia mới thì ghi lại ở đây.

### D12. Giờ địa phương bằng thư viện múi giờ
`add_local_time` (`src/preprocess/local_time.py`) tra IANA bằng `timezonefinder` theo ô 0,5° (tại tâm ô, có cache) rồi đổi giờ bằng `zoneinfo`; thêm `tz_name`, `tz_offset_h`. Theo yêu cầu của mentor họp 3/11. Không kiểm thêm; ô 0,5° là xấp xỉ (A9).

## Stay point và địa điểm

### D7. Stay point theo Li et al. (2008), chạy liền qua khoảng trống
Thuật toán Li et al. (2008) chạy trên toàn bộ dữ liệu đã lọc của user (gộp các file, sắp theo thời gian), chỉ ngắt ở khoảng trống dài hơn max gap. Khác bài gốc: thời lượng và tâm tính trên các điểm thực sự nằm trong bán kính; stay ở cuối dữ liệu vẫn được ghi nhận. Chạy liền qua khoảng trống để giữ gap-stay (A12). D = 200 m, T = 30 phút (A14), max gap 24 giờ (D16): chốt 2026-11-07.

### D8. Gom địa điểm v1: tham lam quanh điểm neo
Stay dài nhất chưa gán làm tâm, gom mọi stay chưa gán trong bán kính (A15, 200 m); `place_id` đánh theo tổng thời gian, 0 là nơi ở lâu nhất. Đây là phiên bản heuristic cho CP1; v2 (DBSCAN) chỉ thay bước này.

### D9. Kiểm D, T bằng nhãn phương tiện
Giá trị khởi điểm của bài gốc; kiểm bằng tỷ lệ bị nhận nhầm là stay trong các đoạn có nhãn đang di chuyển (`tuning/09`, A14). Không quét lưới trên toàn bộ dữ liệu vì chậm và không có đáp án để chấm.

### D13. Điểm neo của stay point: `h1_mean`
**Chốt 2026-11-07: dùng `h1_mean`.** Căn cứ `tuning/10` (validation 115 user): giảm 47% số cặp stay bị tách (1.095 xuống 578), giảm 5,4% số stay; đổi lại nhận nhầm di chuyển tăng 1,0 điểm % (10,4% lên 11,4%) và bán kính 95% trung vị tăng 119 lên 157 m. Chọn vì ít tách stay hơn và dễ giải thích.
`detect.detect_stays_h1`, `detect.mean_center`: chạy Li, dời neo vào điểm GPS gần nhất với trung bình vĩ độ và trung bình kinh độ của stay Li (không trọng số), mở rộng hai phía, chỉ nhận nếu không ngắn hơn stay của Li. Các cách đã thử và bỏ trước đây (`h1_keep`, `h2`, `h3`, ngắt stay khi hai đầu khoảng trống xa nhau) không còn trong code; nếu cần so lại thì phải làm lại.

### D16. Max gap (`MAX_GAP_S`)
**Chốt 2026-11-07 (Duy): 24 giờ, là quy ước, không phải tối ưu.** Đo ở `tuning/11` (validation 115 user): tỉ lệ hai đầu khoảng trống gần nhau (≤ 200 m) giảm dần theo độ dài (62% ở 0,5–2 giờ, 28% ở 12–24 giờ, 20% ở 24–36 giờ), không có điểm gãy; cắt ở 12 giờ làm 22% user mất bằng chứng đêm và home đổi nơi ở 36% user; 24 giờ giữ 76,6% giờ đêm (trung vị). Không có đáp án để chứng minh một mức là đúng (A13); gán nhãn tay cũng phải suy từ chính dữ liệu GPS. Đo ở `tuning/11` (mục 2): bằng chứng đêm theo mức, độ nhạy khi đổi mức, tỉ lệ hai đầu khoảng trống gần nhau. Khi chọn phải ghi đúng là quy ước nằm trong vùng ổn định (nếu có), không nói là tối ưu.

### D20. Gom địa điểm v2: DBSCAN, `eps` = 200 m, `min_samples` = 1
**Chốt 2026-11-09: `eps` = 200 m; `min_samples` = 1.** `src/places/cluster_v2.py`, chọn ở `notebooks/tuning/14_place_eps.ipynb` (validation 115 user). v2 chỉ thay bước 6; stay point (bước 5) và bỏ phiếu (bước 7) giữ nguyên.
- **Cách gom:** `DBSCAN(eps, min_samples=1)`, tức hai stay cùng một địa điểm nếu nối được qua chuỗi stay mà mỗi cặp liền kề cách nhau ≤ `eps`. Không có điểm neo hay hình tròn, không phụ thuộc thứ tự, không có nhiễu (mọi stay có địa điểm, như v1). Viết bằng numpy, khớp scikit-learn trên dữ liệu giả lập.
- **Không có ngưỡng giờ hay số stay tối thiểu:** mỗi stay đã ≥ 30 phút (A14), ngưỡng phiếu ở bước 7 (A11) lo phần còn lại; tính cộng dồn giờ ở đây là tính trùng, và gap-stay làm một nơi qua ngưỡng chỉ nhờ một lần tắt máy.
- **Căn cứ `eps`** (bảng 1, 2 của notebook 14): stay của cùng một nơi home cách tâm p95 = 151 m, p99 = 196 m. Quét `eps` ∈ {100, 150, 200, 300, 500}: confidence home trung vị tăng mạnh đến 150 m rồi phẳng (v1 89,2; 150 m: 97,2; 200 m: 98,0; 300 m: 98,0), trong khi số user home đổi so với v1 (6, 6, 7, 9, 12), số user bị gộp home với office mới (1, 3, 3, 4, 6) và đường kính home p95 (468, 682, 798, 1062, 1676 m) tăng dần theo `eps`. 150 và 200 m chênh nhau khoảng 1 user nên không phân biệt được; chọn 200 m cho khớp D và A15 và phủ 99% stay. **Là quy ước trong vùng ổn định, không phải tối ưu.**
- **So với v1 ở 200 m:** office không đổi ở user nào; home cùng chỗ ở 108/115 user (93%). Trong 7 user đổi home: 2 user (042, 083) vốn `unstable_home` ở v1 (hai nơi cách nhau gần 3 km, phiếu ngang nhau); 4 user (078, 101, 007, 038) là `home_eq_office` ở cả hai bản, tâm dịch 231–456 m vì cụm to ra; 1 user (073) là gộp nhầm rõ ràng (v1: home và office cách 362 m; v2 gộp thành một cụm đường kính 881 m, dù 40 phiếu đêm và 29 phiếu ngày). Gộp mới tổng cộng 3 user (073, 083, 179); 083 và 179 chỉ có 4 và 7 phiếu ngày làm việc.
- **Hạn chế:** (1) không có nhãn (A13), nên chưa biết v2 đúng hơn hay sai hơn ở 7 user đổi. (2) Confidence tăng khi gộp cụm là hệ quả của cách tính (phiếu dồn vào ít nơi hơn), kể cả khi gộp nhầm; độ ổn định (chẵn/lẻ, nửa đầu/nửa sau) không đổi theo `eps`. Không dùng mức tăng confidence làm bằng chứng v2 tốt hơn. (3) Chaining: cụm home lớn nhất rộng 1070 m ở 200 m, và p95 đường kính đã 468 m ngay ở `eps` = 100 m (lớn hơn trần ~400 m của v1), nên đây là chuỗi stay dày chứ không chỉ do chọn `eps`. (4) `min_samples` > 1 (đếm số lần ghé, gồm chính stay đó) đã quét ở `eps` = 200 m (bảng 3, `tuning/14`, validation 115 user) và **không lợi**: stay bị coi là nhiễu 20,4% / 28,1% / 36,0% (`min_samples` = 2 / 3 / 5), số user mất home so với `min_samples` = 1 là 12 / 15 / 29 và mất office 6 / 9 / 18, gộp mới so với v1 tăng từ 3 lên 4 / 6 / 8, đường kính home p95 không giảm (798 lên 833 / 841 / 867 m). Cột "hết phiếu" giảm giả tạo vì user mất hết địa điểm được gắn cờ riêng. Nên giữ `min_samples` = 1.
- **Vì sao vẫn làm v2:** CP2 cần ít nhất hai version (heuristic và clustering); v2 sửa được về nguyên tắc lỗi phụ thuộc thứ tự và tròn cố định của v1 (D8, A15). Hai bản giống nhau ở 93% home và 100% office, nên là cặp version rủi ro thấp để demo deploy strategy.

## Chia dữ liệu và bước home/office

### D17. Chia validation / test theo user, là bước đầu tiên sau khảo sát
`src/eda/split.py`: chia theo user, không theo thời gian. Kết quả `data/split/users.csv`; mọi EDA chọn ngưỡng (notebook 05–13) chỉ đọc `split.val_users()`; pipeline làm sạch, stay, địa điểm vẫn chạy cho mọi user. Nhóm test dành cho đánh giá một lần (D19).

**Chia lại ngày 2026-11-07 (Duy chốt): đổi tên validation / test, gom user trùng file, cân bằng theo phân phối và nhãn, tách khảo sát và tuning.**
- *Vì sao chia lại:* bản chia đầu không xét việc một số user có file `.plt` giống hệt từng byte với user khác (khoảng 6–8% dữ liệu thô): 17/60 user test dính dữ liệu trùng với nhóm kia. Kiểm tra trùng chỉ so md5 file, không đọc vị trí hay giờ giấc, nên không phải chọn ngưỡng và làm được trên toàn bộ dữ liệu trước khi chia.
- *Cách chia (`split.py`, seed 20261107):* user có chung file (trực tiếp hoặc qua người khác) thuộc một cụm và vào cùng một nhóm. Chọn cách gán cụm bằng simulated annealing để phần test sát 1/3 ở các đại lượng: số user, số ngày, số file, số user có nhãn, số đoạn nhãn theo nhóm phương tiện (walk, bike, bus, car, rail, other), số user ở từng tứ phân vị số ngày. Chỉ dùng số đếm (tên file, dòng `labels.txt`, md5), không đọc quỹ đạo. Cụm có tổng số ngày vượt 1/6 tổng toàn bộ (cụm 15 user) cố định vào validation, vì nếu vào test thì một nhóm user chép lẫn nhau chiếm phần lớn test.
- *Lọc bản sao trước, rồi chia (Duy chốt 2026-11-07):* user gần như toàn bộ là bản sao (`mostly_copy`, từ 90% file chép từ user khác) bị loại trước khi chia (cột `excluded`, `group = excluded`), chỉ giữ một đại diện cho mỗi nhóm bản sao: user 057 đại diện cho 057/094/150 (giống nhau hoàn toàn, không có bản gốc); user 075 được giữ vì có 509 đoạn nhãn riêng (quy tắc `KEEP_LABELS = 100` đoạn nhãn). 10 user bị loại: 059, 070, 088, 094, 108, 109, 124, 127, 150, 156. Lý do: không đếm đôi cùng một dữ liệu (không phải rò rỉ: cụm luôn cùng một nhóm). Chỉ dùng md5 file và số dòng `labels.txt`.
- *Kết quả (172 user được chia):* **115 validation / 57 test**; test chiếm 33,1% user, 32,2% ngày, 32,9% file, 35,4% user có nhãn (23/65), 30,5% đoạn nhãn. Theo nhóm phương tiện: walk 28,4%, bike 35,5%, bus 38,7%, rail 39,8%, **car chỉ 16,2%** (car tập trung ở cụm 15 user nằm cố định trong validation; không cân được nếu không tách cụm). 18 cụm từ 2 user (52 user), không cụm nào bị tách. Survey 01–04 vẫn chạy trên toàn bộ 182 user. Notebook tuning 05–08 đã chạy trên bản chia trước nên phải chạy lại.
- *Hạn chế còn lại:* cụm 15 user chỉ nằm ở validation nên validation chứa nhiều dữ liệu của các user chép lẫn nhau (cụm 15 user), nên thống kê gộp ở validation lệch về nhóm đó. Mọi số và ngưỡng cũ thuộc bản chia cũ nên không dùng nữa.

### D14. Gap-stay ở bước home/office: không có quy tắc riêng theo mục đích
Giữ gap-stay như bước stay (A12), không áp quy tắc "gap qua đêm cho home, gap ban ngày cho office", không học giờ nghỉ của từng user; mọi gap-stay tham gia bỏ phiếu như stay thường, cờ ở D18 cho user thiếu bằng chứng. Đây là lựa chọn thiết kế (cho đơn giản); lý do dựa trên số đo cũ đã bỏ, nên **cần đo lại** ở `tuning/13` (mục 1, 2) trước khi coi là chốt.

### D18. Bỏ phiếu home / office theo ngày, khung theo dữ liệu, có confidence
Mã: `src/places/home_office_conf.py`, chạy `python -m src.places.home_office_conf` (mặc định nhóm validation, ghi `reports/home_office_v1_val.csv`; `--test` chỉ nhóm test theo D19, `--all` cả hai).
- **Khung (A10):** đêm cho home, ngày làm việc T2–T6 cho office; mốc giờ chốt 2026-11-07: đêm 20–7h, làm việc 9–18h (A10). Giờ địa phương, tính theo số phút chồng lên khung.
- **Phiếu:** mỗi đêm một phiếu home, mỗi ngày làm việc một phiếu office, cho nơi có nhiều phút nhất (ít nhất 60 phút, A11). Home là nơi nhiều phiếu đêm nhất; office là nơi nhiều phiếu ngày làm việc nhất. Nếu office trùng home thì `office = None`, cờ `home_eq_office`.
- **Lịch lễ:** `src/preprocess/calendar_cn.py` (ngày nghỉ T2–T6 và ngày làm bù T7/CN 2007–2012, sinh từ thư viện `chinesecalendar`, chưa đối chiếu nguồn gốc). Chỉ áp dụng cho user có vị trí trung vị của stay trong hộp thô quanh Trung Quốc; user khác dùng T2–T6. Chỉ ảnh hưởng phiếu office.
- **Confidence:** tính bằng %, lấy mẫu lại (bootstrap): bốc lại ngẫu nhiên, có hoàn lại, đúng số đêm (hoặc ngày làm việc) có phiếu của user, bỏ phiếu lại, lặp N lần (200, hạt giống 20261106); confidence = % lần vẫn ra cùng nơi (hoà thì chia đều). Một con số. Dưới số phiếu tối thiểu (A11, 7, chốt 2026-11-07 như quy ước): vẫn trả home / office, confidence để trống, cờ `few_nights` / `few_workdays`. Đây là độ chắc của quy tắc, không phải xác suất đúng (A13).
- **Cờ:** `no_stays`, `no_night`, `no_workday`, `few_nights`, `few_workdays`, `home_eq_office`, `unstable_home`, `unstable_office`.
- **Chưa làm:** giả định mỗi user một home cho cả thời gian dữ liệu (chuyển nhà chưa có cờ riêng; Duy không muốn thêm cờ `home_moved`); `cluster_v1` có thể cắt đôi một nơi (để v2 DBSCAN); chưa xử lý riêng ca đêm và WFH ngoài cờ `home_eq_office`.
- **Kết quả chạy:** chưa có (chạy lại sau khi tuning xong).

### D19. Kiểm tra trên nhóm test: chạy một lần sau khi khoá cấu hình
Chạy bằng `notebooks/test/15_test.ipynb` (T1 in cấu hình, T2–T4 đặt validation và test cạnh nhau). Quy trình:
1. **Khoá cấu hình:** ghi ngày khoá và toàn bộ giá trị đã chọn ở tuning vào đây.
2. **Chạy một lần:** `python -m src.places.home_office_conf --test` (ghi `reports/home_office_v1_test.csv`), lưu file riêng, không ghi đè kết quả validation.
3. **Đo đúng những thước đo đã dùng ở validation, đặt cạnh số validation:** tỉ lệ stay báo nhầm theo nhãn phương tiện; tỉ lệ có home / office và các cờ; phân bố confidence; nửa đầu / nửa sau trùng nơi theo mức confidence (notebook 13, mục 4).
4. **Không sửa gì sau khi xem số test.** Lệch nhiều so với validation thì ghi là hạn chế. Nếu vẫn sửa thì số test cũ không còn là số test, phải ghi rõ.

**Trạng thái: chưa chạy** (lần chạy ngày 2026-11-06 thuộc bản chia cũ nên đã bỏ). Test chỉ đo độ ổn định và khả năng lặp lại trên user mới, không đo độ đúng vì không có nhãn home / office (A13). Không làm gán tay (mentor chốt 2026-11-06).
