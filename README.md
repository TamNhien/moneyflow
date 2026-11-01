# MoneyFlow Local v1.0.6

Ứng dụng quản lý chi tiêu cá nhân có nhiều người dùng, giao diện tiếng Việt, chạy tại **https://127.0.0.1:8765**, dữ liệu trong **PostgreSQL**. Phần giao diện dùng HTML/CSS/JavaScript thuần, không cần CDN; chức năng thu chi hoạt động offline, còn gửi email khôi phục cần Internet và cấu hình SMTP. API dùng Python/FastAPI và SQLAlchemy.

## Yêu cầu

- Windows 10/11, Docker Desktop đã bật và có thể chạy Linux containers.
- Internet cần để tải Docker image/phụ thuộc lần đầu và **khi gửi email khôi phục mật khẩu** qua SMTP.
- Cổng `8765` (Web) và `5435` (PostgreSQL cho pgAdmin trên chính máy) chưa có ứng dụng khác sử dụng.

## Chạy trên Windows

1. Giai nen source vao `D:\LienThongDH\DoAn\moneyflow` (thu muc chua `docker-compose.yml`).
2. Mở Docker Desktop, chờ Docker Engine hoạt động.
3. Mở PowerShell **trong thư mục MoneyFlow** (nơi có `docker-compose.yml`).
4. Chạy:

```powershell
Get-ChildItem .\scripts -Recurse -Filter *.ps1 | Unblock-File
.\scripts\start.ps1
```

Với cấu hình **local theo yêu cầu**, lần đầu `start.ps1` tạo `.env` với `DB_PASSWORD=moneyflow` rồi khởi chạy database + server. Lần đầu mở web, điền **tên đăng nhập, email, số điện thoại, địa chỉ và mật khẩu mạnh** để tạo tài khoản Admin đầu tiên. **Không có mật khẩu Admin mặc định.**

Truy cập: **https://127.0.0.1:8765**

**Kết nối pgAdmin 4 (cài trên Windows):** Host `127.0.0.1`, Port `5435`, Database `moneyflow`, Username `moneyflow`, Password `moneyflow`. PostgreSQL bên trong Docker vẫn nghe ở `db:5432`; không chỉnh `DATABASE_URL` thành 5435. Đây là mật khẩu kết nối DB, **không phải** mật khẩu tài khoản Admin Web.

**Chỉ dành cho nâng cấp v1.0.0 lên v1.0.1:** Chép đè các tệp cập nhật vào thư mục dự án cũ (giữ nguyên `.env` và volume), sau đó chạy `Get-ChildItem .\scripts -Filter *.ps1 | Unblock-File` và `.\scripts\configure-local.ps1`. Script đổi password của role trong database hiện có bằng `ALTER ROLE`, sau đó cập nhật `.env` và dựng lại container; không xóa giao dịch. Việc chỉ sửa `.env` sẽ không đổi mật khẩu role trong PostgreSQL đã khởi tạo.

## Bắt đầu sử dụng

1. Tạo Admin lần đầu → vào **Cài đặt** nhập tiền ban đầu, ví dụ 20.000.000 VNĐ.
2. Vào **Giao dịch** hoặc nhấn **Ghi khoản chi**: điền tên, tiền, danh mục, ngày, ghi chú → số dư được trừ tự động.
3. Nhấn **Thêm thu nhập** để ghi tiền vào (lương, thưởng...).
4. Vào **Ngân sách** để đặt hạn mức từng danh mục, từng tháng.
5. Vào **Danh mục** để tự thêm/ẩn loại thu và chi.
6. Xuất CSV (UTF-8 BOM, mở tốt với Excel) bằng nút **Xuất Excel / CSV** trong trang Giao dịch.
7. Admin quản lý các tài khoản, đổi quyền, khóa/mở, đặt lại mật khẩu, xóa vĩnh viễn tài khoản (có xác nhận) và xem nhật ký. Mỗi tài khoản có **sổ thu chi riêng**.

