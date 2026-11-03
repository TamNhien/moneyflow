"""Local SQLite smoke tests for money handling, auth, access control and reporting."""
import os
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DATABASE_URL'] = 'sqlite:///' + str(ROOT / ('test-'+uuid4().hex+'.db'))
from cryptography.fernet import Fernet
os.environ['TOTP_ENCRYPTION_KEY'] = Fernet.generate_key().decode('ascii')
from backend.app import app


@pytest.fixture(scope='module')
def client():
    with TestClient(app) as c:
        yield c
    Path(os.environ['DATABASE_URL'].replace('sqlite:///','')).unlink(missing_ok=True)


def credentials(username='owner'):
    return {'username':username,'email':f'{username}@example.com','phone':'0901234567','address':'123 Nguyen Hue, Quan 1, TP HCM','password':'SecurePassword@12345','confirm_password':'SecurePassword@12345'}


def auth_post(c, path, payload=None, method='post', csrf=None):
    headers={'x-csrf-token':csrf} if csrf else {}
    return c.request(method.upper(),path,json=payload if payload is not None else {},headers=headers)


def test_full_flow(client):
    assert client.get('/api/setup-status').json()['needs_setup'] is True
    res=auth_post(client,'/api/setup',credentials()); assert res.status_code==200,res.text
    token=res.json()['csrf_token']; assert 'httponly' in res.headers['set-cookie'].lower()
    assert client.get('/api/setup-status').json()['needs_setup'] is False
    assert client.get('/api/me').json()['user']['email']=='owner@example.com'
    assert client.get('/api/me').json()['user']['profile_complete'] is True
    assert auth_post(client,'/api/setup',credentials()).status_code==403
    c=client.get('/api/categories').json(); exp=next(x for x in c if x['kind']=='expense'); inc=next(x for x in c if x['kind']=='income')
    assert auth_post(client,'/api/opening-balance',{'opening_balance':1_000_000},method='put').status_code==403
    assert auth_post(client,'/api/opening-balance',{'opening_balance':1_000_000},csrf=token,method='put').status_code==200
    expense={'title':'Đổ xăng','kind':'expense','amount':200_000,'occurred_on':'2026-11-01','category_id':exp['id'],'note':'Chi tiết'}
    r=auth_post(client,'/api/transactions',expense,csrf=token); assert r.status_code==200,r.text
    exp_id=r.json()['id']
    income={'title':'Thưởng','kind':'income','amount':350_000,'occurred_on':'2026-11-01','category_id':inc['id'],'note':''}
    r=auth_post(client,'/api/transactions',income,csrf=token);assert r.status_code==200,r.text
    inc_id=r.json()['id']
    dash=client.get('/api/dashboard?month=2026-11').json()
    assert (dash['balance'],dash['month_expense'],dash['month_income'])==(1_150_000,200_000,350_000)
    assert len(dash['trend'])==6
    too_much={**expense,'amount':1_300_000}
    assert auth_post(client,'/api/transactions',too_much,csrf=token).status_code==409
    assert auth_post(client,'/api/transactions/'+str(exp_id),{**too_much,'amount':1_400_000},csrf=token,method='put').status_code==409
    assert client.get('/api/dashboard?month=2026-11').json()['balance']==1_150_000
    assert auth_post(client,'/api/budgets',{'category_id':exp['id'],'amount':150_000,'month':'2026-11'},csrf=token,method='put').status_code==200
    assert client.get('/api/dashboard?month=2026-11').json()['overspent_budgets']==1
    assert client.get('/api/transactions?month=2026-11&q=%C4%90%E1%BB%95').json()['total']==1
    assert client.get('/api/export.csv?month=2026-11').content.startswith(b'\xef\xbb\xbf')
    assert auth_post(client,'/api/transactions/'+str(exp_id),csrf=token,method='delete').status_code==200
    assert client.get('/api/dashboard?month=2026-11').json()['balance']==1_350_000
    assert auth_post(client,'/api/opening-balance',{'opening_balance':0},csrf=token,method='put').status_code==200
    assert auth_post(client,'/api/transactions/'+str(inc_id),csrf=token,method='delete').status_code==200
    assert client.get('/api/dashboard?month=2026-11').json()['balance']==0
    added = auth_post(client,'/api/users',{**credentials('member'),'phone':'+84776905506'},csrf=token)
    assert added.status_code==200,added.text
    assert added.json()['phone']=='0776905506'
    assert auth_post(client,'/api/users',{**credentials('another'),'email':'member@example.com'},csrf=token).status_code==409
    users=client.get('/api/users').json();member=next(x for x in users if x['username']=='member')
    assert member['phone']=='0776905506'
    edited=auth_post(client,f'/api/users/{member["id"]}',{'phone':'0084933445566'},csrf=token,method='put')
    assert edited.status_code==200,edited.text
    assert edited.json()['phone']=='0933445566'
    # Full account lifecycle and temporary brute-force protection.
    t=auth_post(client,'/api/users',credentials('trash'),csrf=token).json()
    for _ in range(5):
        assert auth_post(client,'/api/login',{'username':'trash','password':'WrongPassword@2026'}).status_code==401
    assert auth_post(client,'/api/login',{'username':'trash','password':'SecurePassword@12345'}).status_code==429
    assert auth_post(client,f"/api/users/{t['id']}",{'confirm_username':'wrong'},csrf=token,method='delete').status_code==422
    assert auth_post(client,f"/api/users/{t['id']}",{'confirm_username':'trash'},csrf=token,method='delete').status_code==200
    assert not any(x['username']=='trash' for x in client.get('/api/users').json())
    assert auth_post(client,'/api/users/1',{'role':'member'},csrf=token,method='put').status_code==409
    assert auth_post(client,f'/api/users/{member["id"]}/reset-password',{'new_password':'AnotherPassword@567','confirm_password':'AnotherPassword@567'},csrf=token).status_code==200
    assert client.get('/api/audit').status_code==200
    assert auth_post(client,'/api/logout',csrf=token).status_code==200
    assert client.get('/api/me').status_code==401
    r=auth_post(client,'/api/login',{'username':'member','password':'AnotherPassword@567'})
    assert r.status_code==200,r.text
    t2=r.json()['csrf_token']
    assert client.get('/api/users').status_code==403
    assert client.get('/api/dashboard?month=2026-11').json()['balance']==0
    assert auth_post(client,'/api/opening-balance',{'opening_balance':220000},csrf=t2,method='put').status_code==200
    assert client.get('/api/dashboard?month=2026-11').json()['balance']==220000
    assert auth_post(client,'/api/change-password',{'old_password':'AnotherPassword@567','new_password':'BetterPassword@987','confirm_password':'BetterPassword@987'},csrf=t2).status_code==200
    assert auth_post(client,'/api/logout',csrf=t2).status_code==200
    assert auth_post(client,'/api/login',{'username':'member','password':'AnotherPassword@567'}).status_code==401
    assert auth_post(client,'/api/login',{'username':'member','password':'BetterPassword@987'}).status_code==200


def test_basic_headers(client):
    resp=client.get('/')
    assert resp.status_code==200
    assert 'moneyflow' in resp.text
    assert 'id="header-logout"' in resp.text
    assert 'data-action="logout"' in resp.text
    assert resp.headers['x-frame-options']=='DENY'
    resp=client.post('/api/login',data='username=foo',headers={'Content-Type':'application/x-www-form-urlencoded'})
    assert resp.status_code==415
    resp=client.post('/api/login',json={'username':'owner','password':'No'},headers={'Origin':'https://attack.example'})
    assert resp.status_code==403


