'use strict';
// MoneyFlow is a local web app; discard optional campaign tracking query strings.
if (window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost') {
  const clean = new URL(window.location.href);
  let changed = false;
  for (const key of [...clean.searchParams.keys()]) {
    if (/^utm_/i.test(key)) { clean.searchParams.delete(key); changed = true; }
  }
  if (changed) history.replaceState(history.state, '', clean.pathname + clean.search + clean.hash);
}
const $ = (s, parent=document) => parent.querySelector(s);
const $$ = (s, parent=document) => Array.from(parent.querySelectorAll(s));
const fmoney = n => new Intl.NumberFormat('vi-VN', {maximumFractionDigits:0}).format(Number(n)||0) + ' ₫';
// Keep Vietnamese numbers readable even when old records were stored with +84.
const vietnamPhone = value => {
  const raw=String(value??'').trim();
  const compact=raw.replace(/[\s().-]/g,'');
  const m=compact.match(/^(?:\+84|0084|84)([1-9]\d{8,9})$/);
  return m?'0'+m[1]:raw;
};

const fcompact = n => {n=Number(n)||0;const a=Math.abs(n);if(a>=1e9)return (n/1e9).toLocaleString('vi-VN',{maximumFractionDigits:1})+' tỷ';if(a>=1e6)return (n/1e6).toLocaleString('vi-VN',{maximumFractionDigits:1})+' tr';if(a>=1e3)return (n/1e3).toLocaleString('vi-VN',{maximumFractionDigits:0})+'k';return n.toLocaleString('vi-VN')};
const esc = v => String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const today = () => {const d=new Date();return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`};
const thisMonth = () => today().slice(0,7);
const monthText = m => {const [y,mo]=m.split('-');return `Tháng ${+mo}/${y}`};
const pct=(a,b)=>b>0?Math.round(a/b*100):0;
const state={user:null,csrf:null,loginTicket:null,needsSetup:false,authMode:'login',resetToken:null,page:'dashboard',month:thisMonth(),categories:[],transPage:1,transKind:'',transCategory:'',transSearch:'',transWallet:'',receiptSearch:'',receiptKind:'',receiptMonth:'',receiptPage:1,wallets:[],data:null,reminders:[],recurringData:null,reportMonths:12,annualYear:new Date().getFullYear(),forecastDays:30};
const PAGE_NAMES={annual:'Thống kê theo năm',forecast:'Dự báo dòng tiền',reports:'Báo cáo tài chính',recurring:'Định kỳ & nhắc lịch',wallets:'Ví & tài khoản',stashes:'Tiền tích để dành',savings:'Mục tiêu tiết kiệm',dashboard:'Tổng quan',transactions:'Giao dịch',receipts:'Hóa đơn & chứng từ',reconciliation:'Đối soát tài chính',budgets:'Ngân sách',debts:'Quản lý nợ',categories:'Danh mục',settings:'Cài đặt',users:'Người dùng',audit:'Nhật ký hệ thống'};

async function api(path, options={}) {
  const headers={...(options.headers||{})};
  if(options.body!==undefined)headers['Content-Type']='application/json';
  if(state.csrf && options.method && !['GET','HEAD'].includes(options.method))headers['X-CSRF-Token']=state.csrf;
  let r;
  try {r=await fetch('/api/'+path.replace(/^\//,''),{...options,headers,credentials:'same-origin'});} catch {throw new Error('Không thể kết nối máy chủ. Hãy kiểm tra Docker đang chạy.');}
  if(!r.ok){let err={};try{err=await r.json()}catch{};if(r.status===401&&state.user){state.user=null;showAuth();throw new Error('Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.')}throw new Error(typeof err.detail==='string'?err.detail:'Yêu cầu không thành công.');}
  return r.headers.get('content-type')?.includes('application/json')?r.json():r;
}
function toast(message,error=false){const r=$('#toast-root');r.innerHTML=`<div class="toast ${error?'error':''}">${esc(message)}</div>`;clearTimeout(toast.timer);toast.timer=setTimeout(()=>r.innerHTML='',4200)}
function setBusy(b){$$('button[type="submit"]').forEach(x=>x.disabled=b)}
function strongPassword(password) {
  return password.length>=12 && password.length<=128 && /[a-z]/.test(password) && /[A-Z]/.test(password) && /[0-9]/.test(password) && /[^\w\s]|_/.test(password);
}
function passwordMeter(value) {
  const checks=[value.length>=12,/[a-z]/.test(value),/[A-Z]/.test(value),/[0-9]/.test(value),/[^\w\s]|_/.test(value)];
  let score=checks.filter(Boolean).length;
  if(value.length>=16&&score===5)score=6;
  if(!value)score=0;
  const labels=['Chưa nhập mật khẩu','Rất yếu','Yếu','Trung bình','Khá','Mạnh','Rất mạnh'];
  const widths=[0,16,32,48,64,84,100];
  return `<div class="strength-head"><span>Độ mạnh mật khẩu</span><strong class="strength-level level-${score}">${labels[score]}</strong></div><div class="strength-track" role="progressbar" aria-label="Độ mạnh mật khẩu" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${widths[score]}"><i class="level-${score}" style="width:${widths[score]}%"></i></div><div class="strength-checks">${['12+ ký tự','Chữ thường','Chữ hoa','Chữ số','Ký tự đặc biệt'].map((item,i)=>`<span class="${checks[i]?'met':''}">${checks[i]?'✓':'○'} ${item}</span>`).join('')}</div>`;
}
function updateStrength(input) {
  const target=$(`[data-meter="${input.dataset.passwordStrength}"]`);
  if(target)target.innerHTML=passwordMeter(input.value);
}
function updatePasswordConfirmation(kind, scope=document) {
  const password=$(`[data-password-strength="${kind}"]`,scope);
  const confirmation=$(`[data-confirm-password="${kind}"]`,scope);
  const feedback=$(`[data-confirm-status="${kind}"]`,scope);
  if(!password||!confirmation||!feedback)return;
  // Avoid stale confirmation errors when the setup form is hidden in login mode.
  if(confirmation.disabled) {confirmation.setCustomValidity('');feedback.textContent='';return;}
  const provided=confirmation.value.length>0;
  const same=provided && password.value===confirmation.value;
  confirmation.setCustomValidity(provided&&!same?'Mật khẩu xác nhận không khớp.':'');
  feedback.textContent=provided?(same?'✓ Hai mật khẩu trùng khớp.':'✕ Mật khẩu xác nhận chưa trùng khớp.'):'Nhập lại mật khẩu để xác nhận.';
  feedback.classList.toggle('is-match',same);
  feedback.classList.toggle('is-mismatch',provided&&!same);
}
function checkPasswordConfirmation(password, confirmation){
  if(password!==confirmation)throw new Error('Mật khẩu xác nhận không trùng khớp.');
}
function showAuth(mode=null){
  $('#shell').hidden=true;$('#auth-screen').hidden=false;$('#modal-root').innerHTML='';
  if(mode)state.authMode=mode;
  else if(state.authMode!=='reset')state.authMode=state.needsSetup?'setup':'login';
  const modeNow=state.authMode,setup=modeNow==='setup',forgot=modeNow==='forgot',reset=modeNow==='reset',otp=modeNow==='otp';
  $('#auth-title').textContent=otp?'Xác thực hai bước':setup?'Tạo tài khoản quản trị':forgot?'Lấy lại mật khẩu':reset?'Đặt lại mật khẩu':'Đăng nhập tài khoản';
  $('#auth-subtitle').textContent=otp?'Nhập mã 6 số trên ứng dụng xác thực hoặc mã dự phòng.':setup?'Tạo tài khoản quản trị với thông tin liên hệ đầy đủ.':forgot?'Khôi phục quyền truy cập bằng email đã đăng ký.':reset?'Chọn mật khẩu mạnh để bảo vệ dữ liệu tài chính.':'Đăng nhập để tiếp tục quản lý tài chính.';
  $('#auth-form').hidden=forgot||reset||otp;$('#forgot-form').hidden=!forgot;$('#reset-form').hidden=!reset;$('#otp-form').hidden=!otp;
  $$('.signup-only').forEach(el=>el.hidden=!setup);
  $$('.signup-only input').forEach(el=>{el.required=setup;el.disabled=!setup;if(!setup)el.setCustomValidity('');});
  $('#auth-form [name="password"]').autocomplete=setup?'new-password':'current-password';
  $('#auth-submit').innerHTML=setup?'Tạo tài khoản <span>→</span>':'Đăng nhập <span>→</span>';
  $('#auth-links').hidden=setup||otp;$('#forgot-link').hidden=modeNow!=='login';$('#back-login-link').hidden=modeNow==='login';
  for(const key of ['auth','forgot','reset','otp']) {const x=$(`#${key}-error`);if(x)x.textContent='';}
  $$('[data-password-strength]').forEach(updateStrength);
  updatePasswordConfirmation('auth');updatePasswordConfirmation('reset');
  if(forgot){api('recovery-config').then(config=>{if(state.authMode==='forgot'&&!config.email_configured)$('#forgot-notice').textContent='Hệ thống chưa cấu hình SMTP. Cần thiết lập email gửi trong file .env theo README trước khi sử dụng chức năng này.'}).catch(()=>{});}
}
function showShell(){ $('#auth-screen').hidden=true;$('#shell').hidden=false;$('#sidebar-username').textContent=state.user.username;$('#sidebar-role').textContent=state.user.role==='admin'?'Quản trị viên':'Thành viên';$('#sidebar-avatar').textContent=state.user.username.charAt(0).toUpperCase();$('#header-avatar').textContent=state.user.username.charAt(0).toUpperCase();$$('.admin-only').forEach(el=>el.hidden=state.user.role!=='admin'); }
async function bootstrap(){
  const token=new URLSearchParams(window.location.search).get('token');
  if(token && window.location.pathname==='/reset'){state.resetToken=token;history.replaceState({},'', '/reset');}
  try{const m=await api('me');state.user=m.user;state.csrf=m.csrf_token;
    if(state.resetToken){showAuth('reset');return;}
    showShell();await navigate('dashboard');if(!state.user.profile_complete)setTimeout(()=>profileModal(),180);
  }catch{try{state.needsSetup=(await api('setup-status')).needs_setup}catch{state.needsSetup=false}
    showAuth(state.resetToken?'reset':state.needsSetup?'setup':'login');}
}
async function refreshReminders() {
  const result=await api('reminders');
  state.reminders=result.items||[];
  const count=state.reminders.length;
  window.MoneyFlowPWA?.onReminders?.(count, state.user?.id)?.catch?.(()=>{});
  const label=$('#reminder-count');
  if(label){label.hidden=count===0;label.textContent=count>99?'99+':String(count);}
  return result;
}
const recurrenceName={daily:'Hằng ngày',weekly:'Hằng tuần',monthly:'Hằng tháng',yearly:'Hằng năm'};
function dueTag(due){const delta=Math.ceil((Date.parse(due+'T00:00:00')-Date.parse(today()+'T00:00:00'))/86400000);
 return delta<0?`<span class="schedule-pill overdue">Trễ ${Math.abs(delta)} ngày</span>`:delta===0?'<span class="schedule-pill today">Hôm nay</span>':`<span class="schedule-pill">Còn ${delta} ngày</span>`;}
function remindItem(r){return `<div class="reminder-item"><span class="reminder-symbol">${r.kind==='debt'?'◈':r.direction==='income'?'↗':'↘'}</span><div class="reminder-copy"><strong>${esc(r.title)}</strong><small>${r.kind==='debt'?(r.direction==='payable'?'Trả nợ':'Thu hồi nợ'):'Giao dịch định kỳ'} · ${esc(r.due_on)} · ${fmoney(r.amount)}</small></div>${dueTag(r.due_on)}</div>`;}
async function renderRecurring(){
  const result=await api('recurring');state.recurringData=result;
  const reminders=state.reminders;
  const items=result.items||[];
  const upcoming=items.filter(x=>x.active).length;
  const alerts=reminders.length?reminders.map(remindItem).join(''):empty('Không có lịch cần nhắc','Nhắc nhở hiển thị khi đến gần hạn thanh toán hoặc nhận lương.');
  const cards=items.map(r=>`<article class="schedule-card"><div class="schedule-top"><span class="tag ${r.active?'tag-active':'tag-disabled'}">${r.active?'Đang theo dõi':'Đã tạm dừng'}</span><span class="schedule-pill">${esc(recurrenceName[r.frequency]||r.frequency)}</span></div><h3>${esc(r.title)}</h3><strong class="schedule-money ${r.kind}">${r.kind==='income'?'+':'−'}${fmoney(r.amount)}</strong><p>${esc(walletName(r.wallet_id))} · ${esc(state.categories.find(c=>c.id===r.category_id)?.name||'Danh mục')}</p><div class="schedule-date">Kỳ tiếp theo: <b>${esc(r.next_due)}</b> ${dueTag(r.next_due)}</div><div class="schedule-caption">${r.mode==='auto'?'⚡ Tự ghi khi đến hạn':'✓ Chờ xác nhận'} · Đã xử lý ${r.processed_count} kỳ</div><div class="schedule-actions"><button class="table-action" data-action="recurring-edit" data-id="${r.id}">Sửa</button><button class="table-action" data-action="recurring-toggle" data-id="${r.id}">${r.active?'Tạm dừng':'Kích hoạt'}</button>${r.processed_count===0?`<button class="table-action delete" data-action="recurring-delete" data-id="${r.id}">Xóa</button>`:''}${r.mode==='manual'&&r.active&&r.next_due<=today()?`<button class="table-action" data-action="recurring-confirm" data-id="${r.id}">Ghi giao dịch</button><button class="table-action delete" data-action="recurring-skip" data-id="${r.id}">Bỏ qua kỳ</button>`:''}</div></article>`).join('');
  const history=(result.history||[]).map(h=>{const rule=items.find(r=>r.id===h.rule_id);return `<tr><td>${esc(h.due_on)}</td><td>${esc(rule?.title||'Lịch đã ẩn')}</td><td><span class="tag ${h.status==='posted'?'tag-active':'tag-disabled'}">${h.status==='posted'?'Đã ghi':h.status==='skipped'?'Đã bỏ qua':'Giao dịch đã xóa'}</span></td><td>${h.entry_id?'#'+h.entry_id:'—'}</td></tr>`;}).join('');
  $('#page-content').innerHTML=heading('Giao dịch định kỳ & nhắc lịch','Quản lý lương, hóa đơn, tiền nhà và lịch trả nợ. Chế độ thủ công là mặc định.',`<button class="btn btn-primary" data-action="recurring-add">+ Tạo lịch định kỳ</button>`)+
    `<div class="schedule-summary"><div class="schedule-kpi"><small>Lịch đang hoạt động</small><strong>${upcoming}</strong></div><div class="schedule-kpi"><small>Cần chú ý</small><strong>${reminders.length}</strong></div><div class="schedule-kpi"><small>Đã xử lý</small><strong>${(result.history||[]).length}</strong></div></div>`+
    `<section class="panel"><div class="panel-head"><div><h2>🔔 Nhắc nhở sắp tới</h2><p class="panel-sub">Giao dịch định kỳ theo số ngày bạn chọn; khoản nợ nhắc trước 7 ngày.</p></div></div><div class="reminder-stack">${alerts}</div></section>`+
    `<section class="panel schedule-section"><div class="panel-head"><div><h2>Danh sách lịch định kỳ</h2><p class="panel-sub">Giao dịch tự động chỉ chạy khi MoneyFlow/Docker còn hoạt động, và sẽ xử lý kỳ còn lại khi mở lại.</p></div><span class="mini-stat">${items.length} lịch</span></div>${cards?`<div class="schedule-grid">${cards}</div>`:empty('Chưa có lịch định kỳ','Tạo lịch nhận lương hoặc thanh toán hóa đơn theo tháng.')}</section>`+
    `<section class="panel schedule-section"><div class="panel-head"><div><h2>Lịch sử xử lý</h2><p class="panel-sub">Mỗi kỳ chỉ tạo tối đa một giao dịch, kể cả khi hệ thống khởi động lại.</p></div></div><div class="table-wrap"><table class="data-table"><thead><tr><th>NGÀY ĐẾN HẠN</th><th>LỊCH</th><th>KẾT QUẢ</th><th>GIAO DỊCH</th></tr></thead><tbody>${history||'<tr><td colspan="4" class="table-row-empty">Chưa xử lý kỳ nào.</td></tr>'}</tbody></table></div></section>`;
}
function recurringModal(existing=null){
 const kind=existing?.kind||'expense';const options=state.categories.filter(x=>x.kind===kind&&x.active).map(x=>`<option value="${x.id}" ${existing?.category_id===x.id?'selected':''}>${esc(x.name)}</option>`).join('');
 const body=`<input type="hidden" name="id" value="${existing?.id||''}"/>`+
 (existing?`<div class="simple-info">Loại giao dịch, tần suất và ngày bắt đầu được giữ nguyên sau khi tạo lịch để đảm bảo lịch sử chính xác.</div>`:`<label>Loại giao dịch<select class="select" name="kind" id="recurring-kind"><option value="expense">↘ Chi định kỳ</option><option value="income">↗ Thu định kỳ</option></select></label>`)+
 `<label>Nội dung<input class="input" name="title" maxlength="120" required placeholder="Ví dụ: Lương, tiền thuê nhà, điện nước" value="${esc(existing?.title||'')}"/></label>`+
 `<div class="row-fields"><label>Số tiền (VNĐ)<input class="input" type="number" min="1" max="1000000000000" step="1" name="amount" required value="${existing?.amount??''}"/></label>${existing?'':`<label>Bắt đầu từ ngày<input class="input" type="date" name="start_on" value="${today()}" required/></label>`}</div>`+
 (existing?'':`<label>Tần suất<select class="select" name="frequency"><option value="monthly">Hằng tháng</option><option value="weekly">Hằng tuần</option><option value="daily">Hằng ngày</option><option value="yearly">Hằng năm</option></select></label>`)+
 `<label>Danh mục<select class="select" name="category_id" id="recurring-category" required>${options}</select></label>${walletSelect(existing?.wallet_id)}`+
 `<label>Cách ghi nhận<select class="select" name="mode"><option value="manual" ${existing?.mode==='manual'||!existing?'selected':''}>Xác nhận trước khi ghi (khuyến nghị)</option><option value="auto" ${existing?.mode==='auto'?'selected':''}>Tự ghi khi đến hạn</option></select></label>`+
 `<label>Nhắc trước (ngày)<input class="input" type="number" name="remind_days" min="0" max="30" step="1" value="${existing?.remind_days??3}" required/></label>`+
 `<label>Ghi chú<textarea class="textarea" name="note" maxlength="500">${esc(existing?.note||'')}</textarea></label>`+
 `<div class="simple-info">Khoản thu định kỳ sẽ ưu tiên trừ nợ phải trả như các khoản thu thường. Khoản chi tự động chỉ ghi khi ví đủ tiền. Các thông báo hiển thị bên trong ứng dụng, không gửi email.</div>`;
 openModal(existing?'Chỉnh sửa lịch định kỳ':'Tạo lịch thu/chi định kỳ','Bạn có thể tạm dừng hoặc bỏ qua một kỳ sau này.',body,'recurring',existing?'Lưu thay đổi':'Tạo lịch');
}