> Số dư = số tiền ban đầu + tổng các khoản thu - tổng các khoản chi. Khoản chi không được vượt số tiền hiện có. Sửa/xóa khoản thu cũng bị từ chối nếu khiến số dư âm.

## Lệnh quản trị

```powershell
# Trạng thái dịch vụ
docker compose ps

# Xem lỗi máy chủ
docker compose logs --tail 100 app

# Dừng dịch vụ nhưng GIỮ dữ liệu
.\scripts\stop.ps1

# Chạy lại
.\scripts\start.ps1

# Sao lưu dữ liệu PostgreSQL
.\scripts\backup.ps1

# Phục hồi từ bản sao lưu (có xác nhận, GHI ĐÈ dữ liệu hiện tại)
.\scripts\restore.ps1 -BackupFile '.\backups\moneyflow-YYYYMMDD-HHMMSS.dump'
```

**Rất quan trọng:** Không chạy `docker compose down -v` nếu chưa sao lưu vì lệnh này **xóa toàn bộ PostgreSQL volume**. `docker compose down` thông thường **không xóa volume**. Không chia sẻ tệp `.env` hay bản dump cho người khác.

## Bảo mật

- Mật khẩu: **Argon2id**, salt riêng ngẫu nhiên, cấu hình `m=65536 KiB, t=3, p=2`; không thể giải mã ngược.
- Mật khẩu dài 12-128 ký tự, cần chữ hoa, thường, số, ký tự đặc biệt.
- Phiên đăng nhập sử dụng token ngẫu nhiên; database chỉ giữ **SHA-256 token**, trình duyệt giữ cookie **HttpOnly + SameSite=Strict** (hết hạn sau 7 ngày). CSRF token gửi qua header cho mọi thao tác cập nhật.
- Khóa tạm tài khoản sau 5 lần nhập sai mật khẩu liên tiếp; yêu cầu JSON + same-origin.
- Chỉ bind `127.0.0.1`; cổng PostgreSQL `5435` mở **chỉ cho chính máy Windows** dùng pgAdmin, không mở ra LAN hoặc Internet.
- Theo yêu cầu, mật khẩu DB `moneyflow` là mật khẩu đơn giản, **chỉ nên sử dụng cho môi trường local**; khi cần bảo mật hơn, hãy chuyển sang mật khẩu mạnh và thay đổi đồng bộ trong PostgreSQL + `.env`.
- Dữ liệu của từng người dùng được tách bằng `user_id`, admin chỉ quản trị tài khoản, không xem giao dịch riêng của người khác qua API.
- Vận hành **local HTTP** không cung cấp HTTPS qua mạng. **Không đổi cấu hình thành 0.0.0.0 / public Internet** nếu chưa bổ sung HTTPS, reverse proxy và hardening chuyên nghiệp.
- Bản hiện tại **chưa có MFA, mã hóa dữ liệu tại ổ đĩa, hệ thống migration đầy đủ**, không được xem là sản phẩm đã trải qua pentest. Hãy bật BitLocker của Windows và thực hiện backup định kỳ khi lưu dữ liệu thật.

## Công nghệ

- Backend: FastAPI, SQLAlchemy 2, psycopg 3, Argon2-cffi.
- Frontend: HTML, CSS, JavaScript thuần; không phụ thuộc CDN.
- Database: PostgreSQL 18.6 trong Docker named volume.
- Docker Compose: ứng dụng và PostgreSQL tách service, chạy local.

## Kiểm thử cho lập trình viên

Cài dependencies tại `backend/requirements.txt` thêm `pytest`, `httpx` (để dùng TestClient). Chạy `pytest -q tests` (tests dùng SQLite tạm để kiểm tra nghiệp vụ, **không** thay thế bài kiểm thử tích hợp với PostgreSQL). Đảm bảo chạy từ thư mục root của project.

## Ghi chú cập nhật

Phiên bản này tạo bảng khi khởi động nếu database còn trống. Giao diện đăng nhập và tạo Admin đã sử dụng nền tối đồng bộ phong cách xanh tím.  Khi phát triển những phiên bản có thay đổi schema, cần bổ sung Alembic migration trước khi áp dụng cho database thật. Nên sao lưu bằng `backup.ps1` trước khi nâng cấp.

