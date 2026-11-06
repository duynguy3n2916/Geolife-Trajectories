# Nhật ký quyết định (bản hiện hành)

Chỉ giữ các quyết định đang áp dụng. Ngưỡng và căn cứ số liệu: `notes/assumptions.md`. Mã D1, D2, ... giữ nguyên để code, notebook và slide còn tham chiếu được; các mã đã bỏ (D6, D10, D11, D15) không dùng lại. Bản đầy đủ trước khi gọn (có phương án đã thử và bỏ) lưu ngoài dự án: `notes_old/decisions_truoc_gon_2026-11-05.md`.

## Dữ liệu và làm sạch

### D1. Chuyển dữ liệu thô sang `data/interim` một lần
Đọc mọi file `.plt` bằng `read_plt`, ghi ra định dạng nhị phân; EDA và các bước lọc đều đọc từ đây. `data/interim` chỉ đổi định dạng, không lọc.

### D2. EDA mô tả tách khỏi bước chọn ngưỡng
Notebook 01, 02, 04, 05 chỉ mô tả, không gắn ngưỡng. Ngưỡng được chọn và ghi ở `assumptions.md`, mỗi ngưỡng dẫn về mục EDA làm căn cứ.

### D3. Thứ tự các bước lọc, xử lý từng file `.plt`
(1) xóa lỗi dữ liệu (A2), (2) xử lý timestamp trùng (A3), (3) xóa outlier (A5, A6), (4) thêm giờ địa phương (A9). Không cắt segment: khoảng trống và cú nhảy không quay về được để nguyên, bước sau tự ngắt ở khoảng trống > 30 phút (A7) khi cần tính tốc độ hay quãng đường.

### D4. Chỉ xóa khi biết chắc điểm nào sai
Xóa chỉ với lỗi dữ liệu, bản trùng, và chuỗi đi ra rồi quay về (hai điểm A, B hai bên khớp nhau nên biết X sai). Cú nhảy một chiều không biết bên nào sai nên không xóa.

### D5. Lọc outlier theo số điểm của chuỗi (N), không theo thời gian
Xóa chuỗi `A → X1..Xk → B` khi k ≤ 5 (A6). Đếm điểm không phụ thuộc tần suất ghi, còn đếm theo giây bỏ sót hết nhóm ghi thưa.
Mốc 5 chọn trên 182 user trước khi chia dev / test. Chạy lại notebook 03 trên dev (2026-11-06): 327 chuỗi ở 59 user; quy tắc "bậc ngay trước chỗ số điểm xoá thêm tăng gấp đôi" chọn N = 2 (N = 3 xoá thêm ×2,5). Duy giữ N = 5 vì khác biệt chỉ 95 điểm (N = 5 xoá 109, N = 2 xoá 14) trên 16,9 triệu điểm, không đổi được stay hay home / office, còn đổi N phải chạy lại toàn bộ pipeline. Pipeline xoá 115 điểm ở 17 user dev (lặp tối đa 5 vòng).

## Stay point và địa điểm

### D7. Stay point theo Li et al. (2008), chạy liền qua khoảng trống
D = 200 m, T = 30 phút (A14), chạy trên toàn bộ dữ liệu đã lọc của user (gộp các file, sắp theo thời gian), chỉ ngắt ở khoảng trống > 24 giờ (D16). Khác bài gốc: thời lượng và tâm tính trên các điểm thực sự nằm trong bán kính; stay ở cuối dữ liệu vẫn được ghi nhận. Chạy liền qua khoảng trống để giữ gap-stay (A12), nếu không mất khoảng 90% giờ stay.

### D8. Gom địa điểm v1: tham lam quanh điểm neo
Stay dài nhất chưa gán làm tâm, gom mọi stay chưa gán trong 200 m (A15); `place_id` đánh theo tổng thời gian, 0 là nơi ở lâu nhất. Đây là phiên bản heuristic cho CP1; v2 (DBSCAN) chỉ thay bước này.