function heading(name,subtitle,buttons=''){return `<div class="page-heading"><div class="heading-main"><div class="eyebrow">MONEYFLOW / ${esc(name.toUpperCase())}</div><h1>${esc(name)}</h1><p>${esc(subtitle)}</p></div><div class="heading-actions">${buttons}</div></div>`}
const addButton=(name='Thêm giao dịch')=>`<button class="btn btn-primary" data-action="add-entry"><span class="plus-symbol">+</span> ${esc(name)}</button>`;
function empty(title,subtitle){return `<div class="empty-state"><div class="empty-emoji">✳</div><strong>${esc(title)}</strong><div>${esc(subtitle)}</div></div>`}
function iconCat(c){return `<i class="legend-dot" style="background:${esc(c.color)}"></i>`}
function rows(entries, actions=false){if(!entries?.length)return `<tr><td colspan="${actions?6:5}" class="table-row-empty">Chưa có giao dịch nào. Hãy thêm khoản thu hoặc chi đầu tiên ✨</td></tr>`;
 return entries.map(e=>`<tr><td><div class="item-name">${esc(e.title)}</div><div class="item-note">${esc(e.note||'')}<div class="wallet-tagline">◈ ${esc(walletName(e.wallet_id))}</div>${e.debt_paid?`<div class="debt-paid-hint">↘ Đã tự trừ nợ: ${fmoney(e.debt_paid)}</div>`:''}</div></td><td>${esc(new Date(e.occurred_on+'T00:00:00').toLocaleDateString('vi-VN'))}</td><td><span class="category-chip">${iconCat(e)} ${esc(e.category)}</span></td><td><span class="tag ${e.kind==='income'?'tag-active':'tag-disabled'}">${e.kind==='income'?'Thu':'Chi'}</span></td><td class="amount ${e.kind}">${e.kind==='income'?'+':'−'}${fmoney(e.amount)}</td>${actions?`<td><div class="row-actions"><button class="table-action receipt-action" data-action="entry-receipts" data-id="${e.id}" title="Quản lý ảnh, PDF chứng từ cho giao dịch">▣ Chứng từ${e.receipt_count?` (${e.receipt_count})`:''}</button><button class="table-action" data-action="edit-entry" data-id="${e.id}">Sửa</button><button class="table-action delete" data-action="delete-entry" data-id="${e.id}">Xóa</button></div></td>`:''}</tr>`).join('');}
function tableHtml(entries,actions=false){return `<div class="table-wrap"><table class="data-table"><thead><tr><th>NỘI DUNG</th><th>NGÀY</th><th>DANH MỤC</th><th>LOẠI</th><th style="text-align:right">SỐ TIỀN</th>${actions?'<th style="text-align:right">THAO TÁC</th>':''}</tr></thead><tbody>${rows(entries,actions)}</tbody></table></div>`}
function trendChart(trend){const max=Math.max(1,...trend.flatMap(t=>[t.income,t.expense]));return `<div class="chart-wrap"><div class="bar-chart">${trend.map(t=>`<div class="bar-month" title="${esc(monthText(t.month))}: Thu ${fmoney(t.income)} · Chi ${fmoney(t.expense)}"><div class="bar income" style="height:${Math.max(t.income>0?2:0,t.income/max*100)}%"></div><div class="bar expense" style="height:${Math.max(t.expense>0?2:0,t.expense/max*100)}%"></div></div>`).join('')}</div><div class="chart-axis">${trend.map(t=>`<span>T${+t.month.slice(5)}</span>`).join('')}</div></div>`}
// v1.0.5: Radial pie chart (solid sectors reach the centre, unlike a doughnut).
function donutChart(rawData) {
  const safeColor = value => /^#[0-9a-fA-F]{6}$/.test(String(value)) ? String(value) : '#8377f9';
  const parsed = (Array.isArray(rawData) ? rawData : []).map((c, i) => ({
    name: String(c.name || 'Khác'),
    value: Number(c.value),
    color: safeColor(c.color),
    index: i
  })).filter(c => Number.isFinite(c.value) && c.value > 0).sort((a, b) => b.value - a.value);
  const total = parsed.reduce((sum, c) => sum + c.value, 0);
  if (!total) {
    return `<div class="pie-layout pie-empty-layout"><div class="pie-chart pie-empty" role="img" aria-label="Chưa có chi tiêu trong tháng"><span class="pie-empty-glyph" aria-hidden="true">✳</span></div><div class="pie-details"><div class="pie-total-label">TỔNG CHI TIÊU</div><div class="pie-total-number">${fmoney(0)}</div>${empty('Chưa có chi tiêu','Danh mục và tỷ trọng sẽ xuất hiện khi bạn thêm khoản chi.')}</div></div>`;
  }
  // Keep the legend and the sectors identical when there are more than six categories.
  const items = parsed.length > 6 ? [
    ...parsed.slice(0, 5),
    {name: 'Danh mục khác', value: parsed.slice(5).reduce((sum, c) => sum + c.value, 0), color: '#66738f'}
  ] : parsed;
  let start = -Math.PI / 2;
  const circle = (cx, cy, r) => `${cx},${cy} ${r},${r}`;
  const sectors = items.map((c, idx) => {
    const proportion = c.value / total;
    const end = idx === items.length - 1 ? 3 * Math.PI / 2 : start + proportion * 2 * Math.PI;
    const x1 = 100 + 90 * Math.cos(start), y1 = 100 + 90 * Math.sin(start);
    const x2 = 100 + 90 * Math.cos(end), y2 = 100 + 90 * Math.sin(end);
    const sector = items.length === 1
      ? `<circle cx="100" cy="100" r="90" fill="${c.color}"/>`
      : `<path d="M 100 100 L ${x1.toFixed(4)} ${y1.toFixed(4)} A 90 90 0 ${proportion > 0.5 ? 1 : 0} 1 ${x2.toFixed(4)} ${y2.toFixed(4)} Z" fill="${c.color}" stroke="#1b2540" stroke-width="1.7" stroke-linejoin="round"/>`;
    start = end;
    return `<g class="pie-sector" tabindex="0" aria-label="${esc(c.name)}: ${pct(c.value,total)}%, ${fmoney(c.value)}"><title>${esc(c.name)} · ${pct(c.value,total)}% · ${fmoney(c.value)}</title>${sector}</g>`;
  }).join('');
  const label = items.map(c => `${c.name}: ${pct(c.value,total)}%`).join('; ');
  return `<div class="pie-layout"><div class="pie-visual"><svg class="pie-chart" viewBox="0 0 200 200" role="img" aria-label="Biểu đồ tròn chi tiêu theo danh mục: ${esc(label)}"><circle cx="100" cy="100" r="94" fill="#283455"/>${sectors}</svg><span class="pie-caption">Biểu đồ tròn · Chia từ tâm</span></div><div class="pie-details"><div class="pie-total-label">TỔNG CHI TIÊU</div><div class="pie-total-number">${fmoney(total)}</div><div class="category-legend">${items.map(c => `<div class="cat-legend-item" title="${esc(c.name)}: ${fmoney(c.value)}"><i class="legend-dot" style="background:${c.color}"></i><span>${esc(c.name)}</span><b>${pct(c.value,total)}%</b></div>`).join('')}</div></div></div>`;
}

function budgetStatusLabel(b){
 const labels={exceeded:'Đã vượt mức',limit:'Chạm 100%',critical:'Cảnh báo 90%',warning:'Cảnh báo 70%',zero:'Hạn mức 0',ok:'Trong hạn mức'};
 return labels[b.status]||'Đang theo dõi';
}
function budgetAlertMarkup(alerts){
 if(!Array.isArray(alerts)||!alerts.length)return '';
 return `<section class="panel smart-budget-alerts" aria-label="Cảnh báo ngân sách"><div class="panel-head"><div><h2>⚠ Cảnh báo ngân sách</h2><p class="panel-sub">Ngưỡng sử dụng 70%, 90%, 100% và khả năng vượt hạn mức tháng hiện tại</p></div><button class="panel-link" data-page="budgets">Chi tiết →</button></div><div class="smart-alert-list">${alerts.slice(0,5).map(b=>`<div class="smart-alert-row"><span class="smart-status smart-${b.status}">${esc(budgetStatusLabel(b))}</span><strong>${esc(b.category)}</strong><span>${fmoney(b.spent)} / ${fmoney(b.amount)}${b.at_risk&&b.status==='ok'?' · Có nguy cơ vượt vào cuối tháng':''}</span></div>`).join('')}</div></section>`;
}
function budgetBars(budgets){return budgets.length?`<div class="budget-stack">${budgets.slice(0,5).map(b=>`<div><div class="budget-name-row"><span>${esc(b.category)}</span><small>${fcompact(b.spent)} / ${fcompact(b.amount)}</small></div><div class="progress-track"><div class="progress-fill" style="width:${Math.min(100,pct(b.spent,b.amount))}%;background:${b.spent>b.amount?'#fc6b88':esc(b.color)}"></div></div>${b.spent>b.amount?'<div class="budget-caption over">⚠ Đã vượt ngân sách</div>':''}</div>`).join('')}</div>`:empty('Chưa tạo ngân sách','Đặt hạn mức cho từng danh mục để kiểm soát chi tiêu.')}
function signedMoney(n){return `${n>=0?'+':'−'}${fmoney(Math.abs(n))}`}
function reportDifference(compare){
 if(!compare)return '';
 const pctText=compare.percentage===null?'không có cơ sở so sánh':`${compare.percentage>0?'+':''}${compare.percentage.toLocaleString('vi-VN')}%`;
 return `<span class="report-difference ${compare.difference>=0?'up':'down'}">${signedMoney(compare.difference)} · ${pctText} so với tháng trước</span>`;
}
function reportChart(series){
 const max=Math.max(1,...series.flatMap(r=>[r.income,r.expense]));
 return `<div class="report-bar-chart" role="img" aria-label="Biểu đồ thu nhập và chi tiêu theo ${series.length} tháng"><div class="report-bar-plot">${series.map(r=>{
   const hInc=Math.max(1,r.income/max*100),hExp=Math.max(1,r.expense/max*100);
   return `<div class="report-bar-column" title="${esc(r.month)}: Thu ${fmoney(r.income)}, chi ${fmoney(r.expense)}"><div class="report-bars"><div class="report-bar income" style="height:${hInc}%"></div><div class="report-bar expense" style="height:${hExp}%"></div></div><small>${esc(r.month.slice(5))}/${esc(r.month.slice(2,4))}</small></div>`;
 }).join('')}</div></div>`;
}
// v1.0.24: read-only yearly activity and retrospective estimated net-worth.
function annualLinePlot(rows){
 if(!rows.length)return empty('Chưa có dữ liệu','Năm này chưa có dữ liệu để hiển thị.');
 const w=900,h=250,p=30;
 const values=rows.map(x=>Number(x.net_worth));
 let lo=Math.min(...values,0),hi=Math.max(...values,0);
 if(lo===hi)hi=lo+1;
 const X=i=>p+i*(w-2*p)/Math.max(1,rows.length-1);
 const Y=n=>p+(hi-Number(n))*(h-2*p)/(hi-lo);
 const d=rows.map((r,i)=>(i?'L':'M')+X(i).toFixed(1)+' '+Y(r.net_worth).toFixed(1)).join(' ');
 const labels=rows.map((r,i)=>`<text x="${X(i)}" y="245" font-size="12" text-anchor="middle" fill="#a4b2cd">T${i+1}</text>`).join('');
 return `<div class="annual-plot"><svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Biểu đồ tài sản ròng theo tháng"><line x1="${p}" y1="${Y(0)}" x2="${w-p}" y2="${Y(0)}" stroke="#57648b" stroke-dasharray="6 4"/><path d="${d}" fill="none" stroke="#9b86ff" stroke-width="4" stroke-linejoin="round"/>${rows.map((r,i)=>`<circle cx="${X(i)}" cy="${Y(r.net_worth)}" r="4" fill="#48d7b4"><title>${esc(r.month)}: ${fmoney(r.net_worth)}</title></circle>`).join('')}${labels}</svg></div>`;
}
async function renderAnnual(){
 const d=await api(`reports/annual?year=${state.annualYear}`);
 const t=d.totals,close=d.closing||{available:0,reserved:0,receivable:0,payable:0,net_worth:0};
 const buttons=`<button type="button" class="btn export-btn export-excel" data-action="annual-excel">Xuất Excel .XLSX</button><button type="button" class="btn export-btn export-pdf" data-action="annual-pdf">Xuất PDF .PDF</button>`;
 const r=(label,value)=>`<div class="report-card"><span>${esc(label)}</span><strong>${fmoney(value)}</strong></div>`;
 const rows=d.monthly.map(x=>`<tr><td>${esc(x.month)}</td><td class="amount income">${fmoney(x.income)}</td><td class="amount expense">${fmoney(x.expense)}</td><td>${signedMoney(x.net_cash)}</td><td>${fmoney(x.available)}</td><td>${fmoney(x.reserved)}</td><td><b>${fmoney(x.net_worth)}</b></td></tr>`).join('');
 const opts=Array.from({length:Math.min(12,new Date().getFullYear()-1999)},(_,i)=>new Date().getFullYear()-i).map(y=>`<option value="${y}" ${y===state.annualYear?'selected':''}>${y}</option>`).join('');
 $('#page-content').innerHTML=heading(`Thống kê tài chính năm ${d.year}`,`Báo cáo đến ${d.as_of}; lịch sử tài sản là ước tính từ sổ hiện có.`,buttons)+
 `<div class="report-controls"><label>Chọn năm <select id="annual-year" class="select">${opts}</select></label><button class="btn btn-soft" data-page="reports">Báo cáo theo tháng</button></div>`+
 `<div class="report-kpis">${r('Tổng thu nhập',t.income)}${r('Tổng chi tiêu',t.expense)}${r('Trả nợ',t.debt_paid)}${r('Thu hồi nợ',t.debt_collected)}${r('Dòng tiền thuần',t.net_cash)}</div>`+
 `<section class="panel"><div class="panel-head"><div><h2>So s\u00e1nh v\u1edbi n\u0103m ${d.previous_year}</h2><p class="panel-sub">\u0110\u1ed1i chi\u1ebfu ti\u1ec1n thu/chi gi\u1eefa hai n\u0103m.</p></div></div><div class="report-comparison"><div><span>Thu nh\u1eadp</span><b>${fmoney(t.income)}</b>${reportDifference(d.comparison.income)}</div><div><span>Chi ti\u00eau</span><b>${fmoney(t.expense)}</b>${reportDifference(d.comparison.expense)}</div></div></section>`+`<section class="panel"><div class="panel-head"><div><h2>Lịch sử tài sản ròng</h2><p class="panel-sub">Số liệu cuối tháng ước tính từ giao dịch, nợ và quỹ.</p></div></div>${annualLinePlot(d.monthly)}</section>`+
 `<div class="report-kpis">${r('Tiền khả dụng',close.available)}${r('Tiền dành riêng',close.reserved)}${r('Nợ phải thu',close.receivable)}${r('Nợ phải trả',close.payable)}${r('Tài sản ròng ước tính',close.net_worth)}</div>`+
 `<section class="panel report-ledger"><div class="panel-head"><div><h2>Bảng thống kê 12 tháng</h2><p class="panel-sub">Tiền chuyển giữa ví không tính vào dòng tiền.</p></div></div><div class="table-wrap"><table class="data-table"><thead><tr><th>THÁNG</th><th>THU</th><th>CHI</th><th>TIỀN THUẦN</th><th>KHẢ DỤNG*</th><th>DÀNH RIÊNG*</th><th>TÀI SẢN RÒNG*</th></tr></thead><tbody>${rows}</tbody></table></div></section>`+
 `<p class="annual-disclaimer">* ${esc(d.disclaimer)}</p>`;
}
async function downloadAnnual(ext){
 const r=await fetch(`/api/reports/annual.${ext}?year=${state.annualYear}`,{credentials:'same-origin'});
 if(!r.ok){let detail='Không thể xuất tệp năm.';try{detail=(await r.json()).detail||detail}catch{}throw Error(detail)}
 const blob=await r.blob(), bytes=new Uint8Array(await blob.slice(0,4).arrayBuffer());
 const isPdf=ext==='pdf';
 if(isPdf?!(bytes[0]===37&&bytes[1]===80&&bytes[2]===68&&bytes[3]===70):!(bytes[0]===80&&bytes[1]===75))throw Error('Tệp báo cáo không hợp lệ.');
 const url=URL.createObjectURL(blob),a=document.createElement('a');
 a.href=url;a.download=`moneyflow-annual-${state.annualYear}.${ext}`;document.body.append(a);a.click();a.remove();
 setTimeout(()=>URL.revokeObjectURL(url),1000);toast('Xuất báo cáo năm thành công.');
}