## Ảnh giao diện mẫu

Thư mục `preview/` chứa các ảnh minh họa giao diện desktop/mobile được render từ chính mã frontend với **dữ liệu minh họa giả lập**. Ảnh không phải dữ liệu tài chính thật và không được lưu vào database khi chạy ứng dụng.

## Nâng cấp 1.0.2: Hồ sơ và lấy lại mật khẩu qua email

- Mọi tài khoản **mới** phải nhập tên đăng nhập, email duy nhất, số điện thoại, địa chỉ và mật khẩu mạnh; đã bỏ trường tên hiển thị ở giao diện. Người dùng cũ được giữ nguyên, ứng dụng gợi ý bổ sung email/SĐT/địa chỉ tại mục Cài đặt; không xóa tài khoản hay giao dịch.
- Mật khẩu được **băm một chiều Argon2id với salt riêng**, không phải mã hóa đối xứng có thể giải mã; database không chứa mật khẩu gốc.
- Thanh đo độ mạnh cập nhật khi gõ ở trang tạo quản trị viên, tạo người dùng, đổi mật khẩu và đặt lại mật khẩu qua email. Mật khẩu phải có 12-128 ký tự, chữ hoa, chữ thường, số và ký tự đặc biệt (backend luôn kiểm tra lại).
- Nút **Quên mật khẩu?** gửi email với đường dẫn khôi phục localhost; mã ngẫu nhiên được băm SHA-256 trong bảng `password_reset_tokens`, dùng một lần, hết hạn sau 15 phút. Sau khi đổi thành công, tất cả phiên đăng nhập cũ bị thu hồi. Giới hạn 1 yêu cầu mỗi phút và 3 yêu cầu/giờ/tài khoản.
- **Phải cấu hình SMTP thực tế** nếu muốn nhận email: không có SMTP thì hệ thống sẽ thông báo chưa được cấu hình, không giả vờ gửi. Thiết bị cần có Internet để gửi và nhận thư, nhưng các chức năng thu chi vẫn chạy offline.

### Cấu hình email khôi phục

Mở `D:\LienThongDH\DoAn\moneyflow\.env`, giữ `DB_PASSWORD=moneyflow` (theo lựa chọn của bạn) rồi thêm:

```dotenv
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_SECURITY=starttls
SMTP_USER=your-account@gmail.com
SMTP_PASSWORD=YOUR_GMAIL_APP_PASSWORD
SMTP_FROM=your-account@gmail.com
```

`SMTP_PASSWORD` là **mật khẩu ứng dụng Gmail (App Password)**, không phải mật khẩu Gmail chính. Cần bật xác minh 2 bước và tạo mật khẩu ứng dụng theo hướng dẫn tài khoản Google. Nếu dùng nhà cung cấp khác, thay máy chủ, cổng và thông tin tương ứng. Cài đặt này chứa bí mật SMTP, không chia sẻ file `.env`.

Sau khi sửa `.env`, chạy:

```powershell
cd D:\LienThongDH\DoAn\moneyflow
Get-ChildItem .\scripts -Recurse -Filter *.ps1 | Unblock-File
docker compose up -d --build
docker compose ps -a
```

Kết nối pgAdmin: host `127.0.0.1`, port `5435`, database/user `moneyflow`, password `moneyflow` (nếu đã đồng bộ role trong PostgreSQL). Giữ port 5432 **trong mạng Docker**; không đổi thành `db:5435`.

**Trước khi áp dụng bản vá cho database đang dùng, hãy sao lưu bằng `scripts/backup.ps1`.** Không chạy `docker compose down -v` vì sẽ xóa volume chứa dữ liệu.

## v1.0.4: Build, test, push GitHub, tao Release tu dong

**Folder source tren Windows:** `D:\LienThongDH\DoAn\moneyflow`. **Docker data:** `D:\DockerData`.
Port web `https://127.0.0.1:8765`; port PostgreSQL tren Windows `127.0.0.1:5435` (trong Docker `db:5432`).

