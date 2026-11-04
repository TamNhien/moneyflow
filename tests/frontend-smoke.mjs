// Offline dashboard smoke test: catches missing runtime functions in every page.
// Node.js only; no browser, Docker, database, or external dependencies required.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { createContext, runInContext } from 'node:vm';
import assert from 'node:assert/strict';

const source = readFileSync(resolve('frontend/app.js'), 'utf8');
const elements = new Map();
const selectors = new Map();
function element(key) {
  if (!elements.has(key)) {
    const obj = {
      innerHTML: '', textContent: '', hidden: false, disabled: false,
      value: '', required: false, dataset: {}, style: {},
      classList: { add() {}, remove() {}, toggle() {} },
      addEventListener() {}, setCustomValidity() {}, focus() {},
      removeAttribute() {}, remove() {}, append() {},
      querySelector: s => element(s), querySelectorAll: s => selectors.get(s) || []
    };
    elements.set(key, obj);
  }
  return elements.get(key);
}
const doc = {
  querySelector: s => element(s),
  querySelectorAll: s => selectors.get(s) || [],
  addEventListener() {}, createElement: () => element('__element')
};
const fakeUser = { id: 1, username: 'owner', role: 'admin', email: 'owner@example.com',
  phone: '0901234567', address: 'localhost', profile_complete: true };
const wallet = { id: 1, name: 'Ví chính', kind: 'cash', active: true,
  is_default: true, opening_balance: 100000, balance: 100000 };
const categories = [
  { id: 1, name: 'Ăn uống', kind: 'expense', color: '#6475ff', active: true },
  { id: 2, name: 'Lương', kind: 'income', color: '#12b886', active: true },
];
const entry = { id: 7, title: 'Ăn trưa', kind: 'expense', amount: 25000,
  occurred_on: '2026-11-02', category: 'Ăn uống', color: '#6475ff',
  category_id: 1, wallet_id: 1, note: 'Đã thanh toán', debt_paid: 0, receipt_count: 1 };
const dashboard = {
  balance: 100000, savings_reserved: 0, total_assets: 100000, opening_balance: 100000, total_opening_balance: 100000,
  total_income: 0, total_expense: 0, month_income: 0, month_expense: 0,
  month_count: 0, wallets: [wallet], debt_remaining: 0, receivable_remaining: 0,
  debt_paid: 0, net_worth: 100000, trend: [], categories: [], recent: [entry], budgets: [],
};
const debtData = { items: [], payments: [{id: 2, paid_on: '2026-11-02',
  debt: 'Nợ gốc', direction: 'payable', wallet_id: 1, mode: 'manual',
  amount: 10000, interest_amount: 0}], total_remaining: 0, total_paid: 10000,
  total_receivable_remaining: 0, total_receivable_collected: 0,
  total_interest_paid: 0, total_interest_received: 0 };
