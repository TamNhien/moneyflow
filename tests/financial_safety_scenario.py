"""Isolated black-box scenario, run against a fresh SQLite file or ephemeral PG CI DB."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from backend.app import app, SessionLocal, Entry, FinancialOperation, TransactionRevision, Wallet, wallet_balance


def expect(response, status=200):
    assert response.status_code == status, f'{response.status_code}: {response.text}'
    return response.json()


def main():
    with TestClient(app) as client:
        info = dict(username='owner', email='owner@example.com', phone='0901234567',
                    address='TP Ho Chi Minh', password='SecurePassword@12345',
                    confirm_password='SecurePassword@12345')
        assert client.get('/api/setup-status').json()['needs_setup']
        csrf = expect(client.post('/api/setup', json=info))['csrf_token']
        base = {'X-CSRF-Token': csrf}

        def req(method, path, body=None, key=None):
            headers={**base, **({'X-Idempotency-Key':key} if key else {})}
            return client.request(method, path, json=body if body is not None else {}, headers=headers)

        expect(req('PUT','/api/opening-balance', {'opening_balance':5000}))
        wallet = client.get('/api/wallets').json()['items'][0]['id']
        cats=client.get('/api/categories').json()
        expense=next(x['id'] for x in cats if x['kind']=='expense')
        payload={'title':'Chi thử an toàn','kind':'expense','amount':1000,
                 'occurred_on':date.today().isoformat(),'wallet_id':wallet,
                 'category_id':expense,'note':'Một giao dịch'}
        # An insufficient-balance attempt must leave no success key receipt.
        failed={**payload, 'amount':6000, 'title':'Không đủ tiền'}
        failed_key='financial-test-retry-after-fail'
        assert req('POST','/api/transactions',failed,failed_key).status_code==409
        with SessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(FinancialOperation))==0
        transaction_key='financial-test-create-00001'
        created=expect(req('POST','/api/transactions',payload,transaction_key))
        assert expect(req('POST','/api/transactions',payload,transaction_key))==created
        assert req('POST','/api/transactions',{**payload,'amount':1500},transaction_key).status_code==409
        assert req('POST','/api/transactions',payload,'invalid').status_code==422
        assert client.get('/api/wallets').json()['items'][0]['balance']==4000
        eid=created['id']
        updated={**payload,'amount':700,'note':'Đã sửa'}
        assert expect(req('PUT',f'/api/transactions/{eid}',updated,'financial-test-edit-000001')) == \
               expect(req('PUT',f'/api/transactions/{eid}',updated,'financial-test-edit-000001'))
        assert client.get('/api/wallets').json()['items'][0]['balance']==4300
        assert expect(req('DELETE',f'/api/transactions/{eid}',key='financial-test-delete-0001')) == \
               expect(req('DELETE',f'/api/transactions/{eid}',key='financial-test-delete-0001'))
        assert client.get('/api/wallets').json()['items'][0]['balance']==5000
        history=expect(client.get(f'/api/transactions/revisions?entry_id={eid}'))['items']
        assert [r['operation'] for r in history]==['delete','update','create'],history
        assert history[0]['before']['amount']==700 and history[0]['after'] is None
        assert history[1]['before']['amount']==1000 and history[1]['after']['amount']==700

        target=expect(req('POST','/api/wallets',{'name':'Ví phụ','kind':'bank','opening_balance':0}))['id']
        transfer={'from_wallet_id':wallet,'to_wallet_id':target,'amount':700,
                  'occurred_on':date.today().isoformat(),'note':'Chuyển thử'}
        first=expect(req('POST','/api/wallet-transfers',transfer,'financial-test-transfer-01'))
        assert first==expect(req('POST','/api/wallet-transfers',transfer,'financial-test-transfer-01'))
        assert client.get('/api/wallets').json()['total_balance']==5000

        fund=expect(req('POST','/api/stashes',{'name':'Để dành','note':'','auto_mode':'off','auto_value':0}))['id']
        movement={'kind':'deposit','wallet_id':wallet,'amount':500,
                  'occurred_on':date.today().isoformat(),'note':'Tích lũy thử'}
        saved=expect(req('POST',f'/api/stashes/{fund}/movements',movement,'financial-test-stash-00001'))
        assert saved==expect(req('POST',f'/api/stashes/{fund}/movements',movement,'financial-test-stash-00001'))
        assert saved['saved_amount']==500

        debt=expect(req('POST','/api/debts',{
            'name':'Khoản vay', 'lender':'Người thân', 'principal':1200,
            'direction':'payable', 'interest_rate_pct':0,
            'installment_count':1,'due_date':None,'note':''}))['id']
        pay={'wallet_id':wallet,'amount':500,'interest_amount':0,'paid_on':date.today().isoformat()}
        paid=expect(req('POST',f'/api/debts/{debt}/payments',pay,'financial-test-debt-000001'))
        assert paid==expect(req('POST',f'/api/debts/{debt}/payments',pay,'financial-test-debt-000001'))
        assert paid['remaining']==700

        # Multiple requests with DISTINCT keys must not overdraw the same wallet.
        # The account row lock is effective in PostgreSQL (SQLite is not a row-lock test).
        expensive={**payload,'amount':2500,'title':'Chi đồng thời'}
        def concurrent(i):
            return req('POST','/api/transactions',expensive,f'financial-concurrent-key-{i:04d}').status_code
        with ThreadPoolExecutor(max_workers=2) as executor:
            codes=list(executor.map(concurrent,range(2)))
        assert sorted(codes)==[200,409],codes

        with SessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(Entry).where(Entry.title=='Chi thử an toàn'))==0
            assert db.scalar(select(func.count()).select_from(Entry).where(Entry.title=='Chi đồng thời'))==1
            assert db.scalar(select(func.count()).select_from(TransactionRevision).where(TransactionRevision.entry_id==eid))==3
            assert db.scalar(select(func.count()).select_from(FinancialOperation))==7
            w=db.get(Wallet,wallet)
            assert wallet_balance(db,w)>=0

        # Legacy behavior is opt-in since v1.0.28.
        expect(req('PUT','/api/settings/auto-debt',{'enabled':True}))
        # One income may repay principal AND reserve funds. A retry must not
        # repeat either side effect, even when all allocations are automatic.
        expect(req('PUT',f'/api/stashes/{fund}', {
            'name':'Để dành','note':'','auto_mode':'percent','auto_value':20,'auto_wallet_id':None}))
        income_cat=next(x['id'] for x in cats if x['kind']=='income')
        income={'title':'Thu nhập có phân bổ','kind':'income','amount':1000,
                'category_id':income_cat,'wallet_id':wallet,
                'occurred_on':date.today().isoformat(),'note':''}
        credited=expect(req('POST','/api/transactions',income,'financial-test-income-0001'))
        assert credited['debt_paid']==700 and credited['auto_saved']==60,credited
        assert expect(req('POST','/api/transactions',income,'financial-test-income-0001'))==credited
        revisions=expect(client.get(f"/api/transactions/revisions?entry_id={credited['id']}"))['items']
        assert revisions[0]['after']['allocated_debt_principal']==700
        assert revisions[0]['after']['allocated_stash']==60
        with SessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(FinancialOperation))==8

        # The second user cannot read the first user's edit history.
        expect(req('POST','/api/users',{
            'username':'other','email':'other@example.com','phone':'0987654321',
            'address':'TP Ho Chi Minh','password':'SecurePassword@12345','confirm_password':'SecurePassword@12345'}))
        with TestClient(app) as other:
            login=expect(other.post('/api/login',json={'username':'other','password':'SecurePassword@12345'}))
            assert other.get('/api/transactions/revisions').json()['items']==[]
            assert other.get(f'/api/transactions/revisions?entry_id={eid}').json()['items']==[]
        print('FINANCIAL SAFETY SCENARIO PASS')


if __name__=='__main__':
    main()