### D9. Chọn D, T theo bài gốc, kiểm chứng bằng nhãn phương tiện
Giữ D = 200 m, T = 30 phút; kiểm bằng tỷ lệ bị nhận nhầm là stay trong các đoạn có nhãn đang di chuyển (notebook 06, A14). Không quét lưới trên toàn bộ dữ liệu vì chậm (khoảng 2 giờ) và không có đáp án để chấm.

### D12. Giờ địa phương bằng thư viện múi giờ
`add_local_time` (`src/preprocess/local_time.py`) tra IANA bằng `timezonefinder` theo ô 0,5° (tại tâm ô, có cache) rồi đổi giờ bằng `zoneinfo`; thêm `tz_name`, `tz_offset_h` (số thực). Theo yêu cầu của mentor họp 3/11. Cần `timezonefinder` và `tzdata`. Chưa kiểm trên dữ liệu thật (A9).

### D13. Điểm neo `h1_mean` thay cho Li, đã nằm trong `detect.py` (đổi 2026-11-06, Duy chốt)
Mặc định `--method h1_mean` (`detect.detect_stays_h1`, `detect.mean_center`): chạy Li, dời neo vào **điểm GPS gần nhất với trung bình vĩ độ và trung bình kinh độ** của stay Li (không trọng số), mở rộng hai phía trong D, chỉ nhận nếu không ngắn hơn stay của Li. D, T không đổi. Chọn vì dễ giải thích nhất trong các cách có kết quả tương đương.
- **Căn cứ (notebook 07 mục 21.4–21.5 bản trước, nhóm dev 122 user, 47 user có nhãn):** stay bị tách / 100 stay 8,7 (Li) xuống 4,8; số stay 12.312 xuống 11.720; tổng giờ stay 56.656 lên 57.323; nhận nhầm trên đoạn có nhãn 10,08% lên 10,94% (+0,86 điểm, xe 2,31% lên 2,45%); 92,1% user giữ địa điểm 1 (lệch < 100 m so với Li), 83,6% giữ địa điểm 2; tâm địa điểm 1 lệch trung vị 18,5 m. Đạt ba tiêu chí của 21.3. So sánh nội bộ, không có đáp án (A13). Notebook 07 viết lại theo `h1_mean`; chạy lại để xác nhận số.
- **Đã thử và bỏ (code đã xoá):**
  - `h1_keep`: neo = điểm gần trung vị có trọng số thời gian (trọng số = thời gian đến điểm kế tiếp, chặn 30 phút). Trên cùng nhóm: tách 5,0 / 100 stay, nhận nhầm 10,74%, địa điểm 1 giữ 94,7%, địa điểm 2 giữ 89,1%. Kết quả gần như `h1_mean` (neo hai cách lệch trung vị 63,6 m nhưng chỉ 6,1% user đổi địa điểm 1 giữa hai cách); bỏ vì trọng số và mức chặn 30 phút khó giải thích và chưa có căn cứ đo.
  - `h2` (neo lưới 1 phút) và `h3` (neo chỗ dày điểm nhất): đổi địa điểm đứng đầu của khoảng 19% user, stay giả tăng 2,5–3,3 điểm % (182 user).
  - Ngắt stay khi hai đầu khoảng trống cách nhau > 200 m (`h1_keep_g200`): 19% user đổi địa điểm 1; hai đầu xa nhau phần lớn là lúc đang đi.

