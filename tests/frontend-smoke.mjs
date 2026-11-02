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
  category_id: 1, wallet_id: 1, note: 'Đã thanh toán', debt_paid: 0 };
const dashboard = {
  balance: 100000, opening_balance: 100000, total_opening_balance: 100000,
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
  'dashboard': dashboard,
  'transactions': { items: [entry], total: 1, page: 1, pages: 1 },
  'budgets': [], 'debts': debtData, 'users': [fakeUser],
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
  ['dashboard', 'Xin chào'], ['wallets', 'Ví &amp; tài khoản'],
  ['transactions', 'Quản lý giao dịch'], ['budgets', 'Ngân sách chi tiêu'],
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