### Cai dat mot lan

Cai Git, GitHub CLI, Docker Desktop. GitHub repository mac dinh **private**; khong gui mat khau/credentials len GitHub.

```powershell
winget install --id Git.Git -e
winget install --id GitHub.cli -e
# Mo cua so PowerShell moi sau khi cai dat
cd D:\LienThongDH\DoAn\moneyflow
gh auth login
git config --global user.name "Your GitHub display name"
git config --global user.email "your-github-email@example.com"
Get-ChildItem .\scripts -Recurse -Filter *.ps1 | Unblock-File
.\scripts\github-setup.ps1 -Repository moneyflow
```

Script `github-setup.ps1` tao private GitHub repo va gan `origin`; neu `origin` da co thi giu nguyen.
Xac nhan URL remote truoc khi day: `git remote -v`.

### Mot lenh test + build + push + tao Release

**Phat hanh ban dau v1.0.4** (v1.0.4 la ban full source hien tai):

Neu lan dau da dung tai `fatal: pathspec 'CHANGELOG.md' did not match any files`, cap nhat `scripts/publish.ps1` tu ban sua loi truoc khi chay lai. Ban `v1.0.4` chua push/tag thi **giu nguyen v1.0.4**, khong can xoa Git repository, `.git` hay tao lai database. Script phat hanh se chi stage cac duong dan dang ton tai va theo doi viec xoa nhung file huong dan cu da duoc Git quan ly. Khong can xoa thu muc `dist/`.

```powershell
cd D:\LienThongDH\DoAn\moneyflow
.\scripts\publish.ps1 -Version 1.0.4
```

**Cac ban nang cap ke tiep** (tu dong tang so patch theo VERSION, vi du v1.0.4 -> v1.0.5):

```powershell
.\scripts\publish.ps1
```

Hoac tang minor / major khi can:

```powershell
.\scripts\publish.ps1 -Bump minor
.\scripts\publish.ps1 -Bump major
```

Qua trinh: API tests -> frontend JS syntax (Node cai tren may) -> Docker app build -> ZIP/SHA-256 -> kiem tra file Git staging -> commit/push nhanh `main` -> push tag `vX.Y.Z` -> GitHub Actions kiem thu lai -> tao GitHub Release voi ZIP va SHA-256.

Neu can chay rieng:

```powershell
.\scripts\test.ps1
.\scripts\build.ps1 -Version 1.0.4
.\scripts\package.ps1 -Version 1.0.4
```

**Ket qua:** ZIP tao trong `dist/`, chi chua source, khong chua `.env`, database, dumps hay backup. File `.sha256` dung de kiem tra goi tai ve. Workflow CI tai `.github/workflows/ci.yml`, workflow Release tai `.github/workflows/release.yml` (can GitHub Actions duoc bat va quyen `contents: write`). Release chi xuat hien neu GitHub Actions test/build thanh cong. Local test dung SQLite tam trong container doc lap; chua thay the test tich hop PostgreSQL.

**Luu y:** Luon kiem tra cac file truoc khi push. Khong chep token/mat khau that vao source, `.env.example` hoac `README.md`. Script khong truy cap GitHub neu chua `gh auth login`; no khong tu tao Release neu chua co `origin` va chua duoc phep.

### Giao dien gon hon trong pgAdmin

Bang `public.users` can nhieu truong de quan ly dang nhap, phan quyen, so du, khoa tai khoan va thoi gian tao. `display_name` duoc giu de tuong thich database cu; khong xoa cot do.

Chay SQL `scripts/sql/users-overview.sql` trong pgAdmin Query Tool (database `moneyflow`) de tao view `public.v_users_overview` chi chua 9 cot: `id, username, email, phone, address, role, active, opening_balance, created_at`. View khong hien `password_hash`, `failed_attempts` hay `locked_until`. No khong thay doi bang `users` that.

### Ghi chu phien ban (tat ca trong README.md)

