# MoneyFlow Local v1.0.24

Ứng dụng quản lý tài chính cá nhân chạy trên Windows, giao diện **dark mode**, hỗ trợ nhiều người dùng, phân quyền, thu chi, giao dịch định kỳ, nhắc lịch, **mục tiêu tiết kiệm, tiền tích để dành tự động theo % hoặc số tiền cố định**, ngân sách, **quản lý nợ phải trả/phải thu, lãi thực tế và lịch trả góp** **hóa đơn & chứng từ ảnh/PDF gắn với giao dịch**, **đối soát số dư theo ví và phát hiện giao dịch nghi vấn**, và báo cáo. Backend Python/FastAPI, frontend HTML/CSS/JavaScript, PostgreSQL 18 trong Docker. Tất cả tài liệu và lịch sử phiên bản được duy trì trong **README.md duy nhất**.

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
| Lưu tệp hóa đơn/chứng từ | Docker volume `moneyflow-local_moneyflow_receipts` (riêng với PostgreSQL) |
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

Giữ nguyên các volume Docker và CA cũ. Không dùng `docker compose down -v`. Nếu HTTPS vẫn lỗi, kiểm tra nhật ký Caddy và thử cả hai địa chỉ HTTPS ở bảng trên.

## v1.0.24 - Thống kê theo năm và tự động kiểm soát phiên bản thư viện

**Thong ke theo nam**

- Menu **Thống kê theo năm**: xem thu nhap, chi tieu, no da tra, tien thu hoi no, dong tien thuan cua tung thang va ca nam, cung bieu do gia tri tai san rong cuoi thang.
- Co the chon nam tu 2000 den nam hien tai, so sanh thu/chi voi nam truoc; xuat bao cao nam qua **Excel (.xlsx)** va **PDF (.pdf)**. Xuat bao cao yeu cau dang nhap; khong ghi them giao dich hoac sua so du.
- Tien chuyen giua cac vi khong bi tinh thanh thu/chi, tien chuyen vao quy tich luy van tinh la tai san. Tien tra no va thu hoi no duoc tinh rieng, khong tinh trung thu/chi.
- **Gioi han quan trong**: so du va tai san rong trong lich su la **uoc tinh tai lap tu so giao dich dang co**, khong phai snapshot da khoa so. Neu nguoi dung sua/xoa/ghi lui ngay giao dich, sua so tien dau ky, thay doi no, hoac tao vi sau khi da co giao dich cu, bang tai san cuoi thang co the duoc tinh lai. Vi tao khi migrate se gia dinh so dau ky co tu ngay phat sinh giao dich som nhat cua vi. Viec nhap no khong tu tang tien mat neu khong co giao dich thu nhap.
- Endpoint: `GET /api/reports/annual?year=2026`, `GET /api/reports/annual.xlsx?year=2026`, `GET /api/reports/annual.pdf?year=2026`. Khong thay doi schema PostgreSQL.

**Tu dong cap nhat package / framework**

- `.github/dependabot.yml`: GitHub Dependabot kiem tra **Python packages hang ngay luc 08:00 (Asia/Ho_Chi_Minh)**; Docker image va GitHub Actions moi thu Hai. Cac phien ban moi duoc de xuat qua **Pull Request** tren repository private `TamNhien/moneyflow`.
- `backend/requirements.txt` duoc **ghim phien ban khoi tao da biet** thay vi khoang phien ban troi: moi lan build lai co the tai lap bo dependency on dinh. Dependabot tao PR cho phien ban moi nhat, ke ca ban major; **khong dong nghia v1.0.24 da su dung moi package moi nhat**.
- GitHub Actions `MoneyFlow CI` kiem tra frontend, backend, Docker build truoc. `.github/workflows/dependency-auto-merge.yml` chi tu dong gop PR cua `dependabot[bot]` neu CI tren **dung commit** thanh cong, patch chi sua `backend/requirements.txt`, cac pin chi tang **trong cung major** (voi 0.x thi cung minor), va repository cho phep token ghi. Moi truong CI khong su dung ket noi PostgreSQL thuc te, vi vay chay tren Docker/PostgreSQL Windows van can kiem chung.
- Ban cap nhat **major** (Python framework 0.x doi minor, ReportLab 4 -> 5, Pillow 12 -> 13, PostgreSQL 18 -> 19...), Docker base image va GitHub Actions can kiem tra PR thu cong. **Khong tu dong thay the PostgreSQL volume hoac upgrade major DB**. Anh Docker va GitHub Actions duoc theo doi qua PR, khong auto-merge.
- Truoc khi muon auto-merge, trong GitHub **Settings -> Actions -> General -> Workflow permissions**, cho phep `Read and write permissions` va `Allow GitHub Actions to create and approve pull requests` neu can; neu bi gioi han boi to chuc thi PR chi o trang thai cho xem xet. Nen bat **required status check** `MoneyFlow CI / test-and-build` tren nhanh chinh. Khong can cung cap access token/mat khau trong source.
- Repo tai may Windows khong tu dong ghi de khi GitHub thay doi; muon nhan dependency da duoc gop va build thi dong bo Git theo quy trinh Git thong thuong. Khong nen tu dong `git pull --force` hay thay doi bo source dang co sua doi.

**Lenh thu nghiem va phat hanh** (mac dinh tren Windows):