### D16. Max gap 24 giờ (`MAX_GAP_S`): quy ước nằm giữa một vùng ổn định, chưa chứng minh là đúng
Giữ 24 giờ: không nối khoảng trống dài hơn, không cắt ngắn hơn. Đây là **quy ước**, không có đáp án để chứng minh (A13); gán nhãn tay cũng phải suy từ chính dữ liệu GPS nên không chuẩn hơn. Căn cứ (notebook 08, mục 23, nhóm dev 122 user):
- **Dưới 20 giờ mất bằng chứng đêm (23.2, chuẩn 72 giờ):** 12 giờ có 28 user mất hẳn bằng chứng đêm, giờ đêm trung vị còn 42,2%; 8 giờ có 51 user, giờ đêm trung vị còn 7,2%; 20 và 24 giờ chỉ 13 và 12 user.
- **Vùng 20–36 giờ phẳng (23.4, chạy lại với neo h1_mean 2026-11-06):** chuyển 24 giờ sang 20 hoặc 36 giờ chỉ đổi home của 2,1–4,2% user; office đổi 6,1% (20 giờ) và 9,2% (36 giờ); sang 48 giờ đổi home 5,3–8,2%, office 10,2–12,0%; sang 12 giờ đổi home 12,9–21,3%, office 11,7–15,3%. 24 giờ nằm giữa vùng ổn định, nhưng 20 giờ cũng vậy; 36 giờ phẳng với home, kém hơn với office. Địa điểm 1 nhạy hơn (24 so với 20 giờ đổi 9,6%, so với 36 giờ 18,4%).
- **Khoảng trống dài (23.1):** tỉ lệ hai đầu cách nhau ≤ 200 m giảm dần: 63% (0,5–1 giờ), 39% (8–12 giờ), 30% (12–24 giờ), 20% (24–36 giờ), 17% (48–72 giờ). Không có điểm gãy rõ ở 24 giờ.
- **Khoảng trống dài so với home GPS (23.3, 14 user):** trong số khoảng trống hai đầu gần nhau, tỉ lệ cả hai đầu ở home là 52,4% (12–24 giờ), 37,5% (24–36 giờ, n = 48), 52,1% (36–48 giờ, n = 48), 40% (48–72 giờ, n = 20). Không thấy khoảng trống trên 24 giờ kém hơn, nhưng mẫu nhỏ nên không kết luận; office chỉ 6 user.
- **Lập luận quy trình:** khoảng trống trên 24 giờ bỏ qua trọn một đêm nên không gán được cho phiếu home của đêm nào.
- **Đã thử, bỏ khỏi notebook vì không giúp chọn được mức:** nhận nhầm theo nhãn và xoá khoảng trống nhân tạo (kết quả phẳng theo độ dài); dự đoán sang giai đoạn khác (home 0,24–0,27, office 0,15–0,16, phẳng giữa 12–48 giờ, có thiên lệch sẵn cho mức nhỏ); khoảng trống trùng nơi thường lệ (không mức nào đạt, mẫu trên 24 giờ chỉ 17 khoảng); phân vị độ dài khoảng trống theo user (24 giờ ứng với khoảng p75–p80, p90 từ 14,6 đến 118,7 giờ giữa các user, nên không suy được ngưỡng chung). Tiêu chí cũ "đổi ≤ 5% user so với 24 giờ" cũng bỏ: so với chính mốc 24 giờ là vòng tròn.

## Chia dữ liệu và bước home/office

### D17. Chia dev / test theo user, là bước đầu tiên
`src/eda/split.py`: chia theo user, không theo thời gian; hạt giống 20261105, 1/3 vào test, phân tầng theo tứ phân vị số ngày dữ liệu × có `labels.txt`. Kết quả `data/split/users.csv`: 122 dev, 60 test (labeled: 47 dev, 22 test). Chỉ đọc tên file `.plt` thô nên chạy được trước mọi EDA. Mọi EDA chọn ngưỡng (notebook 01–10) chỉ đọc `split.dev_users()`; pipeline làm sạch, stay, địa điểm vẫn chạy cho mọi user. Nhóm test dành cho nhãn gán tay và đánh giá một lần, cách dùng ở D19.

