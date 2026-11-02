# MoneyFlow Local v1.0.12

Ứng dụng quản lý tài chính cá nhân chạy trên Windows, giao diện **dark mode**, hỗ trợ nhiều người dùng, phân quyền, thu chi, ngân sách, **quản lý nợ phải trả/phải thu, lãi thực tế và lịch trả góp** và báo cáo. Backend Python/FastAPI, frontend HTML/CSS/JavaScript, PostgreSQL 18 trong Docker. Tất cả tài liệu và lịch sử phiên bản được duy trì trong **README.md duy nhất**.

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

## v1.0.12 — Quản lý nợ chuyên sâu (nợ phải trả và phải thu)

- **Phân biệt chiều nợ:** **Phải trả** (mình vay tiền) và **Phải thu** (mình đã cho người khác vay). Nợ của các tài khoản người dùng được tách biệt.
- **Lãi suất năm:** nhập từ 0–100%/năm (tối đa hai chữ số thập phân); lập lịch *tham khảo* tính theo **dư nợ giảm dần, chia đều tiền gốc theo từng tháng**. Chưa hỗ trợ lãi kép, thay đổi lãi theo kỳ, ngày thực tế/365, phí trả chậm hoặc điều kiện ngân hàng đặc thù.
- **Trả góp:** 1–360 kỳ, yêu cầu ngày đến hạn kỳ đầu với nhiều kỳ; xem từng kỳ gồm hạn trả, gốc kế hoạch, lãi ước tính, tổng ước tính và tiến độ gốc. Gốc/lãi ước tính **không tự ghi bút toán** vào ví; khoản thu/chi thực tế chỉ phát sinh khi người dùng xác nhận.
- **Thanh toán thực tế:** ghi **gốc** (bắt buộc lớn hơn 0) và **lãi thực trả/thu** riêng. Nợ phải trả: ví trừ *(gốc + lãi)*; nợ phải thu: ví cộng *(gốc + lãi)*; **chỉ tiền gốc làm giảm dư nợ**. Không nhập cùng khoản thu hồi nợ vào mục “Thu nhập” lần nữa vì sẽ tính trùng tiền.
- **Tự trừ nợ giữ nguyên:** các khoản **Thu nhập mới** chỉ tự trả **nợ phải trả** theo thứ tự tạo trước, mặc định trả **gốc**, không tự tính hay trừ lãi. Nợ phải thu chỉ giảm khi chọn **Thu hồi** trong Quản lý nợ.
- **An toàn sổ sách:** giới hạn tổng thanh toán không vượt trần; không thể thanh toán vượt dư nợ gốc, trả nợ khi ví không đủ tiền hoặc hoàn tác khoản thu hồi đã sử dụng hết. Khoản nợ đã có thanh toán khóa các điều khoản trọng yếu (gốc, chiều nợ, lãi suất, số kỳ và lịch); vẫn sửa được tên/đối tác/ghi chú. Không xóa khoản có lịch sử thanh toán.
- **Tổng quan:** nợ phải trả, nợ phải thu và **tài sản ròng = tổng số dư ví − nợ phải trả + nợ phải thu** (chưa gồm tài sản/nghĩa vụ khác). Tiền lãi thực thu/trả của các khoản nợ hiển thị riêng, không tự ghi vào thống kê danh mục thu/chi.
- **Migration không phá dữ liệu:** cột mới trên `debts` là `direction`, `annual_rate_bps`, `installment_count`; trên `debt_payments` là `interest_amount`. Nợ từ v1.0.11 hoặc cũ hơn mặc định **phải trả, 0%/năm, 1 kỳ, lãi thực tế 0**; ví/giao dịch/tiền đã trả nợ cũ vẫn được giữ nguyên. Migration được kiểm thử lặp lại trên SQLite; PostgreSQL Windows/Docker thực tế cần xác nhận sau khi chạy.

## v1.0.11 — Quản lý nhiều ví