const visited = [];
const responses = {
  'me': { user: fakeUser, csrf_token: 'csrf-for-test' },
  'categories': categories,
  'wallets': { items: [wallet], transfers: [], total_balance: wallet.balance },
  'stashes': {items:[{id:1,name:'Tiền tích để dành',note:'Quỹ linh hoạt',auto_mode:'percent',auto_value:10,auto_wallet_id:1,saved_amount:50000,created_at:'2026-11-03'}],total_saved:50000,history:[]},
  'savings': {items: [{id:1,name:'Quỹ dự phòng',target_amount:200000,saved_amount:25000,remaining_amount:175000,progress_pct:12.5,complete:false,due_date:null,note:'Tích lũy',created_at:'2026-11-01'}],total_saved:25000,total_targets:200000,history:[]},
  'dashboard': {...dashboard, budget_alerts:[{category_id:1,category:'Ăn uống',color:'#6475ff',amount:1000,spent:950,status:'critical',at_risk:true,projected_over:500}]},
  'transactions': { items: [entry], total: 1, page: 1, pages: 1 },
  'reconciliation': {as_of:'2026-11-04T10:00:00Z', summary:{wallet_count:1,book_total:100000,checked_wallets:1,latest_discrepancies:0,integrity_issues:0,anomaly_candidates:1},ledger_total:100000, integrity_issues:[],sample_limited:false,
    wallets:[{id:1,name:'Ví chính',kind:'cash',active:true,book_balance:100000,last_check:{id:2,wallet_id:1,recorded_balance:100000,counted_balance:100000,difference:0,note:'Kiem tra',created_at:'2026-11-04T09:00:00Z'}}],
    anomalies:[{type:'duplicate_candidate',title:'Giao dịch có dấu hiệu trùng',description:'Hai giao dịch cùng ngày',entry_title:'Ăn trưa',occurred_on:'2026-11-02',entry_ids:[7,8],amount:25000,wallet_id:1}],
    checks:[{id:2,wallet_id:1,recorded_balance:100000,counted_balance:100000,difference:0,note:'Kiem tra',created_at:'2026-11-04T09:00:00Z'}]},
  'receipts':{items:[{id:5,entry_id:7,name:'hoa-don.png',mime_type:'image/png',size_bytes:2048,entry_title:'Ăn trưa',entry_kind:'expense',entry_amount:25000,occurred_on:'2026-11-02',created_at:'2026-11-04T09:00:00Z'}],total:1,page:1,pages:1},
  'transactions/7/receipts':{items:[{id:5,entry_id:7,name:'hoa-don.png',mime_type:'image/png',size_bytes:2048,created_at:'2026-11-04T09:00:00Z'}],max_files:8,max_bytes:8388608},
  'budgets': [], 'budgets/insights':{month:'2026-11',is_current_month:true,as_of:'2026-11-04',days_remaining:26,summary:{count:1,budget_total:1000,spent_total:950,critical_count:1,warning_count:0,at_risk_count:1},items:[{category_id:1,category:'Ăn uống',color:'#6475ff',amount:1000,spent:950,spent_percent:95,remaining:50,over_by:0,status:'critical',projected_spent:1400,projected_over:400,at_risk:true,scheduled_remaining:200,scheduled_count:1,safe_daily:0}],alerts:[{category_id:1,category:'Ăn uống',color:'#6475ff',amount:1000,spent:950,status:'critical',at_risk:true,projected_over:400}]}, 'debts': debtData, 'users': [fakeUser],
  'recurring': {items:[],history:[]}, 'reminders': {items:[],overdue_count:0,upcoming_count:0},
  'reports': {end_month:'2026-11',from_month:'2025-12',to_month:'2026-11',months_count:12,totals:{income:100,expense:40,debt_paid:0,debt_collected:0,net_cash:60},snapshot:{cash_balance:100000,payable:0,receivable:0,net_worth:100000},selected_month:{income:100,expense:40,debt_paid:0,debt_collected:0,net_cash:60},comparison:{income:{current:100,previous:0,difference:100,percentage:null},expense:{current:40,previous:0,difference:40,percentage:null},net_cash:{current:60,previous:0,difference:60,percentage:null}},monthly:Array.from({length:12},(_,i)=>({month:`2026-${String(i+1).padStart(2,'0')}`,income:100,expense:40,debt_paid:0,debt_collected:0,net_cash:60})),categories:[{name:'Ăn uống',color:'#6475ff',amount:40}],transfer_count:0},
  'reports/annual': {year:2026,as_of:'2026-11-04',monthly:Array.from({length:11},(_,i)=>({month:`2026-${String(i+1).padStart(2,'0')}`,income:1000,expense:300,debt_paid:100,debt_collected:0,net_cash:600,available:100000+i*600,reserved:1000,assets:101000+i*600,receivable:0,payable:0,net_worth:101000+i*600})),totals:{income:11000,expense:3300,debt_paid:1100,debt_collected:0,net_cash:6600},comparison:{income:{current:11000,previous:10000,difference:1000,percentage:10},expense:{current:3300,previous:4000,difference:-700,percentage:-17.5}},previous_year:2025,closing:{available:106000,reserved:1000,receivable:0,payable:0,net_worth:107000},disclaimer:'Reconstructed estimate'},
  'forecast': {as_of:'2026-11-03',through:'2026-12-03',horizon_days:30,start_balance:100000,end_balance:45000,net_change:-55000,income_gross:30000,expense:75000,debt_allocated:10000,min_total_balance:45000,first_shortfall_on:null,risk_wallet_count:0,overdue_rules:[],inactive_wallet_rules:[],payable_remaining_scenario:0,wallets:[{id:1,name:'Ví chính',active:true,start_balance:100000,projected_balance:45000,lowest_balance:45000,first_shortfall_on:null}],timeline:Array.from({length:31},(_,i)=>({date:`2026-11-${String(i+3).padStart(2,'0')}`,balance:100000-i*1000,income:0,expense:0,debt_paid:0,shortfall:false})),total_events:2,events:[{due_on:'2026-11-20',title:'Lương',wallet_name:'Ví chính',kind:'income',mode:'manual',amount:30000,allocated_to_debt:10000,net_wallet_delta:20000}] ,truncated_events:false,assumptions:['Chỉ dự báo lịch định kỳ đang hoạt động.']},
  'audit': [{ id: 1, at: '2026-11-02T10:00:00Z', actor: 'owner', action: 'login', detail: 'OK' }],
};
async function fetchMock(path) {
  const key = path.replace(/^\/api\//, '').split('?')[0];
  visited.push(key);
  assert.ok(Object.hasOwn(responses, key), `Unexpected API route: ${key}`);
  return { ok: true, status: 200, headers: {get: () => 'application/json'},
    json: async () => responses[key] };
}
const context = createContext({
  document: doc,
  window: {location: {hostname: 'localhost', href: 'http://localhost:8765/', search: '', pathname: '/' }},
  history: { state: null, replaceState() {} },
  fetch: fetchMock, URL, URLSearchParams, Date, Intl, Math, Number, String,
  Array, Object, RegExp, Error, Promise, setTimeout: () => 1, clearTimeout() {},
  console,
});
runInContext(source, context, {filename: 'frontend/app.js'});

// Wait until bootstrap's initial async navigation finishes.
for (let i = 0; i < 20 && !element('#page-content').innerHTML.includes('Xin chào'); ++i) {
  await new Promise(resolve => setTimeout(resolve, 0));
}
assert.match(element('#page-content').innerHTML, /Xin chào/, 'Initial dashboard failed');
assert.ok(visited.includes('categories') && visited.includes('wallets'), 'Lookup data was not fetched');

const pages = [
  ['annual', 'Thống kê tài chính năm'], ['dashboard', 'Xin chào'], ['forecast','Dự báo dòng tiền'], ['savings', 'Mục tiêu tiết kiệm'], ['stashes', 'Tiền tích để dành'], ['reports', 'Báo cáo &amp; phân tích tài chính'], ['recurring', 'Giao dịch định kỳ'], ['wallets', 'Ví &amp; tài khoản'],
  ['transactions', 'Quản lý giao dịch'], ['receipts', 'Hóa đơn &amp; chứng từ'], ['reconciliation', 'Đối soát &amp; kiểm tra tài chính'], ['budgets', 'Ngân sách thông minh'],
  ['debts', 'Quản lý nợ chuyên sâu'], ['categories', 'Danh mục thu'],
  ['settings', 'Cài đặt tài khoản'], ['users', 'Quản lý người dùng'],
  ['audit', 'Nhật ký hoạt động'],
];
for (const [page, expected] of pages) {
  await runInContext(`navigate(${JSON.stringify(page)})`, context);
  const html = element('#page-content').innerHTML;
  assert.ok(html.includes(expected), `${page}: page heading not found; got ${html.slice(0, 300)}`);
  assert.ok(!html.includes('Không thể tải dữ liệu'), `${page}: runtime exception: ${html}`);
  if (page === 'transactions' || page === 'debts') {
    assert.ok(html.includes('Ví chính'), `${page}: wallet name not rendered`);
  }
}
assert.equal(visited.filter(x => x === 'categories').length, pages.length + 1);
assert.equal(visited.filter(x => x === 'wallets').length >= pages.length + 1, true);
console.log(`Frontend smoke PASS: bootstrap + ${pages.length} pages (mocked API, no database).`);
// Recurring form and reminder badge are essential new surfaces in v1.0.14.
await runInContext('navigate("recurring")', context);
assert.match(element('#page-content').innerHTML, /Tạo lịch định kỳ/);
assert.ok(element('#reminder-count').hidden, 'Empty reminders should not display a badge');
runInContext('recurringModal()', context);
const recurringForm = element('#modal-root').innerHTML;
assert.match(recurringForm, /name="frequency"/);
assert.match(recurringForm, /name="mode"/);
assert.match(recurringForm, /name="wallet_id"/);
assert.match(recurringForm, /name="remind_days"/);
console.log('Recurring modal smoke PASS: frequency, mode, wallet, reminder settings.');

await runInContext('navigate("reports")', context);
assert.match(element('#page-content').innerHTML,/Xuất Excel/);
assert.match(element('#page-content').innerHTML,/Xuất PDF/);
assert.match(element('#page-content').innerHTML,/Tài sản ròng/);
console.log('Financial reports smoke PASS: chart, filters, export controls, net worth.');

assert.match(element('#page-content').innerHTML, /data-action="report-excel"/);
assert.match(element('#page-content').innerHTML, /data-action="report-pdf"/);
assert.match(element('#page-content').innerHTML, /\.XLSX/);
assert.match(element('#page-content').innerHTML, /\.PDF/);
await runInContext('navigate("annual")',context);
assert.match(element('#page-content').innerHTML, /data-action="annual-excel"/);
assert.match(element('#page-content').innerHTML, /data-action="annual-pdf"/);
assert.match(element('#page-content').innerHTML, /annual-plot/);
assert.match(element('#page-content').innerHTML, /Reconstructed estimate/);
console.log('Annual analytics smoke PASS: net worth history, table, selector, XLSX and PDF.');
await runInContext('navigate("settings")',context);
assert.match(element('#page-content').innerHTML,/Bật xác thực 2 bước/);
assert.match(element('#page-content').innerHTML,/Phiên đăng nhập/);
assert.match(element('#page-content').innerHTML,/Cài ứng dụng/);
assert.match(element('#page-content').innerHTML,/data-action="pwa-notify-on"/);
assert.match(element('#page-content').innerHTML,/data-action="pwa-notify-off"/);
console.log('Security & export smoke PASS: TOTP setup, sessions and distinct Excel/PDF buttons.');

assert.ok(visited.includes('savings'), 'Savings goals screen not fetched');
await runInContext('navigate("savings")', context);
assert.match(element('#page-content').innerHTML, /Quỹ dự phòng/);

await runInContext('savingsModal(state.savingsData.items[0])', context);
assert.match(element('#modal-root').innerHTML, /Sửa mục tiêu tiết kiệm/);
await runInContext('savingsMoveModal(state.savingsData.items[0], "deposit")', context);
assert.match(element('#modal-root').innerHTML, /Góp tiền vào mục tiêu/);
await runInContext('savingsMoveModal(state.savingsData.items[0], "withdraw")', context);
assert.match(element('#modal-root').innerHTML, /Rút tiền về ví/);
console.log('Savings goals modal smoke PASS: create/edit, deposit and withdraw.');

await runInContext('navigate("forecast")',context);
assert.match(element('#page-content').innerHTML,/forecast-chart/);
assert.match(element('#page-content').innerHTML,/Số dư dự kiến cuối kỳ/);
assert.match(element('#page-content').innerHTML,/name=""|forecast-days/);
console.log('Forecast smoke PASS: 30-day projection cards, SVG chart and wallet risk panels.');

await runInContext('navigate("stashes")',context);
assert.match(element('#page-content').innerHTML,/Tiền tích để dành/);
assert.match(element('#page-content').innerHTML,/data-action="stash-deposit"/);
assert.match(element('#page-content').innerHTML, /Tự góp 10% thu nhập/);
assert.match(element('#page-content').innerHTML,/data-action="stash-withdraw"/);
await runInContext('stashModal(state.stashData.items[0])',context);
assert.match(element('#modal-root').innerHTML, /name="auto_mode"/);
assert.match(element('#modal-root').innerHTML, /name="auto_value"/);
assert.match(element('#modal-root').innerHTML, /name="auto_wallet_id"/);
assert.match(element('#modal-root').innerHTML,/Sửa quỹ tích lũy/);
await runInContext('stashMovementModal(state.stashData.items[0], "deposit")',context);
assert.match(element('#modal-root').innerHTML,/Góp vào tiền để dành/);
await runInContext('stashMovementModal(state.stashData.items[0], "withdraw")',context);
assert.match(element('#modal-root').innerHTML,/Rút tiền về ví/);
console.log('Stash funds smoke PASS: dashboard navigation, fund lifecycle, deposit and withdraw.');

await runInContext('navigate("budgets")',context);
assert.match(element('#page-content').innerHTML,/Cảnh báo 70%/);
assert.match(element('#page-content').innerHTML,/Cuối tháng dự kiến/);
assert.match(element('#page-content').innerHTML,/Có thể chi\/ngày còn lại/);
await runInContext('navigate("dashboard")',context);
assert.match(element('#page-content').innerHTML,/Cảnh báo ngân sách/);
assert.ok(visited.includes('budgets/insights'), 'Smart budget endpoint was not fetched');
console.log('Smart budget smoke PASS: 70/90/100 warnings, month projection, safe daily estimate, dashboard alerts.');

await runInContext('navigate("transactions")',context);
assert.match(element('#page-content').innerHTML,/data-action="entry-receipts"/);
assert.match(element('#page-content').innerHTML,/Chứng từ \(1\)/);
await runInContext('openReceiptsModal(7)',context);
assert.match(element('#modal-root').innerHTML,/hoa-don\.png/);
assert.match(element('#modal-root').innerHTML,/data-form="receipt-upload"/);
assert.match(element('#modal-root').innerHTML,/name="receipt_file"/);
console.log('Receipt UI smoke PASS: transaction action, owner file list and upload form.');

await runInContext('navigate("receipts")',context);
assert.match(element('#page-content').innerHTML,/Kho chứng từ/);
assert.match(element('#page-content').innerHTML,/hoa-don\.png/);
assert.match(element('#page-content').innerHTML,/data-action="receipt-search"/);
console.log('Receipt overview smoke PASS: list, search, filters and ownership-scoped metadata.');