```powershell
cd D:\LienThongDH\DoAn\moneyflow
Get-ChildItem .\scripts -Recurse -Filter *.ps1 | Unblock-File
.\scripts\run.ps1
.\scripts\publish.ps1 -Version 1.0.24
```

Giu mot `README.md` duy nhat, khong them huong dan Patch hay sao luu vao quy trinh mac dinh.

## v1.0.23 — Đối soát số dư và cảnh báo giao dịch cần xem lại

Trang **Đối soát tài chính** trên menu hỗ trợ theo dõi sổ tiền MoneyFlow và những lần kiểm đếm thực tế:

- **Đối soát từng ví:** nhập số dư **thực tế hiện tại** tự kiểm tra trong tiền mặt, tài khoản ngân hàng hoặc ví điện tử; MoneyFlow ghi lại đồng thời số dư **theo sổ tại thời điểm nhập**, số thực tế, khoản chênh lệch (`thực tế − theo sổ`) và ghi chú. Đây là thông tin do người dùng cung cấp, **không tự lấy số dư từ ngân hàng**.
- **Lịch sử bất biến:** kết quả mỗi lần kiểm được lưu trong bảng PostgreSQL mới `wallet_reconciliations`; hiển thị tối đa **60 lần gần nhất**. Khi phát sinh giao dịch mới, chênh lệch kiểm đếm lịch sử **giữ nguyên theo thời điểm đã kiểm**, không so sánh lại với số dư hiện tại và không tự điều chỉnh các ví.
- **Kiểm tra sổ chung:** so sánh tổng số dư theo từng ví với tổng số dư chung từ thu/chi/nợ/quỹ tiết kiệm; tái sử dụng các kiểm tra tính nhất quán từ mục Bảo mật: liên kết ví, sổ nợ, số dư âm, liên kết mục tiêu/quỹ. Kiểm tra này **không thể xác minh số dư thực tế** nếu chưa có kiểm đếm thủ công.
- **Giao dịch nghi trùng:** tìm các bút toán cùng ví, ngày, loại, danh mục, số tiền và nội dung đã chuẩn hóa. Giao dịch giống nhau có thể là những lần thanh toán hoàn toàn hợp lệ; MoneyFlow chỉ đánh dấu **nghi vấn** để kiểm tra, **không xóa hoặc gộp**.
- **Số tiền khác thường:** so sánh các giao dịch cùng loại với trung vị trong **mẫu tối đa 2.000 giao dịch mới nhất**; khi có ít nhất 6 giao dịch cùng loại, cảnh báo khoản từ **1.000.000đ** trở lên và cao ít nhất **5 lần** trung vị. Đây là **quy tắc đơn giản**, không phải phân tích AI hay bằng chứng gian lận. Nếu dữ liệu vượt 2.000 giao dịch, màn hình đánh dấu giới hạn mẫu và kết quả không bao quát toàn bộ lịch sử.
- **Không thay đổi tài chính:** API `GET /api/reconciliation` chỉ đọc; `POST /api/reconciliation/check` chỉ thêm một kết quả kiểm đếm, không tạo giao dịch, không cộng/trừ số dư và không sửa nợ. Bảo vệ theo phiên đăng nhập, CSRF khi ghi và phân quyền ví, không cho người dùng xem/kiểm đếm ví của người khác. Đăng nhập vẫn qua HTTPS localhost.
- **Migration:** chỉ thêm bảng `wallet_reconciliations` bằng SQLAlchemy `create_all` khi khởi chạy. Không sửa bảng thu chi/nợ/tiền để dành cũ. Khi xóa một người dùng theo quyền Admin, các bản ghi kiểm đếm thuộc người đó cũng được xóa, tránh khóa ngoại còn sót.
- **Sử dụng:** mở **Đối soát tài chính**, chọn ví, nhập số dư bạn kiểm được, bấm **Lưu kết quả kiểm đếm**; xem mục **Kiểm tra tính nhất quán**, **Giao dịch cần xem lại** và **Lịch sử đối soát**. Nếu có sai lệch, hãy đối chiếu sao kê/chứng từ, sau đó tự chỉnh giao dịch nguồn phù hợp; không tùy tiện chỉnh số dư ban đầu để xóa chênh lệch.

## v1.0.18 — Dự báo dòng tiền và cảnh báo thiếu tiền (đọc, không ghi dữ liệu)