- Mỗi tài khoản có **Ví chính**, có thể tạo tối đa 30 ví: **Tiền mặt, Ngân hàng, Ví điện tử**. Số dư được tính độc lập từ tiền đầu kỳ, giao dịch, trả nợ và chuyển ví.
- Màn hình **Ví & tài khoản**: xem số dư từng ví, tổng tiền, tạo ví, sửa tên/loại, khóa/mở ví khi hợp lệ, chuyển tiền và xem lịch sử.
- Form **thu/chi** và **trả nợ thủ công** có trường chọn ví; tiền thu trả nợ tự động được khấu trừ ở chính ví nhận tiền.
- **Chuyển ví là giao dịch nội bộ**, không làm thay đổi tổng tài sản, không tăng thu hoặc chi và không ảnh hưởng thống kê danh mục.
- Dữ liệu cũ được chuyển vào ví chính bằng migration không phá dữ liệu (`wallets`, `wallet_transfers`, cột `wallet_id` ở `entries` và `debt_payments`). Migration chạy lại không nhân đôi ví hay số dư.
- Không cho chuyển tiền vượt số dư; sửa/xóa giao dịch hoặc hoàn tác chuyển tiền không được làm bất kỳ ví nào âm. Không cho khóa ví còn số dư, không cho khóa ví chính.
- **Tiền ban đầu trong Cài đặt** chỉ điều chỉnh tiền đầu kỳ Ví chính; khi tạo ví mới có thể khai báo số dư tiền đã có sẵn, hoặc nhập 0 rồi chuyển tiền từ ví cũ để tránh tính trùng.

## Chức năng

- **Tiền ban đầu và số dư:** số dư = tiền gốc + thu nhập − chi tiêu − trả nợ gốc/lãi + tiền thu hồi nợ gốc/lãi. Các lần chuyển ví không làm thay đổi tổng số dư. Chặn thao tác khiến từng ví âm.
- **Giao dịch thu/chi:** thêm, sửa, xóa, lọc theo tháng, danh mục; xuất CSV UTF-8 BOM.
- **Quản lý nợ:** nợ phải trả/phải thu, người vay/cho vay, lịch trả góp, lãi suất ước tính, lịch sử gốc và lãi thực tế; có thu hồi/trả thủ công và hoàn tác khi hợp lệ.
- **Tự trừ nợ khi thu nhập mới:** khoản tiền mới chỉ phân bổ trả **nợ phải trả** theo thứ tự tạo trước; phần dư mới tăng số dư. Không trừ hồi tố các giao dịch thu nhập cũ, không tính trả nợ gốc như chi phí sinh hoạt.
- **Thống kê:** tổng thu/chi, biến động 6 tháng, biểu đồ tròn chia từ tâm theo danh mục, ngân sách, số nợ và tài sản ròng.
- **Tài khoản:** username, email, điện thoại Việt Nam dạng `0...` (tự nhận `+84`, `84`, `0084`), địa chỉ; phân quyền Admin/Member, khóa tài khoản, nhật ký hệ thống. Tài khoản có sổ giao dịch riêng.
- **Mật khẩu:** Argon2id với salt riêng, xác nhận mật khẩu, thanh đo độ mạnh và kiểm tra ở backend; khôi phục bằng liên kết email dùng một lần, hết hạn 15 phút khi có SMTP.
- **Giao diện:** theme tối xanh tím, logo SVG, favicon, phù hợp desktop và điện thoại. Có nút **Đăng xuất** cạnh biểu tượng tài khoản tại thanh đầu trang (trên điện thoại hiển thị biểu tượng có nhãn trợ năng).

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

Đã đăng nhập GitHub CLI và cấu hình `origin` trỏ tới repository chính là điều kiện trước khi phát hành. Script `publish.ps1` tự kiểm tra Docker, chạy test, build image, đóng ZIP + SHA-256, kiểm tra staging (không gửi `.env`, database hoặc bí mật), commit/push rồi push tag để GitHub Actions kiểm thử lại, tạo Release. **v1.0.10 chỉ thông báo thành công khi đã kiểm tra workflow `success`, Release `published` và đủ Full Source ZIP + SHA-256.**