def test_email_recovery(client,monkeypatch):
    from backend import app as app_module
    sent=[]
    monkeypatch.setenv('SMTP_HOST','smtp.example.com')
    monkeypatch.setenv('SMTP_FROM','noreply@example.com')
    monkeypatch.setattr(app_module,'send_reset_email',lambda email, token: sent.append((email,token)))
    assert client.get('/api/recovery-config').json()['email_configured'] is True
    r=auth_post(client,'/api/forgot-password',{'email':'not-exists@example.com'})
    assert r.status_code==200 and not sent
    r=auth_post(client,'/api/forgot-password',{'email':'member@example.com'})
    assert r.status_code==200 and len(sent)==1
    from backend.app import SessionLocal,PasswordResetToken,User
    from sqlalchemy import select
    with SessionLocal() as db:
        r=db.scalar(select(PasswordResetToken))
        assert r and r.token_hash!=sent[0][1]
        assert len(r.token_hash)==64
    assert auth_post(client,'/api/reset-password-by-email',{'token':'badtoken'*5,'new_password':'ResetStrong@2026AB','confirm_password':'ResetStrong@2026AB'}).status_code==422
    assert auth_post(client,'/api/reset-password-by-email',{'token':sent[0][1],'new_password':'simple','confirm_password':'simple'}).status_code==422
    r=auth_post(client,'/api/reset-password-by-email',{'token':sent[0][1],'new_password':'ResetStrong@2026AB','confirm_password':'ResetStrong@2026AB'})
    assert r.status_code==200,r.text
    assert auth_post(client,'/api/reset-password-by-email',{'token':sent[0][1],'new_password':'AnotherStrong@2026','confirm_password':'AnotherStrong@2026'}).status_code==422
    assert auth_post(client,'/api/login',{'username':'member','password':'ResetStrong@2026AB'}).status_code==200
    assert auth_post(client,'/api/forgot-password',{'email':'member@example.com'}).status_code==200
    assert len(sent)==1  # cooldown
    with SessionLocal() as db:
        u=db.scalar(select(User).where(User.username=='member'))
        assert u.password_hash.startswith('$argon2id$')
        assert 'ResetStrong@2026AB' not in u.password_hash


def test_legacy_profile(client):
    # Existing accounts retain transactions and can add contact info without a destructive migration.
    from backend.app import SessionLocal,User,ph
    with SessionLocal() as db:
        db.add(User(username='legacy',display_name='Legacy',password_hash=ph.hash('SecurePassword@12345'),role='member'))
        db.commit()
    res=auth_post(client,'/api/login',{'username':'legacy','password':'SecurePassword@12345'})
    assert res.status_code==200
    csrf=res.json()['csrf_token']
    assert res.json()['user']['profile_complete'] is False
    data={'email':'legacy@example.com','phone':'0988888888','address':'456 Le Loi, Thanh pho HCM','current_password':'WrongPass!'}
    assert auth_post(client,'/api/profile',data,method='put',csrf=csrf).status_code==403
    res=auth_post(client,'/api/profile',{**data,'current_password':'SecurePassword@12345'},method='put',csrf=csrf)
    assert res.status_code==200 and res.json()['profile_complete'] is True
    assert res.json()['email']=='legacy@example.com'


def test_mismatched_password_confirmation(client):
    # Setup and admin user creation are guarded by the same Pydantic mismatch check.
    assert auth_post(client, '/api/users', {**credentials('mismatched'),'confirm_password':'WrongPassword@123'}, csrf=None).status_code in (403, 401)
    from backend.app import NewUser, ChangePassword, CompleteReset, ResetPassword
    from pydantic import ValidationError
    invalid_cases=[
        (NewUser,{**credentials('a_user'),'confirm_password':'Mismatch123@'}),
        (ChangePassword,{'old_password':'Current@123AA','new_password':'NewSecure@123AA','confirm_password':'Different@123AA'}),
        (CompleteReset,{'token':'somevalidrandomplaceholder12345','new_password':'NewSecure@123AA','confirm_password':'Different@123AA'}),
        (ResetPassword,{'new_password':'NewSecure@123AA','confirm_password':'Different@123AA'}),
    ]
    for schema, payload in invalid_cases:
        with pytest.raises(ValidationError):
            schema.model_validate(payload)
    for schema, payload in invalid_cases:
        with pytest.raises(ValidationError):
            schema.model_validate({key:value for key,value in payload.items() if key!='confirm_password'})


def test_brand_assets_and_https_local_link(client, monkeypatch):
    from backend import app as app_module
    assert 'logo.svg' in client.get('/').text
    for name in ('logo.svg', 'favicon.svg'):
        r=client.get('/'+name)
        assert r.status_code==200
        assert b'<svg' in r.content and b'linearGradient' in r.content
    icon=client.get('/apple-touch-icon.png')
    assert icon.status_code==200 and icon.content[:8] == b'\x89PNG\r\n\x1a\n'
    monkeypatch.setenv('APP_BASE_URL', 'https://127.0.0.1:8765')
    from email.message import EmailMessage
    from unittest.mock import MagicMock
    class FakeSMTP:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def ehlo(self): pass
        def starttls(self, **kwargs): pass
        def login(self, *args): pass
        def send_message(self, message):
            assert 'https://127.0.0.1:8765/reset?token=sample' in message.get_content()
    monkeypatch.setenv('SMTP_HOST','localhost')
    monkeypatch.setenv('SMTP_FROM','moneyflow@example.com')
    monkeypatch.setattr(app_module.smtplib, 'SMTP',lambda *args,**kwargs:FakeSMTP())
    app_module.send_reset_email('user@example.com','sample')