- Thêm trang **Dự báo dòng tiền**: xem 30/60/90 ngày theo các lịch thu/chi định kỳ còn hoạt động. Hiển thị đường dự kiến tổng số dư khả dụng, các kỳ thu/chi, số dư dự kiến cuối kỳ và từng ví.
- Các khoản thu dự kiến được mô phỏng **ưu tiên trả nợ gốc phải trả** theo thứ tự nợ cũ trước; chỉ phần dư mới vào ví. Không giả lập tự trả lãi, thu hồi nợ hay chuyển khoản bên ngoài; nợ đến hạn tiếp tục nằm trong khu vực nhắc lịch và **không bị trừ thêm** trong dự báo.
- Phát hiện nguy cơ **âm từng ví**, kể cả khi tổng số dư các ví còn dương; đánh dấu ngày đầu có rủi ro. Dữ liệu thật **không bị sửa**, kể cả khi số dư dự kiến âm; quy tắc chặn chi vượt tiền vẫn hoạt động như trước.
- Những kỳ quá hạn chưa xử lý được báo riêng, không giả vờ đã thanh toán hôm nay. Lịch gắn ví đang khóa được cảnh báo và loại khỏi dự báo. Chuyển tiền nội bộ và góp/rút quỹ tiết kiệm không bị nhận nhầm thành thu/chi.
- API chỉ đọc `GET /api/forecast?days=30|60|90`, yêu cầu đăng nhập; trả header `Cache-Control: no-store`. Không thay schema database và không tạo giao dịch; các mốc dự báo phụ thuộc vào giả định lịch sẽ diễn ra đúng hạn, không phải cam kết số dư thực tế.
- Trường hợp dự báo quá nhiều kỳ, API chỉ gửi 160 kỳ đầu tiên cho bảng chi tiết; các chỉ số tổng và biểu đồ vẫn tính tất cả. Bộ kiểm thử bao gồm cách tính trả nợ, rủi ro theo ví, chặn truy cập chéo tài khoản và kiểm tra API không làm thay đổi dữ liệu.

## v1.0.14 — Giao dịch định kỳ và nhắc lịch trong ứng dụng

- **Lịch định kỳ:** tạo tối đa 100 lịch thu/chi riêng cho mỗi tài khoản; chọn ví, danh mục, số tiền, ngày bắt đầu, nhịp hằng ngày/tuần/tháng/năm, số ngày báo trước (0–30). Các tháng không đủ ngày được tự điều chỉnh (31/1 → 28/2 → 31/3). Có sửa nội dung, số tiền, ví, danh mục; tạm dừng/kích hoạt lịch; xóa lịch nếu chưa có lịch sử xử lý.
- **Xác nhận trước khi ghi (mặc định):** tại **Định kỳ & nhắc lịch**, nhấn *Ghi giao dịch* khi đến ngày để cập nhật số dư; có thể chọn *Bỏ qua kỳ* mà không ảnh hưởng số dư. Trạng thái kỳ đã xử lý và liên kết giao dịch được ghi trong `recurring_runs`.
- **Chế độ tự ghi (tùy chọn):** tác vụ chạy trong FastAPI mỗi 60 giây khi container hoạt động. Khi khởi động lại, xử lý các kỳ còn đến hạn theo thứ tự (giới hạn 30 kỳ/lịch mỗi lượt), chống ghi trùng bằng unique constraint, khóa hàng ở PostgreSQL và transaction. Khoản chi thiếu tiền hoặc ví bị khóa sẽ không ghi và giữ kỳ đến hạn để xem xét lại; không tạo lệnh chuyển tiền ngân hàng bên ngoài.
- **Tương tác với quản lý nợ:** tiền thu định kỳ sử dụng cùng hàm phân bổ nợ **phải trả** như thu nhập thường. Khi tiền thu không đủ thanh toán hết nợ thì số dư khả dụng chỉ tăng phần còn lại; nợ **phải thu** không tự giảm.
- **Thông báo nội bộ:** menu hiển thị số lịch/khoản nợ cần chú ý; dashboard và màn hình định kỳ có danh sách hạn sắp tới/trễ hạn. Lịch định kỳ dùng số ngày báo trước do người dùng chọn; trả góp/nợ nhắc trước 7 ngày. Không có thông báo push hay email tự động ở bản này; muốn thấy nhắc nhở phải mở ứng dụng.
- **Lịch sử an toàn:** một kỳ chỉ được ghi một lần kể cả khi app khởi động lại. Nếu xóa giao dịch định kỳ đã ghi, lịch sử chuyển sang trạng thái “giao dịch đã xóa”, không tự tạo lại kỳ đó. Không ảnh hưởng dữ liệu đang có trong `entries`, `wallets` và `debts`.
- **Database:** thêm hai bảng mới `recurring_rules` và `recurring_runs`, tạo không phá dữ liệu qua `Base.metadata.create_all`. Giao dịch trước đây không được đưa vào các lịch mới hoặc ghi hồi tố khi tạo lịch.

### Giới hạn vận hành lịch

- Lịch tự ghi chỉ thực hiện khi Docker Desktop, PostgreSQL và FastAPI đang chạy; việc khởi động máy tính không tự mở ứng dụng nếu người dùng chưa khởi chạy MoneyFlow. Ngày hẹn sử dụng múi giờ `Asia/Ho_Chi_Minh` từ cấu hình container.
- Tự động **ghi vào sổ thu chi nội bộ**, không tự chuyển khoản ngân hàng, không gửi thông báo qua SMS/email và không tạo tiền nếu không có ví hợp lệ.
- Nếu đổi một lịch từ thủ công sang tự động, những kỳ còn tồn đọng đã đến hạn có thể được tự động ghi; cần kiểm tra và bỏ qua kỳ không cần ghi trước khi chuyển chế độ.
- Các thao tác chi, sửa và xóa vẫn phải giữ số dư từng ví không âm. Kiểm thử local sử dụng SQLite; cần xác minh tác vụ chạy nền và khóa hàng PostgreSQL trên Docker Windows khi triển khai.

## v1.0.13 — Sửa lỗi tải trang và kiểm thử giao diện tự động

