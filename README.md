# MoneyFlow Local v1.0.8

Ứng dụng quản lý tài chính cá nhân chạy trên Windows, giao diện **dark mode**, hỗ trợ nhiều người dùng, phân quyền, thu chi, ngân sách, **quản lý nợ gốc** và báo cáo. Backend Python/FastAPI, frontend HTML/CSS/JavaScript, PostgreSQL 18 trong Docker. Tất cả tài liệu và lịch sử phiên bản được duy trì trong **README.md duy nhất**.

## Địa chỉ và hệ thống

| Thành phần | Giá trị |
|---|---|
| Thư mục source trên Windows | `D:\LienThongDH\DoAn\moneyflow` |
| Thư mục dữ liệu Docker trên Windows | `D:\DockerData` (tùy cấu hình Docker Desktop đã cài) |
| MoneyFlow HTTPS | `https://127.0.0.1:8765` |
| HTTPS thay thế | `https://localhost:8765` |
| HTTP chuyển hướng | `http://127.0.0.1:8764` |
| pgAdmin kết nối PostgreSQL | `127.0.0.1:5435`, DB/user `moneyflow` |
| PostgreSQL nội bộ Docker | `db:5432` |
| Source trên GitHub | `TamNhien/moneyflow` (repository private) |

> Cổng `8765` chỉ dùng HTTPS; `http://127.0.0.1:8765` không hoạt động. `D:\DockerData` là **thư mục dữ liệu**, không nhất thiết là vị trí cài `Docker Desktop.exe`.

## Khởi động tự động Docker Desktop (mới trong v1.0.8)

Bạn không cần mở Docker Desktop trước. Các script `test.ps1`, `start.ps1`, `build.ps1`, `run.ps1`, `configure-local.ps1` và `publish.ps1` đều sử dụng `scripts/ensure-docker.ps1`.

- Khi Docker Engine đã chạy, bỏ qua khởi động và tiếp tục ngay.
- Khi Docker Engine chưa chạy, script thử `docker desktop start --detach` (Docker Desktop CLI), dự phòng mở `Docker Desktop.exe` qua `Start-Process` trên Windows.
- Script đợi tối đa **180 giây** để Docker Engine thực sự sẵn sàng; nếu quá thời hạn hoặc Docker/WSL bị lỗi, dừng với thông báo có hướng chẩn đoán (không chạy tiếp các lệnh Compose thất bại).
- Không tự xóa volume, sửa cấu hình WSL, thay đổi `D:\DockerData`, cấp quyền Administrator hay mở Docker Engine ra mạng.

**Lệnh khuyến nghị, một bước tự mở Docker + kiểm thử + build và chạy website:**

```powershell
cd D:\LienThongDH\DoAn\moneyflow
Get-ChildItem .\scripts -Recurse -Filter *.ps1 | Unblock-File
.\scripts\run.ps1
```

**Chỉ khởi động ứng dụng (không chạy lại bộ kiểm thử):**

```powershell
.\scripts\start.ps1
```

**Chỉ chạy kiểm thử:**

```powershell
.\scripts\test.ps1
```

**Tùy chọn kiểm tra Engine với thời gian đợi dài hơn:**

```powershell
.\scripts\ensure-docker.ps1 -TimeoutSeconds 300
```

Sau khi Docker chạy: `docker compose ps -a` để kiểm tra `db`, `app`, `caddy`. Nếu mở trình duyệt báo lỗi, xem `docker compose logs --tail=100 app caddy`. Với sự cố Docker Desktop/WSL, xem `docker desktop status` và `wsl --list --verbose`.

**Lưu ý:** Chạy riêng `docker compose up -d --build` không tự khởi động Docker Desktop. Hãy dùng `start.ps1` hoặc `run.ps1` để có cơ chế tự mở Docker.

### HTTPS nội bộ

Caddy reverse proxy dùng `tls internal` và `default_sni 127.0.0.1`, cấp chứng chỉ từ CA nội bộ lưu trong volume Caddy. Trên máy Windows chưa tin cậy CA, chạy thủ công script sau; script hỏi xác nhận `YES` và **không tự ý cài chứng chỉ âm thầm**:

```powershell
.\scripts\trust-local-https.ps1
```

Giữ các volume Docker để không mất database và CA cũ. Không dùng `docker compose down -v`. Nếu HTTPS vẫn lỗi, kiểm tra nhật ký Caddy và thử cả hai địa chỉ HTTPS ở bảng trên.

## Chức năng