def test_debts_auto_repayment_and_consistency(client):
    """New income repays oldest debts first, while the ledger remains reversible."""
    # Authenticate owner and create a distinct profile with no previous balance.
    r=auth_post(client,'/api/login',{'username':'owner','password':'SecurePassword@12345'})
    assert r.status_code==200,r.text
    admin_csrf=r.json()['csrf_token']
    r=auth_post(client,'/api/users',credentials('debtor'),csrf=admin_csrf)
    assert r.status_code==200,r.text
    r=auth_post(client,'/api/login',{'username':'debtor','password':'SecurePassword@12345'})
    assert r.status_code==200,r.text
    csrf=r.json()['csrf_token']
    categories=client.get('/api/categories').json()
    inc=next(c for c in categories if c['kind']=='income')
    exp=next(c for c in categories if c['kind']=='expense')
    base={'name':'No goc 1','lender':'Ngan hang','principal':1_000_000,'due_date':None,'note':''}
    assert auth_post(client,'/api/debts',base).status_code==403
    d1=auth_post(client,'/api/debts',base,csrf=csrf)
    assert d1.status_code==200,d1.text
    id1=d1.json()['id']
    d2=auth_post(client,'/api/debts',{**base,'name':'No goc 2','principal':500_000},csrf=csrf)
    assert d2.status_code==200,d2.text
    id2=d2.json()['id']
    assert client.get('/api/dashboard?month=2026-11').json()['balance']==0
    def income(amount):
        return {'title':'Thu nhap', 'kind':'income','amount':amount,'category_id':inc['id'], 'occurred_on':'2026-11-02','note':''}
    def spend(amount):
        return {'title':'Mua hang', 'kind':'expense','amount':amount,'category_id':exp['id'], 'occurred_on':'2026-11-02','note':''}
    r=auth_post(client,'/api/transactions',income(1_200_000),csrf=csrf)
    assert r.status_code==200,r.text
    first_id=r.json()['id']
    assert r.json()['debt_paid']==1_200_000
    d=client.get('/api/debts').json()
    assert (d['total_remaining'],d['total_paid'])==(300_000,1_200_000)
    assert [p['debt_id'] for p in sorted(d['payments'],key=lambda p:p['id'])]==[id1,id2]
    assert client.get('/api/dashboard?month=2026-11').json()['balance']==0
    r=auth_post(client,'/api/transactions',income(500_000),csrf=csrf)
    assert r.status_code==200,r.text
    second_id=r.json()['id']
    assert r.json()['debt_paid']==300_000
    dashboard=client.get('/api/dashboard?month=2026-11').json()
    assert (dashboard['balance'],dashboard['debt_remaining'],dashboard['debt_paid'],dashboard['month_income']) == (200_000,0,1_500_000,1_700_000)
    assert auth_post(client,'/api/transactions',spend(200_001),csrf=csrf).status_code==409
    assert auth_post(client,'/api/transactions',spend(80_000),csrf=csrf).status_code==200
    # Editing an income reverses only that income's earlier allocation and reapplies it.
    assert auth_post(client,f'/api/transactions/{second_id}',income(350_000),csrf=csrf,method='put').status_code==409
    r=auth_post(client,f'/api/transactions/{second_id}',income(400_000),csrf=csrf,method='put')
    assert r.status_code==200,r.text
    assert client.get('/api/dashboard?month=2026-11').json()['balance']==20_000
    assert client.get('/api/debts').json()['total_remaining']==0

    # Undo income: it should restore the debt it paid; the 80,000 expense
    # would then cause an overdraft, so the whole operation must roll back.
    r=auth_post(client,f'/api/transactions/{second_id}',csrf=csrf,method='delete')
    assert r.status_code==409,r.text
    assert client.get('/api/debts').json()['total_remaining']==0
    # Remove expense and delete income, so the debt is restored atomically.
    expense_id=client.get('/api/transactions?kind=expense').json()['items'][0]['id']
    assert auth_post(client,f'/api/transactions/{expense_id}',csrf=csrf,method='delete').status_code==200
    assert auth_post(client,f'/api/transactions/{second_id}',csrf=csrf,method='delete').status_code==200
    assert client.get('/api/debts').json()['total_remaining']==300_000
    assert client.get('/api/dashboard?month=2026-11').json()['balance']==0
    assert auth_post(client,f'/api/debts/{id1}',csrf=csrf,method='delete').status_code==409
    # A new loan is not retroactively paid by income entered before it existed.
    new=auth_post(client,'/api/debts',{**base,'name':'No moi','principal':100_000},csrf=csrf)
    assert new.status_code==200,new.text
    new_id=new.json()['id']
    assert client.get('/api/debts').json()['total_remaining']==400_000
    # Dedicated manual payment lowers both available balance and principal.
    assert auth_post(client,'/api/opening-balance',{'opening_balance':60_000},csrf=csrf,method='put').status_code==200
    r=auth_post(client,f'/api/debts/{new_id}/payments',{'amount':30_000,'paid_on':'2026-11-02'},csrf=csrf)
    assert r.status_code==200,r.text
    assert client.get('/api/dashboard?month=2026-11').json()['balance']==30_000
    assert client.get('/api/debts').json()['total_remaining']==370_000
    assert auth_post(client,f'/api/debts/{new_id}/payments',{'amount':31_000,'paid_on':'2026-11-02'},csrf=csrf).status_code==409
    manual=next(p for p in client.get('/api/debts').json()['payments'] if p['mode']=='manual')
    assert auth_post(client,f'/api/debt-payments/{manual["id"]}',csrf=csrf,method='delete').status_code==200
    assert client.get('/api/dashboard?month=2026-11').json()['balance']==60_000
    assert client.get('/api/debts').json()['total_remaining']==400_000
    # User isolation: another user cannot edit the debtor's debt.
    login_other=auth_post(client,'/api/login',{'username':'member','password':'ResetStrong@2026AB'})
    assert login_other.status_code==200,login_other.text
    other_csrf=client.get('/api/me').json()['csrf_token']
    assert auth_post(client,f'/api/debts/{new_id}/payments',{'amount':1},csrf=other_csrf).status_code==404
    # Admin deletion removes debts and debt-payment dependents before entries.
    login_admin=auth_post(client,'/api/login',{'username':'owner','password':'SecurePassword@12345'})
    assert login_admin.status_code==200
    admin_csrf=login_admin.json()['csrf_token']
    r=auth_post(client,'/api/users',{'username':'noop'},csrf=admin_csrf)
    assert r.status_code==422
    debtor=next(u for u in client.get('/api/users').json() if u['username']=='debtor')
    assert auth_post(client,f"/api/users/{debtor['id']}",{'confirm_username':'debtor'},csrf=admin_csrf,method='delete').status_code==200


def test_legacy_phone_without_database_migration():
    from backend.app import User, local_vietnam_phone, normalized_phone, user_json
    from datetime import datetime, timezone
    assert normalized_phone('+84 776 905 506') == '0776905506'
    assert normalized_phone('84776905506') == '0776905506'
    assert normalized_phone('0084776905506') == '0776905506'
    assert normalized_phone('0776905506') == '0776905506'
    assert normalized_phone('+12025550131') == '+12025550131'
    assert local_vietnam_phone('+84776905506') == '0776905506'
    # Existing PostgreSQL rows are not rewritten; API makes the old prefix readable.
    legacy = User(username='legacy-phone', phone='+84776905506', email='legacy-phone@example.com',
                  address='123 Nguyen Hue, Quan 1', created_at=datetime.now(timezone.utc))
    assert user_json(legacy)['phone'] == '0776905506'