- **v1.0.0:** Thu/chi, so du tu dong, bao cao, danh muc, ngan sach, quan ly tai khoan, Docker/PostgreSQL.
- **v1.0.1:** PostgreSQL host 5435, giao dien dang nhap nen toi.
- **v1.0.2:** Email, so dien thoai, dia chi, lay lai mat khau qua SMTP, do manh mat khau Argon2id.
- **v1.0.3:** Xac nhan mat khau tren nhieu form, lam sach tham so tracking cua URL.
- **v1.0.4:** Tu dong test, build, ZIP checksum, GitHub push/tag, CI va GitHub Release; SQL view nguoi dung gon.

**Nguyen tac:** moi ban nang cap tang `VERSION` va bo sung muc ghi chu phien ban vao chinh file `README.md`; khong tao them `CHANGELOG.md` hay `UPGRADE-TO-*.md`.

Neu nang cap tu v1.0.3 bang patch, chay `.\scripts\cleanup-docs.ps1` de xoa cac file CHANGELOG/UPGRADE cu sau khi README da duoc thay the. Script chi xoa bon file tai lieu cu duoc liet ke; khong dong vao `.env`, source hoac volume.


### v1.0.5: Nền tối toàn bộ, biểu đồ từ tâm, logo và HTTPS localhost

- Dashboard, điều hướng, bảng giao dịch, ngân sách, danh mục, cài đặt, biểu mẫu và cửa sổ thao tác được chuyển sang giao diện tối xanh đen đồng bộ với đăng nhập. Màu chữ, đường phân cách và biểu đồ được điều chỉnh để có độ tương phản tốt.
- Phân bổ chi tiêu theo danh mục đổi từ *doughnut* sang **pie chart SVG**, các phần màu chạy **từ tâm ra mép**. Mỗi phần có tooltip giá trị VNĐ và tỷ trọng; tên danh mục hiển thị trong bảng chú giải bên cạnh.
- Khi có hơn 6 danh mục chi tiêu, biểu đồ hiển thị 5 danh mục lớn nhất và nhóm **Danh mục khác** để bảng chú giải nhất quán với đồ thị. Không tạo phần dữ liệu giả khi chưa có giao dịch.
- Không thay đổi schema PostgreSQL hoặc mật khẩu. Giữ cổng HTTPS `8765`, pgAdmin PostgreSQL `5435` và Docker data tại `D:\DockerData`.
- Sau khi chép bản vá vào `D:\LienThongDH\DoAn\moneyflow`, chạy:

```powershell
cd D:\LienThongDH\DoAn\moneyflow
Get-ChildItem .\scripts -Recurse -Filter *.ps1 | Unblock-File
.\scripts\test.ps1
docker compose up -d --build
docker compose ps -a
```

- Mở lại `https://127.0.0.1:8765`, nhấn `Ctrl + Shift + R` nếu trình duyệt còn giao diện cũ. Với bản phát hành tiếp theo, chạy `./scripts/publish.ps1` từ PowerShell để tiếp tục GitHub Releases (tự tăng theo file `VERSION`).


#### Logo MoneyFlow & HTTPS nội bộ (v1.0.5)

- Logo vector tại `frontend/logo.svg`, favicon tại `frontend/favicon.svg`, icon cho điện thoại tại `frontend/apple-touch-icon.png`. Header, sidebar và màn hình đăng nhập cùng dùng logo mới.
- **HTTPS loopback:** Caddy reverse proxy là dịch vụ `caddy` trong `docker-compose.yml`. Trình duyệt: **`https://127.0.0.1:8765`** hoặc **`https://localhost:8765`**. Cổng **`8765` giờ chỉ nhận TLS**, truy cập bằng `http://` trên cổng này sẽ thất bại. Cổng HTTP `8764` (chỉ loopback) được dùng để chuyển hướng đến HTTPS nếu muốn.
- Service `app` chỉ lắng nghe nội bộ Docker `app:8000`, không mở cổng ra Windows. `COOKIE_SECURE=true` giúp cookie phiên chỉ được gửi qua HTTPS. SMTP dùng liên kết đặt lại mật khẩu `https://127.0.0.1:8765/reset?token=...`.
- PostgreSQL tiếp tục dùng host `127.0.0.1:5435` và `db:5432` trong Docker; **không chạy `docker compose down -v`**. Các volume `moneyflow_db`, `caddy_data`, `caddy_config` được giữ lại khi khởi động lại container.
- Caddy dùng `tls internal` và tự cấp chứng chỉ qua **CA nội bộ**, không phải chứng chỉ công khai của Let's Encrypt. Do đó máy Windows cần tin cậy CA này một lần. Thực hiện có xác nhận (KHÔNG tự cài root CA âm thầm):