- Khôi phục các hàm `refreshCategories`, `refreshWallets`, `walletName`, `renderUsers` và `renderAudit` bị thiếu trong JavaScript v1.0.12. Thiếu hàm đã khiến Tổng quan báo `refreshCategories is not defined`, đồng thời ảnh hưởng các trang Giao dịch, Ví, Người dùng và Nhật ký.
- Tăng version query của `app.js` và `main.css` lên `1.0.13` để trình duyệt lấy bản mới.
- Bổ sung `tests/frontend-smoke.mjs` chạy bằng Node.js và được gọi bởi test PowerShell và CI: mô phỏng đăng nhập Admin, lần lượt tải toàn bộ màn hình, xác nhận không phát sinh lỗi JavaScript, kiểm tra sự hiện diện của các thành phần chính.
- Không sửa schema, không xóa/sửa dữ liệu PostgreSQL, không thay đổi HTTPS 8765 hoặc PostgreSQL 5435; giữ nguyên quản lý nợ và nhiều ví.

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

- Quản lý nhiều người dùng, phân quyền Admin/Member, phiên đăng nhập và khôi phục mật khẩu qua SMTP.
- Ví tiền mặt/ngân hàng/ví điện tử, chuyển ví nội bộ, danh mục, thu/chi, ngân sách và lịch sử.
- Nợ phải thu/phải trả, gốc/lãi, thanh toán từ ví, lịch trả góp và tự phân bổ khoản thu cho nợ phải trả.
- Giao dịch định kỳ, nhắc hạn trong ứng dụng, dashboard và báo cáo tài chính có xuất Excel/PDF.
- GitHub Actions tự test/build/phát hành và xác minh Release có đủ ZIP + SHA-256.

- **Tiền ban đầu và số dư:** số dư = tiền gốc + thu nhập − chi tiêu − trả nợ gốc/lãi + tiền thu hồi nợ gốc/lãi. Các lần chuyển ví không làm thay đổi tổng số dư. Chặn thao tác khiến từng ví âm.
- **Giao dịch thu/chi:** thêm, sửa, xóa, lọc theo tháng, danh mục; xuất CSV UTF-8 BOM.
- **Quản lý nợ:** nợ phải trả/phải thu, người vay/cho vay, lịch trả góp, lãi suất ước tính, lịch sử gốc và lãi thực tế; có thu hồi/trả thủ công và hoàn tác khi hợp lệ.
- **Tự trừ nợ khi thu nhập mới:** khoản tiền mới chỉ phân bổ trả **nợ phải trả** theo thứ tự tạo trước; phần dư mới tăng số dư. Không trừ hồi tố các giao dịch thu nhập cũ, không tính trả nợ gốc như chi phí sinh hoạt.
- **Giao dịch định kỳ và nhắc lịch:** lịch lương, tiền nhà, điện nước theo ngày/tuần/tháng/năm; xác nhận thủ công hoặc tự ghi, nhắc sắp đến hạn; lịch sử kỳ đã xử lý.
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
.\scripts\publish.ps1 -Version 1.0.23
```

Từ lần phát hành kế tiếp, khi phiên bản trước đã được phát hành đầy đủ, có thể chạy `.\scripts\publish.ps1` để tăng patch tự động. GitHub Actions đặt trong `.github/workflows/ci.yml` và `release.yml`.

Đối với môi trường phát triển CI trên Linux, workflow gọi trực tiếp `docker build`/`docker run`; phần tự mở Docker Desktop chỉ sử dụng trên Windows.

### Xác nhận GitHub Release và thông báo tự động (v1.0.10)

Sau khi push tag phiên bản, `publish.ps1` tự đợi workflow `release.yml` **đúng tag và commit** hoàn thành, kiểm tra kết quả thành công, xác minh Release đã **xuất bản (không ở dạng draft)** và đã tải lên **hai file Full Source ZIP và SHA-256 có dung lượng khác 0**. Chỉ khi đó mới hiện thông báo màu xanh trong PowerShell kèm URL Release và **hộp thoại xác nhận trên Windows** (có thể tắt bằng `-NoReleasePopup`). Đang chạy, lỗi hoặc hết thời gian không được báo thành công.

```powershell
cd D:\LienThongDH\DoAn\moneyflow
.\scripts\publish.ps1 -Version 1.0.21
```

Kiểm tra lại một tag **đã được đẩy**, không cần build hoặc push lại:

```powershell
.\scripts\verify-release.ps1 -Version 1.0.15
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


## Báo cáo tài chính nâng cao (v1.0.15)

Menu **Báo cáo tài chính** cho phép chọn 3, 6, 12 hoặc 24 tháng tính đến tháng đang chọn ở góc phải. Các chỉ tiêu bao gồm tổng thu/chi, dòng tiền thuần (thu − chi − các khoản trả nợ + thu hồi nợ), so sánh với tháng liền trước, chi theo danh mục, số dư ví, nợ phải thu/phải trả và tài sản ròng hiện tại.