def test_wallets_transfer_income_expense_and_debt(client):
    # A separate tenant avoids relying on the balances of previous tests.
    owner=auth_post(client,'/api/login',{'username':'owner','password':'SecurePassword@12345'})
    assert owner.status_code==200,owner.text
    owner_csrf=owner.json()['csrf_token']
    made=auth_post(client,'/api/users',credentials('walletmember'),csrf=owner_csrf)
    assert made.status_code==200,made.text
    member=auth_post(client,'/api/login',{'username':'walletmember','password':'SecurePassword@12345'})
    assert member.status_code==200,member.text
    csrf=member.json()['csrf_token']
    w=client.get('/api/wallets').json()
    assert len(w['items'])==1 and w['items'][0]['is_default']
    cash_id=w['items'][0]['id']
    assert auth_post(client,'/api/opening-balance',{'opening_balance':1000},csrf=csrf,method='put').status_code==200
    created=auth_post(client,'/api/wallets',{'name':'Ngân hàng VCB','kind':'bank','opening_balance':200},csrf=csrf)
    assert created.status_code==200,created.text
    bank_id=created.json()['id']
    assert client.get('/api/wallets').json()['total_balance']==1200
    transfer={'from_wallet_id':cash_id,'to_wallet_id':bank_id,'amount':600,'occurred_on':'2026-11-02','note':'Chuyển vốn'}
    assert auth_post(client,'/api/wallet-transfers',{**transfer,'amount':1001},csrf=csrf).status_code==409
    r=auth_post(client,'/api/wallet-transfers',transfer,csrf=csrf)
    assert r.status_code==200,r.text
    transfer_id=r.json()['id']
    w=client.get('/api/wallets').json()
    assert [(v['balance']) for v in w['items']]==[400,800]
    dash=client.get('/api/dashboard?month=2026-11').json()
    assert dash['balance']==1200 and dash['month_income']==0 and dash['month_expense']==0
    cs=client.get('/api/categories').json()
    ci=next(x['id'] for x in cs if x['kind']=='income')
    ce=next(x['id'] for x in cs if x['kind']=='expense')
    def transaction(kind,amount,wallet_id):
        return {'title':'Test giao dịch','kind':kind,'amount':amount,'category_id':ci if kind=='income' else ce,'occurred_on':'2026-11-02','wallet_id':wallet_id}
    assert auth_post(client,'/api/transactions',transaction('expense',500,cash_id),csrf=csrf).status_code==409
    assert auth_post(client,'/api/transactions',transaction('expense',500,bank_id),csrf=csrf).status_code==200
    assert client.get('/api/wallets').json()['total_balance']==700
    assert auth_post(client,'/api/wallet-transfers/'+str(transfer_id),csrf=csrf,method='delete').status_code==409
    d=auth_post(client,'/api/debts',{'name':'Nợ xe','principal':250},csrf=csrf)
    assert d.status_code==200,d.text
    r=auth_post(client,'/api/transactions',transaction('income',300,bank_id),csrf=csrf)
    assert r.status_code==200 and r.json()['debt_paid']==250,r.text
    w=client.get('/api/wallets').json()['items']
    assert [(x['balance']) for x in w]==[400,350]
    assert client.get('/api/dashboard?month=2026-11').json()['balance']==750
    assert client.get('/api/debts').json()['total_remaining']==0
    assert auth_post(client,'/api/transactions',transaction('expense',500,cash_id),csrf=csrf).status_code==409
    # Reassigning an existing expense to the cash wallet cannot overdraw it.
    expense_id=client.get('/api/transactions?kind=expense').json()['items'][0]['id']
    assert auth_post(client,f'/api/transactions/{expense_id}',transaction('expense',500,cash_id),csrf=csrf,method='put').status_code==409
    assert client.get('/api/wallets').json()['total_balance']==750
    assert auth_post(client,f'/api/wallets/{bank_id}/toggle',csrf=csrf).status_code==409
    assert auth_post(client,f'/api/wallets/{cash_id}/toggle',csrf=csrf).status_code==409
    assert auth_post(client,f'/api/wallets/{bank_id}',{'name':'VCB mới','kind':'bank'},csrf=csrf,method='put').status_code==200
    assert client.get('/api/wallets').json()['items'][1]['name']=='VCB mới'
    csv=client.get('/api/export.csv?month=2026-11').content.decode('utf-8-sig')
    assert 'Ví tiền' in csv and 'VCB mới' in csv
    # Another account cannot withdraw from a wallet it does not own.
    assert auth_post(client,'/api/login',{'username':'owner','password':'SecurePassword@12345'}).status_code==200
    r=client.get('/api/wallets').json()
    assert all(w['id']!=bank_id for w in r['items'])
    owner_csrf=client.get('/api/me').json()['csrf_token']
    assert auth_post(client,'/api/wallet-transfers',transfer,csrf=owner_csrf).status_code==422
    assert auth_post(client,'/api/transactions',transaction('income',100,bank_id),csrf=owner_csrf).status_code==422


def test_advanced_receivables_installments_interest_and_wallet_cashflow(client):
    # Isolated account ensures debt figures from older tests do not mix in.
    root_login=auth_post(client,'/api/login',{'username':'owner','password':'SecurePassword@12345'})
    assert root_login.status_code==200,root_login.text
    root_csrf=root_login.json()['csrf_token']
    unique='loan'+uuid4().hex[:10]
    r=auth_post(client,'/api/users',credentials(unique),csrf=root_csrf)
    assert r.status_code==200,r.text
    r=auth_post(client,'/api/login',{'username':unique,'password':'SecurePassword@12345'})
    assert r.status_code==200,r.text
    csrf=r.json()['csrf_token']
    assert auth_post(client,'/api/opening-balance',{'opening_balance':1000000},method='put',csrf=csrf).status_code==200
    payable={'name':'Vay mua xe','lender':'Ngân hàng','principal':200000,'direction':'payable',
             'interest_rate_pct':'12.00','installment_count':4,'due_date':'2026-12-01','note':''}
    receivable={'name':'Cho bạn vay','lender':'Bạn A','principal':90000,'direction':'receivable',
                'interest_rate_pct':'6.00','installment_count':3,'due_date':'2027-01-31','note':''}
    p=auth_post(client,'/api/debts',payable,csrf=csrf);assert p.status_code==200,p.text;pid=p.json()['id']
    r=auth_post(client,'/api/debts',receivable,csrf=csrf);assert r.status_code==200,r.text;rid=r.json()['id']
    schedule=client.get(f'/api/debts/{pid}/schedule');assert schedule.status_code==200,schedule.text
    sched=schedule.json()['schedule']
    assert len(sched)==4 and sched[0]['principal']==50000 and sched[0]['estimated_interest']==2000
    assert sched[-1]['due_date']=='2027-03-01'
    r2=client.get(f'/api/debts/{rid}/schedule').json()['schedule']
    assert r2[1]['due_date']=='2027-02-28' and r2[2]['due_date']=='2027-03-31'
    assert auth_post(client,'/api/debts', {**receivable,'installment_count':2,'due_date':None},csrf=csrf).status_code==422
    assert auth_post(client,'/api/debts',{**payable,'interest_rate_pct':101},csrf=csrf).status_code==422
    assert auth_post(client,'/api/debts',{**payable,'installment_count':361},csrf=csrf).status_code==422
    paid=auth_post(client,f'/api/debts/{pid}/payments',{'amount':50000,'interest_amount':5000,'paid_on':'2026-11-01'},csrf=csrf)
    assert paid.status_code==200,paid.text
    rec=auth_post(client,f'/api/debts/{rid}/payments',{'amount':20000,'interest_amount':1000,'paid_on':'2026-11-01'},csrf=csrf)
    assert rec.status_code==200,rec.text
    d=client.get('/api/debts').json()
    assert d['total_remaining']==150000 and d['total_receivable_remaining']==70000
    assert d['total_interest_paid']==5000 and d['total_interest_received']==1000
    dash=client.get('/api/dashboard?month=2026-11').json()
    assert dash['balance']==966000 and dash['net_worth']==886000  # 966k - 150k + 70k
    assert dash['receivable_remaining']==70000
    cats=client.get('/api/categories').json();inc=next(c for c in cats if c['kind']=='income')
    entry={'title':'Lương','kind':'income','amount':100000,'category_id':inc['id'],
           'occurred_on':'2026-11-02'}
    add=auth_post(client,'/api/transactions',entry,csrf=csrf)
    assert add.status_code==200 and add.json()['debt_paid']==100000,add.text
    d=client.get('/api/debts').json()
    assert d['total_remaining']==50000 and d['total_receivable_remaining']==70000
    assert client.get('/api/dashboard?month=2026-11').json()['balance']==966000
    # Even though a receivable remains, extra income is free cash after payables clear.
    add2=auth_post(client,'/api/transactions',{**entry,'amount':80000},csrf=csrf)
    assert add2.status_code==200 and add2.json()['debt_paid']==50000,add2.text
    assert client.get('/api/dashboard?month=2026-11').json()['balance']==996000
    d=client.get('/api/debts').json();assert d['total_remaining']==0 and d['total_receivable_remaining']==70000
    # Terms freeze once any principal payment is recorded.
    changed=auth_post(client,f'/api/debts/{rid}',{**receivable,'direction':'payable'},csrf=csrf,method='put')
    assert changed.status_code==409
    # Another user cannot query this user's schedule.
    r=auth_post(client,'/api/login',{'username':'owner','password':'SecurePassword@12345'})
    assert r.status_code==200
    assert client.get(f'/api/debts/{rid}/schedule').status_code==404
    # Login restores isolated user's view and rollback of a receivable decreases cash.
    r=auth_post(client,'/api/login',{'username':unique,'password':'SecurePassword@12345'});csrf=r.json()['csrf_token']
    receivable_payment=next(x for x in client.get('/api/debts').json()['payments'] if x['debt_id']==rid)
    und=auth_post(client,f'/api/debt-payments/{receivable_payment["id"]}',csrf=csrf,method='delete')
    assert und.status_code==200,und.text
    assert client.get('/api/dashboard?month=2026-11').json()['balance']==975000
    # Previously booked payable is unaffected by receivable rollback.
    assert client.get('/api/debts').json()['total_remaining']==0
    # A receivable rollback must not make a wallet negative.
    collected=auth_post(client,f'/api/debts/{rid}/payments',{'amount':30000,'interest_amount':0,'paid_on':'2026-11-02'},csrf=csrf)
    assert collected.status_code==200,collected.text
    payment=next(x for x in client.get('/api/debts').json()['payments'] if x['debt_id']==rid)
    expense=next(x for x in client.get('/api/categories').json() if x['kind']=='expense')
    used=auth_post(client,'/api/transactions',{'title':'Mua hàng','kind':'expense','amount':1000000,
        'category_id':expense['id'],'occurred_on':'2026-11-02'},csrf=csrf)
    assert used.status_code==200,used.text
    failed=auth_post(client,f'/api/debt-payments/{payment["id"]}',csrf=csrf,method='delete')
    assert failed.status_code==409,failed.text
    assert client.get('/api/dashboard?month=2026-11').json()['balance']==5000
    assert auth_post(client,f'/api/transactions/{used.json()["id"]}',csrf=csrf,method='delete').status_code==200
    assert auth_post(client,f'/api/debt-payments/{payment["id"]}',csrf=csrf,method='delete').status_code==200
    assert client.get('/api/dashboard?month=2026-11').json()['balance']==975000