async function renderReports(){
 const q=`end=${encodeURIComponent(state.month)}&months=${state.reportMonths}`;
 const d=await api(`reports?${q}`);state.reportData=d;
 const t=d.totals,s=d.snapshot,sel=d.selected_month;
 const card=(label,value,note='')=>`<div class="report-card"><span>${esc(label)}</span><strong>${fmoney(value)}</strong>${note?`<small>${note}</small>`:''}</div>`;
 const options=[3,6,12,24].map(n=>`<option value="${n}" ${n===state.reportMonths?'selected':''}>${n} tháng</option>`).join('');
 const cats=d.categories.map(c=>`<div class="report-category-item"><span class="legend-dot" style="background:${/^#[0-9a-fA-F]{6}$/.test(c.color)?c.color:'#7769ee'}"></span><b>${esc(c.name)}</b><strong>${fmoney(c.amount)}</strong></div>`).join('');
 const table=d.monthly.map(r=>`<tr><td>${esc(monthText(r.month))}</td><td class="amount income">${fmoney(r.income)}</td><td class="amount expense">${fmoney(r.expense)}</td><td>${fmoney(r.debt_paid)}</td><td>${fmoney(r.debt_collected)}</td><td class="amount">${signedMoney(r.net_cash)}</td></tr>`).join('');
 $('#page-content').innerHTML=heading('Báo cáo & phân tích tài chính',`Thống kê từ ${d.from_month} đến ${d.to_month}. Số dư và tài sản ròng là số liệu hiện tại.`,
 `<button type="button" class="btn export-btn export-excel" data-action="report-excel" title="Tải báo cáo Excel" aria-label="Tải báo cáo Excel định dạng XLSX"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M8 3h8l5 5v13H8z"/><path d="M16 3v5h5"/><path d="m2 10 6 8m0-8-6 8"/></svg>Xuất Excel <small>.XLSX</small></button><button type="button" class="btn export-btn export-pdf" data-action="report-pdf" title="Tải báo cáo PDF" aria-label="Tải báo cáo PDF định dạng PDF"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M5 3h10l4 4v14H5z"/><path d="M15 3v5h4"/><path d="M8 17h8M8 13h5"/></svg>Xuất PDF <small>.PDF</small></button>`)+
 `<div class="report-controls"><label>Khoảng xem <select id="report-months" class="select" aria-label="Chọn số tháng">${options}</select></label><div class="report-help">Chọn tháng kết thúc ở góc phải trên. Chuyển tiền giữa ví không tính là thu/chi.</div></div>`+
 `<div class="report-kpis">${card('Tổng thu nhập',t.income)}${card('Tổng chi tiêu',t.expense)}${card('Đã trả nợ (gốc + lãi)',t.debt_paid)}${card('Đã thu hồi nợ',t.debt_collected)}${card('Dòng tiền thuần',t.net_cash,'Đã tính các khoản trả/thu hồi nợ')}</div>`+
 `<section class="panel report-snapshot"><div class="panel-head"><div><h2>Tình hình tài chính hiện tại</h2><p class="panel-sub">Tổng hợp số dư ví và nợ, không phải số dư lịch sử cuối tháng.</p></div></div><div class="report-kpis report-kpis-five">${card('Số dư khả dụng',s.cash_balance)}${card('Tổng tiền dành riêng',s.savings_balance||0)}${card('Trong đó: tích để dành',s.stash_balance||0)}${card('Nợ phải thu',s.receivable)}${card('Nợ phải trả',s.payable)}${card('Tài sản ròng',s.net_worth)}</div></section>`+
 `<div class="report-dual"><section class="panel"><div class="panel-head"><div><h2>Thu và chi theo thời gian</h2><p class="panel-sub">Tiền trả nợ nằm trong chỉ tiêu riêng.</p></div><div class="chart-legend"><span><i class="legend-dot" style="background:#7569f5"></i>Thu</span><span><i class="legend-dot" style="background:#45d9b7"></i>Chi</span></div></div>${reportChart(d.monthly)}</section>`+
 `<section class="panel"><div class="panel-head"><div><h2>So sánh ${esc(monthText(d.end_month))}</h2><p class="panel-sub">Với tháng ngay trước đó</p></div></div><div class="report-comparison"><div><span>Thu nhập</span><b>${fmoney(sel.income)}</b>${reportDifference(d.comparison.income)}</div><div><span>Chi tiêu</span><b>${fmoney(sel.expense)}</b>${reportDifference(d.comparison.expense)}</div><div><span>Dòng tiền thuần</span><b>${signedMoney(sel.net_cash)}</b>${reportDifference(d.comparison.net_cash)}</div></div></section></div>`+
 `<div class="report-dual"><section class="panel"><div class="panel-head"><div><h2>Chi tiêu theo danh mục</h2><p class="panel-sub">${esc(monthText(d.end_month))}</p></div></div>${d.categories.length?`<div class="report-categories">${cats}</div>`:empty('Chưa có khoản chi trong tháng','Khi có giao dịch, tỷ trọng theo danh mục sẽ hiển thị tại đây.')}</section>`+
 `<section class="panel"><div class="panel-head"><div><h2>Chi tiết biến động tiền</h2><p class="panel-sub">Tiền thuần = thu − chi − trả nợ + thu hồi nợ.</p></div></div><div class="report-mini-grid"><div><small>Thu nhập tháng chọn</small><b>${fmoney(sel.income)}</b></div><div><small>Chi tiêu tháng chọn</small><b>${fmoney(sel.expense)}</b></div><div><small>Trả nợ tháng chọn</small><b>${fmoney(sel.debt_paid)}</b></div><div><small>Thu hồi tháng chọn</small><b>${fmoney(sel.debt_collected)}</b></div></div></section></div>`+
 `<section class="panel report-ledger"><div class="panel-head"><div><h2>Bảng dòng tiền theo tháng</h2><p class="panel-sub">Khoản trả nợ tự động đã được khấu trừ khi tính tiền thuần; không đếm trùng vào chi tiêu.</p></div></div><div class="table-wrap"><table class="data-table"><thead><tr><th>THÁNG</th><th>THU NHẬP</th><th>CHI TIÊU</th><th>TRẢ NỢ</th><th>THU HỒI NỢ</th><th>TIỀN THUẦN</th></tr></thead><tbody>${table}</tbody></table></div></section>`;
}
// v1.0.18 – Forward-looking, read-only forecasts from scheduled internal records.
function forecastPlot(points){
 if(!points.length)return empty('Chưa có dự báo','Hãy tạo lịch định kỳ để xem diễn biến số dư.');
 const w=900,h=270,pad=28;
 const values=points.map(x=>Number(x.balance));
 let min=Math.min(0,...values),max=Math.max(0,...values);
 if(max===min)max=min+1;
 const yy=v=>pad+(max-v)*(h-2*pad)/(max-min);
 const xx=i=>pad+i*(w-2*pad)/Math.max(1,points.length-1);
 const path=points.map((p,i)=>(i?'L':'M')+xx(i).toFixed(2)+' '+yy(Number(p.balance)).toFixed(2)).join(' ');
 const zero=yy(0).toFixed(2);
 const riskDots=points.map((p,i)=>p.shortfall?`<circle cx="${xx(i).toFixed(2)}" cy="${yy(p.balance).toFixed(2)}" r="3" fill="#ff7d96"/>`:'').join('');
 return `<div class="forecast-chart"><svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Số dư tổng dự kiến từng ngày" preserveAspectRatio="none"><defs><linearGradient id="forecast-fill" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#8174ff" stop-opacity=".29"/><stop offset="1" stop-color="#8174ff" stop-opacity="0"/></linearGradient></defs><line x1="${pad}" x2="${w-pad}" y1="${zero}" y2="${zero}" stroke="#65728f" stroke-dasharray="6 5" opacity=".5"/><path d="${path} L${xx(points.length-1).toFixed(2)} ${h-pad} L${pad} ${h-pad} Z" fill="url(#forecast-fill)"/><path d="${path}" fill="none" stroke="#8b7dff" stroke-width="3.5" stroke-linejoin="round" stroke-linecap="round"/>${riskDots}</svg><div class="forecast-axis"><span>${esc(points[0].date)}</span><span>${esc(points[points.length-1].date)}</span></div></div>`;
}
async function renderForecast(){
 const d=await api(`forecast?days=${state.forecastDays}`);state.forecastData=d;
 const summary=(label,val,note='',cls='')=>`<div class="forecast-kpi ${cls}"><span>${esc(label)}</span><strong>${fmoney(val)}</strong><small>${esc(note)}</small></div>`;
 const cards=d.wallets.map(w=>`<article class="forecast-wallet"><div><strong>${esc(w.name)}</strong><small>${w.active?'Đang sử dụng':'Ví đã khóa'}</small></div><div class="forecast-wallet-numbers"><span>${fmoney(w.start_balance)} → <b>${fmoney(w.projected_balance)}</b></span>${w.first_shortfall_on?`<em>⚠ Nguy cơ thiếu tiền: ${esc(w.first_shortfall_on)}</em>`:'<small>Không dự báo âm ví</small>'}</div></article>`).join('');
 const events=d.events.map(e=>`<tr><td>${esc(e.due_on)}</td><td><strong>${esc(e.title)}</strong><small class="forecast-table-note">${e.mode==='auto'?'Tự ghi':'Chờ xác nhận'}</small></td><td>${esc(e.wallet_name)}</td><td><span class="tag ${e.kind==='income'?'tag-active':'tag-disabled'}">${e.kind==='income'?'Thu':'Chi'}</span></td><td class="amount">${fmoney(e.amount)}</td><td class="amount">${e.allocated_to_debt?fmoney(e.allocated_to_debt):'—'}</td><td class="amount">${e.allocated_to_stash?fmoney(e.allocated_to_stash):'—'}</td><td class="amount ${e.net_wallet_delta<0?'expense':'income'}">${e.net_wallet_delta<0?'−':'+'}${fmoney(Math.abs(e.net_wallet_delta))}</td></tr>`).join('');
 const notice=(d.overdue_rules.length?`<p class="forecast-notice">⚠ Có ${d.overdue_rules.length} lịch còn kỳ quá hạn chưa xử lý. Các kỳ quá hạn không được giả định đã thanh toán trong dự báo. <button type="button" data-page="recurring">Xem lịch</button></p>`:'')+
 (d.inactive_wallet_rules.length?`<p class="forecast-notice">⚠ ${d.inactive_wallet_rules.length} lịch gắn với ví đã khóa/không tồn tại, không được tính vào dự báo.</p>`:'');
 const options=[30,60,90].map(n=>`<option value="${n}" ${n===state.forecastDays?'selected':''}>${n} ngày</option>`).join('');
 $('#page-content').innerHTML=heading('Dự báo dòng tiền','Ước tính số dư tương lai từ lịch thu/chi đã thiết lập. Không thay đổi tiền thực tế.',`<button class="btn btn-secondary" type="button" data-page="recurring">◷ Quản lý lịch định kỳ</button>`)+
 `<div class="forecast-controls"><label>Khoảng dự báo <select id="forecast-days" class="select" aria-label="Chọn khoảng dự báo">${options}</select></label><p>Dữ liệu hiện tại: ${esc(d.as_of)} · Kết thúc dự kiến: ${esc(d.through)}. Tất cả là số liệu giả định.</p></div>`+
 `<div class="forecast-kpis">${summary('Số dư khả dụng hiện tại',d.start_balance,'Tổng các ví')}${summary('Số dư dự kiến cuối kỳ',d.end_balance,'Không bao gồm tiền quỹ tiết kiệm',d.end_balance<0?'danger':'')}${summary('Thu nhập dự kiến',d.income_gross,'Trước khấu trừ nợ')}${summary('Chi định kỳ dự kiến',d.expense,'Không tính chuyển ví')}${summary('Dự kiến trả nợ gốc',d.debt_allocated,'Khấu trừ từ nguồn thu')}${summary('Dự kiến để dành',d.stash_allocated||0,'Đã trừ khỏi số dư khả dụng')}</div>`+
 (d.first_shortfall_on?`<div class="forecast-alert" role="alert">⚠ <strong>Có nguy cơ thiếu tiền từ ${esc(d.first_shortfall_on)}</strong> · ${d.risk_wallet_count} ví dự kiến âm tại ít nhất một thời điểm. Giao dịch chi thực tế vẫn bị chặn nếu không đủ tiền.</div>`:`<div class="forecast-ok">✓ Theo các lịch hiện có, chưa dự kiến số dư âm cho từng ví trong ${d.horizon_days} ngày.</div>`)+notice+
 `<section class="panel forecast-panel"><div class="panel-head"><div><h2>Xu hướng số dư dự kiến</h2><p class="panel-sub">Đường biểu diễn tổng số dư khả dụng theo ngày, không bao gồm tiền tiết kiệm dành riêng.</p></div><span class="mini-stat">${d.total_events} kỳ dự kiến</span></div>${forecastPlot(d.timeline)}</section>`+
 `<div class="forecast-columns"><section class="panel"><div class="panel-head"><div><h2>Số dư theo từng ví</h2><p class="panel-sub">Cảnh báo được tính ở từng ví, không bù trừ âm/dương giữa các ví.</p></div></div><div class="forecast-wallets">${cards||empty('Chưa có ví','Hãy tạo một ví đầu tiên.')}</div></section><section class="panel"><div class="panel-head"><div><h2>Cách tính và giới hạn</h2><p class="panel-sub">Dự báo để lập kế hoạch; không phải cam kết giao dịch.</p></div></div><ul class="forecast-assumptions">${d.assumptions.map(a=>`<li>${esc(a)}</li>`).join('')}</ul></section></div>`+
 `<section class="panel forecast-panel"><div class="panel-head"><div><h2>Lịch thu/chi sẽ phát sinh</h2><p class="panel-sub">Các khoản thu được giả định ưu tiên trả nợ gốc trước, khoản dư mới vào ví.</p></div></div><div class="table-wrap"><table class="data-table"><thead><tr><th>NGÀY</th><th>NỘI DUNG</th><th>VÍ</th><th>LOẠI</th><th>SỐ TIỀN</th><th>TRỪ NỢ</th><th>ĐỂ DÀNH</th><th>VÀO / RA VÍ</th></tr></thead><tbody>${events||'<tr><td colspan="8" class="table-row-empty">Chưa có lịch thu/chi trong giai đoạn này.</td></tr>'}</tbody></table></div>${d.truncated_events?'<p class="forecast-truncated">Chỉ hiển thị 160 kỳ đầu tiên; tổng kết và biểu đồ vẫn tính tất cả kỳ trong khoảng.</p>':''}</section>`;
}
async function downloadReport(ext){
 const q=`end=${encodeURIComponent(state.month)}&months=${state.reportMonths}`;
 const r=await fetch(`/api/reports.${ext}?${q}`,{credentials:'same-origin'});
 if(!r.ok){let message='Không thể xuất báo cáo.';try{const error=await r.json();if(typeof error.detail==='string')message=error.detail}catch{}throw Error(message)}
 const blob=await r.blob();
 const mime=r.headers.get('content-type')||'';
 const header=new Uint8Array(await blob.slice(0,4).arrayBuffer());
 const pdf=ext==='pdf',magicOk=pdf?(header[0]===37&&header[1]===80&&header[2]===68&&header[3]===70):(header[0]===80&&header[1]===75);
 if(!magicOk || !mime.includes(pdf?'application/pdf':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'))
   throw Error('Máy chủ trả về sai định dạng. Chưa lưu file báo cáo.');
 const url=URL.createObjectURL(blob),a=document.createElement('a');
 a.href=url;a.download=`moneyflow-report-${state.month}.${ext}`;document.body.append(a);a.click();a.remove();
 setTimeout(()=>URL.revokeObjectURL(url),1000);toast(`Đã xuất báo cáo ${ext.toUpperCase()}.`);
}
async function renderDashboard(){const d=await api(`dashboard?month=${state.month}`);state.data=d;const growth=d.balance<0?'danger-text':'';const button=`${d.opening_balance===0 && d.total_income===0 && d.total_expense===0?'<button class="btn btn-soft" data-action="opening-modal">◈ Nhập tiền ban đầu</button>':''}<button class="btn btn-secondary" data-action="add-income">↗ Thêm thu nhập</button>${addButton('Ghi khoản chi')}<button class="btn btn-soft" data-page="debts">◈ Quản lý nợ</button><button class="btn btn-soft" data-page="wallets">▣ Các ví</button><button class="btn btn-soft" data-page="savings">✦ Tiết kiệm</button><button class="btn btn-soft" data-page="stashes">◉ Tiền để dành</button>`;
 $('#page-content').innerHTML=heading(`Xin chào, ${state.user.username}! 👋`,'Đây là bức tranh tài chính của bạn trong '+monthText(state.month)+'.',button)+`<div class="summary-grid"><div class="balance-card"><div class="balance-top"><span>◈ Số dư khả dụng</span><span class="balance-icon">▧</span></div><div class="balance-number ${growth}">${fmoney(d.balance)}</div><div class="balance-foot"><span>Tiết kiệm mục tiêu: ${fmoney(d.savings_reserved||0)} · Tích để dành: ${fmoney(d.stash_reserved||0)} · Tổng tài sản tiền: ${fmoney(d.total_assets??d.balance)}</span><strong>● Đã đồng bộ</strong></div></div><div class="stat-card"><div class="stat-top"><span>Thu nhập trong tháng</span><div class="stat-icon green">↗</div></div><div class="stat-number">${fmoney(d.month_income)}</div><div class="stat-bottom"><span class="growth green">↗ THU NHẬP</span> Tổng thu ${fcompact(d.total_income)}</div></div><div class="stat-card"><div class="stat-top"><span>Chi tiêu trong tháng</span><div class="stat-icon pink">↘</div></div><div class="stat-number">${fmoney(d.month_expense)}</div><div class="stat-bottom"><span class="growth pink">↘ CHI TIÊU</span> ${d.month_count} giao dịch tháng này</div></div></div>
 <section class="panel reminder-dashboard"><div class="panel-head"><div><h2>🔔 Nhắc việc sắp tới</h2><p class="panel-sub">Lịch thu/chi và các khoản nợ đến hạn</p></div><button class="panel-link" data-page="recurring">Xem tất cả →</button></div>${state.reminders.length?`<div class="reminder-stack">${state.reminders.slice(0,5).map(remindItem).join('')}</div>`:empty('Chưa có khoản đến hạn','Tạo lịch thu/chi định kỳ hoặc đặt ngày thanh toán nợ.')}</section>
 <section class="panel wallet-dashboard-mini"><div class="panel-head"><div><h2>Ví & tài khoản</h2><p class="panel-sub">Tổng số dư được phân bổ theo từng ví, không tính trùng chuyển khoản.</p></div><button class="panel-link" data-page="wallets">Quản lý ví →</button></div><div class="wallet-mini-list">${(d.wallets||[]).map(w=>`<div class="wallet-mini"><span>${w.kind==='bank'?'▤':w.kind==='ewallet'?'◈':'◉'} ${esc(w.name)}</span><strong>${fmoney(w.balance)}</strong></div>`).join('')}</div></section>
 <section class="debt-overview-panel panel"><div class="debt-overview-copy"><span class="debt-overline">◈ THEO DÕI NỢ GỐC</span><h2>${fmoney(d.debt_remaining)}</h2><p>Nợ phải trả · Nợ phải thu: ${fmoney(d.receivable_remaining||0)} · Đã trả gốc: ${fmoney(d.debt_paid)}.</p><span class="debt-note">Thu nhập mới ưu tiên trả nợ phải trả; nợ phải thu chỉ giảm khi ghi nhận thu hồi. Tài sản ròng: ${fmoney(d.net_worth)}.</span></div><button class="btn btn-secondary" data-page="debts">Xem các khoản nợ →</button></section>
 <div class="dashboard-grid"><section class="panel"><div class="panel-head"><div><h2>Biến động thu & chi</h2><p class="panel-sub">Tổng quan dòng tiền trong 6 tháng gần nhất</p></div><div class="chart-legend"><span><i class="legend-dot" style="background:#7569f5"></i>Thu nhập</span><span><i class="legend-dot" style="background:#a3eee0"></i>Chi tiêu</span></div></div>${trendChart(d.trend)}</section><section class="panel category-panel"><div class="panel-head"><div><h2>Chi tiêu theo danh mục</h2><p class="panel-sub">Tỷ trọng chi tiêu ${esc(monthText(state.month))}</p></div></div>${donutChart(d.categories)}</section></div>
 <div class="bottom-grid"><section class="panel"><div class="panel-head"><div><h2>Giao dịch gần đây</h2><p class="panel-sub">Các khoản thu chi mới nhất</p></div><button class="panel-link" data-page="transactions">Xem tất cả →</button></div>${tableHtml(d.recent)}</section><section class="panel"><div class="panel-head"><div><h2>Ngân sách tháng này</h2><p class="panel-sub">Theo dõi các hạn mức đã đặt</p></div><button class="panel-link" data-page="budgets">Quản lý →</button></div>${budgetBars(d.budgets)}</section></div>${budgetAlertMarkup(d.budget_alerts)}`;}
async function openReceiptsModal(entryId){
 if(currentReceiptPreview){URL.revokeObjectURL(currentReceiptPreview);currentReceiptPreview=null;}
 const data=await api(`transactions/${entryId}/receipts`);
 const entry=state.transData?.items?.find(e=>e.id===entryId);
 const used=data.items.length;
 const cards=data.items.map(r=>`<div class="receipt-line"><div class="receipt-icon">${r.mime_type==='application/pdf'?'PDF':'ẢNH'}</div><div class="receipt-info"><strong>${esc(r.name)}</strong><small>${(r.size_bytes/1024).toLocaleString('vi-VN',{maximumFractionDigits:0})} KB · ${esc(new Date(r.created_at).toLocaleString('vi-VN'))}</small></div><div class="receipt-buttons">${r.mime_type.startsWith('image/')?`<button type="button" class="table-action" data-action="receipt-preview" data-id="${r.id}">Xem</button>`:''}<button type="button" class="table-action" data-action="receipt-download" data-id="${r.id}" data-name="${esc(r.name)}">Tải</button><button type="button" class="table-action delete" data-action="receipt-delete" data-id="${r.id}" data-entry="${entryId}">Xóa</button></div></div>`).join('');
 openModal('Hóa đơn & chứng từ',`Giao dịch: ${entry?.title||'#'+entryId} · ${used}/${data.max_files} tệp`,
 `<input type="hidden" name="entry_id" value="${entryId}"/><div class="receipt-list">${cards||'<div class="simple-info">Giao dịch chưa có hóa đơn hoặc chứng từ đính kèm.</div>'}</div><div class="receipt-preview" id="receipt-preview" hidden></div><label>Chọn ảnh hóa đơn hoặc PDF<input class="input receipt-input" name="receipt_file" type="file" accept=".jpg,.jpeg,.png,.webp,.pdf,image/jpeg,image/png,image/webp,application/pdf" ${used>=data.max_files?'disabled':'required'}/></label><p class="form-help">Hỗ trợ JPG, PNG, WEBP, PDF · Tối đa 8 MB/tệp, 8 tệp/giao dịch. Chứng từ chỉ lưu trên máy của bạn và chỉ tài khoản sở hữu xem được.</p>`,
 'receipt-upload',used>=data.max_files?'Đã đủ 8 chứng từ':'Đính kèm chứng từ');
 const submit=$('#modal-form button[type="submit"]');if(submit&&used>=data.max_files)submit.disabled=true;
}
async function receiptToBase64(file){
 const bytes=new Uint8Array(await file.arrayBuffer());let binary='';
 for(let offset=0;offset<bytes.length;offset+=0x8000){binary+=String.fromCharCode(...bytes.subarray(offset,offset+0x8000));}
 return btoa(binary);
}
async function receiptDownload(id,name){
 const r=await api(`receipts/${id}/file`);
 const blob=await r.blob(),url=URL.createObjectURL(blob),link=document.createElement('a');
 link.href=url;link.download=name||`chung-tu-${id}`;document.body.append(link);link.click();link.remove();
 setTimeout(()=>URL.revokeObjectURL(url),1000);
}
let currentReceiptPreview=null;
async function receiptPreview(id){
 const r=await api(`receipts/${id}/file`);const blob=await r.blob();
 if(!blob.type.startsWith('image/'))throw Error('Chỉ xem trước ảnh. Tệp PDF dùng nút Tải.');
 if(currentReceiptPreview)URL.revokeObjectURL(currentReceiptPreview);
 currentReceiptPreview=URL.createObjectURL(blob);
 const container=$('#receipt-preview');if(container){container.hidden=false;container.innerHTML=`<img src="${currentReceiptPreview}" alt="Xem trước hóa đơn"/>`;}
}
async function renderReceipts(){
 const query=new URLSearchParams({page:String(state.receiptPage),size:'30'});
 if(state.receiptSearch)query.set('q',state.receiptSearch);
 if(state.receiptKind)query.set('kind',state.receiptKind);
 if(state.receiptMonth==='selected')query.set('month',state.month);
 const data=await api('receipts?'+query);
 state.receiptData=data;
 const rows=data.items.map(r=>`<div class="receipt-line receipt-overview-row"><div class="receipt-icon">${r.mime_type==='application/pdf'?'PDF':'ẢNH'}</div><div class="receipt-info"><strong>${esc(r.name)}</strong><small>${esc(r.entry_title)} · ${esc(r.occurred_on)} · ${r.entry_kind==='income'?'Thu':'Chi'} ${fmoney(r.entry_amount)}</small><small>${(r.size_bytes/1024).toLocaleString('vi-VN',{maximumFractionDigits:0})} KB</small></div><div class="receipt-buttons">${r.mime_type.startsWith('image/')?`<button class="table-action" data-action="receipt-preview-full" data-id="${r.id}">Xem ảnh</button>`:''}<button class="table-action" data-action="receipt-download" data-id="${r.id}" data-name="${esc(r.name)}">Tải xuống</button><button class="table-action" data-action="receipt-open-entry" data-entry="${r.entry_id}">Giao dịch</button><button class="table-action delete" data-action="receipt-delete" data-id="${r.id}" data-entry="${r.entry_id}">Xóa</button></div></div>`).join('');
 $('#page-content').innerHTML=heading('Hóa đơn & chứng từ','Lưu ảnh hóa đơn, biên lai và chứng từ PDF gắn với từng giao dịch. Dữ liệu chỉ có trên máy bạn.',`<button class="btn btn-primary" data-page="transactions">+ Đính kèm từ giao dịch</button>`)+
 `<section class="panel"><div class="panel-head"><h2>Kho chứng từ</h2><span class="mini-stat">${data.total} tệp</span></div><div class="toolbar receipt-toolbar"><input class="input search-input" id="receipt-search" placeholder="Tìm tên tệp hoặc giao dịch" value="${esc(state.receiptSearch)}"/><select class="select" id="receipt-kind"><option value="">Tất cả định dạng</option><option value="image" ${state.receiptKind==='image'?'selected':''}>Hình ảnh</option><option value="pdf" ${state.receiptKind==='pdf'?'selected':''}>PDF</option></select><select class="select" id="receipt-month"><option value="" ${state.receiptMonth===''?'selected':''}>Tất cả thời gian</option><option value="selected" ${state.receiptMonth==='selected'?'selected':''}>${esc(monthText(state.month))}</option></select><button class="btn btn-secondary" data-action="receipt-search">Lọc</button></div><div class="receipt-list">${rows||'<div class="simple-info">Không tìm thấy chứng từ phù hợp. Mở một giao dịch để đính kèm ảnh hóa đơn hoặc PDF.</div>'}</div><div class="pagination"><span>Trang ${data.page}/${data.pages} · ${data.total} chứng từ</span><div class="pagination-actions"><button data-action="receipt-prev" ${data.page<=1?'disabled':''}>← Trước</button><button data-action="receipt-next" ${data.page>=data.pages?'disabled':''}>Sau →</button></div></div></section>`;
}
async function renderTransactions(){let query=new URLSearchParams({page:String(state.transPage),size:'15'});if(state.month)query.set('month',state.month);if(state.transKind)query.set('kind',state.transKind);if(state.transCategory)query.set('category_id',state.transCategory);if(state.transWallet)query.set('wallet_id',state.transWallet);if(state.transSearch)query.set('q',state.transSearch);const d=await api('transactions?'+query);state.transData=d;
 $('#page-content').innerHTML=heading('Quản lý giao dịch','Theo dõi, tìm kiếm và chỉnh sửa mọi khoản thu chi.',`<button class="btn btn-secondary" data-action="export">↓ Xuất Excel / CSV</button>${addButton()}`)+`<section class="panel full-panel"><div class="toolbar"><input id="search-trans" class="input search-input" placeholder="⌕ Tìm theo nội dung..." value="${esc(state.transSearch)}"/><select id="filter-type" class="select"><option value="">Tất cả loại</option><option value="income" ${state.transKind==='income'?'selected':''}>Khoản thu</option><option value="expense" ${state.transKind==='expense'?'selected':''}>Khoản chi</option></select><select id="filter-category" class="select"><option value="">Tất cả danh mục</option>${state.categories.filter(c=>c.active).map(c=>`<option value="${c.id}" ${String(c.id)===state.transCategory?'selected':''}>${esc(c.name)} (${c.kind==='income'?'Thu':'Chi'})</option>`).join('')}</select><select id="filter-wallet" class="select"><option value="">Tất cả ví</option>${state.wallets.map(w=>`<option value="${w.id}" ${String(w.id)===state.transWallet?'selected':''}>${esc(w.name)}</option>`).join('')}</select><button class="btn btn-secondary" data-action="search-trans">Tìm kiếm</button></div><div class="stats-line"><span>Tổng số giao dịch: <b>${d.total}</b></span><span>Tháng: <b>${monthText(state.month)}</b></span></div>${tableHtml(d.items,true)}<div class="pagination"><span>Trang ${d.page}/${d.pages} · ${d.total} giao dịch</span><div class="pagination-actions"><button data-action="page-prev" ${d.page<=1?'disabled':''}>← Trước</button><button data-action="page-next" ${d.page>=d.pages?'disabled':''}>Sau →</button></div></div></section>`;}
async function renderBudgets(){
 const d=await api(`budgets/insights?month=${encodeURIComponent(state.month)}`);
 state.budgetData=d.items;
 const all=d.items, total=d.summary.budget_total, spent=d.summary.spent_total;
 const expenses=state.categories.filter(c=>c.kind==='expense'&&c.active);
 const activeStatus=r=>`<span class="smart-status smart-${esc(r.status)}">${esc(budgetStatusLabel(r))}</span>`;
 const tiles=all.map(b=>`<article class="budget-tile smart-budget-tile">
  <button class="table-action edit" data-action="edit-budget" data-id="${b.category_id}">Chỉnh sửa</button>
  <h3>${iconCat(b)}${esc(b.category)}</h3>
  <div class="budget-amount">${fmoney(b.amount)}</div>
  <p class="meta">Đã chi: <strong>${fmoney(b.spent)}</strong> · Còn: ${fmoney(b.remaining)}</p>
  <div class="progress-track" role="progressbar" aria-label="Đã sử dụng ngân sách ${esc(b.category)}" aria-valuenow="${Math.min(100,Math.round(b.spent_percent||0))}" aria-valuemin="0" aria-valuemax="100"><div class="progress-fill" style="width:${Math.min(100,b.spent_percent??(b.spent>0?100:0))}%;background:${b.status==='exceeded'||b.status==='limit'?'#fb7185':b.status==='critical'?'#f0ab65':b.status==='warning'?'#f4cb68':esc(b.color)}"></div></div>
  <div class="smart-budget-meta">${activeStatus(b)}<span>${b.spent_percent===null?'Hạn mức bằng 0':'Đã dùng '+b.spent_percent.toLocaleString('vi-VN')+'%'}</span></div>
  ${d.is_current_month?`<div class="smart-budget-prediction"><div><span>Cuối tháng dự kiến</span><strong class="${b.at_risk?'smart-over':''}">${fmoney(b.projected_spent)}</strong></div><div><span>Chi định kỳ còn lại</span><strong>${fmoney(b.scheduled_remaining)}</strong></div><div><span>Có thể chi/ngày còn lại</span><strong>${fmoney(b.safe_daily)}</strong></div></div>${b.at_risk?`<p class="smart-warning">⚠ Có nguy cơ vượt ${fmoney(b.projected_over)} cuối tháng (ước tính, không phải khoản chi thực tế).</p>`:''}`:'<p class="smart-historical">Tháng đã chọn không phải tháng hiện tại: chỉ hiển thị số liệu đã ghi, không dự báo.</p>'}
 </article>`).join('');
 $('#page-content').innerHTML=heading('Ngân sách thông minh',`Cảnh báo 70% / 90% / 100%, ước tính chi tiêu cuối tháng và phân bổ an toàn mỗi ngày cho ${monthText(state.month)}.`,`<button class="btn btn-primary" data-action="add-budget">+ Thiết lập ngân sách</button>`)+
 `<div class="smart-budget-overview"><div class="smart-kpi"><span>Tổng hạn mức</span><strong>${fmoney(total)}</strong><small>${all.length} danh mục</small></div><div class="smart-kpi"><span>Đã chi</span><strong>${fmoney(spent)}</strong><small>Chỉ các danh mục có ngân sách</small></div><div class="smart-kpi"><span>Cần chú ý</span><strong>${d.summary.critical_count+d.summary.warning_count}</strong><small>Đã chạm từ 70% hạn mức</small></div><div class="smart-kpi"><span>Dự kiến vượt</span><strong>${d.is_current_month?d.summary.at_risk_count:'—'}</strong><small>${d.is_current_month?'Danh mục có nguy cơ vượt cuối tháng':'Chỉ dự báo cho tháng hiện tại'}</small></div></div>`+
 `<div class="smart-budget-note">ℹ Dự báo dùng nhịp chi tiêu đã ghi và các lịch chi định kỳ còn lại; chọn kịch bản lớn hơn để tránh đếm trùng. Không tự ghi giao dịch, không thay đổi hạn mức hay tiền trong ví.</div>`+
 `${all.length?`<div class="budget-grid smart-budget-grid">${tiles}</div>`:`<section class="panel">${empty('Chưa có ngân sách','Hãy tạo hạn mức đầu tiên để được nhắc khi đạt 70%, 90% và 100%.')}</section>`}`+
 `${expenses.length?'':'<div class="simple-info">Hãy tạo danh mục chi tiêu trước khi thiết lập ngân sách.</div>'}`;
}
async function renderCategories(){const cats=state.categories;$('#page-content').innerHTML=heading('Danh mục thu & chi','Tùy chỉnh nhóm chi tiêu và nguồn thu nhập của bạn.',`<button class="btn btn-primary" data-action="add-category">+ Thêm danh mục</button>`)+`<section class="panel"><div class="panel-head"><h2>Danh mục chi tiêu</h2><span class="mini-stat">${cats.filter(c=>c.kind==='expense').length} danh mục</span></div><div class="category-grid">${cats.filter(c=>c.kind==='expense').map(categoryTile).join('')}</div></section><section class="panel" style="margin-top:19px"><div class="panel-head"><h2>Danh mục thu nhập</h2><span class="mini-stat">${cats.filter(c=>c.kind==='income').length} danh mục</span></div><div class="category-grid">${cats.filter(c=>c.kind==='income').map(categoryTile).join('')}</div></section>`;}
function categoryTile(c){return `<div class="category-tile"><span class="category-swatch" style="background:${esc(c.color)}22;color:${esc(c.color)}">${c.kind==='expense'?'↘':'↗'}</span><span class="cat-text"><strong>${esc(c.name)}</strong><small>${c.active?'Đang sử dụng':'Đã ẩn'}</small></span><button class="table-action ${c.active?'delete':''}" title="${c.active?'Ẩn danh mục':'Kích hoạt danh mục'}" data-action="toggle-category" data-id="${c.id}">${c.active?'Ẩn':'Mở'}</button></div>`;}

// v1.0.19 - flexible reserves, without savings goals or due dates.
async function renderStashes(){
 const d=await api('stashes');state.stashData=d;
 const cards=d.items.map(f=>`<article class="saving-card"><div class="saving-card-head"><span class="saving-icon">◉</span><span class="tag tag-active">Tích lũy linh hoạt</span></div><h3>${esc(f.name)}</h3><p class="saving-desc">${esc(f.note||'Tiền để dành không đặt hạn mức')}</p><div class="stash-auto-status">${f.auto_mode==='percent'?`<span class="tag tag-active">↻ Tự góp ${f.auto_value}% thu nhập còn lại</span>`:f.auto_mode==='fixed'?`<span class="tag tag-active">↻ Tự góp ${fmoney(f.auto_value)} / lần nhận thu nhập</span>`:`<span class="tag tag-disabled">Tự góp đang tắt</span>`}${f.auto_mode!=='off'?`<small>${f.auto_wallet_id?`Chỉ ví ${esc(walletName(f.auto_wallet_id))}`:'Mọi ví nhận tiền'} · Sau khi trả nợ gốc</small>`:''}</div><div class="saving-amount">${fmoney(f.saved_amount)}</div><div class="saving-meta"><span>Không giới hạn mục tiêu</span><span>Tiền dành riêng</span></div><div class="saving-actions"><button class="btn btn-primary" data-action="stash-deposit" data-id="${f.id}">+ Để dành</button><button class="btn btn-secondary" data-action="stash-withdraw" data-id="${f.id}" ${f.saved_amount?'':'disabled'}>↩ Rút về ví</button><button class="table-action" data-action="stash-edit" data-id="${f.id}">Sửa</button>${f.saved_amount===0?`<button class="table-action delete" data-action="stash-delete" data-id="${f.id}">Xóa</button>`:''}</div></article>`).join('');
 const history=d.history.map(m=>`<tr><td>${esc(m.occurred_on)}</td><td>${esc(m.fund)}</td><td>${esc(m.wallet)}</td><td><span class="tag ${m.kind==='deposit'?'tag-active':'tag-disabled'}">${m.kind==='deposit'?(m.source==='auto'?'Tự động tích lũy':'Để dành thủ công'):'Rút về'}</span></td><td class="amount ${m.kind==='deposit'?'expense':'income'}">${m.kind==='deposit'?'−':'+'}${fmoney(m.amount)}</td><td>${esc(m.note||'—')}</td></tr>`).join('');
 $('#page-content').innerHTML=heading('Tiền tích để dành','Tạo quỹ không giới hạn số tiền, góp hoặc rút bất kỳ lúc nào. Tiền vẫn thuộc tài sản của bạn.',`<button class="btn btn-primary" data-action="stash-add">+ Tạo quỹ để dành</button>`)+
 `<section class="panel saving-overview"><div><span>TỔNG TIỀN ĐANG ĐỂ DÀNH</span><strong>${fmoney(d.total_saved)}</strong><small>${d.items.length} quỹ linh hoạt · Không tính là chi tiêu hoặc thu nhập</small></div><div class="saving-overview-mark">◉</div></section>`+
 (cards?`<div class="saving-grid">${cards}</div>`:`<section class="panel">${empty('Chưa có quỹ để dành','Tạo quỹ Tiền tích lũy, Quỹ khẩn cấp hoặc Quỹ dự phòng và dành riêng tiền từ ví.')}</section>`)+
 `<section class="panel saving-history"><div class="panel-head"><div><h2>Lịch sử tiền để dành</h2><p class="panel-sub">Mỗi lần góp/rút đều có lịch sử riêng; chỉ điều chuyển nội bộ, không ảnh hưởng thu/chi.</p></div></div><div class="table-wrap"><table class="data-table"><thead><tr><th>NGÀY</th><th>QUỸ</th><th>VÍ</th><th>LOẠI</th><th>SỐ TIỀN</th><th>GHI CHÚ</th></tr></thead><tbody>${history||'<tr><td colspan="6" class="table-row-empty">Chưa có giao dịch tích lũy.</td></tr>'}</tbody></table></div></section>`;
}
function stashModal(fund=null){
 const body=`<input type="hidden" name="id" value="${fund?.id||''}"/><label>Tên quỹ<input class="input" name="name" maxlength="120" required value="${esc(fund?.name||'')}" placeholder="Ví dụ: Tiền tích để dành"/></label><label>Ghi chú<textarea class="textarea" name="note" maxlength="300">${esc(fund?.note||'')}</textarea></label><section class="stash-rule-section"><h3>↻ Tự động tích lũy khi nhận thu nhập</h3><label>Chế độ tích lũy<select class="select" name="auto_mode" id="stash-auto-mode"><option value="off" ${!fund||fund.auto_mode==='off'?'selected':''}>Tắt (góp thủ công)</option><option value="percent" ${fund?.auto_mode==='percent'?'selected':''}>Theo % thu nhập sau trả nợ</option><option value="fixed" ${fund?.auto_mode==='fixed'?'selected':''}>Số tiền cố định mỗi lần có thu nhập</option></select></label><label>Giá trị (% hoặc VNĐ)<input class="input" name="auto_value" type="number" min="0" max="1000000000000" step="1" value="${fund?.auto_value||0}" required/></label><label>Áp dụng cho ví<select class="select" name="auto_wallet_id"><option value="">Tất cả ví nhận tiền</option>${state.wallets.filter(w=>w.active||w.id===Number(fund?.auto_wallet_id)).map(w=>`<option value="${w.id}" ${fund?.auto_wallet_id===w.id?'selected':''}>${esc(w.name)}</option>`).join('')}</select></label><div class="simple-info">Mặc định tắt. Khi có thu nhập mới, ứng dụng trả nợ gốc trước; sau đó trích tiền vào các quỹ tự động theo thứ tự tạo quỹ. Trường hợp thiếu tiền, số tiền trích sẽ được giới hạn theo khoản còn lại. Không áp dụng hồi tố cho giao dịch cũ.</div></section><div class="simple-info">Không cần hạn mức hoặc thời hạn. Tiền trong quỹ vẫn thuộc tổng tài sản, không tính vào chi tiêu.</div>`;
 openModal(fund?'Sửa quỹ tích lũy':'Tạo quỹ tích để dành','Tạo khoản dành riêng linh hoạt từ số dư ví.',body,'stash-fund',fund?'Cập nhật':'Tạo quỹ');
}
function stashMovementModal(fund,kind){
 if(!fund)return;
 const deposit=kind==='deposit';
 const body=`<input type="hidden" name="id" value="${fund.id}"/><input type="hidden" name="kind" value="${kind}"/><div class="simple-info">${deposit?'Góp thêm vào quỹ, ví giảm số dư khả dụng.':'Số tiền đang để dành: '+fmoney(fund.saved_amount)+'. Rút về ví sẽ tăng tiền khả dụng.'} Tổng tài sản không đổi.</div>${walletSelect(null,deposit?'Trích tiền từ ví':'Nhận tiền về ví')}<label>Số tiền (VNĐ)<input class="input" type="number" name="amount" step="1" min="1" max="${deposit?1000000000000:fund.saved_amount}" required/></label><label>Ngày thực hiện<input class="input" type="date" name="occurred_on" value="${today()}" required/></label><label>Ghi chú<input class="input" name="note" maxlength="300"/></label>`;
 openModal(deposit?'Góp vào tiền để dành':'Rút tiền về ví',`${fund.name} · ${deposit?'Tích lũy':'Rút khoản dành riêng'}`,body,'stash-movement',deposit?'Góp tiền':'Xác nhận rút');
}

// v1.0.17 – Savings are allocated assets, NOT an expense or income.
async function renderSavings(){
 const d=await api('savings');state.savingsData=d;
 const cards=(d.items||[]).map(g=>{
   const progress=Math.max(0,Math.min(100,Number(g.progress_pct)||0));
   const flag=g.complete?'<span class="tag tag-active">Đã đạt mục tiêu</span>':(g.due_date&&g.due_date<today()?'<span class="tag tag-disabled">Quá hạn dự kiến</span>':'<span class="tag tag-admin">Đang tiết kiệm</span>');
   return `<article class="saving-card"><div class="saving-card-head"><span class="saving-icon">✦</span>${flag}</div><h3>${esc(g.name)}</h3><p class="saving-desc">${esc(g.note||'Tích lũy cho kế hoạch của bạn')}</p><div class="saving-amount">${fmoney(g.saved_amount)}<small> / ${fmoney(g.target_amount)}</small></div><div class="saving-track" role="progressbar" aria-label="Tiến độ ${esc(g.name)}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${progress}"><span style="width:${progress}%"></span></div><div class="saving-meta"><span>Đạt ${progress.toLocaleString('vi-VN')}%</span><span>${g.due_date?'Hạn '+esc(g.due_date):'Không đặt hạn'}</span></div><div class="saving-actions"><button class="btn btn-primary" data-action="savings-deposit" data-id="${g.id}" ${g.complete?'disabled':''}>+ Góp tiền</button><button class="btn btn-secondary" data-action="savings-withdraw" data-id="${g.id}" ${g.saved_amount?'':'disabled'}>↩ Rút về ví</button><button class="table-action" data-action="savings-edit" data-id="${g.id}">Sửa</button>${g.saved_amount===0?`<button class="table-action delete" data-action="savings-delete" data-id="${g.id}">Xóa</button>`:''}</div></article>`;
 }).join('');
 const history=(d.history||[]).map(m=>`<tr><td>${esc(m.occurred_on)}</td><td>${esc(m.goal)}</td><td>${esc(m.wallet)}</td><td><span class="tag ${m.kind==='deposit'?'tag-active':'tag-disabled'}">${m.kind==='deposit'?'Góp vào':'Rút về'}</span></td><td class="amount ${m.kind==='deposit'?'expense':'income'}">${m.kind==='deposit'?'−':'+'}${fmoney(m.amount)}</td><td>${esc(m.note||'—')}</td></tr>`).join('');
 $('#page-content').innerHTML=heading('Mục tiêu tiết kiệm','Dành riêng tiền từ các ví cho kế hoạch tương lai mà không tính thành chi tiêu.',`<button class="btn btn-primary" data-action="savings-add">+ Tạo mục tiêu</button>`)+
 `<section class="panel saving-overview"><div><span>TỔNG TIỀN ĐANG DÀNH RIÊNG</span><strong>${fmoney(d.total_saved)}</strong><small>${d.items.length} mục tiêu • Tiền trong mục tiêu vẫn thuộc tài sản của bạn.</small></div><div class="saving-overview-mark">✦</div></section>`+
 (cards?`<div class="saving-grid">${cards}</div>`:`<section class="panel">${empty('Chưa có mục tiêu tiết kiệm','Tạo mục tiêu như quỹ dự phòng, du lịch, mua xe; sau đó góp tiền từ ví.')}</section>`)+
 `<section class="panel saving-history"><div class="panel-head"><div><h2>Lịch sử góp và rút tiền</h2><p class="panel-sub">Chỉ chuyển giữa số dư khả dụng và số tiền dành riêng; không phải thu nhập hay chi tiêu.</p></div></div><div class="table-wrap"><table class="data-table"><thead><tr><th>NGÀY</th><th>MỤC TIÊU</th><th>VÍ</th><th>LOẠI</th><th>SỐ TIỀN</th><th>GHI CHÚ</th></tr></thead><tbody>${history||'<tr><td colspan="6" class="table-row-empty">Chưa có lần góp hoặc rút tiền.</td></tr>'}</tbody></table></div></section>`;
}
function savingsModal(goal=null){
 const body=`<input type="hidden" name="id" value="${goal?.id||''}"/><label>Tên mục tiêu<input class="input" name="name" maxlength="120" required value="${esc(goal?.name||'')}" placeholder="Ví dụ: Quỹ dự phòng 6 tháng"/></label><label>Số tiền cần đạt (VNĐ)<input class="input" type="number" step="1" min="1" max="1000000000000" name="target_amount" value="${goal?.target_amount||''}" required/></label><label>Hạn dự kiến (không bắt buộc)<input class="input" type="date" name="due_date" value="${esc(goal?.due_date||'')}"/></label><label>Ghi chú<textarea class="textarea" name="note" maxlength="300">${esc(goal?.note||'')}</textarea></label><div class="simple-info">Tiền dành riêng vẫn được tính vào tài sản ròng; chỉ số dư có thể chi từ ví giảm xuống. Mục tiêu không tự trừ lương.</div>`;
 openModal(goal?'Sửa mục tiêu tiết kiệm':'Tạo mục tiêu tiết kiệm','Lập kế hoạch, theo dõi tiến độ và rút tiền khi cần.',body,'savings-goal',goal?'Cập nhật':'Tạo mục tiêu');
}
function savingsMoveModal(goal,kind){
 if(!goal)return;
 const deposit=kind==='deposit';
 const body=`<input type="hidden" name="id" value="${goal.id}"/><input type="hidden" name="kind" value="${kind}"/><div class="simple-info">${deposit?'Còn thiếu để đạt mục tiêu: '+fmoney(goal.remaining_amount):'Đang dành riêng: '+fmoney(goal.saved_amount)}. ${deposit?'Tiền sẽ giảm khỏi số dư khả dụng trong ví.':'Tiền sẽ trở lại ví bạn chọn.'}</div>${walletSelect(null,deposit?'Trích từ ví':'Nhận lại vào ví')}<label>Số tiền (VNĐ)<input class="input" type="number" name="amount" step="1" min="1" max="${deposit?goal.remaining_amount:goal.saved_amount}" required/></label><label>Ngày thực hiện<input class="input" type="date" name="occurred_on" value="${today()}" required/></label><label>Ghi chú<input class="input" name="note" maxlength="300" placeholder="Không bắt buộc"/></label>`;
 openModal(deposit?'Góp tiền vào mục tiêu':'Rút tiền về ví',`${goal.name} · ${deposit?'Dành riêng tiền':'Giải ngân khỏi quỹ'}`,body,'savings-movement',deposit?'Góp tiền':'Xác nhận rút');
}

// v1.0.23: read-only ledger checks and append-only manually observed balances.
async function renderReconciliation(){
 const d=await api('reconciliation');state.reconciliationData=d;
 const sum=d.summary;
 const latestLabel=c=>!c?'Chưa kiểm đếm':c.difference===0?'Đã khớp lúc kiểm đếm':'Có chênh lệch lúc kiểm đếm';
 const cards=d.wallets.map(w=>{
   const c=w.last_check;
   return `<article class="recon-wallet"><div class="recon-wallet-title"><strong>${esc(w.name)}</strong><span class="recon-tag ${!c?'pending':c.difference?'alert':'ok'}">${latestLabel(c)}</span></div>`+
     `<div class="recon-book">${fmoney(w.book_balance)}</div><div class="panel-sub">Số dư theo sổ MoneyFlow hiện tại</div>`+
     (c?`<div class="recon-foot">Kiểm đếm gần nhất: ${esc(new Date(c.created_at).toLocaleString('vi-VN'))}<br>`+
       `Ghi nhận thực tế: ${fmoney(c.counted_balance)} · Theo sổ lúc đó: ${fmoney(c.recorded_balance)}<br>`+
       `Chênh lệch tại thời điểm kiểm: <b class="${c.difference?'recon-alert-text':'recon-ok-text'}">${signedMoney(c.difference)}</b></div>`:
       `<div class="recon-foot">Chưa ghi nhận số dư thực tế của ví.</div>`)+`</article>`;
 }).join('');
 const anomalies=d.anomalies.map(a=>`<div class="recon-alert-row"><div><strong>${esc(a.title)}</strong>`+
   `<div class="panel-sub">${esc(a.entry_title)} · ${esc(a.occurred_on)} · ${fmoney(a.amount)}</div>`+
   `<p>${esc(a.description)}</p></div><button type="button" class="table-action" data-action="recon-find-entry" data-date="${esc(a.occurred_on)}" data-title="${esc(a.entry_title)}">Xem giao dịch</button></div>`).join('');
 const integrity=d.integrity_issues.map(issue=>`<div class="recon-alert-row"><span class="recon-issue-icon">!</span><span>${esc(issue.detail)}</span></div>`).join('');
 const history=d.checks.map(c=>`<tr><td>${esc(new Date(c.created_at).toLocaleString('vi-VN'))}</td>`+
   `<td>${esc(d.wallets.find(w=>w.id===c.wallet_id)?.name||'Ví đã xóa')}</td>`+
   `<td>${fmoney(c.recorded_balance)}</td><td>${fmoney(c.counted_balance)}</td>`+
   `<td class="${c.difference?'recon-alert-text':'recon-ok-text'}">${signedMoney(c.difference)}</td><td>${esc(c.note||'—')}</td></tr>`).join('');
 $('#page-content').innerHTML=heading('Đối soát & kiểm tra tài chính',
   'So sánh sổ MoneyFlow với số tiền thực bạn tự kiểm đếm; phát hiện dấu hiệu cần xem lại. Không sửa số dư.',
   `<button class="btn btn-secondary" data-action="recon-reload">↻ Kiểm tra lại</button>`)+
 `<div class="recon-summary"><div class="recon-metric"><span>TỔNG SỐ DƯ THEO SỔ</span><strong>${fmoney(sum.book_total)}</strong></div>`+
 `<div class="recon-metric"><span>VÍ ĐÃ TỪNG KIỂM</span><strong>${sum.checked_wallets}/${sum.wallet_count}</strong></div>`+
 `<div class="recon-metric"><span>CHÊNH LỆCH LẦN GẦN NHẤT</span><strong>${sum.latest_discrepancies}</strong></div>`+
 `<div class="recon-metric"><span>DẤU HIỆU CẦN XEM</span><strong>${sum.anomaly_candidates+sum.integrity_issues}</strong></div></div>`+
 `<section class="panel"><div class="panel-head"><div><h2>◎ Số dư từng ví</h2><p class="panel-sub">Số liệu thực tế được nhập thủ công, không kết nối ngân hàng. Sổ hiện tại có thể đã thay đổi kể từ lần kiểm gần nhất.</p></div></div><div class="recon-wallet-grid">${cards}</div></section>`+
 `<section class="panel recon-section"><div class="panel-head"><div><h2>Ghi nhận số dư thực tế</h2><p class="panel-sub">Hãy xem số dư thực trong ví/ngân hàng tại thời điểm này rồi nhập bên dưới. Đây chỉ là lưu kết quả đối soát, không cộng/trừ tiền.</p></div></div>`+
 `<form class="recon-form" data-form="reconciliation"><label>Chọn ví<select name="wallet_id" class="select" required>${d.wallets.map(w=>`<option value="${w.id}">${esc(w.name)} · sổ ${fmoney(w.book_balance)}</option>`).join('')}</select></label>`+
 `<label>Số dư thực tế (VNĐ)<input name="counted_balance" class="input" type="number" min="0" max="1000000000000" step="1" required placeholder="Nhập số tiền bạn kiểm đếm"/></label>`+
 `<label class="recon-note">Ghi chú (không bắt buộc)<input name="note" class="input" maxlength="300" placeholder="Ví dụ: Theo số dư tài khoản ngân hàng lúc 19:30"/></label>`+
 `<button type="submit" class="btn btn-primary">Lưu kết quả kiểm đếm</button></form></section>`+
 `<section class="panel recon-section"><div class="panel-head"><div><h2>Kiểm tra tính nhất quán</h2><p class="panel-sub">Kiểm tra liên kết dữ liệu, số dư âm và sổ nợ/quỹ tiết kiệm. Không phải xác nhận số dư ngân hàng.</p></div></div>`+
 (integrity||`<div class="recon-empty-ok">✓ Không phát hiện lỗi toàn vẹn trong phạm vi kiểm tra.</div>`)+`</section>`+
 `<section class="panel recon-section"><div class="panel-head"><div><h2>Giao dịch cần xem lại</h2><p class="panel-sub">Dấu hiệu trùng và số tiền lớn dựa trên tối đa 2.000 giao dịch gần nhất; cảnh báo không có nghĩa là giao dịch sai.</p></div></div>`+
 (anomalies||`<div class="recon-empty-ok">✓ Không phát hiện dấu hiệu đáng chú ý trong mẫu giao dịch đã xét.</div>`)+
 (d.sample_limited?`<p class="panel-sub">Đã giới hạn mẫu ở 2.000 giao dịch gần nhất; kết quả không bao quát toàn bộ lịch sử.</p>`:'')+`</section>`+
 `<section class="panel recon-section"><div class="panel-head"><div><h2>Lịch sử đối soát</h2><p class="panel-sub">Lưu tối đa 60 lần ghi nhận gần nhất ở danh sách này. Không tự điều chỉnh các khoản chênh lệch.</p></div></div>`+
 `<div class="table-wrap"><table class="data-table"><thead><tr><th>THỜI ĐIỂM</th><th>VÍ</th><th>THEO SỔ LÚC KIỂM</th><th>KIỂM ĐẾM</th><th>CHÊNH LỆCH</th><th>GHI CHÚ</th></tr></thead>`+
 `<tbody>${history||'<tr><td colspan="6" class="table-row-empty">Chưa có lần đối soát nào.</td></tr>'}</tbody></table></div></section>`;
}

async function renderWallets(){
  const data=await refreshWallets();
  const kindText={cash:'Tiền mặt',bank:'Ngân hàng',ewallet:'Ví điện tử'};
  const cards=data.items.map(w=>`<article class="wallet-card"><div class="wallet-card-head"><span class="wallet-kind">${w.kind==='bank'?'▤':w.kind==='ewallet'?'◈':'◉'} ${kindText[w.kind]||'Ví'}</span>${w.is_default?'<span class="tag tag-admin">Ví chính</span>':`<span class="tag ${w.active?'tag-active':'tag-disabled'}">${w.active?'Hoạt động':'Đã khóa'}</span>`}</div><h3>${esc(w.name)}</h3><div class="wallet-big-balance">${fmoney(w.balance)}</div><p class="panel-sub">Số tiền ban đầu: ${fmoney(w.opening_balance)}</p><div class="wallet-card-actions"><button class="table-action" data-action="wallet-edit" data-id="${w.id}">Sửa tên/loại</button>${w.is_default?'':`<button class="table-action" data-action="wallet-toggle" data-id="${w.id}">${w.active?'Khóa ví':'Mở ví'}</button>`}</div></article>`).join('');
  const transfers=data.transfers.map(t=>`<tr><td>${esc(t.occurred_on)}</td><td>${esc(t.from_wallet)} → ${esc(t.to_wallet)}<div class="item-note">${esc(t.note)}</div></td><td class="amount expense">${fmoney(t.amount)}</td><td><button class="table-action delete" data-action="wallet-transfer-undo" data-id="${t.id}">Hoàn tác</button></td></tr>`).join('');
  $('#page-content').innerHTML=heading('Ví & tài khoản','Quản lý tiền mặt, ngân hàng và ví điện tử. Chuyển ví không tính vào tổng thu/chi.',`<button class="btn btn-secondary" data-action="wallet-transfer">⇄ Chuyển tiền</button><button class="btn btn-primary" data-action="wallet-add">+ Thêm ví</button>`)+`<section class="panel wallet-summary"><span>TỔNG SỐ DƯ KHẢ DỤNG</span><strong>${fmoney(data.total_balance)}</strong><small>${data.items.length} ví · Mỗi ví có sổ số dư độc lập</small></section><div class="wallet-grid">${cards}</div><section class="panel"><div class="panel-head"><div><h2>Lịch sử chuyển giữa các ví</h2><p class="panel-sub">Chỉ dịch chuyển tiền nội bộ; không phải thu nhập hay chi tiêu.</p></div></div><div class="table-wrap"><table class="data-table"><thead><tr><th>NGÀY</th><th>TỪ VÍ → ĐẾN VÍ</th><th>SỐ TIỀN</th><th>THAO TÁC</th></tr></thead><tbody>${transfers||'<tr><td colspan="4" class="table-row-empty">Chưa có giao dịch chuyển ví.</td></tr>'}</tbody></table></div></section>`;
}
function walletModal(w=null){openModal(w?'Chỉnh sửa ví':'Tạo ví mới',w?'Giữ nguyên lịch sử và số dư khi đổi tên/loại ví.':'Ví mới có số dư riêng. Số dư ban đầu là tiền bạn đã có sẵn trong ví.',`<input type="hidden" name="id" value="${w?.id||''}"/><label>Tên ví<input class="input" name="name" maxlength="80" required placeholder="Ví dụ: Tiền mặt, VCB, MoMo" value="${esc(w?.name||'')}"/></label><label>Loại ví<select class="select" name="kind"><option value="cash" ${w?.kind==='cash'?'selected':''}>◉ Tiền mặt</option><option value="bank" ${w?.kind==='bank'?'selected':''}>▤ Ngân hàng</option><option value="ewallet" ${w?.kind==='ewallet'?'selected':''}>◈ Ví điện tử</option></select></label>${w?'':`<label>Số dư ban đầu (VNĐ)<input class="input" name="opening_balance" type="number" min="0" max="1000000000000" step="1" value="0" required/></label><div class="simple-info">Nếu chuyển tiền từ ví có sẵn, hãy đặt số dư ban đầu = 0, rồi dùng chức năng Chuyển tiền để tránh tính trùng.</div>`}`,'wallet',w?'Lưu thông tin':'Tạo ví');}
function walletTransferModal(){const active=state.wallets.filter(w=>w.active);if(active.length<2)return toast('Cần ít nhất 2 ví đang hoạt động.',true);const opts=active.map(w=>`<option value="${w.id}">${esc(w.name)} · ${fmoney(w.balance)}</option>`).join('');openModal('Chuyển tiền giữa các ví','Số tiền được trừ khỏi ví nguồn và cộng vào ví đích; tổng tài sản không đổi.',`<label>Ví nguồn<select class="select" name="from_wallet_id" required>${opts}</select></label><label>Ví nhận<select class="select" name="to_wallet_id" required>${active.slice().reverse().map(w=>`<option value="${w.id}">${esc(w.name)} · ${fmoney(w.balance)}</option>`).join('')}</select></label><div class="row-fields"><label>Số tiền (VNĐ)<input class="input" type="number" name="amount" min="1" max="1000000000000" step="1" required/></label><label>Ngày chuyển<input class="input" name="occurred_on" type="date" value="${today()}" required/></label></div><label>Ghi chú<textarea class="textarea" name="note" maxlength="300" placeholder="Ví dụ: Chuyển tiền vào ngân hàng"></textarea></label>`,'wallet-transfer','Xác nhận chuyển');}

async function renderSettings(){const d=await api(`dashboard?month=${state.month}`);$('#page-content').innerHTML=heading('Cài đặt tài khoản','Quản lý số dư ban đầu, mật khẩu và các thông tin tài khoản.')+`<div class="settings-grid"><section class="panel"><div class="panel-head"><h2>◈ Số tiền ban đầu</h2></div><p class="panel-sub" style="margin-bottom:20px">Số tiền bạn có khi bắt đầu sử dụng MoneyFlow. Số dư thực tế được cộng trừ tự động từ các giao dịch.</p><form data-form="opening"><div class="form-group"><label>Số tiền gốc (VNĐ)</label><input class="input" name="opening_balance" inputmode="numeric" type="number" min="0" max="1000000000000" step="1" value="${d.opening_balance}" required/><small>Số dư hiện tại: ${fmoney(d.balance)}</small></div><button type="submit" class="btn btn-primary">Lưu số tiền ban đầu</button></form></section><section class="panel"><div class="panel-head"><h2>♙ Thông tin tài khoản</h2></div><div class="simple-info"><strong>Tên đăng nhập:</strong> ${esc(state.user.username)}<br><strong>Email:</strong> ${esc(state.user.email||'Chưa cập nhật')}<br><strong>Số điện thoại:</strong> ${esc(vietnamPhone(state.user.phone)||'Chưa cập nhật')}<br><strong>Địa chỉ:</strong> ${esc(state.user.address||'Chưa cập nhật')}<br><strong>Vai trò:</strong> ${state.user.role==='admin'?'Quản trị viên':'Thành viên'}<br><strong>Lưu trữ:</strong> PostgreSQL chạy local</div><p class="panel-sub" style="margin:19px 0">Không chia sẻ tài khoản. Hãy đặt mật khẩu mạnh và sao lưu dữ liệu định kỳ.</p><button class="btn btn-secondary" data-action="edit-profile">✎ Cập nhật hồ sơ</button><button class="btn btn-secondary" data-action="change-password" style="margin-left:8px">🔒 Đổi mật khẩu</button><button class="btn btn-danger" data-action="logout" style="margin-left:8px">Đăng xuất</button></section></div><div class="panel" style="margin-top:18px"><div class="panel-head"><h2>🔐 An toàn dữ liệu</h2></div><div class="simple-info">Mật khẩu được băm bằng Argon2id (salt riêng cho từng mật khẩu). Phiên đăng nhập dùng cookie HttpOnly và mã chống CSRF. Ứng dụng chỉ mở tại 127.0.0.1 trên máy bạn. Dữ liệu được lưu trong Docker volume; muốn sao lưu hãy chạy <strong>scripts/backup.ps1</strong> trên Windows. Khi xóa Docker volume, dữ liệu sẽ mất nếu không có bản sao lưu.</div></div><section class="panel security-panel"><div class="panel-head"><div><h2>🛡️ Bảo mật nâng cao</h2><p class="panel-sub">Mã xác thực hai bước, quản lý phiên đăng nhập và kiểm tra dữ liệu.</p></div></div><div class="security-actions"><span class="security-pill">${state.user.totp_enabled?'● 2FA đang bật':'○ 2FA chưa bật'}</span><button type="button" class="btn btn-secondary" data-action="totp-setup" ${state.user.totp_enabled?'hidden':''}>Bật xác thực 2 bước</button><button type="button" class="btn btn-secondary" data-action="totp-disable" ${state.user.totp_enabled?'':'hidden'}>Tắt xác thực 2 bước</button><button type="button" class="btn btn-secondary" data-action="security-sessions">Phiên đăng nhập</button><button type="button" class="btn btn-secondary" data-action="security-integrity">Kiểm tra số dư</button></div><p class="panel-sub">Sử dụng Google Authenticator, Microsoft Authenticator hoặc ứng dụng TOTP tương thích. Mã dự phòng chỉ hiển thị một lần khi bật.</p></section>`+`<section class="panel pwa-settings"><div class="panel-head"><div><h2>📲 Ứng dụng & thông báo máy tính</h2><p class="panel-sub">Cài MoneyFlow như ứng dụng riêng trên Windows hoặc điện thoại.</p></div></div><div class="pwa-actions"><button type="button" class="btn btn-primary" data-action="pwa-install">Cài ứng dụng</button><button type="button" class="btn btn-secondary" data-action="pwa-notify-on">Bật thông báo nhắc lịch</button><button type="button" class="btn btn-secondary" data-action="pwa-notify-off" hidden>Tắt thông báo</button></div><p class="panel-sub" id="pwa-status" role="status" aria-live="polite">Đang kiểm tra hỗ trợ từ trình duyệt...</p><div class="simple-info">Chỉ thông báo lịch đến hạn khi ứng dụng còn mở ở nền và đã được cấp quyền. Không hiển thị số tiền hoặc nội dung giao dịch trong thông báo Windows. Không có đồng bộ tài chính ngoại tuyến; khi mất kết nối, ứng dụng yêu cầu kết nối lại Docker.</div></section>`;window.MoneyFlowPWA?.status?.();}
async function renderDebts(){
 const d=await api('debts');state.debtData=d;
 const typeLabel=x=>x.direction==='receivable'?'Phải thu':'Phải trả';
 const cards=d.items.map(x=>`<article class="debt-card ${x.remaining===0?'debt-settled':''}">
   <div class="debt-card-top"><div><span class="debt-overline">${x.direction==='receivable'?'↗ NỢ PHẢI THU':'↘ NỢ PHẢI TRẢ'} · #${x.id}</span><h3>${esc(x.name)}</h3><div class="debt-lender">${esc(x.lender||'Chưa nhập đối tác')} ${x.due_date?'· Kỳ đầu: '+esc(x.due_date):''}</div></div><span class="tag ${x.remaining===0?'tag-active':'tag-disabled'}">${x.remaining===0?'Đã tất toán':'Đang theo dõi'}</span></div>
   <div class="debt-amount">${fmoney(x.remaining)} <small>/ ${fmoney(x.principal)}</small></div>
   <div class="debt-loan-meta"><span>${x.interest_rate_pct}%/năm</span><span>${x.installment_count} kỳ</span><span>${typeLabel(x)}</span></div>
   <div class="progress-track"><div class="progress-fill" style="width:${pct(x.paid,x.principal)}%;background:${x.remaining===0?'#56dabc':'#7d70f8'}"></div></div>
   <div class="debt-card-foot"><span>Đã ${x.direction==='receivable'?'thu':'trả'} gốc ${pct(x.paid,x.principal)}% · ${fmoney(x.paid)}</span><div class="row-actions"><button class="table-action" data-action="debt-schedule" data-id="${x.id}">Lịch trả góp</button><button class="table-action" data-action="edit-debt" data-id="${x.id}">Sửa</button>${x.remaining>0?`<button class="table-action" data-action="pay-debt" data-id="${x.id}">${x.direction==='receivable'?'Thu hồi':'Trả nợ'}</button>`:''}${x.paid===0?`<button class="table-action delete" data-action="delete-debt" data-id="${x.id}">Xóa</button>`:''}</div></div>
   ${x.note?`<p class="debt-lender">${esc(x.note)}</p>`:''}</article>`).join('');
 const history=d.payments.map(p=>`<tr><td>${esc(p.paid_on)}</td><td>${esc(p.debt)}<div class="wallet-tagline">${p.direction==='receivable'?'Đã thu từ':'Đã trả từ'} ví ${esc(walletName(p.wallet_id))}</div></td><td><span class="tag ${p.mode==='auto'?'tag-admin':'tag-active'}">${p.mode==='auto'?'Tự động từ thu nhập':p.direction==='receivable'?'Thu hồi thủ công':'Trả thủ công'}</span></td><td class="amount ${p.direction==='receivable'?'income':'expense'}">${p.direction==='receivable'?'+':'−'}${fmoney(p.amount+(p.interest_amount||0))}<div class="debt-lender">Gốc: ${fmoney(p.amount)} · Lãi: ${fmoney(p.interest_amount||0)}</div></td><td>${p.mode==='manual'?`<button class="table-action delete" data-action="undo-debt-payment" data-id="${p.id}">Hoàn tác</button>`:'<span class="debt-lender">Sửa giao dịch thu để điều chỉnh</span>'}</td></tr>`).join('');
 $('#page-content').innerHTML=heading('Quản lý nợ chuyên sâu','Nợ phải trả, nợ phải thu, lãi và lịch trả góp · Các khoản tiền được hạch toán theo từng ví.',`<button class="btn btn-primary" data-action="add-debt">+ Thêm khoản nợ</button>`)+
 `<div class="debt-summary-grid debt-summary-four"><div class="debt-summary debt-due"><span>NỢ PHẢI TRẢ</span><strong>${fmoney(d.total_remaining)}</strong><small>Đã trả gốc: ${fmoney(d.total_paid)}</small></div><div class="debt-summary"><span>NỢ PHẢI THU</span><strong>${fmoney(d.total_receivable_remaining)}</strong><small>Đã thu gốc: ${fmoney(d.total_receivable_collected)}</small></div><div class="debt-summary"><span>LÃI ĐÃ TRẢ</span><strong>${fmoney(d.total_interest_paid)}</strong><small>Chi ra ngoài phần nợ gốc</small></div><div class="debt-summary"><span>LÃI ĐÃ THU</span><strong>${fmoney(d.total_interest_received)}</strong><small>Cộng vào số dư ví</small></div></div>
 <div class="debt-explainer"><strong>Quy tắc hạch toán:</strong> Tiền thu mới chỉ tự động thanh toán <b>nợ phải trả</b> theo thứ tự tạo trước, không tự trừ nợ phải thu. Khoản <b>thu hồi nợ</b> cộng vào ví, khoản <b>trả nợ</b> trừ từ ví. Lãi chỉ ghi nhận khi bạn nhập thanh toán thật. Lịch trả góp là <b>dự tính tham khảo</b> theo dư nợ giảm dần, chia đều gốc từng tháng.</div>
 <div class="debt-grid">${cards||`<section class="panel debt-empty">${empty('Chưa có khoản nợ','Hãy tạo nợ phải thu hoặc nợ phải trả để theo dõi.')}</section>`}</div>
 <section class="panel debt-history"><div class="panel-head"><div><h2>Lịch sử thanh toán / thu hồi</h2><p class="panel-sub">100 khoản gần nhất; tách gốc và lãi, không tính trùng vào thu/chi thông thường</p></div></div><div class="table-wrap"><table class="data-table"><thead><tr><th>NGÀY</th><th>KHOẢN NỢ</th><th>HÌNH THỨC</th><th>TIỀN MẶT</th><th>THAO TÁC</th></tr></thead><tbody>${history||'<tr><td colspan="5" class="table-row-empty">Chưa có thanh toán nào.</td></tr>'}</tbody></table></div></section>`;
}
async function debtScheduleModal(id){
 const d=await api(`debts/${id}/schedule`);
 const rows=d.schedule.map(p=>`<tr><td>${p.period}</td><td>${esc(p.due_date||'—')}</td><td>${fmoney(p.principal)}</td><td>${fmoney(p.estimated_interest)}</td><td>${fmoney(p.estimated_total)}</td><td><span class="tag ${p.status==='paid'?'tag-active':p.status==='overdue'?'tag-disabled':'tag-admin'}">${p.status==='paid'?'Đủ gốc':p.status==='overdue'?'Quá hạn':'Dự kiến'}</span></td></tr>`).join('');
 const body=`<div class="simple-info">${esc(d.disclaimer)}<br>Lãi dự tính cả lịch: <strong>${fmoney(d.estimated_total_interest)}</strong> · Lãi thực tế đã ghi: <strong>${fmoney(d.actual_interest_recorded)}</strong>.</div><div class="table-wrap"><table class="data-table debt-schedule-table"><thead><tr><th>KỲ</th><th>HẠN</th><th>GỐC</th><th>LÃI ƯỚC TÍNH</th><th>TỔNG</th><th>TRẠNG THÁI GỐC</th></tr></thead><tbody>${rows}</tbody></table></div>`;
 openModal('Lịch trả góp · '+d.debt.name,'Kế hoạch tham khảo; không tự động trừ tiền hoặc phát sinh lãi.',body,'readonly','Đóng');
 $('#modal-form')?.removeAttribute('data-form');$('#modal-form .modal-footer button[type="submit"]')?.remove();
}
function debtModal(existing=null){
 const frozen=!!(existing?.paid);
 const direction=existing?.direction||'payable';
 const body=`<input type="hidden" name="id" value="${existing?.id||''}"/>
 <label>Loại khoản nợ<select class="select" name="direction" ${frozen?'disabled':''}><option value="payable" ${direction==='payable'?'selected':''}>↘ Nợ phải trả (mình đi vay)</option><option value="receivable" ${direction==='receivable'?'selected':''}>↗ Nợ phải thu (người khác vay mình)</option></select></label>
 <label>Tên khoản nợ<input class="input" name="name" maxlength="120" required placeholder="Ví dụ: Vay mua xe / Cho bạn A vay" value="${esc(existing?.name||'')}"/></label>
 <label>Người vay / cho vay<input class="input" name="lender" maxlength="120" placeholder="Ngân hàng / người thân / đối tác" value="${esc(existing?.lender||'')}"/></label>
 <div class="row-fields"><label>Gốc ban đầu (VNĐ)<input class="input" type="number" name="principal" min="1" max="1000000000000" step="1" required value="${existing?.principal||''}" ${frozen?'readonly':''}/></label><label>Lãi suất năm (%)<input class="input" type="number" name="interest_rate_pct" min="0" max="100" step="0.01" required value="${existing?.interest_rate_pct??0}" ${frozen?'readonly':''}/></label></div>
 <div class="row-fields"><label>Số kỳ trả góp (tháng)<input class="input" type="number" name="installment_count" min="1" max="360" step="1" required value="${existing?.installment_count||1}" ${frozen?'readonly':''}/></label><label>Ngày đến hạn kỳ đầu<input class="input" type="date" name="due_date" value="${esc(existing?.due_date||'')}" ${frozen?'readonly':''}/></label></div>
 <label>Ghi chú<textarea class="textarea" maxlength="500" name="note" placeholder="Ghi chú khoản vay">${esc(existing?.note||'')}</textarea></label>
 <div class="simple-info">Khoản vay có nhiều kỳ cần nhập ngày đến hạn kỳ đầu. Lãi suất chỉ dùng lập lịch <b>ước tính</b>, không tự ghi tiền lãi. ${frozen?'Khoản đã thanh toán không được đổi gốc, loại nợ, lãi hoặc lịch kỳ.':''}</div>`;
 openModal(existing?'Chỉnh sửa khoản nợ':'Tạo khoản nợ','Theo dõi nợ phải thu và nợ phải trả tách biệt.',body,'debt',existing?'Lưu khoản nợ':'Tạo khoản nợ');
}
function payDebtModal(debt){
 if(!debt)return;
 const recv=debt.direction==='receivable';
 openModal(recv?'Thu hồi khoản cho vay':'Trả nợ từ số dư',recv?'Tiền nhận từ người vay sẽ cộng vào ví đã chọn.':'Tiền trả sẽ trừ vào ví đã chọn.',
 `<input type="hidden" name="debt_id" value="${debt.id}"/><div class="simple-info">${esc(debt.name)} · Gốc còn lại <strong>${fmoney(debt.remaining)}</strong></div>
 <div class="row-fields"><label>Gốc ${recv?'thu':'trả'} (VNĐ)<input class="input" type="number" name="amount" step="1" min="1" max="${debt.remaining}" required placeholder="Nhập tiền gốc"/></label><label>Lãi thực tế ${recv?'thu':'trả'} (VNĐ)<input class="input" type="number" name="interest_amount" step="1" min="0" max="1000000000000" value="0" required/></label></div>
 ${walletSelect(null,recv?'Tiền vào ví':'Tiền trả từ ví')}<label>Ngày thanh toán<input class="input" type="date" name="paid_on" required value="${today()}"/></label>
 <div class="simple-info">Số tiền ví ${recv?'nhận':'bị trừ'} = gốc + lãi thực tế. Phần gốc làm giảm nợ, phần lãi không làm giảm nợ gốc.</div>`,
 'debt-pay',recv?'Xác nhận thu hồi':'Xác nhận trả nợ');
}

async function renderUsers(){const users=await api('users');state.userData=users;$('#page-content').innerHTML=heading('Quản lý người dùng','Tạo tài khoản, phân quyền và quản lý quyền truy cập.',`<button class="btn btn-primary" data-action="add-user">+ Thêm người dùng</button>`)+`<section class="panel"><div class="panel-head"><h2>Tất cả tài khoản</h2><span class="mini-stat">${users.length} tài khoản</span></div><div class="table-wrap"><table class="data-table"><thead><tr><th>TÀI KHOẢN</th><th>VAI TRÒ</th><th>TRẠNG THÁI</th><th>NGÀY TẠO</th><th>HÀNH ĐỘNG</th></tr></thead><tbody>${users.map(u=>`<tr><td><div class="item-name">${esc(u.username)}</div><div class="item-note">${esc(u.email||'Chưa có email')} · ${esc(vietnamPhone(u.phone)||'Chưa có SĐT')}</div></td><td><span class="tag ${u.role==='admin'?'tag-admin':'tag-member'}">${u.role==='admin'?'Admin':'Thành viên'}</span></td><td><span class="tag ${u.active?'tag-active':'tag-disabled'}">${u.active?'Hoạt động':'Đã khóa'}</span></td><td>${esc(new Date(u.created_at).toLocaleDateString('vi-VN'))}</td><td><div class="row-actions" style="justify-content:flex-start"><button class="table-action" data-action="edit-user" data-id="${u.id}">Sửa</button><button class="table-action" data-action="reset-password" data-id="${u.id}">Đặt lại MK</button>${u.id===state.user.id?'':`<button class="table-action delete" data-action="delete-user" data-id="${u.id}">Xóa</button>`}</div></td></tr>`).join('')}</tbody></table></div></section>`;}
async function renderAudit(){const logs=await api('audit');$('#page-content').innerHTML=heading('Nhật ký hoạt động','Theo dõi các thao tác quan trọng của hệ thống.')+`<section class="panel"><div class="panel-head"><h2>80 hoạt động gần nhất</h2></div><div class="table-wrap"><table class="data-table"><thead><tr><th>THỜI GIAN (UTC)</th><th>NGƯỜI THỰC HIỆN</th><th>HÀNH ĐỘNG</th><th>CHI TIẾT</th></tr></thead><tbody>${logs.length?logs.map(l=>`<tr><td>${esc(new Date(l.at).toLocaleString('vi-VN',{timeZone:'UTC'}))}</td><td>${esc(l.actor)}</td><td><span class="category-chip">${esc(l.action)}</span></td><td>${esc(l.detail)}</td></tr>`).join(''):`<tr><td colspan="4" class="table-row-empty">Chưa có lịch sử.</td></tr>`}</tbody></table></div></section>`;}
async function refreshCategories(){state.categories=await api('categories')}
async function refreshWallets(){const d=await api('wallets');state.wallets=d.items||[];return d;}
const walletName=id=>state.wallets.find(w=>w.id===Number(id))?.name||'Ví chính';
function walletChoices(selected=null){const chosen=selected??state.wallets.find(w=>w.is_default)?.id;return state.wallets.filter(w=>w.active||w.id===Number(chosen)).map(w=>`<option value="${w.id}" ${w.id===Number(chosen)?'selected':''}>${esc(w.name)} (${fmoney(w.balance)})</option>`).join('')}
function walletSelect(selected=null,label='Ví tiền'){return `<label>${esc(label)}<select class="select" name="wallet_id" required>${walletChoices(selected)}</select></label>`}
async function navigate(page){if(!PAGE_NAMES[page] || ((page==='users'||page==='audit')&&state.user.role!=='admin'))return;state.page=page;$$('[data-page]', $('#main-nav')).forEach(x=>x.classList.toggle('active',x.dataset.page===page));$('#breadcrumb-current').textContent=PAGE_NAMES[page];$('#header-month-label').textContent=monthText(state.month);$('#page-content').innerHTML='<div class="skeleton">Đang tải dữ liệu...</div>';$('#sidebar').classList.remove('open');$('#mobile-overlay').hidden=true;
 try {await refreshCategories();await refreshWallets();await refreshReminders();switch(page){case 'forecast':await renderForecast();break;case 'reports':await renderReports();break;case 'annual':await renderAnnual();break;case 'wallets':await renderWallets();break;case 'savings':await renderSavings();break;case 'stashes':await renderStashes();break;case 'recurring':await renderRecurring();break;case 'dashboard':await renderDashboard();break;case 'transactions':await renderTransactions();break;case 'receipts':await renderReceipts();break;case 'reconciliation':await renderReconciliation();break;case 'budgets':await renderBudgets();break;case 'debts':await renderDebts();break;case 'categories':await renderCategories();break;case 'settings':await renderSettings();break;case 'users':await renderUsers();break;case 'audit':await renderAudit();break;}}
 catch(e){$('#page-content').innerHTML=`<section class="panel">${empty('Không thể tải dữ liệu',e.message)}</section>`;toast(e.message,true)}}
function openModal(title,subtitle,body,formName,submit='Lưu thay đổi'){$('#modal-root').innerHTML=`<div class="modal-overlay"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="dialog-title"><div class="modal-header"><div><h2 id="dialog-title">${esc(title)}</h2><p>${esc(subtitle)}</p></div><button class="close-modal" data-action="close-modal" aria-label="Đóng">✕</button></div><form id="modal-form" data-form="${esc(formName)}"><div class="modal-body">${body}<div class="form-error" id="modal-error"></div></div><div class="modal-footer"><button class="btn btn-secondary" type="button" data-action="close-modal">Hủy</button><button class="btn btn-primary" type="submit">${esc(submit)}</button></div></form></section></div>`;setTimeout(()=>$('#modal-form input:not([type="hidden"])')?.focus(),0)}
function closeModal(){if(currentReceiptPreview){URL.revokeObjectURL(currentReceiptPreview);currentReceiptPreview=null;}$('#modal-root').innerHTML=''}
function selectCats(kind,selected){const items=state.categories.filter(c=>c.kind===kind && (c.active||c.id===selected));return `<select id="entry-category" name="category_id" class="select" required><option value="">-- Chọn danh mục --</option>${items.map(c=>`<option value="${c.id}" ${c.id===selected?'selected':''}>${esc(c.name)}</option>`).join('')}</select>`}
function entryModal(entry=null,forcedKind='expense'){const kind=entry?.kind||forcedKind;const body=`<input type="hidden" name="id" value="${entry?.id||''}"/><label>Loại giao dịch<select id="entry-kind" name="kind" class="select"><option value="expense" ${kind==='expense'?'selected':''}>↘ Chi tiền</option><option value="income" ${kind==='income'?'selected':''}>↗ Thu tiền</option></select></label><label>Nội dung giao dịch<input class="input" name="title" maxlength="120" placeholder="Ví dụ: Ăn trưa, nhận lương..." required value="${esc(entry?.title||'')}"/></label><div class="row-fields"><label>Số tiền (VNĐ)<input class="input" name="amount" type="number" min="1" max="1000000000000" step="1" inputmode="numeric" required placeholder="150000" value="${entry?.amount||''}"/></label><label>Ngày giao dịch<input class="input" name="occurred_on" type="date" required value="${esc(entry?.occurred_on||today())}"/></label></div><label>Danh mục<div id="entry-category-wrap">${selectCats(kind,entry?.category_id)}</div></label>${walletSelect(entry?.wallet_id)}<label>Ghi chú (không bắt buộc)<textarea class="textarea" maxlength="500" name="note" placeholder="Thông tin bổ sung">${esc(entry?.note||'')}</textarea></label>`;
 openModal(entry?'Chỉnh sửa giao dịch':'Thêm giao dịch mới','Thu nhập sẽ tự trả nợ trước và tích tiền vào quỹ nếu bạn đã bật quy tắc.',body,'entry',entry?'Cập nhật':'Lưu giao dịch');}
function openingModal(){openModal('Thiết lập số tiền ban đầu','Nhập tổng số tiền hiện có để bắt đầu quản lý chi tiêu.',`<label>Tổng số tiền hiện có (VNĐ)<input class="input" name="opening_balance" inputmode="numeric" type="number" min="0" max="1000000000000" step="1" required placeholder="Ví dụ: 20000000"/></label><div class="simple-info">Số dư sẽ thay đổi tự động sau mỗi lần ghi nhận thu nhập hoặc chi tiêu.</div>`,'opening','Bắt đầu sử dụng')}
function categoryModal(){openModal('Tạo danh mục mới','Cá nhân hóa các loại thu nhập hoặc chi tiêu.',`<label>Tên danh mục<input class="input" name="name" maxlength="60" required placeholder="Ví dụ: Nuôi thú cưng"/></label><label>Loại danh mục<select class="select" name="kind"><option value="expense">Chi tiêu</option><option value="income">Thu nhập</option></select></label><label>Màu nhận diện<input class="input" style="height:50px;padding:5px" type="color" name="color" value="#7065f6"/></label>`,'category','Tạo danh mục')}
function budgetModal(existing=null){const expenses=state.categories.filter(c=>c.kind==='expense'&&c.active);if(!expenses.length)return toast('Hãy tạo danh mục chi tiêu trước.',true);const body=`<label>Danh mục chi tiêu<select class="select" name="category_id" required>${expenses.map(c=>`<option value="${c.id}" ${c.id===existing?.category_id?'selected':''}>${esc(c.name)}</option>`).join('')}</select></label><label>Tháng ngân sách<input class="input" name="month" type="month" required value="${state.month}"/></label><label>Hạn mức (VNĐ)<input class="input" name="amount" type="number" min="0" max="1000000000000" step="1" value="${existing?.amount??''}" required/></label>`;openModal('Thiết lập ngân sách','Hạn mức sẽ hiển thị trên biểu đồ tiến độ.',body,'budget','Lưu ngân sách')}
function contactFields(u=null){return `<label>Email đăng ký<input class="input" type="email" name="email" maxlength="254" required placeholder="tenban@gmail.com" value="${esc(u?.email||'')}"/></label><label>Số điện thoại<input class="input" type="tel" name="phone" maxlength="25" required placeholder="09xxxxxxxx" value="${esc(vietnamPhone(u?.phone))}"/></label><label>Địa chỉ<input class="input" name="address" minlength="5" maxlength="300" required placeholder="Số nhà, đường, phường/xã, tỉnh/thành" value="${esc(u?.address||'')}"/></label>`}
function newPasswordField(field='password',name='password'){return `<label>${esc(name)}<div class="password-input"><input class="input" type="password" name="${field}" minlength="12" maxlength="128" autocomplete="new-password" required placeholder="Mật khẩu từ 12 ký tự" data-password-strength="modal"/><button type="button" data-peek class="peek-password" aria-label="Hiện/ẩn mật khẩu">◉</button></div></label><div class="strength-meter" data-meter="modal" aria-live="polite"></div><label>Xác nhận mật khẩu<div class="password-input"><input class="input" type="password" name="confirm_password" minlength="12" maxlength="128" autocomplete="new-password" required placeholder="Nhập lại mật khẩu" data-confirm-password="modal"/><button type="button" data-peek class="peek-password" aria-label="Hiện/ẩn mật khẩu xác nhận">◉</button></div></label><div class="password-confirm-feedback" data-confirm-status="modal" aria-live="polite"></div>`}
function userModal(u=null){const body=u?`<input name="id" type="hidden" value="${u.id}"/>${contactFields(u)}<label>Phân quyền<select name="role" class="select"><option value="member" ${u.role==='member'?'selected':''}>Thành viên</option><option value="admin" ${u.role==='admin'?'selected':''}>Quản trị viên</option></select></label><label>Trạng thái<select name="active" class="select"><option value="true" ${u.active?'selected':''}>Đang hoạt động</option><option value="false" ${!u.active?'selected':''}>Khóa tài khoản</option></select></label>`:`<label>Tên đăng nhập<input class="input" name="username" minlength="3" maxlength="32" required placeholder="vidu: thanhvien01"/></label>${contactFields()}${newPasswordField()}`;openModal(u?'Chỉnh sửa người dùng':'Tạo người dùng','Email, điện thoại, địa chỉ là bắt buộc đối với tài khoản mới.',body,u?'user-edit':'user-add',u?'Lưu thay đổi':'Tạo tài khoản');setTimeout(()=>$$('[data-password-strength]', $('#modal-root')).forEach(updateStrength),0)}
function profileModal(){openModal('Cập nhật thông tin tài khoản','Email, điện thoại và địa chỉ là thông tin bắt buộc. Xác nhận mật khẩu hiện tại để bảo vệ email khôi phục.',`${contactFields(state.user)}<label>Mật khẩu hiện tại<input class="input" name="current_password" type="password" autocomplete="current-password" required/></label>`,'profile','Lưu thông tin')}
function deleteUserModal(user){if(!user)return;openModal('Xóa tài khoản vĩnh viễn','Toàn bộ giao dịch, danh mục, ngân sách và phiên đăng nhập của tài khoản này sẽ bị xóa. Không thể hoàn tác nếu chưa sao lưu.',`<input type="hidden" name="id" value="${user.id}"/><div class="simple-info danger-text">Để xác nhận xóa tài khoản ${esc(user.username)}, nhập chính xác tên đăng nhập <strong>${esc(user.username)}</strong>:</div><label>Tên đăng nhập xác nhận<input class="input" name="confirm_username" required autocomplete="off" placeholder="${esc(user.username)}"/></label>`,'user-delete','Xóa vĩnh viễn')}
function changePasswordModal(target=null){const isAdmin=!!target;openModal(isAdmin?'Đặt lại mật khẩu':'Đổi mật khẩu',isAdmin?'Người dùng sẽ bị đăng xuất khỏi mọi phiên.':'Các phiên đăng nhập khác sẽ bị vô hiệu hóa.',`<input type="hidden" name="user_id" value="${target?.id||''}"/>${isAdmin?'':`<label>Mật khẩu hiện tại<input class="input" type="password" name="old_password" autocomplete="current-password" required/></label>`}${newPasswordField('new_password','Mật khẩu mới')}`,'password',isAdmin?'Đặt lại mật khẩu':'Cập nhật mật khẩu');setTimeout(()=>$$('[data-password-strength]', $('#modal-root')).forEach(updateStrength),0)}
function monthModal(){openModal('Chọn tháng thống kê','Thay đổi khoảng thời gian hiển thị trên biểu đồ và danh sách.',`<label>Tháng cần xem<input class="input" type="month" name="month" min="2000-01" max="2099-12" value="${state.month}" required/></label>`,'month','Áp dụng')}
function formObj(form){return Object.fromEntries(new FormData(form).entries())}
async function submitForm(form){const type=form.dataset.form, raw=formObj(form);const n=val=>Number(val);
 if(type==='receipt-upload'){
   const file=raw.receipt_file;
   if(!(file instanceof File)||!file.size)throw Error('Hãy chọn tệp ảnh hoặc PDF.');
   if(file.size>8*1024*1024)throw Error('Dung lượng tối đa 8 MB/tệp.');
   const entryId=Number(raw.entry_id);
   await api(`transactions/${entryId}/receipts`,{method:'POST',body:JSON.stringify({name:file.name,data_base64:await receiptToBase64(file)})});
   toast('Đã đính kèm chứng từ an toàn.');await navigate('transactions');await openReceiptsModal(entryId);return;
 }
 if(type==='entry'){const payload={title:raw.title.trim(),kind:raw.kind,amount:n(raw.amount),category_id:n(raw.category_id),occurred_on:raw.occurred_on,note:raw.note||'',wallet_id:n(raw.wallet_id)};const result=await api(raw.id?`transactions/${raw.id}`:'transactions',{method:raw.id?'PUT':'POST',body:JSON.stringify(payload)});toast(result.auto_saved?`Đã tự để dành ${fmoney(result.auto_saved)}${result.debt_paid?` sau khi trả nợ ${fmoney(result.debt_paid)}`:''}!`:result.debt_paid?`Đã tự động trừ ${fmoney(result.debt_paid)} vào nợ gốc!`:(raw.id?'Đã cập nhật giao dịch!':'Đã ghi nhận giao dịch, số dư đã cập nhật!'));}
 else if(type==='wallet'){const payload={name:raw.name.trim(),kind:raw.kind};if(!raw.id)payload.opening_balance=n(raw.opening_balance);await api(raw.id?`wallets/${raw.id}`:'wallets',{method:raw.id?'PUT':'POST',body:JSON.stringify(payload)});toast(raw.id?'Đã cập nhật ví!':'Đã tạo ví mới!');}
 else if(type==='savings-goal'){
   const payload={name:raw.name.trim(),target_amount:n(raw.target_amount),due_date:raw.due_date||null,note:raw.note||''};
   await api(raw.id?`savings/${raw.id}`:'savings',{method:raw.id?'PUT':'POST',body:JSON.stringify(payload)});
   toast(raw.id?'Đã cập nhật mục tiêu.':'Đã tạo mục tiêu tiết kiệm.');
 }
 else if(type==='savings-movement'){
   const payload={kind:raw.kind,wallet_id:n(raw.wallet_id),amount:n(raw.amount),occurred_on:raw.occurred_on,note:raw.note||''};
   await api(`savings/${raw.id}/movements`,{method:'POST',body:JSON.stringify(payload)});
   toast(raw.kind==='deposit'?'Đã góp tiền. Ví khả dụng đã trừ; tổng tài sản không đổi.':'Đã rút tiền về ví; tổng tài sản không đổi.');
 }
 else if(type==='stash-fund'){
   const mode=raw.auto_mode||'off';
   const payload={name:raw.name.trim(),note:raw.note||'',auto_mode:mode,
     auto_value:mode==='off'?0:n(raw.auto_value),
     auto_wallet_id:mode==='off'||!raw.auto_wallet_id?null:n(raw.auto_wallet_id)};
   await api(raw.id?`stashes/${raw.id}`:'stashes',{method:raw.id?'PUT':'POST',body:JSON.stringify(payload)});
   toast(raw.id?'Đã cập nhật quỹ để dành.':'Đã tạo quỹ để dành.');
 }
 else if(type==='stash-movement'){
   const payload={kind:raw.kind,wallet_id:n(raw.wallet_id),amount:n(raw.amount),occurred_on:raw.occurred_on,note:raw.note||''};
   await api(`stashes/${raw.id}/movements`,{method:'POST',body:JSON.stringify(payload)});
   toast(raw.kind==='deposit'?'Đã dành riêng tiền; tổng tài sản giữ nguyên.':'Đã rút tiền về ví; tổng tài sản giữ nguyên.');
 }
 else if(type==='reconciliation'){const d=await api('reconciliation/check',{method:'POST',body:JSON.stringify({wallet_id:n(raw.wallet_id),counted_balance:n(raw.counted_balance),note:raw.note||''})});toast(d.difference===0?'Đối soát khớp số dư lúc kiểm đếm.':'Đã ghi nhận chênh lệch '+fmoney(Math.abs(d.difference))+' để kiểm tra lại.');}
 else if(type==='wallet-transfer'){await api('wallet-transfers',{method:'POST',body:JSON.stringify({from_wallet_id:n(raw.from_wallet_id),to_wallet_id:n(raw.to_wallet_id),amount:n(raw.amount),occurred_on:raw.occurred_on,note:raw.note||''})});toast('Đã chuyển tiền; tổng số dư không đổi!');}
 else if(type==='recurring'){const payload={title:raw.title.trim(),amount:n(raw.amount),category_id:n(raw.category_id),wallet_id:n(raw.wallet_id),note:raw.note||'',mode:raw.mode,remind_days:n(raw.remind_days)};if(!raw.id)Object.assign(payload,{kind:raw.kind,frequency:raw.frequency,start_on:raw.start_on});await api(raw.id?`recurring/${raw.id}`:'recurring',{method:raw.id?'PUT':'POST',body:JSON.stringify(payload)});toast(raw.id?'Đã lưu lịch định kỳ.':'Đã tạo lịch định kỳ.');}
 else if(type==='totp-begin'){await showTotpQr(raw.password);return;}
 else if(type==='totp-enable'){
   const result=await api('security/totp/enable',{method:'POST',body:JSON.stringify({code:raw.code.trim()})});
   state.user.totp_enabled=true;toast('Đã bật xác thực hai bước.');showRecoveryCodes(result.recovery_codes);return;
 }
 else if(type==='totp-disable'){
   await api('security/totp/disable',{method:'POST',body:JSON.stringify({password:raw.password,code:raw.code.trim()})});
   state.user.totp_enabled=false;toast('Đã tắt xác thực hai bước.');
 }
 else if(type==='category'){await api('categories',{method:'POST',body:JSON.stringify(raw)});toast('Đã tạo danh mục mới!');}
 else if(type==='debt'){const old=state.debtData?.items?.find(x=>String(x.id)===raw.id);const payload={name:raw.name.trim(),lender:raw.lender||'',direction:raw.direction||old?.direction||'payable',principal:n(raw.principal),interest_rate_pct:n(raw.interest_rate_pct),installment_count:n(raw.installment_count),due_date:raw.due_date||null,note:raw.note||''};await api(raw.id?`debts/${raw.id}`:'debts',{method:raw.id?'PUT':'POST',body:JSON.stringify(payload)});toast(raw.id?'Đã cập nhật khoản nợ!':'Đã thêm nợ gốc. Tiền thu sau này tự động trừ nợ!');}
 else if(type==='debt-pay'){await api(`debts/${raw.debt_id}/payments`,{method:'POST',body:JSON.stringify({amount:n(raw.amount),interest_amount:n(raw.interest_amount),paid_on:raw.paid_on,wallet_id:n(raw.wallet_id)})});toast('Đã ghi nhận gốc và lãi thực tế, số dư ví đã cập nhật!');}
 else if(type==='budget'){await api('budgets',{method:'PUT',body:JSON.stringify({...raw,amount:n(raw.amount),category_id:n(raw.category_id)})});toast('Đã lưu ngân sách!');}
 else if(type==='opening'){await api('opening-balance',{method:'PUT',body:JSON.stringify({opening_balance:n(raw.opening_balance)})});toast('Đã cập nhật số tiền gốc!');}
 else if(type==='user-add'){if(!strongPassword(raw.password))throw new Error('Mật khẩu chưa đáp ứng đủ 5 điều kiện an toàn.');checkPasswordConfirmation(raw.password,raw.confirm_password);await api('users',{method:'POST',body:JSON.stringify(raw)});toast('Đã tạo người dùng mới!');}
 else if(type==='user-edit'){await api(`users/${raw.id}`,{method:'PUT',body:JSON.stringify({email:raw.email,phone:raw.phone,address:raw.address,role:raw.role,active:raw.active==='true'})});toast('Đã cập nhật người dùng!');if(Number(raw.id)===state.user.id){state.user={...state.user,email:raw.email,phone:vietnamPhone(raw.phone),address:raw.address,profile_complete:true}}}
 else if(type==='user-delete'){await api(`users/${raw.id}`,{method:'DELETE',body:JSON.stringify({confirm_username:raw.confirm_username})});toast('Đã xóa người dùng và dữ liệu liên quan.');}
 else if(type==='profile'){state.user=await api('profile',{method:'PUT',body:JSON.stringify(raw)});toast('Đã cập nhật thông tin liên hệ!');}
 else if(type==='password'){if(!strongPassword(raw.new_password))throw new Error('Mật khẩu mới chưa đủ mạnh.');checkPasswordConfirmation(raw.new_password,raw.confirm_password);await api(raw.user_id?`users/${raw.user_id}/reset-password`:'change-password',{method:'POST',body:JSON.stringify(raw.user_id?{new_password:raw.new_password,confirm_password:raw.confirm_password}:{old_password:raw.old_password,new_password:raw.new_password,confirm_password:raw.confirm_password})});toast('Đã cập nhật mật khẩu!');if(raw.user_id&&Number(raw.user_id)===state.user.id){state.user=null;showAuth();return;}}
 else if(type==='month'){state.month=raw.month;state.transPage=1;}
 closeModal();await navigate(state.page);}
function beginTotp(){
 openModal('Bật xác thực hai bước','Xác nhận mật khẩu hiện tại trước khi tạo mã QR dùng một lần.',
 `<label>Mật khẩu hiện tại<input class="input" type="password" name="password" autocomplete="current-password" required/></label>`,
 'totp-begin','Tạo mã QR xác thực');
}
async function showTotpQr(password){
 const d=await api('security/totp/setup',{method:'POST',body:JSON.stringify({password})});
 openModal('Thiết lập Authenticator','Quét QR bằng ứng dụng Authenticator, sau đó nhập mã 6 số. Mã QR hết hạn sau 10 phút.',
 `<div class="totp-qr"><img src="${d.qr_data_url}" width="175" height="175" alt="Mã QR cấu hình TOTP"/></div><div class="simple-info">Nếu không quét QR được, nhập mã thủ công: <strong class="totp-secret">${esc(d.secret)}</strong></div><label>Mã xác nhận 6 số<input class="input" type="text" inputmode="numeric" name="code" pattern="[0-9]{6}" maxlength="6" autocomplete="one-time-code" required placeholder="123456"/></label>`,
 'totp-enable','Xác nhận và bật 2FA');
}
function showRecoveryCodes(codes){
 openModal('Lưu mã dự phòng','Hãy lưu 8 mã này vào nơi riêng tư. Chúng chỉ hiển thị một lần; mỗi mã chỉ dùng một lần.',
 `<div class="recovery-codes" aria-label="Mã khôi phục">${codes.map(code=>`<code>${esc(code)}</code>`).join('')}</div><div class="form-help">Không chụp hoặc gửi mã dự phòng cho người khác. Khi mất điện thoại, dùng một mã dự phòng để đăng nhập.</div>`,
 'recovery-done','Tôi đã lưu mã dự phòng');
}
async function listSecuritySessions(){
 const d=await api('security/sessions');
 const html=d.items.map(x=>`<div class="security-session"><div><b>${esc(x.user_agent)}</b><small>${esc(x.created_at.slice(0,16).replace('T',' '))} · Hết hạn ${esc(x.expires_at.slice(0,10))}</small></div>${x.current?'<span class="security-pill">Phiên hiện tại</span>':`<button type="button" class="btn btn-danger" data-action="security-revoke" data-id="${x.id}">Thu hồi</button>`}</div>`).join('');
 openModal('Các phiên đăng nhập','Có thể thu hồi những thiết bị không còn dùng. Phiên hiện tại vẫn được giữ.',
 `${html||'<div class="simple-info">Không có phiên đăng nhập.</div>'}<div class="security-actions"><button type="button" class="btn btn-danger" data-action="security-revoke-others">Đăng xuất tất cả phiên khác</button></div>`,
 'sessions-done','Đóng');
}
async function showSecurityIntegrity(){
 const d=await api('security/integrity');
 openModal('Kiểm tra tính nhất quán','Kiểm tra chỉ đọc, không điều chỉnh số dư hoặc lịch sử giao dịch.',
 `<div class="simple-info"><strong>${d.ok?'✓ Không phát hiện bất thường':'⚠ Phát hiện bất thường'}</strong><p>Đã kiểm tra ${d.checked_wallets} ví và ${d.checked_entries} giao dịch.</p></div>${d.issues.map(x=>`<p class="security-issue">${esc(x.detail)}</p>`).join('')}`,
 'integrity-done','Đóng');
}
async function clickAction(el){const action=el.dataset.action,id=Number(el.dataset.id);if(action.startsWith('pwa-')&&await window.MoneyFlowPWA?.handleAction?.(action))return;switch(action){case 'otp-back':state.loginTicket=null;showAuth('login');break;case 'totp-setup':await beginTotp();break;
case 'totp-disable':openModal('Tắt xác thực hai bước','Nhập mật khẩu hiện tại và mã TOTP hoặc mã dự phòng.',`<label>Mật khẩu hiện tại<input class="input" name="password" type="password" autocomplete="current-password" required/></label><label>Mã xác thực / mã dự phòng<input class="input" name="code" maxlength="32" required autocomplete="one-time-code"/></label>`,'totp-disable','Tắt 2FA');break;
case 'security-sessions':await listSecuritySessions();break;
case 'security-integrity':await showSecurityIntegrity();break;
case 'recon-reload':await navigate('reconciliation');toast('Đã tính lại báo cáo đối soát.');break;
case 'recon-find-entry':state.month=el.dataset.date?.slice(0,7)||state.month;state.transSearch=el.dataset.title||'';state.transPage=1;await navigate('transactions');break;
case 'security-revoke':if(confirm('Thu hồi phiên đăng nhập này?')){await api(`security/sessions/${id}`,{method:'DELETE',body:'{}'});toast('Đã thu hồi phiên.');await listSecuritySessions();}break;
case 'security-revoke-others':if(confirm('Đăng xuất tất cả phiên khác?')){const d=await api('security/sessions/revoke-others',{method:'POST',body:'{}'});toast(`Đã thu hồi ${d.revoked} phiên.`);await listSecuritySessions();}break;
case 'stash-add':stashModal();break;
case 'stash-edit':stashModal(state.stashData?.items?.find(f=>f.id===id));break;
case 'stash-deposit':stashMovementModal(state.stashData?.items?.find(f=>f.id===id),'deposit');break;
case 'stash-withdraw':stashMovementModal(state.stashData?.items?.find(f=>f.id===id),'withdraw');break;
case 'stash-delete':if(confirm('Xóa quỹ trống này? Quỹ có lịch sử sẽ được giữ để đối soát.')){await api(`stashes/${id}`,{method:'DELETE',body:'{}'});toast('Đã xóa quỹ.');await navigate('stashes')}break;
case 'savings-add':savingsModal();break;
case 'savings-edit':savingsModal(state.savingsData?.items?.find(g=>g.id===id));break;
case 'savings-deposit':savingsMoveModal(state.savingsData?.items?.find(g=>g.id===id),'deposit');break;
case 'savings-withdraw':savingsMoveModal(state.savingsData?.items?.find(g=>g.id===id),'withdraw');break;
case 'savings-delete':if(confirm('Xóa mục tiêu này? Chỉ xóa được khi số tiền đã dành riêng bằng 0.')){await api(`savings/${id}`,{method:'DELETE',body:'{}'});toast('Đã xóa mục tiêu.');await navigate('savings')}break;
case 'annual-excel': await downloadAnnual('xlsx');break;case 'annual-pdf': await downloadAnnual('pdf');break;case 'report-excel':await downloadReport('xlsx');break;case 'report-pdf':await downloadReport('pdf');break;case 'opening-modal':openingModal();break;case 'wallet-add':walletModal();break;case 'wallet-edit':walletModal(state.wallets.find(w=>w.id===id));break;case 'wallet-transfer':walletTransferModal();break;case 'wallet-toggle':if(confirm('Thay đổi trạng thái ví? Ví phải có số dư 0 khi khóa.')){await api(`wallets/${id}/toggle`,{method:'POST',body:'{}'});toast('Đã thay đổi trạng thái ví.');await navigate('wallets')}break;case 'wallet-transfer-undo':if(confirm('Hoàn tác lần chuyển tiền này? Ví nhận phải còn đủ số dư.')){await api(`wallet-transfers/${id}`,{method:'DELETE',body:'{}'});toast('Đã hoàn tác chuyển tiền.');await navigate('wallets')}break;case 'receipt-search':state.receiptSearch=$('#receipt-search')?.value?.trim()||'';state.receiptKind=$('#receipt-kind')?.value||'';state.receiptMonth=$('#receipt-month')?.value||'';state.receiptPage=1;await navigate('receipts');break;
case 'receipt-prev':state.receiptPage=Math.max(1,state.receiptPage-1);await navigate('receipts');break;
case 'receipt-next':state.receiptPage++;await navigate('receipts');break;
case 'receipt-open-entry':await navigate('transactions');await openReceiptsModal(Number(el.dataset.entry));break;
case 'receipt-preview-full':openModal('Xem trước hóa đơn','Ảnh được tải có xác thực, không lộ đường dẫn lưu trữ.',`<div class="receipt-preview" id="receipt-preview" hidden></div>`,'receipt-preview-view','Đóng');await receiptPreview(id);break;
case 'entry-receipts':await openReceiptsModal(id);break;
case 'receipt-download':await receiptDownload(id,el.dataset.name);break;
case 'receipt-preview':await receiptPreview(id);break;
case 'receipt-delete':if(confirm('Xóa vĩnh viễn chứng từ này? Giao dịch thu/chi sẽ không bị xóa.')){await api(`receipts/${id}`,{method:'DELETE',body:'{}'});toast('Đã xóa chứng từ.');if(state.page==='receipts'){await navigate('receipts')}else{const entryId=Number(el.dataset.entry);await navigate('transactions');await openReceiptsModal(entryId)}}break;
case 'close-modal':closeModal();break;case 'add-entry':entryModal();break;case 'add-income':entryModal(null,'income');break;case 'edit-entry':{const found=state.transData?.items?.find(x=>x.id===id);if(found)entryModal(found);break}case 'delete-entry':if(confirm('Xóa giao dịch này? Số dư sẽ được tính lại.')){await api(`transactions/${id}`,{method:'DELETE',body:'{}'});toast('Đã xóa giao dịch!');await navigate(state.page)}break;
case 'export':{const r=await fetch(`/api/export.csv?month=${encodeURIComponent(state.month)}`,{credentials:'same-origin'});if(!r.ok)throw Error('Không thể xuất dữ liệu.');const blob=await r.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`moneyflow-${state.month}.csv`;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('Đã xuất file CSV.');break}
case 'search-trans':state.transSearch=$('#search-trans')?.value?.trim()||'';state.transPage=1;await navigate('transactions');break;
case 'page-prev':state.transPage=Math.max(1,state.transPage-1);await navigate('transactions');break;case 'page-next':state.transPage++;await navigate('transactions');break;
case 'recurring-add':recurringModal();break;
case 'recurring-edit':recurringModal(state.recurringData?.items?.find(r=>r.id===id));break;
case 'recurring-toggle':await api(`recurring/${id}/toggle`,{method:'POST',body:'{}'});toast('Đã đổi trạng thái lịch.');await navigate('recurring');break;
case 'recurring-delete':if(confirm('Xóa lịch chưa có lịch sử này?')){await api(`recurring/${id}`,{method:'DELETE',body:'{}'});toast('Đã xóa lịch.');await navigate('recurring')}break;
case 'recurring-confirm':if(confirm('Ghi giao dịch cho kỳ đến hạn? Số dư ví và nợ gốc (nếu là khoản thu) sẽ được cập nhật.')){const result=await api(`recurring/${id}/confirm`,{method:'POST',body:'{}'});toast(result.auto_saved?`Đã ghi giao dịch, tự tích ${fmoney(result.auto_saved)} vào quỹ!`:result.debt_paid?`Đã ghi giao dịch và tự trả nợ ${fmoney(result.debt_paid)}!`:'Đã ghi giao dịch kỳ này!');await navigate('recurring')}break;
case 'recurring-skip':if(confirm('Bỏ qua kỳ đến hạn? Không cộng hoặc trừ số dư.')){await api(`recurring/${id}/skip`,{method:'POST',body:'{}'});toast('Đã bỏ qua kỳ này.');await navigate('recurring')}break;
case 'add-category':categoryModal();break;case 'toggle-category':await api(`categories/${id}/toggle`,{method:'POST',body:'{}'});toast('Đã cập nhật danh mục.');await navigate('categories');break;
case 'add-debt':debtModal();break;case 'edit-debt':debtModal(state.debtData?.items?.find(d=>d.id===id));break;case 'pay-debt':payDebtModal(state.debtData?.items?.find(d=>d.id===id));break;case 'debt-schedule':await debtScheduleModal(id);break;case 'delete-debt':if(confirm('Xóa khoản nợ chưa có thanh toán này?')){await api(`debts/${id}`,{method:'DELETE',body:'{}'});toast('Đã xóa khoản nợ.');await navigate('debts')}break;case 'undo-debt-payment':if(confirm('Hoàn tác khoản thanh toán này? Số dư ví sẽ được tính lại.')){await api(`debt-payments/${id}`,{method:'DELETE',body:'{}'});toast('Đã hoàn tác lần trả nợ.');await navigate('debts')}break;case 'add-budget':budgetModal();break;case 'edit-budget':budgetModal(state.budgetData?.find(x=>x.category_id===id));break;case 'change-password':changePasswordModal();break;
case 'edit-profile':profileModal();break;case 'add-user':userModal();break;case 'delete-user':deleteUserModal(state.userData?.find(x=>x.id===id));break;case 'edit-user':userModal(state.userData?.find(x=>x.id===id));break;case 'reset-password':changePasswordModal(state.userData?.find(x=>x.id===id));break;
case 'logout':{
  if(el.disabled)return;
  el.disabled=true;
  try {
    await api('logout',{method:'POST',body:'{}'});
    state.user=null;state.csrf=null;state.needsSetup=false;
    showAuth('login');toast('Đã đăng xuất an toàn.');
  } finally { el.disabled=false; }
  break;
}}}
document.addEventListener('click',async e=>{const b=e.target.closest('[data-action]'),link=e.target.closest('[data-page]');try{if(b){await clickAction(b);return}if(link)await navigate(link.dataset.page)}catch(err){toast(err.message,true)}});
document.addEventListener('submit',async e=>{
 if(e.target.id==='auth-form'){
   e.preventDefault();const error=$('#auth-error');error.textContent='';const raw=formObj(e.target);setBusy(true);
   try{const setup=state.authMode==='setup';if(setup&&!strongPassword(raw.password))throw new Error('Mật khẩu phải có tối thiểu 12 ký tự, chữ hoa, chữ thường, số và ký tự đặc biệt.');if(setup)checkPasswordConfirmation(raw.password,raw.confirm_password);
     const payload={username:raw.username,password:raw.password};if(setup)Object.assign(payload,{email:raw.email,phone:raw.phone,address:raw.address,confirm_password:raw.confirm_password});
     const result=await api(setup?'setup':'login',{method:'POST',body:JSON.stringify(payload)});
     if(result.two_factor_required){state.loginTicket=result.login_ticket;showAuth('otp');$('#otp-form [name="code"]').focus();return;}
     state.user=result.user;state.csrf=result.csrf_token;state.resetToken=null;showShell();await navigate('dashboard');if(setup)openingModal();if(!state.user.profile_complete)setTimeout(()=>profileModal(),180);
     toast(setup?'Tạo tài khoản thành công!':'Chào mừng quay trở lại!');
   }catch(err){error.textContent=err.message}finally{setBusy(false)}return;
 }
 if(e.target.id==='otp-form'){
   e.preventDefault();$('#otp-error').textContent='';setBusy(true);
   try{if(!state.loginTicket)throw Error('Yêu cầu xác thực đã hết hạn. Hãy đăng nhập lại.');
     const result=await api('login-otp',{method:'POST',body:JSON.stringify({login_ticket:state.loginTicket,code:formObj(e.target).code.trim()})});
     state.loginTicket=null;state.user=result.user;state.csrf=result.csrf_token;showShell();await navigate('dashboard');toast('Đã xác thực hai bước thành công.');}
   catch(ex){$('#otp-error').textContent=ex.message}finally{setBusy(false)}return;
 }
 if(e.target.id==='forgot-form'){
   e.preventDefault();$('#forgot-error').textContent='';$('#forgot-notice').textContent='';setBusy(true);
   try{const response=await api('forgot-password',{method:'POST',body:JSON.stringify({email:formObj(e.target).email})});$('#forgot-notice').textContent=response.message;}
   catch(err){$('#forgot-error').textContent=err.message}finally{setBusy(false)}return;
 }
 if(e.target.id==='reset-form'){
   e.preventDefault();$('#reset-error').textContent='';const raw=formObj(e.target);setBusy(true);
   try{if(!state.resetToken)throw Error('Không tìm thấy mã đặt lại mật khẩu.');if(!strongPassword(raw.new_password))throw Error('Mật khẩu mới phải đạt đủ 5 điều kiện bảo mật.');checkPasswordConfirmation(raw.new_password,raw.confirm_password);
     await api('reset-password-by-email',{method:'POST',body:JSON.stringify({token:state.resetToken,new_password:raw.new_password,confirm_password:raw.confirm_password})});state.resetToken=null;state.user=null;state.csrf=null;state.needsSetup=false;history.replaceState({},'','/');showAuth('login');toast('Đã đặt lại mật khẩu. Hãy đăng nhập bằng mật khẩu mới.');}
   catch(err){$('#reset-error').textContent=err.message}finally{setBusy(false)}return;
 }
 if(e.target.dataset.form){e.preventDefault();const err=$('#modal-error');if(err)err.textContent='';setBusy(true);try{await submitForm(e.target)}catch(ex){if(err)err.textContent=ex.message;else toast(ex.message,true)}finally{setBusy(false)}}
});
document.addEventListener('input',e=>{if(e.target.matches('[data-password-strength]')){updateStrength(e.target);updatePasswordConfirmation(e.target.dataset.passwordStrength,e.target.closest('form')||document);}else if(e.target.matches('[data-confirm-password]'))updatePasswordConfirmation(e.target.dataset.confirmPassword,e.target.closest('form')||document);});
$('#forgot-link').addEventListener('click',()=>{showAuth('forgot')});
$('#back-login-link').addEventListener('click',()=>{state.resetToken=null;history.replaceState({},'','/');showAuth('login')});
document.addEventListener('change',async e=>{if(e.target.id==='forecast-days'){const n=Number(e.target.value);if([30,60,90].includes(n)){state.forecastDays=n;await navigate('forecast')}return;}if(e.target.id==='annual-year'){const y=Number(e.target.value);if(Number.isInteger(y)&&y>=2000&&y<=new Date().getFullYear()){state.annualYear=y;await navigate('annual')}return;}if(e.target.id==='report-months'){const n=Number(e.target.value);if([3,6,12,24].includes(n)){state.reportMonths=n;await navigate('reports')}return;}if(e.target.id==='entry-kind')$('#entry-category-wrap').innerHTML=selectCats(e.target.value,null);if(e.target.id==='recurring-kind'){$('#recurring-category').innerHTML=state.categories.filter(c=>c.kind===e.target.value&&c.active).map(c=>`<option value="${c.id}">${esc(c.name)}</option>`).join('');}if(e.target.id==='filter-type'){state.transKind=e.target.value;state.transPage=1;await navigate('transactions')}if(e.target.id==='filter-wallet'){state.transWallet=e.target.value;state.transPage=1;await navigate('transactions')}if(e.target.id==='filter-category'){state.transCategory=e.target.value;state.transPage=1;await navigate('transactions')}});
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeModal();if(e.key==='Enter'&&e.target.id==='search-trans'){e.preventDefault();document.querySelector('[data-action="search-trans"]')?.click()}});
document.addEventListener('click',e=>{const toggle=e.target.closest('[data-peek]');if(toggle){const field=toggle.closest('.password-input')?.querySelector('input');if(field){field.type=field.type==='password'?'text':'password';toggle.setAttribute('aria-label',field.type==='password'?'Hiện mật khẩu':'Ẩn mật khẩu')}}});
$('#header-month-button').addEventListener('click',monthModal);
$('#menu-toggle').addEventListener('click',()=>{$('#sidebar').classList.add('open');$('#mobile-overlay').hidden=false});
$('#mobile-overlay').addEventListener('click',()=>{$('#sidebar').classList.remove('open');$('#mobile-overlay').hidden=true});
$('#sidebar-user').addEventListener('click',()=>navigate('settings'));
bootstrap();