- **Excel** (`/api/reports.xlsx`): 6 sheet Tổng quan, Theo tháng, Danh mục chi, Các ví, Giao dịch, Thanh toán nợ; số tiền dạng số nguyên VNĐ; nội dung do người dùng nhập được xử lý chống công thức độc hại.
- **PDF** (`/api/reports.pdf`): báo cáo A4 Unicode tiếng Việt, tóm tắt, biểu đồ và bảng từng tháng.
- Các API chỉ xuất dữ liệu của **tài khoản đang đăng nhập**; không thay đổi số dư hay database; tải về có header `Cache-Control: no-store`.
- Chuyển tiền qua lại giữa các ví **không tính là thu/chi**, tiền trả nợ gốc/lãi không cộng hai lần vào chi phí. Số dư ví/nợ/tài sản ròng là **số liệu tại thời điểm xuất**; không suy luận thành số dư chốt cuối các tháng trong quá khứ.
- Docker cài gói font DejaVu trong image để PDF hiển thị dấu tiếng Việt, không cần tải font thủ công trên Windows.

## Mục tiêu tiết kiệm (v1.0.17)

Trang **Mục tiêu tiết kiệm** cho phép tạo tối đa 50 kế hoạch (quỹ dự phòng, mua xe, du lịch...), đặt số tiền cần đạt, ngày dự kiến và ghi chú. Mỗi tài khoản có danh sách và lịch sử riêng, hiển thị số tiền dành riêng và thanh tiến độ.

- **Góp tiền:** chọn ví đang hoạt động và số tiền. Hệ thống ghi vào `savings_movements` và **giảm số dư khả dụng của ví**, đồng thời tăng số tiền dành riêng. Chặn góp vượt mục tiêu hoặc vượt số dư ví. Không ghi thêm thu nhập hoặc chi tiêu.
- **Rút về ví:** cho phép chuyển tiền đã dành riêng về một ví đang hoạt động; kiểm tra không rút quá quỹ. Giảm quỹ và tăng tiền khả dụng tương ứng. Không phải giao dịch thu nhập mới, không kích hoạt tự động trả nợ.
- **Không có chuyển khoản ngân hàng thật:** đây là phân bổ logic giữa phần có thể chi và phần dành riêng cho mục tiêu; nếu bạn cần chuyển tiền thật tại ngân hàng, hãy thực hiện tại ngân hàng. Mục tiêu và giao dịch ghi sổ không tự sinh lãi.
- **Tổng tài sản tiền = số dư khả dụng + tiền dành riêng**. Tài sản ròng cộng thêm nợ phải thu và trừ nợ phải trả. Chuyển tiền vào/ra mục tiêu không đổi tổng tài sản và không làm thay đổi dòng tiền thuần trên báo cáo tháng.
- Chỉ xóa mục tiêu khi tiền dành riêng đã về **0đ**; sửa hạn mức không được nhỏ hơn tiền đã góp. Các khoản góp/rút đã ghi giữ dạng lịch sử bất biến (không sửa/xóa từng chuyển động). Khi mục tiêu bị xóa ở trạng thái 0đ, lịch sử liên quan bị xóa theo.
- Database có hai bảng `savings_goals` và `savings_movements` tự tạo khi FastAPI khởi động. Bảng cũ, tiền đang có trong ví, khoản nợ và giao dịch trước đó **không bị sửa**. Không tự động trích tiền khỏi ví khi tạo mục tiêu.
- Dashboard và báo cáo Excel/PDF bổ sung chỉ tiêu dành riêng và tính lại tài sản ròng. **Dòng tiền thuần** tiếp tục chỉ dùng thu, chi, trả nợ, thu hồi nợ; không cộng trùng chuyển ví/mục tiêu.
- Tích hợp kiểm tra bất thường trong **Cài đặt → Bảo mật nâng cao → Kiểm tra số dư**, phát hiện quỹ âm, vượt mục tiêu hoặc liên kết sai chủ tài khoản. Chỉ phát hiện, không tự sửa.

## Bảo mật nâng cao (v1.0.16)

- Trong **Cài đặt → Bảo mật nâng cao**, bật **Xác thực hai bước (TOTP)**. Đầu tiên nhập mật khẩu tài khoản, sau đó quét QR bằng Google Authenticator/Microsoft Authenticator, nhập mã 6 số và **lưu riêng 8 mã dự phòng** hiển thị một lần. Không bật TOTP trước khi hoàn tất bước xác nhận mã.
- TOTP theo chuẩn RFC 6238, chu kỳ 30 giây, cho lệch thời gian tối đa một kỳ; hạn chế tái sử dụng mã, khóa tạm sau 5 lần nhập sai. Mỗi mã dự phòng chỉ dùng một lần và chỉ lưu dạng SHA-256 trong PostgreSQL.
- Bí mật TOTP trong database **được mã hóa bằng Fernet**, khóa `TOTP_ENCRYPTION_KEY` 256-bit được `scripts/start.ps1` sinh một lần và lưu trong **.env trên máy Windows**. Không đưa khóa vào GitHub. **Không thay hoặc xóa khóa này** khi người dùng đã bật 2FA, vì sẽ không thể giải mã bí mật TOTP cũ.
- Sau khi nhập đúng tên đăng nhập/mật khẩu, người dùng bật 2FA phải nhập mã TOTP/mã dự phòng; phiên `HttpOnly` chưa được cấp cho đến khi hoàn tất hai bước. Thời hạn yêu cầu 2FA là 5 phút.
- Trong **Phiên đăng nhập**, xem thời điểm tạo và trình duyệt, thu hồi một phiên hoặc tất cả phiên khác. Không có tính năng giám sát thiết bị từ xa.
- Trong **Kiểm tra số dư**, ứng dụng đọc kiểm tra số dư ví âm, khoản nợ và đối chiếu gốc đã thanh toán, giao dịch liên kết sai ví. Đây là kiểm tra phát hiện bất thường, **không tự sửa** cơ sở dữ liệu và không thay thế đối soát với sao kê ngân hàng.
- Mật khẩu tiếp tục được băm Argon2id; OTP và mã dự phòng **không thay thế** mật khẩu tài khoản. Nếu mất điện thoại TOTP, dùng một mã dự phòng đã lưu; email khôi phục mật khẩu không tự tắt 2FA.