- **Tiền ban đầu và số dư:** số dư = tiền gốc + tổng thu nhập − chi tiêu − tiền đã trả nợ. Chặn thao tác khiến số dư âm.
- **Giao dịch thu/chi:** thêm, sửa, xóa, lọc theo tháng, danh mục; xuất CSV UTF-8 BOM.
- **Quản lý nợ:** tạo các khoản nợ gốc và người cho vay, ngày đến hạn, ghi chú; theo dõi nợ còn lại, đã trả, thanh toán thủ công và hoàn tác.
- **Tự trừ nợ khi thu nhập mới:** khoản tiền mới được phân bổ cho nợ đang còn theo thứ tự tạo trước; chỉ phần dư mới tăng số dư. Không trừ hồi tố các giao dịch thu nhập cũ, không tính trả nợ gốc như chi phí sinh hoạt.
- **Thống kê:** tổng thu/chi, biến động 6 tháng, biểu đồ tròn chia từ tâm theo danh mục, ngân sách, số nợ và tài sản ròng.
- **Tài khoản:** username, email, điện thoại, địa chỉ; phân quyền Admin/Member, khóa tài khoản, nhật ký hệ thống. Tài khoản có sổ giao dịch riêng.
- **Mật khẩu:** Argon2id với salt riêng, xác nhận mật khẩu, thanh đo độ mạnh và kiểm tra ở backend; khôi phục bằng liên kết email dùng một lần, hết hạn 15 phút khi có SMTP.
- **Giao diện:** theme tối xanh tím, logo SVG, favicon, phù hợp desktop và điện thoại.

### Thư điện tử khôi phục mật khẩu

Cấu hình tùy chọn trong `.env` của chính máy, không đưa thông tin thật vào GitHub:

```dotenv
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_SECURITY=starttls
SMTP_USER=your-account@gmail.com
SMTP_PASSWORD=YOUR_GMAIL_APP_PASSWORD
SMTP_FROM=your-account@gmail.com
```

Cần cấu hình SMTP và kết nối Internet để gửi email; các thao tác thu chi thường ngày vẫn dùng được offline.

## Kiểm thử, build và GitHub Release

Đã đăng nhập GitHub CLI và cấu hình `origin` trỏ tới repository chính là điều kiện trước khi phát hành. Script `publish.ps1` tự kiểm tra Docker, chạy test, build image, đóng ZIP + SHA-256, kiểm tra staging (không gửi `.env`, database hoặc bí mật), commit/push rồi push tag để GitHub Actions kiểm thử lại và tạo Release.

```powershell
cd D:\LienThongDH\DoAn\moneyflow
Get-ChildItem .\scripts -Recurse -Filter *.ps1 | Unblock-File
.\scripts\publish.ps1 -Version 1.0.8
```

Từ lần phát hành kế tiếp, nếu phiên bản trước đã được phát hành đầy đủ, có thể chạy `.\scripts\publish.ps1` để tăng patch tự động. GitHub Actions đặt trong `.github/workflows/ci.yml` và `release.yml`.

Đối với môi trường phát triển CI trên Linux, workflow gọi trực tiếp `docker build`/`docker run`; phần tự mở Docker Desktop chỉ sử dụng trên Windows.

## Bảo mật và giới hạn

- Session cookie `HttpOnly`, `SameSite=Strict`, `Secure` qua HTTPS; CSRF cho API cập nhật.
- Mật khẩu băm Argon2id, không lưu nguyên văn; phiên và token khôi phục chỉ lưu hash, đăng nhập sai nhiều lần bị khóa tạm.
- PostgreSQL chỉ ánh xạ `127.0.0.1:5435` cho máy Windows. Tài khoản DB mật khẩu `moneyflow` là cấu hình local theo yêu cầu và không phù hợp cho triển khai qua Internet.
- Bài kiểm thử API hiện dùng SQLite tạm để kiểm tra nghiệp vụ, không thay thế kiểm thử tích hợp đầy đủ trên PostgreSQL hoặc Windows/Docker.
- Tự mở Docker Desktop không thể chữa các lỗi WSL2/HCS hoặc ổ VHDX bị khóa; script sẽ thông báo rõ thay vì giả định Docker đã chạy.

## Lịch sử phát triển (một README.md)

| Phiên bản | Nội dung |
|---|---|
| v1.0.0 | Quản lý thu/chi, số dư, danh mục, ngân sách, dashboard và tài khoản. |
| v1.0.1 | PostgreSQL host 5435 và giao diện đăng nhập nền tối. |
| v1.0.2 | Hồ sơ email/điện thoại/địa chỉ, độ mạnh mật khẩu, khôi phục qua SMTP. |
| v1.0.3 | Xác nhận mật khẩu và xóa tham số theo dõi không cần thiết khỏi URL. |
| v1.0.4 | Quy trình test, build, GitHub push/tag và phát hành tự động; gộp tài liệu. |
| v1.0.5 | Nền tối toàn ứng dụng, pie chart chia từ tâm, logo/favicon và HTTPS nội bộ Caddy. |
| v1.0.6 | Sửa khả năng bắt tay TLS khi truy cập HTTPS bằng IP, cấu hình SNI Caddy. |
| v1.0.7 | Quản lý nợ gốc, tự phân bổ tiền thu để trả nợ, lịch sử thanh toán. |
| **v1.0.8** | **Tự mở Docker Desktop khi test/build/chạy/phát hành; đợi Engine, báo lỗi có hướng xử lý và thêm lệnh chạy một bước `run.ps1`.** |

Các phiên bản sau cập nhật `VERSION` và ghi chú phát hành trong chính `README.md`, không tạo `CHANGELOG.md` hay các file hướng dẫn theo phiên bản.