def test_recurring_schedule_reminders_and_balances(client):
    """Daily/monthly dates, confirmation, idempotence, cash and debt integrity."""
    from datetime import date, timedelta
    from types import SimpleNamespace
    from backend.app import process_auto_recurring, scheduled_date

    login = auth_post(client,'/api/login',{'username':'owner','password':'SecurePassword@12345'})
    assert login.status_code==200,login.text
    owner_token=login.json()['csrf_token']
    username='schedule'+uuid4().hex[:8]
    created=auth_post(client,'/api/users',credentials(username),csrf=owner_token)
    assert created.status_code==200,created.text
    login=auth_post(client,'/api/login',{'username':username,'password':'SecurePassword@12345'})
    assert login.status_code==200,login.text
    csrf=login.json()['csrf_token']
    assert auth_post(client,'/api/opening-balance',{'opening_balance':50000},method='put',csrf=csrf).status_code==200
    wallet=client.get('/api/wallets').json()['items'][0]
    cats=client.get('/api/categories').json()
    expense=next(x for x in cats if x['kind']=='expense')
    income=next(x for x in cats if x['kind']=='income')
    now=date.today().isoformat()
    schedule={'title':'Tiền điện','kind':'expense','amount':20000,'category_id':expense['id'],
              'wallet_id':wallet['id'],'start_on':now,'frequency':'monthly',
              'remind_days':7,'mode':'manual','note':'Lặp lại tháng'}
    bad=auth_post(client,'/api/recurring',{**schedule,'amount':0},csrf=csrf)
    assert bad.status_code==422
    registered=auth_post(client,'/api/recurring',schedule,csrf=csrf)
    assert registered.status_code==200,registered.text
    rule_id=registered.json()['id']
    assert registered.json()['next_due']==now
    assert client.get('/api/reminders').json()['items'][0]['ref_id']==rule_id
    result=auth_post(client,f'/api/recurring/{rule_id}/confirm',csrf=csrf)
    assert result.status_code==200,result.text
    entry_id=result.json()['entry_id']
    assert client.get('/api/dashboard?month='+now[:7]).json()['balance']==30000
    assert auth_post(client,f'/api/recurring/{rule_id}/confirm',csrf=csrf).status_code==409
    assert auth_post(client,f'/api/recurring/{rule_id}',csrf=csrf,method='delete').status_code==409
    runs=client.get('/api/recurring').json()['history']
    assert len([r for r in runs if r['rule_id']==rule_id])==1
    # Posting is recorded even if the generated entry is later deleted.
    assert auth_post(client,f'/api/transactions/{entry_id}',csrf=csrf,method='delete').status_code==200
    assert client.get('/api/dashboard?month='+now[:7]).json()['balance']==50000
    assert client.get('/api/recurring').json()['history'][0]['status']=='deleted'
    # An expense cannot be posted if it overdraws the associated wallet.
    pending={**schedule,'title':'Tiền thuê nhà','amount':90000,'frequency':'weekly'}
    p=auth_post(client,'/api/recurring',pending,csrf=csrf)
    assert p.status_code==200,p.text
    rid=p.json()['id']
    assert auth_post(client,f'/api/recurring/{rid}/confirm',csrf=csrf).status_code==409
    assert client.get('/api/recurring').json()['items'][0]['next_due']==now
    assert auth_post(client,f'/api/recurring/{rid}/skip',csrf=csrf).status_code==200
    assert client.get('/api/recurring').json()['items'][0]['processed_count']==1
    assert auth_post(client,f'/api/recurring/{rid}',csrf=csrf,method='delete').status_code==409
    # Rule edits do not alter its schedule; pausing hides upcoming reminders.
    changes={'title':'Điện nước','amount':19000,'category_id':expense['id'],
             'wallet_id':wallet['id'],'note':'Test', 'mode':'manual', 'remind_days':3}
    assert auth_post(client,f'/api/recurring/{rid}',changes,csrf=csrf,method='put').status_code==200
    assert auth_post(client,f'/api/recurring/{rid}/toggle',csrf=csrf).status_code==200
    # Automatic income pays down payable principal exactly once.
    debt=auth_post(client,'/api/debts',{'name':'Nợ thẻ','lender':'Ngân hàng','principal':35000,
         'direction':'payable','interest_rate_pct':0,'installment_count':1,'note':''},csrf=csrf)
    assert debt.status_code==200,debt.text
    auto={**schedule,'title':'Lương','kind':'income','amount':60000,
          'category_id':income['id'],'mode':'auto','frequency':'monthly'}
    response=auth_post(client,'/api/recurring',auto,csrf=csrf)
    assert response.status_code==200,response.text
    auto_id=response.json()['id']
    process_auto_recurring()
    assert client.get('/api/dashboard?month='+now[:7]).json()['balance']==75000
    assert client.get('/api/debts').json()['total_remaining']==0
    process_auto_recurring()
    assert len([x for x in client.get('/api/recurring').json()['history'] if x['rule_id']==auto_id])==1
    assert client.get('/api/dashboard?month='+now[:7]).json()['balance']==75000
    assert auth_post(client,f'/api/recurring/{auto_id}/confirm',csrf=csrf).status_code==409
    assert auth_post(client,'/api/recurring',{**auto,'start_on':(date.today()-timedelta(days=1)).isoformat()},csrf=csrf).status_code==422
    # Rules with no executed occurrence can be deleted; unrelated rules remain.
    temp=auth_post(client,'/api/recurring',{**schedule,'start_on':(date.today()+timedelta(days=10)).isoformat()},csrf=csrf)
    assert temp.status_code==200,temp.text
    temp_id=temp.json()['id']
    assert auth_post(client,f'/api/recurring/{temp_id}',csrf=csrf,method='delete').status_code==200
    assert temp_id not in [x['id'] for x in client.get('/api/recurring').json()['items']]
    # Only the owner can modify a rule (no cross-account leakage).
    login=auth_post(client,'/api/login',{'username':'owner','password':'SecurePassword@12345'})
    assert login.status_code==200
    csrf_other=login.json()['csrf_token']
    assert not any(x['id']==auto_id for x in client.get('/api/recurring').json()['items'])
    assert auth_post(client,f'/api/recurring/{auto_id}/toggle',csrf=csrf_other).status_code==404
    # Month clamping preserves the original anchor day (31st -> Feb 28 -> Mar 31).
    obj=SimpleNamespace(start_on=date(2025,1,31),next_index=1,frequency='monthly')
    assert scheduled_date(obj)==date(2025,2,28)
    obj.next_index=2
    assert scheduled_date(obj)==date(2025,3,31)