### D14. Gap-stay ở bước home/office: không có quy tắc riêng theo mục đích
Giữ gap-stay như bước stay (A12), không áp quy tắc "gap qua đêm cho home, gap ban ngày cho office", không học giờ nghỉ của từng user. Home/office được bỏ phiếu theo D18, mọi gap-stay tham gia như stay thường; cờ ở D18 cho user thiếu bằng chứng. Căn cứ (notebook 08, 10): giờ đêm và giờ hành chính của phần lớn user gần như toàn là gap; đáp án từ GPS quá ít user đủ giờ (21 user cho home, 7 cho office) và thiên lệch; học giờ nghỉ không ổn định hơn khung cố định và làm home của 20–23% user, office của 46–48% user đổi nơi (174 user).

### D18. Bỏ phiếu home / office theo ngày, khung theo dữ liệu, có confidence
Mã: `src/places/home_office_conf.py`, chạy `python -m src.places.home_office_conf` (mặc định nhóm dev, ghi `reports/home_office_v1_dev.csv`; `--test` chỉ nhóm test theo D19, `--all` cả hai).
- **Khung (A10):** đêm 20–7h mọi ngày; ngày làm việc T2–T6, 8:30–18:00 liền (không loại giờ trưa: đường cong ở nơi làm việc không lõm ở 12–13h, người ăn trưa ở công ty vẫn ở office), vùng xám 18–20h. Giờ địa phương, tính theo số phút chồng lên khung.
- **Phiếu:** mỗi đêm một phiếu home, mỗi ngày làm việc một phiếu office, cho nơi có nhiều phút nhất (ít nhất 60 phút). Home là nơi nhiều phiếu đêm nhất; office là nơi nhiều phiếu ngày làm việc nhất. Nếu office trùng home thì `office = None`, cờ `home_eq_office`.
- **Lịch lễ:** `src/preprocess/calendar_cn.py` (105 ngày nghỉ T2–T6, 38 ngày làm bù T7/CN, 2007–2012, sinh từ thư viện `chinesecalendar`, chưa đối chiếu nguồn gốc). Chỉ áp dụng cho user có vị trí trung vị của stay trong hộp thô quanh Trung Quốc (lat 18–54, lon 73–135); user khác dùng T2–T6. Chỉ ảnh hưởng phiếu office.
- **Confidence (đổi 2026-11-06, Duy chốt):** tính bằng %, lấy mẫu lại (bootstrap): bốc lại ngẫu nhiên, có hoàn lại, đúng số đêm (hoặc ngày làm việc) có phiếu của user, bỏ phiếu lại, lặp 200 lần; confidence = % lần vẫn ra cùng nơi (hoà thì chia đều). Một con số, tự gộp tỉ lệ phiếu, chênh lệch với nơi thứ hai và số phiếu. **Dưới 7 phiếu:** vẫn trả home / office, nhưng confidence để trống và có cờ `few_nights` / `few_workdays`, vì với ít phiếu cùng một nơi bốc lại luôn ra 100% (1 đêm cũng như 30 đêm). Bỏ vùng cao / giữa / thấp. Các cột `*_share`, `*_margin`, `*_stable`, `*_gps` chỉ báo cáo; `*_stable` < 0,5 bật cờ `unstable_*`. Đã thử và bỏ: min của 4 thành phần (tỉ lệ phiếu, chênh lệch, kiểm định dấu, ổn định), vì khó giải thích và một thành phần (chênh lệch) quyết định gần hết. Đây là độ chắc của quy tắc, không phải xác suất đúng (A13).
- **Cờ:** `no_stays`, `no_night`, `no_workday`, `few_nights`, `few_workdays`, `home_eq_office`, `unstable_home`, `unstable_office`.
- **Kết quả trên dev (122 user, chạy 2026-11-06: neo h1_mean, confidence %):** 103 có home, 62 có office, 57 có cả hai, 31 `home_eq_office`, 28 user không dính cờ. Trung vị 9 đêm có phiếu ở user có home. Confidence có ở 58 user home (trung vị 96,8%; 16 dưới 70%, 9 từ 70–90%, 33 từ 90%) và 40 user office (trung vị 92,7%; 11 / 6 / 23). 56 user `few_nights`, 61 `few_workdays`: thiếu phiếu là hạn chế lớn nhất. Xem `notebooks/eda/10_gap_home_office.ipynb` mục 31.
- **Chưa làm:** giả định mỗi user một home cho cả thời gian dữ liệu; chuyển nhà không có cờ riêng (notebook 10 mục 30, 2026-11-06: trong 8 user confidence nửa đầu ≥ 90% mà nửa sau đổi home, 4 user chuyển nhà thật, 1 user hai nơi cách 210 m, 1 user nửa sau chỉ 5 đêm; bỏ 6 user này thì 17/19 trùng); mốc 7 phiếu vẫn là quy ước (A11); `cluster_v1` có cắt đôi một nơi (đã kiểm 2026-11-06 trên dev: nơi thắng và nơi nhì cách nhau ≤ 300 m ở 9/77 user home và 6/78 user office có từ hai nơi được phiếu; chỉ khoảng 4 user home (071, 082, 128, 179) và 2–3 user office (034, 073, 040) bị ảnh hưởng thật, tức nơi nhì gần ngang phiếu; vị trí home / office vẫn đúng trong khoảng 300 m, chỉ confidence bị kéo xuống; để v2 gộp theo DBSCAN); chưa xử lý riêng ca đêm và WFH ngoài cờ `home_eq_office`; chưa đo số user đổi office khi có và không có lịch lễ.

