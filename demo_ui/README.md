# Mock app đặt xe (demo gợi ý Nhà / Công ty)

Giao diện giả lập app đặt xe (tên "Đi Đâu", không dùng thương hiệu thật). Khi mở màn chọn điểm đến,
app gọi Home/Office API để lấy home/office của user từ lần chạy model gần nhất, ghim lên bản đồ.

Luồng: Trang chủ -> bấm "Đặt xe" -> màn chọn điểm (bản đồ + gợi ý) -> chọn Nhà/Công ty, chạm bản đồ,
kéo ghim, hoặc nhập "lat, lon" -> màn xác nhận (tuyến, giá giả) -> "Đặt xe" (không đặt thật).

## Chạy (PowerShell, thư mục Home_Office)

    # cửa sổ 1: API
    uvicorn api.app:app --port 8000
    # cửa sổ 2: server demo (chỉ dùng thư viện chuẩn)
    python demo_ui\serve.py
    # mở http://localhost:8080/?user=002

serve.py đóng vai backend của app: trình duyệt -> serve.py -> API. Gọi `/v1/users/{id}/home-office`
(spec 0.3.0); nếu API còn bản cũ thì tự gọi `/v1/geolife/users/{id}/locations` (cùng dạng JSON).
API tắt: giao diện hiện "Dữ liệu mẫu" (không phải kết quả model). Biến môi trường: API_URL, API_KEY, PORT.
Bản đồ cần mạng (Leaflet + OpenStreetMap). Nút 👤: đổi user, version (heuristic-v1 / dbscan-v2), nguồn dữ liệu.
"Xem lời gọi API" hiện đường dẫn, mã trạng thái, thời gian, JSON.

## Địa chỉ thật (2026-11-12)
Chạm bản đồ, chọn Nhà/Công ty hoặc lấy GPS: app tra tên đường thật qua serve.py -> OpenStreetMap Nominatim
(`/api/geocode/reverse`). Gõ địa chỉ vào ô điểm đến rồi Enter để tìm (`/api/geocode/search`, ưu tiên gần điểm đón).
Miễn phí, không cần key; serve.py giãn cách 1 lời gọi/giây và lưu cache. Tọa độ được gửi tới Nominatim.

## Nối với API đã deploy trên AWS (2026-11-17, đã thử: 002, 153 trả 200; 999 trả 404)
    $env:API_URL = "https://2ri5mspocd.execute-api.ap-southeast-1.amazonaws.com"
    python demo_ui\serve.py
Không cần chạy uvicorn.

## Đăng nhập OAuth 2.0 qua Cognito (2026-11-18)
Cần 2 file (ghi sau `terraform apply`, trong `deploy\terraform`):

    terraform output -raw cognito_client_id | Set-Content -Encoding ascii ..\..\api\cognito_client_id.txt
    terraform output -raw cognito_domain | Set-Content -Encoding ascii ..\..\api\cognito_domain.txt

Luồng (Authorization Code + PKCE): màn **Đăng nhập** → nút Đăng nhập → `/auth/login` chuyển sang trang đăng nhập của Cognito
→ nhập email + mật khẩu ở đó → Cognito chuyển về `/auth/callback?code=...` → serve.py đổi code lấy token → về trang chủ.
App không thấy mật khẩu; token nằm ở serve.py (theo phiên, cookie HttpOnly), trình duyệt không thấy. Tắt serve.py là mất phiên.
- `userNNN@example.com` (ví dụ `user153@example.com`): chỉ xem gợi ý của user GeoLife NNN; ô "Mã người dùng" bị khoá.
- `admin@example.com`: đổi được sang mọi user trong 👤 Cài đặt.
- Đăng xuất: 👤 → Đăng xuất (xoá phiên ở serve.py và ở Cognito).

    $env:API_URL = "https://2ri5mspocd.execute-api.ap-southeast-1.amazonaws.com"
    python demo_ui\serve.py
    # mở http://localhost:8080  (đúng "localhost", không dùng 127.0.0.1: Cognito chỉ chuyển về địa chỉ đã khai báo)

Thiếu một trong 2 file thì không cần đăng nhập (như trước, cho API đã tắt `auth_enabled`).