def test_reports_cashflow_excel_pdf_and_isolation(client):
    """Report transfers are internal; debt cashflow is counted exactly once."""
    from io import BytesIO
    from openpyxl import load_workbook
    owner=auth_post(client,'/api/login',{'username':'owner','password':'SecurePassword@12345'})
    assert owner.status_code==200,owner.text
    t=owner.json()['csrf_token']
    user=credentials('reporter')
    created=auth_post(client,'/api/users',user,csrf=t)
    assert created.status_code==200,created.text
    login=auth_post(client,'/api/login',{'username':'reporter','password':user['password']})
    assert login.status_code==200,login.text
    token=login.json()['csrf_token']
    assert auth_post(client,'/api/opening-balance',{'opening_balance':1_000_000},method='put',csrf=token).status_code==200
    cats=client.get('/api/categories').json();expense=next(c for c in cats if c['kind']=='expense');income=next(c for c in cats if c['kind']=='income')
    default=client.get('/api/wallets').json()['items'][0]['id']
    created_wallet=auth_post(client,'/api/wallets',{'name':'Tài khoản ngân hàng','kind':'bank','opening_balance':500000},csrf=token)
    assert created_wallet.status_code==200,created_wallet.text
    bank=created_wallet.json()['id']
    assert auth_post(client,'/api/wallet-transfers',{'from_wallet_id':default,'to_wallet_id':bank,'amount':25000,'occurred_on':'2026-11-01'},csrf=token).status_code==200
    payable=auth_post(client,'/api/debts',{'name':'Khoản vay A','direction':'payable','principal':80000},csrf=token).json()['id']
    receivable=auth_post(client,'/api/debts',{'name':'Tiền cho bạn mượn','direction':'receivable','principal':50000},csrf=token).json()['id']
    i=auth_post(client,'/api/transactions',{'kind':'income','title':'Lương', 'amount':60000,
                  'category_id':income['id'],'wallet_id':default,'occurred_on':'2026-11-02'},csrf=token)
    assert i.status_code==200,i.text
    assert i.json()['debt_paid']==60000
    assert auth_post(client,f'/api/debts/{payable}/payments',{'amount':20000,'interest_amount':0,'wallet_id':default,'paid_on':'2026-11-02'},csrf=token).status_code==200
    assert auth_post(client,f'/api/debts/{receivable}/payments',{'amount':10000,'interest_amount':1000,'wallet_id':bank,'paid_on':'2026-11-02'},csrf=token).status_code==200
    bad_title='=HYPERLINK("http://evil.test","bad")'
    assert auth_post(client,'/api/transactions',{'kind':'expense','title':bad_title,
           'amount':40000,'category_id':expense['id'],'wallet_id':default,'occurred_on':'2026-11-02'},csrf=token).status_code==200
    res=client.get('/api/reports?end=2026-11&months=3')
    assert res.status_code==200,res.text
    data=res.json()
    assert len(data['monthly'])==3
    assert data['totals']['income']==60000 and data['totals']['expense']==40000
    assert data['totals']['debt_paid']==80000
    assert data['totals']['debt_collected']==11000
    assert data['totals']['net_cash']==-49000
    assert data['snapshot']['cash_balance']==1451000
    assert data['snapshot']['receivable']==40000
    assert data['snapshot']['payable']==0
    assert data['snapshot']['net_worth']==1491000
    assert data['transfer_count']==1 and data['transfer_amount']==25000
    assert data['comparison']['income']['percentage'] is None
    assert data['categories'][0]['amount']==40000
    assert 'transactions' not in data and 'payments' not in data
    assert client.get('/api/reports?end=bad').status_code==422
    assert client.get('/api/reports?end=2026-11&months=500').status_code==422
    excel=client.get('/api/reports.xlsx?end=2026-11&months=3')
    assert excel.status_code==200 and excel.content[:2]==b'PK'
    assert 'no-store' in excel.headers.get('cache-control','')
    wb=load_workbook(BytesIO(excel.content),data_only=False)
    assert wb.sheetnames==['Tổng quan','Theo tháng','Danh mục chi','Các ví','Giao dịch','Thanh toán nợ']
    ws=wb['Giao dịch'];danger=next(row[2] for row in ws.iter_rows(min_row=2,values_only=True) if 'HYPERLINK' in row[2])
    assert danger.startswith("'=HYPERLINK")
    assert all(cell.data_type!='f' for row in ws for cell in row)
    pdf=client.get('/api/reports.pdf?end=2026-11&months=3')
    assert pdf.status_code==200,pdf.text[:200] if pdf.status_code!=200 else ''
    assert pdf.content.startswith(b'%PDF-') and len(pdf.content)>12000
    # Account isolation: original admin account cannot read 'reporter' finances.
    assert auth_post(client,'/api/login',{'username':'owner','password':'SecurePassword@12345'}).status_code==200
    other=client.get('/api/reports?end=2026-11&months=3').json()
    assert other['totals']['income']!=60000
    assert all(c['amount']!=40000 for c in other['categories'])