### Xuất báo cáo được phân biệt rõ

Hai nút ở trang **Báo cáo tài chính** được làm rõ bằng biểu tượng, màu và tên **Xuất Excel .XLSX** (xanh) / **Xuất PDF .PDF** (đỏ). Khi tải, trình duyệt kiểm tra MIME và chữ ký tệp để chặn việc nhầm nội dung giữa hai định dạng. Chức năng Excel vẫn có 6 sheet, PDF A4 tiếng Việt; API và dữ liệu báo cáo giữ nguyên.

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
| **v1.0.13** | **Sửa các hàm frontend bị thiếu khiến trang Tổng quan trống; khôi phục toàn bộ màn hình Ví, Người dùng và Nhật ký; bổ sung kiểm thử tự động 9 màn hình trong PowerShell và GitHub Actions.** |
| v1.0.14 | **Thu/chi định kỳ theo ví, chế độ xác nhận hoặc tự ghi, lịch sử chống trùng, nhắc trước hạn cho lịch và nợ, dashboard nhận thông báo, 10 màn hình frontend và 12 kiểm thử API/migration.** |
| **v1.0.15** | **Báo cáo theo 3/6/12/24 tháng, so sánh thu chi, tính dòng tiền có xét trả/thu hồi nợ và loại trừ chuyển ví nội bộ; tổng tài sản ròng hiện tại; xuất Excel 6 sheet và PDF tiếng Việt; kiểm thử API và frontend cho báo cáo.** |
| **v1.0.16** | **Phân biệt trực quan nút Excel/PDF, xác nhận MIME/chữ ký tệp; TOTP Authenticator có QR, mã dự phòng một lần, mã hóa bí mật trong DB, khóa sau nhiều lần nhập sai, quản lý phiên, kiểm tra nhất quán dữ liệu và migration không mất tài khoản cũ.** |
| **v1.0.17** | **Mục tiêu tiết kiệm: góp/rút từ các ví, quỹ dành riêng không tính thu chi, tiến độ và hạn dự kiến, quản lý nhiều mục tiêu, phân quyền, kiểm tra sổ tiền, báo cáo tài sản ròng tính cả tiền tiết kiệm.** |
| **v1.0.18** | **Dự báo dòng tiền 30/60/90 ngày từ lịch định kỳ, phân bổ trả nợ gốc theo thu nhập, phát hiện nguy cơ âm từng ví và cảnh báo kỳ quá hạn, API chỉ đọc không thay số dư.** |
| **v1.0.19** | **Tiền tích để dành (quỹ tích lũy linh hoạt): tạo nhiều quỹ không bắt buộc mục tiêu/hạn mức, góp từ ví hoặc rút về ví, sổ góp/rút bất biến, kiểm tra số dư từng ví và phân quyền. Số dư khả dụng trừ khoản để dành, tài sản ròng cộng lại khoản này; báo cáo Excel/PDF tách riêng tích lũy và mục tiêu tiết kiệm.** |
| **v1.0.20** | **Tích để dành tự động: mỗi quỹ có thể trích 1–100% của thu nhập sau trả nợ, hoặc số tiền cố định. Chọn ví áp dụng; ghi bút toán tự động có liên kết giao dịch gốc, hoàn tác an toàn khi sửa/xóa thu nhập, dự báo số dư sau khi dành riêng tiền. Kiểm tra migration v1.0.19 và chống nhân đôi.** |
| **v1.0.23** | **Đối soát số dư thực tế từng ví: lưu lịch sử kiểm đếm bất biến và chênh lệch tại thời điểm kiểm, kiểm tra nhất quán sổ tiền/nợ/quỹ, phát hiện giao dịch nghi trùng hoặc số tiền lớn bất thường; không tự sửa số dư, phân quyền theo người dùng.** |
| **v1.0.22** | **Quản lý hóa đơn & chứng từ: đính kèm tối đa 8 ảnh/PDF (≤8 MB/tệp) vào mỗi giao dịch, xem trước ảnh, tải/xóa, trang tra cứu lọc theo định dạng/tháng, phân quyền theo chủ giao dịch, lưu nội dung tệp ở Docker volume riêng, kiểm tra SHA-256 và tự xóa tệp khi xóa giao dịch hoặc người dùng.** |
| **v1.0.21** | **Ngân sách thông minh: cảnh báo mốc 70%, 90%, 100% cho từng danh mục; dự báo mức chi cuối tháng từ tốc độ chi và lịch chi còn lại, tránh cộng trùng; gợi ý hạn mức chi/ngày, cảnh báo ngay tại Dashboard; API chỉ đọc, không migration database.** |