```powershell
cd D:\LienThongDH\DoAn\moneyflow
Get-ChildItem .\scripts -Recurse -Filter *.ps1 | Unblock-File
.\scripts\test.ps1
docker compose up -d --build
.\scripts\trust-local-https.ps1
# Nhap YES sau khi xem thong tin CA va ban tin tuong CA noi bo
Start-Process 'https://127.0.0.1:8765'
```

- Nếu vẫn thấy cảnh báo chứng chỉ: kiểm tra `docker compose logs caddy`, mở lại trình duyệt, xác nhận đúng URL 127.0.0.1/localhost. Một số trình duyệt sử dụng certificate store riêng và cần nhập chứng chỉ root bằng giao diện trình duyệt. Không bỏ qua cảnh báo chứng chỉ trên trang thật và không dùng `curl -k` để kết luận HTTPS đáng tin cậy.
- **Lưu ý bảo mật:** Một Root CA đã được tin cậy có thể phát hành chứng chỉ cho nhiều tên miền. Chỉ cài chứng chỉ từ Caddy do chính bạn khởi chạy, không chia sẻ khóa/volume `caddy_data`, và không đưa `.crt`/private keys vào GitHub. Chứng chỉ và khóa của CA được lưu trong Docker volume `caddy_data` nên giữ volume này để tránh phải tin cậy CA mới.
- GitHub Actions kiểm tra file `Caddyfile` và `docker compose config` trước khi phát hành; `scripts/publish.ps1` và `scripts/package.ps1` đã đưa `Caddyfile` vào danh sách source cho phép. Với repo ở trạng thái `v1.0.4` được phát hành, chạy `./scripts/publish.ps1 -Version 1.0.5` (KHÔNG dùng lệnh tự tăng phiên bản nếu đã thay `VERSION` lên `1.0.5` nhưng chưa phát hành). Chỉ một `README.md` được duy trì.


### v1.0.6: Khac phuc loi HTTPS ERR_SSL_PROTOCOL_ERROR khi truy cap bang IP

- Sua Caddyfile: them `default_sni 127.0.0.1` trong global options. Trinh duyet truy cap HTTPS bang dia chi IP co the khong gui SNI; Caddy su dung dia chi IP mac dinh de chon certificate noi bo.
- Giữ nguyên `tls internal`, Caddy CA, volume, database, Docker Compose, cong 8765 HTTPS va PostgreSQL 5435. **Khong xoa volume** va khong can cai lai chung chi khi CA khong doi.
- Khi cap nhat **Caddyfile qua bind mount**, phai **restart** service `caddy` de nap cau hinh moi. Lenh `docker compose up -d --build` khong dam bao restart Caddy neu chi file bind-mount thay doi.
- Cap nhat bang Patch v1.0.6 roi chay:

```powershell
cd D:\LienThongDH\DoAn\moneyflow
docker compose exec -T caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
docker compose restart caddy
docker compose ps -a
curl.exe -v https://127.0.0.1:8765/
```

- Neu `curl.exe` van bao SSL protocol error, thu `curl.exe -vk https://localhost:8765/` va `docker compose logs --tail=100 caddy`; `-k` **chi dung chan doan** (bo qua kiem tra CA), khong dung de xac nhan do tin cay HTTPS. Neu `localhost` hoat dong ma IP khong, kiem tra log TLS handshake va `default_sni`.
- Sau khi test HTTPS thanh cong, phat hanh `v1.0.6` bang `./scripts/publish.ps1 -Version 1.0.6`.