def test_two_factor_authenticator_and_session_control(client):
    from backend.app import totp_value, totp_decrypt, SessionLocal, User
    from time import time
    from sqlalchemy import select
    from fastapi.testclient import TestClient

    admin_login=auth_post(client,'/api/login',{'username':'owner','password':'SecurePassword@12345'})
    assert admin_login.status_code==200,admin_login.text
    t=admin_login.json()['csrf_token']
    account=credentials('secureacct')
    assert auth_post(client,'/api/users',account,csrf=t).status_code==200
    owner_client=TestClient(app)
    try:
        login=auth_post(owner_client,'/api/login',{'username':'secureacct','password':account['password']})
        assert login.status_code==200,login.text
        csrf=login.json()['csrf_token']
        assert owner_client.get('/api/security/status').json()['totp_enabled'] is False
        assert owner_client.get('/api/security/integrity').json()['ok'] is True
        assert auth_post(owner_client,'/api/security/totp/setup',{'password':'bad'},csrf=csrf).status_code==403
        begin=auth_post(owner_client,'/api/security/totp/setup',{'password':account['password']},csrf=csrf)
        assert begin.status_code==200,begin.text
        secret=begin.json()['secret']
        assert begin.json()['qr_data_url'].startswith('data:image/png;base64,')
        with SessionLocal() as db:
            u=db.scalar(select(User).where(User.username=='secureacct'))
            assert u.totp_secret is None
            assert secret not in u.totp_pending
            assert totp_decrypt(u.totp_pending)==secret
        code=totp_value(secret,int(time())//30)
        invalid=auth_post(owner_client,'/api/security/totp/enable',{'code':'000000' if code!='000000' else '111111'},csrf=csrf)
        assert invalid.status_code==422
        enabled=auth_post(owner_client,'/api/security/totp/enable',{'code':code},csrf=csrf)
        assert enabled.status_code==200,enabled.text
        recovery=enabled.json()['recovery_codes']; assert len(recovery)==8
        assert owner_client.get('/api/security/status').json()['recovery_codes_remaining']==8
        sessions=owner_client.get('/api/security/sessions').json()['items'];assert len(sessions)==1
        assert sessions[0]['current'] is True
        # Incorrect TOTP cannot produce an authenticated session; old OTP cannot be reused.
        separate=TestClient(app)
        challenged=auth_post(separate,'/api/login',{'username':'secureacct','password':account['password']})
        assert challenged.status_code==200 and challenged.json()['two_factor_required'] is True
        assert separate.get('/api/me').status_code==401
        ticket=challenged.json()['login_ticket']
        wrong=auth_post(separate,'/api/login-otp',{'login_ticket':ticket,'code':'000000' if code!='000000' else '111111'})
        assert wrong.status_code==401
        replay=auth_post(separate,'/api/login-otp',{'login_ticket':ticket,'code':code})
        assert replay.status_code==401  # enrollment consumed same step
        # Recovery codes are one-use and stored only by SHA-256.
        allowed=auth_post(separate,'/api/login-otp',{'login_ticket':ticket,'code':recovery[0]})
        assert allowed.status_code==200,allowed.text
        newcsrf=allowed.json()['csrf_token']
        assert separate.get('/api/me').status_code==200
        sessions=owner_client.get('/api/security/sessions').json()['items'];assert len(sessions)==2
        revoked=auth_post(owner_client,'/api/security/sessions/revoke-others',{},csrf=csrf)
        assert revoked.status_code==200 and revoked.json()['revoked']==1
        assert separate.get('/api/me').status_code==401
        assert owner_client.get('/api/security/status').json()['recovery_codes_remaining']==7
        # Account-level throttle survives repeated password logins / new OTP tickets.
        throttle=auth_post(separate,'/api/login',{'username':'secureacct','password':account['password']})
        ticket2=throttle.json()['login_ticket']
        invalid='000000' if code!='000000' else '111111'
        for _ in range(5):
            bad=auth_post(separate,'/api/login-otp',{'login_ticket':ticket2,'code':invalid})
            assert bad.status_code==401
        assert auth_post(separate,'/api/login',{'username':'secureacct','password':account['password']}).status_code==429
        with SessionLocal.begin() as db:
            locked=db.scalar(select(User).where(User.username=='secureacct'))
            assert locked.totp_locked_until is not None
            locked.totp_locked_until=None  # isolated test cleanup
        # Disabling 2FA requires password AND a different backup code.
        denied=auth_post(owner_client,'/api/security/totp/disable',{'password':'wrong','code':recovery[1]},csrf=csrf)
        assert denied.status_code==403
        disabled=auth_post(owner_client,'/api/security/totp/disable',{'password':account['password'],'code':recovery[1]},csrf=csrf)
        assert disabled.status_code==200,disabled.text
        assert owner_client.get('/api/security/status').json()['totp_enabled'] is False
        assert owner_client.get('/api/security/status').json()['recovery_codes_remaining']==0
        ordinary=auth_post(separate,'/api/login',{'username':'secureacct','password':account['password']})
        assert ordinary.status_code==200 and not ordinary.json().get('two_factor_required')
    finally:
        owner_client.close()

def test_export_controls_are_unambiguous():
    source=(ROOT/'frontend'/'app.js').read_text()
    assert 'data-action="report-excel"' in source
    assert 'data-action="report-pdf"' in source
    assert 'Xuất Excel <small>.XLSX</small>' in source
    assert 'Xuất PDF <small>.PDF</small>' in source
    assert "downloadReport('xlsx')" in source and "downloadReport('pdf')" in source


def test_savings_goals_reserved_funds_and_user_isolation(client):
    # Register a separate user so this test cannot affect existing finance tests.
    login=auth_post(client,'/api/login',{'username':'owner','password':'SecurePassword@12345'})
    assert login.status_code==200,login.text
    admin_csrf=login.json()['csrf_token']
    created=auth_post(client,'/api/users',credentials('saver117'),csrf=admin_csrf)
    assert created.status_code==200,created.text
    assert auth_post(client,'/api/logout',csrf=admin_csrf).status_code==200
    login=auth_post(client,'/api/login',{'username':'saver117','password':'SecurePassword@12345'})
    assert login.status_code==200,login.text
    csrf=login.json()['csrf_token']
    opening=auth_post(client,'/api/opening-balance',{'opening_balance':1_000_000},method='put',csrf=csrf)
    assert opening.status_code==200,opening.text
    wallet_1=client.get('/api/wallets').json()['items'][0]['id']
    wallet_2=auth_post(client,'/api/wallets',{'name':'Ngân hàng','kind':'bank','opening_balance':0},csrf=csrf).json()['id']
    transfer=auth_post(client,'/api/wallet-transfers',{'from_wallet_id':wallet_1,'to_wallet_id':wallet_2,'amount':300000,'occurred_on':'2026-11-03'},csrf=csrf)
    assert transfer.status_code==200,transfer.text
    new=auth_post(client,'/api/savings',{'name':'Quỹ dự phòng','target_amount':400000,'note':'Tài sản dành riêng'},csrf=csrf)
    assert new.status_code==200,new.text
    gid=new.json()['id']
    assert auth_post(client,f'/api/savings/{gid}/movements',{'kind':'deposit','wallet_id':wallet_1,'amount':200000},csrf=csrf).status_code==200
    assert auth_post(client,f'/api/savings/{gid}/movements',{'kind':'deposit','wallet_id':wallet_2,'amount':100000},csrf=csrf).status_code==200
    savings=client.get('/api/savings').json()
    assert savings['total_saved']==300000
    assert savings['items'][0]['progress_pct']==75.0
    assert len(savings['history'])==2
    balances={w['id']:w['balance'] for w in client.get('/api/wallets').json()['items']}
    assert balances=={wallet_1:500000,wallet_2:200000}
    dashboard=client.get('/api/dashboard?month=2026-11').json()
    assert dashboard['balance']==700000 and dashboard['savings_reserved']==300000
    assert dashboard['total_assets']==1_000_000 and dashboard['net_worth']==1_000_000
    report=client.get('/api/reports?end=2026-11&months=3').json()
    assert report['snapshot']['savings_balance']==300000
    assert report['snapshot']['net_worth']==1_000_000
    assert report['totals']['net_cash']==0  # internal movements are not income/expense
    from io import BytesIO
    from openpyxl import load_workbook
    xls=client.get('/api/reports.xlsx?end=2026-11&months=3')
    assert xls.status_code==200 and xls.content.startswith(b'PK')
    wb=load_workbook(BytesIO(xls.content),read_only=True,data_only=True)
    assert any(row[0]=='Tiết kiệm dành riêng' and row[1]==300000 for row in wb['Tổng quan'].values)
    wb.close()
    pdf=client.get('/api/reports.pdf?end=2026-11&months=3')
    assert pdf.status_code==200 and pdf.content.startswith(b'%PDF')
    assert auth_post(client,f'/api/savings/{gid}/movements',{'kind':'deposit','wallet_id':wallet_1,'amount':100001},csrf=csrf).status_code==409
    assert auth_post(client,f'/api/savings/{gid}/movements',{'kind':'withdraw','wallet_id':wallet_1,'amount':300001},csrf=csrf).status_code==409
    assert auth_post(client,f'/api/savings/{gid}',{'name':'Small','target_amount':200000},csrf=csrf,method='put').status_code==409
    assert auth_post(client,f'/api/savings/{gid}',csrf=csrf,method='delete').status_code==409
    withdraw=auth_post(client,f'/api/savings/{gid}/movements',{'kind':'withdraw','wallet_id':wallet_2,'amount':150000},csrf=csrf)
    assert withdraw.status_code==200,withdraw.text
    assert client.get('/api/dashboard?month=2026-11').json()['net_worth']==1_000_000
    assert client.get('/api/savings').json()['total_saved']==150000
    assert auth_post(client,'/api/logout',csrf=csrf).status_code==200
    owner=auth_post(client,'/api/login',{'username':'owner','password':'SecurePassword@12345'})
    assert owner.status_code==200,owner.text
    owner_csrf=owner.json()['csrf_token']
    assert not any(g['id']==gid for g in client.get('/api/savings').json()['items'])
    assert auth_post(client,f'/api/savings/{gid}/movements',{'kind':'withdraw','wallet_id':wallet_1,'amount':100},csrf=owner_csrf).status_code==404
    assert auth_post(client,f'/api/savings/{gid}',{'name':'Tampered','target_amount':150000},csrf=owner_csrf,method='put').status_code==404
    assert auth_post(client,'/api/logout',csrf=owner_csrf).status_code==200
    saver=auth_post(client,'/api/login',{'username':'saver117','password':'SecurePassword@12345'})
    assert saver.status_code==200,saver.text
    csrf=saver.json()['csrf_token']
    assert auth_post(client,f'/api/savings/{gid}/movements',{'kind':'withdraw','wallet_id':wallet_1,'amount':150000},csrf=csrf).status_code==200
    assert auth_post(client,f'/api/savings/{gid}',csrf=csrf,method='delete').status_code==200
    assert client.get('/api/savings').json()['total_saved']==0
    assert client.get('/api/dashboard?month=2026-11').json()['balance']==1_000_000
    assert client.get('/api/security/integrity').status_code==200


def test_forecast_read_only_wallet_risk_and_debt_allocation(client):
    """Scenario simulation is isolated per account and must not post real entries."""
    from datetime import date, timedelta
    from sqlalchemy import select, func
    from backend.app import (SessionLocal, User, Wallet, RecurringRule, Category,
                             Debt, Entry, compute_cash_forecast)
    start=date.today()
    with SessionLocal() as db:
        u=User(username='forecast_test_owner', display_name='forecast_test_owner',
               password_hash='not-used', email='forecast_test_owner@example.com',
               phone='0907777888',address='Local test',role='member',active=True,opening_balance=0)
        db.add(u); db.flush()
        w=Wallet(user_id=u.id,name='Ví thu chi',kind='bank',opening_balance=100000,
                 is_default=True,active=True)
        other=Wallet(user_id=u.id,name='Ví dự phòng',kind='cash',opening_balance=200000,
                     is_default=False,active=True)
        db.add_all([w,other]);db.flush()
        inc=Category(user_id=u.id,name='Dự báo lương',kind='income',color='#00BFA6')
        exp=Category(user_id=u.id,name='Dự báo nhà',kind='expense',color='#FFB870')
        db.add_all([inc,exp]); db.flush()
        due_income=start+timedelta(days=2)
        due_expense=start+timedelta(days=3)
        debt=Debt(user_id=u.id,name='Nợ dùng thử',principal=50000,remaining=50000,
                  direction='payable',annual_rate_bps=0,installment_count=1)
        rule_income=RecurringRule(user_id=u.id,wallet_id=w.id,category_id=inc.id,
                    title='Lương dự kiến',kind='income',amount=70000,note='',frequency='monthly',
                    start_on=due_income,next_index=0,mode='manual',remind_days=3,active=True)
        rule_expense=RecurringRule(user_id=u.id,wallet_id=w.id,category_id=exp.id,
                    title='Tiền nhà',kind='expense',amount=150000,note='',frequency='monthly',
                    start_on=due_expense,next_index=0,mode='manual',remind_days=3,active=True)
        paused=RecurringRule(user_id=u.id,wallet_id=w.id,category_id=exp.id,
                    title='Lịch đã dừng',kind='expense',amount=999999,note='',frequency='daily',
                    start_on=start,next_index=0,mode='auto',remind_days=3,active=False)
        overdue=RecurringRule(user_id=u.id,wallet_id=other.id,category_id=exp.id,
                    title='Hóa đơn quá hạn',kind='expense',amount=1000,note='',frequency='yearly',
                    start_on=start-timedelta(days=3),next_index=0,mode='manual',remind_days=3,active=True)
        db.add_all([debt,rule_income,rule_expense,paused,overdue]);db.commit()
        before_entries=db.scalar(select(func.count()).select_from(Entry).where(Entry.user_id==u.id))
        result=compute_cash_forecast(db,u.id,30,start)
        assert result['start_balance']==300000
        assert result['income_gross']==70000
        assert result['debt_allocated']==50000
        assert result['expense']==150000
        assert result['end_balance']==170000
        assert result['net_change']==-130000
        assert result['risk_wallet_count']==1  # one wallet -30,000, another +200,000
        assert result['first_shortfall_on']==due_expense.isoformat()
        assert result['wallets'][0]['projected_balance']==-30000
        assert result['wallets'][1]['projected_balance']==200000
        assert result['events'][0]['net_wallet_delta']==20000
        assert result['events'][0]['allocated_to_debt']==50000
        assert result['events'][1]['net_wallet_delta']==-150000
        assert result['payable_remaining_scenario']==0
        assert result['overdue_rules'][0]['title']=='Hóa đơn quá hạn'
        assert db.get(Debt,debt.id).remaining==50000
        assert db.get(RecurringRule,rule_income.id).next_index==0
        assert db.scalar(select(func.count()).select_from(Entry).where(Entry.user_id==u.id))==before_entries
        assert len(result['timeline'])==31
        with pytest.raises(Exception) as exc:
            compute_cash_forecast(db,u.id,91,start)
        assert '422' in str(exc.value)
        db.rollback()


def test_forecast_endpoint_auth_filter_and_range(client):
    # User from existing integration tests is whichever account remains authenticated.
    # The endpoint must never expose cross-user wallet data to the active account.
    from backend.app import SessionLocal, User, Wallet
    from sqlalchemy import select
    with SessionLocal() as db:
        target=db.scalar(select(User).where(User.username=='forecast_test_owner'))
        assert target is not None
        owned_wallets=list(db.scalars(select(Wallet).where(Wallet.user_id==target.id)))
    assert len(owned_wallets)==2
    # Login test user through the existing local flow uses an independent account.
    r=auth_post(client,'/api/login',{'username':'owner','password':'SecurePassword@12345'})
    assert r.status_code==200,r.text
    ok=client.get('/api/forecast?days=30')
    assert ok.status_code==200,ok.text
    body=ok.json()
    assert body['horizon_days']==30
    assert all(w['name'] not in ('Ví thu chi','Ví dự phòng') for w in body['wallets'])
    assert ok.headers.get('cache-control')=='no-store'
    assert client.get('/api/forecast?days=45').status_code==422


def test_forecast_clamped_months_and_no_duplicate_periods(client):
    from datetime import date
    from backend.app import RecurringRule, forecast_due_dates
    rule=RecurringRule(user_id=1,wallet_id=1,category_id=1,
           title='Ngày 31',kind='expense',amount=1,frequency='monthly',
           start_on=date(2026,1,31),next_index=1,mode='manual',remind_days=3,active=True)
    dates=list(forecast_due_dates(rule,date(2026,2,1),date(2026,4,30)))
    assert dates==[date(2026,2,28),date(2026,3,31),date(2026,4,30)]
    rule.next_index=2
    assert list(forecast_due_dates(rule,date(2026,2,1),date(2026,4,30)))==dates[1:]