Các phiên bản sau cập nhật `VERSION` và ghi chú phát hành trong chính `README.md`, không tạo `CHANGELOG.md` hay các file hướng dẫn theo phiên bản.

## Tiền tích để dành (v1.0.19)

Mở **Tiền tích để dành** trên menu. Tạo quỹ linh hoạt (ví dụ Tiền tích để dành, Quỹ khẩn cấp, Tiền dự phòng); dùng **Góp tiền** hoặc **Rút về ví**. Các khoản này chỉ là điều chuyển nội bộ trên sổ MoneyFlow, không chuyển tiền ngân hàng thật, không phát sinh thu/chi và không có lãi mặc định. Tiền trong các quỹ cộng với tiền tại mục tiêu tiết kiệm đều được tính trong tổng tài sản; số dư khả dụng ví đã loại trừ khoản được giữ riêng. Quỹ đã có lịch sử không thể xóa để duy trì khả năng đối soát. Bảng mới `stash_funds` và `stash_movements` được tạo qua metadata khi ứng dụng khởi động; không cần xóa dữ liệu cũ.


## v1.0.20 — Tự động tích để dành từ mỗi khoản thu

- Mở **Tiền tích để dành** → **Tạo quỹ để dành** hoặc **Sửa** quỹ đang có. Ở mục **Tự động tích lũy khi nhận thu nhập**, chọn **Tắt**, **Theo % thu nhập sau trả nợ** (từ **1–100%**) hoặc **Số tiền cố định (VNĐ)**. Có thể chọn chỉ áp dụng cho một ví nhận tiền hoặc tất cả các ví. **Mặc định Tắt** để không tự trích tiền khi người dùng chưa chủ động bật.
- Khi thêm khoản **Thu nhập mới** (kể cả xác nhận/giao dịch tự động từ lịch định kỳ), MoneyFlow ưu tiên trả **nợ gốc phải trả** như trước. Từ phần thu nhập còn lại, hệ thống áp dụng các quỹ đang bật theo **thứ tự quỹ được tạo**, tính tỷ lệ trên phần thu nhập sau trả nợ (không tính trên tổng số tiền trong ví), sau đó giới hạn theo số còn chưa được phân bổ. Mức cố định cũng chỉ trích tối đa số tiền còn lại. Không trích từ tiền gốc đã có, khoản chuyển giữa ví, tiền thu hồi nợ hoặc khoản chi.
- Ví dụ có lương mới **10.000.000đ**, trừ nợ gốc **2.000.000đ** → thu nhập sau nợ còn **8.000.000đ**. Quỹ A cài **20%** được **1.600.000đ**, quỹ B cố định **1.000.000đ** được **1.000.000đ**; số tiền thực cộng thêm vào ví là **5.400.000đ**. Tiền chuyển vào các quỹ vẫn nằm trong tổng tài sản và **không được tính là chi tiêu**.
- Lịch sử quỹ ghi rõ **Tự động tích lũy** hay **Thủ công**, có liên kết nội bộ tới giao dịch thu nguồn để ngăn bút toán trùng (chỉ một bút toán tự động/quỹ/giao dịch). **Chỉ các khoản thu được ghi sau khi bật quy tắc** mới áp dụng tự động; tiền thu nhập đã lưu trước đó không bị trích hồi tố.
- Khi sửa hoặc xóa khoản thu có tiền tích tự động, chương trình chỉ hoàn tác các bút toán tự động của chính khoản thu đó, phục hồi nợ gốc và đánh giá lại quy tắc. Nếu đã rút tiền từ quỹ khiến không đủ để hoàn tác, hệ thống **chặn thao tác** và giữ nguyên toàn bộ số dư; cần góp hoàn tiền vào quỹ trước.
- Trang **Dự báo dòng tiền** bổ sung chỉ tiêu **Dự kiến để dành**, tính trên các khoản thu định kỳ giả định và dự báo **số dư khả dụng sau trừ nợ, tích lũy**. Dự báo chỉ đọc, không tự tạo bút toán. Báo cáo Excel/PDF hiện có tiếp tục ghi các khoản quỹ như **tài sản dành riêng**, không cộng hai lần vào thu/chi.
- Database **không thêm bảng mới**: bổ sung `auto_mode`, `auto_value`, `auto_wallet_id` vào `stash_funds` và `source_entry_id` vào `stash_movements`, thêm unique partial index cho (quỹ, giao dịch thu). Migration PostgreSQL/SQLite chạy **idempotent** và giữ quỹ/lịch sử từ v1.0.19. Quy tắc cũ tự mặc định `off`.
- Tài khoản và số dư hiện tại vẫn nằm trong PostgreSQL Docker cũ; không xóa volume. Trên Windows, dùng `scripts/run.ps1` để tự mở Docker Desktop → test/build/chạy; `scripts/publish.ps1 -Version 1.0.21` để phát hành và xác minh GitHub Release.



## v1.0.22 — Quản lý hóa đơn & chứng từ