### D19. Kiểm tra trên nhóm test: chạy một lần sau khi khoá cấu hình
Duy hỏi 2026-11-06; chạy bằng `notebooks/eda/11_test.ipynb` (T1 in cấu hình, T2–T4 đặt dev và test cạnh nhau). Quy trình:
1. **Khoá cấu hình:** neo h1_mean, D = 200 m, T = 30 phút, max gap 24 h, `cluster_v1` 200 m, khung đêm 20–7h, ngày làm việc 8:30–18:00, ≥ 60 phút mỗi phiếu, mốc 7 phiếu, bootstrap 200 lần (hạt giống 20261106). Ghi ngày khoá vào đây.
2. **Chạy một lần:** `python -m src.places.home_office_conf --test` (ghi `reports/home_office_v1_test.csv`), lưu file riêng, không ghi đè kết quả dev. Stay và địa điểm của user test đã có sẵn vì pipeline chạy cho mọi user; không chọn gì từ chúng.
3. **Đo đúng những thước đo đã dùng ở dev, đặt cạnh số dev:** tỉ lệ stay báo nhầm theo nhãn phương tiện (22 user test có `labels.txt`; dev 10,94%); tỉ lệ có home / office và các cờ; phân bố confidence; nửa đầu / nửa sau trùng nơi theo mức confidence (notebook 10, mục 30); mức khớp đáp án GPS (mục 28).
4. **Không sửa gì sau khi xem số test.** Lệch nhiều so với dev thì ghi là hạn chế. Nếu vẫn sửa thì số test cũ không còn là số test, phải ghi rõ.

**Đã chạy một lần ngày 2026-11-06** (cấu hình khoá như mục 1, `reports/home_office_v1_test.csv`, notebook 11). Kết quả test so với dev: có home 96,7% (84,4%), có office 55,0% (50,8%), home = office 28,3% (25,4%), `few_nights` 46,7% (45,9%), `few_workdays` 58,3% (50,0%); trung vị confidence home 92,0% (96,8%), office 100% (92,7%, 15 user); nửa đầu / nửa sau home trùng 33% / 57% / 67% theo mức confidence (đúng chiều, tương quan hạng 0,19, mẫu nhỏ); stay nhận nhầm 11,76% (10,94%). Không sửa gì sau khi xem.

Test chỉ đo độ ổn định và khả năng lặp lại trên user mới, không đo độ đúng vì không có nhãn home / office (A13). Không làm gán tay (mentor chốt 2026-11-06).