```powershell
cd D:\LienThongDH\DoAn\moneyflow
Get-ChildItem .\scripts -Recurse -Filter *.ps1 | Unblock-File
.\scripts\publish.ps1 -Version 1.0.12
```

Từ lần phát hành kế tiếp, khi phiên bản trước đã được phát hành đầy đủ, có thể chạy `.\scripts\publish.ps1` để tăng patch tự động. GitHub Actions đặt trong `.github/workflows/ci.yml` và `release.yml`.

Đối với môi trường phát triển CI trên Linux, workflow gọi trực tiếp `docker build`/`docker run`; phần tự mở Docker Desktop chỉ sử dụng trên Windows.

### Xác nhận GitHub Release và thông báo tự động (v1.0.10)

Sau khi push tag phiên bản, `publish.ps1` tự đợi workflow `release.yml` **đúng tag và commit** hoàn thành, kiểm tra kết quả thành công, xác minh Release đã **xuất bản (không ở dạng draft)** và đã tải lên **hai file Full Source ZIP và SHA-256 có dung lượng khác 0**. Chỉ khi đó mới hiện thông báo màu xanh trong PowerShell kèm URL Release và **hộp thoại xác nhận trên Windows** (có thể tắt bằng `-NoReleasePopup`). Đang chạy, lỗi hoặc hết thời gian không được báo thành công.

```powershell
cd D:\LienThongDH\DoAn\moneyflow
.\scripts\publish.ps1 -Version 1.0.12
```

Kiểm tra lại một tag **đã được đẩy**, không cần build hoặc push lại:

```powershell
.\scripts\verify-release.ps1 -Version 1.0.12
```

Tùy chọn thời gian chờ (mặc định 1200 giây = 20 phút):

```powershell
.\scripts\publish.ps1 -ReleaseTimeoutSeconds 1800 -NoReleasePopup
```

Nếu lần phát hành đã push tag nhưng GitHub Actions bị lỗi, **không chạy lại `publish.ps1` với cùng tag**; xem kết quả tại `https://github.com/TamNhien/moneyflow/actions/workflows/release.yml`, sửa lỗi và chạy lại workflow phù hợp, sau đó dùng `verify-release.ps1` để xác nhận. Khi GitHub Actions chưa thể xác nhận (ví dụ mất Internet, thiếu quyền GitHub hoặc bị timeout), cần kiểm tra thủ công chứ không coi là đã thành công.

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
| v1.0.8 | Tự mở Docker Desktop khi test/build/chạy/phát hành; đợi Engine và thêm lệnh `run.ps1`. |
| v1.0.9 | Nút Đăng xuất cạnh tài khoản; chuẩn hóa số điện thoại Việt Nam về đầu số 0. |
| **v1.0.10** | **Theo dõi GitHub Actions đến khi hoàn thành, xác minh Release published + ZIP/SHA-256, hiển thị thông báo PowerShell và popup Windows khi thành công; lỗi hoặc timeout sẽ báo chính xác.** |
| v1.0.11 | Quản lý nhiều ví tiền mặt/ngân hàng/ví điện tử, chuyển ví nội bộ không tính thu/chi, gắn thu chi và trả nợ vào từng ví, migration an toàn từ sổ cũ. |
| **v1.0.12** | **Phân loại nợ phải trả/phải thu; thu hồi theo ví; nhập lãi thực tế; lịch trả góp và lãi ước tính; bảo vệ tính toàn vẹn dòng tiền và migration dữ liệu nợ cũ.** |

Các phiên bản sau cập nhật `VERSION` và ghi chú phát hành trong chính `README.md`, không tạo `CHANGELOG.md` hay các file hướng dẫn theo phiên bản.