- Trong **Giao dịch**, nhấn **Chứng từ** tại một giao dịch đã ghi. Chọn ảnh hóa đơn/biên lai (JPG, JPEG, PNG, WEBP) hoặc PDF để đính kèm. Có thể mở **Hóa đơn & chứng từ** trong menu để tra cứu, lọc theo loại tệp, theo tháng của giao dịch hoặc tên tệp/nội dung giao dịch; có phân trang 30 tệp mỗi lần.
- **Tệp được lưu riêng tư**: PostgreSQL chứa bảng `receipts` với người dùng, giao dịch, tên gốc, định dạng đã xác thực, dung lượng, SHA-256, ngày tạo và khóa lưu trữ ngẫu nhiên. Nội dung tệp được lưu tại `/opt/moneyflow/receipts` trong Docker volume **`moneyflow_receipts`** của dự án (tên thực tế theo Docker Compose thường là `moneyflow-local_moneyflow_receipts`). Đây là volume độc lập với source ZIP và dữ liệu PostgreSQL, tồn tại qua việc build lại ứng dụng hoặc tạo lại container thông thường.
- **Bảo mật**: chỉ tài khoản sở hữu giao dịch được liệt kê, tải hoặc xóa tệp tương ứng; bảo vệ bằng phiên đăng nhập + CSRF cho thao tác ghi. Giới hạn **8 tệp/giao dịch**, **8 MiB/tệp**; kiểm tra phần mở rộng, chữ ký tệp, đọc xác minh ảnh bằng Pillow; từ chối các tệp khác định dạng, tệp hỏng và HTML/SVG/executable. Tệp PDF được tải về theo dạng attachment; chỉ ảnh mới có nút **Xem** trong ứng dụng.
- **Tính toàn vẹn**: mã SHA-256 được lưu khi đính kèm và kiểm tra trước khi tải. Nếu tệp bị sửa/hỏng trên ổ đĩa, API từ chối tải thay vì gửi nội dung giả. Không lưu đường dẫn hoặc tên do người dùng chọn làm đường dẫn thật; ứng dụng dùng khóa ngẫu nhiên riêng.
- **Vòng đời**: sửa nội dung/số tiền giao dịch không làm mất chứng từ; xóa giao dịch sẽ xóa các tệp của giao dịch. Xóa tài khoản theo quyền Admin cũng xóa các chứng từ của tài khoản đó. Xóa riêng một chứng từ không làm thay đổi số dư hay lịch sử tiền; đính kèm cũng không tạo bút toán thu/chi.
- **Phạm vi**: hoạt động local, không đọc OCR hoặc tự nhập số tiền từ hóa đơn; chưa có tích hợp ngân hàng hoặc quét mã QR thanh toán. Cơ chế kiểm tra loại file không thay thế phần mềm chống virus của Windows; chỉ mở những tệp từ nguồn bạn tin cậy.
- **Database**: tạo mới bảng `receipts` bằng SQLAlchemy `create_all` khi ứng dụng khởi động; không sửa cấu trúc bảng giao dịch cũ, không cần tạo lại database. Quyền ghi thư mục tệp thuộc tài khoản ứng dụng không đặc quyền trong Docker. Các tệp đính kèm không được đóng gói vào Full Source ZIP hoặc tải lên GitHub.
- **Kiểm thử**: thêm bài kiểm tra quyền truy cập, chống giả định dạng, giới hạn dung lượng/số tệp, kiểm tra SHA-256, xóa tệp khi xóa giao dịch/người dùng và API tra cứu. Frontend smoke test mở trang Kho chứng từ và biểu mẫu đính kèm.

## v1.0.21 — Ngân sách thông minh

- **Ngân sách** hiển thị ngưỡng sử dụng **70% (cảnh báo), 90% (nguy cơ cao), 100% (chạm hạn mức)** và **vượt hạn mức** theo từng danh mục. Dashboard hiển thị cảnh báo nổi bật và nút mở trang ngân sách.
- Với **tháng hiện tại**, dự báo chi cuối tháng dùng kịch bản cao hơn giữa (1) tốc độ chi thực tế từ đầu tháng, cộng chi tiêu đã ghi ngày tương lai; và (2) số đã ghi cộng các kỳ chi định kỳ chưa xử lý còn lại. Cách này tránh đếm trùng hóa đơn định kỳ trong cả hai kịch bản. Đơn vị tiền là VNĐ nguyên, không tính chuyển ví hoặc trả nợ gốc là chi tiêu theo danh mục.
- Hiển thị **mức có thể chi/ngày còn lại** = max(0, (hạn mức - tiền đã ghi - kỳ chi định kỳ còn lại) / số ngày còn lại), làm tròn xuống. Nếu cần tăng ngân sách, điều chỉnh thủ công ở nút **Chỉnh sửa**.
- Với tháng quá khứ hoặc tương lai, chỉ xem số tiền đã ghi, **không dự báo**; tháng hiện tại hiển thị nhãn rõ là **ước tính**. Quỹ để dành và nợ không bị thay đổi. Lịch đã ghi hoặc bỏ qua được loại trừ khi dự báo khoản chi định kỳ còn lại.
- Endpoint **GET `/api/budgets/insights?month=YYYY-MM`** được bảo vệ bởi phiên đăng nhập và có `Cache-Control: no-store`; không ghi dữ liệu. Cấu trúc bảng PostgreSQL giữ nguyên, không tạo migration mới.
- Lệnh phát hành lịch sử: `scripts/publish.ps1 -Version 1.0.21`. Kết quả thực tế trên Windows cần được xác minh bằng `scripts/run.ps1` trước khi công bố GitHub Release.
