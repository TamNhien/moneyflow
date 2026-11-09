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
    assert auth_post(client,'/api/settings/auto-debt',{'enabled':True},csrf=csrf,method='put').status_code==200
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
    assert auth_post(client,'/api/settings/auto-debt',{'enabled':True},csrf=csrf,method='put').status_code==200
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
    assert auth_post(client,'/api/settings/auto-debt',{'enabled':True},csrf=csrf,method='put').status_code==200
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
    assert auth_post(client,'/api/settings/auto-debt',{'enabled':True},csrf=csrf,method='put').status_code==200
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
    assert auth_post(client,'/api/settings/auto-debt',{'enabled':True},csrf=token,method='put').status_code==200
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
        u=User(username='forecast_test_owner', auto_repay_debts=True, display_name='forecast_test_owner',
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


def test_stash_funds_lifecycle_and_balance_integrity(client):
    """General-purpose saved money is distinct from target-bound savings."""
    r=auth_post(client,'/api/login',{'username':'owner','password':'SecurePassword@12345'})
    assert r.status_code==200,r.text
    csrf=r.json()['csrf_token']
    # A fresh wallet keeps this test independent of the rest of the ledger.
    wallet_resp=auth_post(client,'/api/wallets',{'name':'Ví để dành kiểm thử','kind':'cash','opening_balance':500000},csrf=csrf)
    assert wallet_resp.status_code==200,wallet_resp.text
    wid=wallet_resp.json()['id']
    first=client.get('/api/dashboard?month=2026-11').json()
    funds=client.get('/api/stashes').json()
    assert funds['total_saved']>=0
    create=auth_post(client,'/api/stashes',{'name':'Tiền tích để dành','note':'Để dành linh hoạt'},csrf=csrf)
    assert create.status_code==200,create.text
    fid=create.json()['id']
    assert create.json()['saved_amount']==0
    assert auth_post(client,'/api/stashes',{'name':'  ', 'note':''},csrf=csrf).status_code==422
    payload={'kind':'deposit','wallet_id':wid,'amount':150000,'occurred_on':'2026-11-03','note':'Tích lũy tháng 11'}
    r=auth_post(client,f'/api/stashes/{fid}/movements',payload,csrf=csrf)
    assert r.status_code==200,r.text
    assert r.json()['saved_amount']==150000
    after=client.get('/api/dashboard?month=2026-11').json()
    assert after['balance']==first['balance']-150000
    assert after['total_assets']==first['total_assets']
    assert after['net_worth']==first['net_worth']
    assert after['stash_reserved']==first.get('stash_reserved',0)+150000
    assert client.get('/api/wallets').json()['total_balance']==after['balance']
    assert auth_post(client,f'/api/stashes/{fid}/movements',{**payload,'amount':400000},csrf=csrf).status_code==409
    assert auth_post(client,f'/api/stashes/{fid}/movements',{**payload,'kind':'withdraw','amount':150001},csrf=csrf).status_code==409
    # Funds cannot disappear while they hold money or a historical ledger.
    assert auth_post(client,f'/api/stashes/{fid}',csrf=csrf,method='delete').status_code==409
    r=auth_post(client,f'/api/stashes/{fid}/movements',{**payload,'kind':'withdraw','amount':50000},csrf=csrf)
    assert r.status_code==200,r.text
    assert r.json()['saved_amount']==100000
    assert auth_post(client,f'/api/stashes/{fid}',{'name':'Quỹ khẩn cấp','note':'Không có hạn mức'},csrf=csrf,method='put').status_code==200
    report=client.get('/api/reports?end=2026-11&months=3')
    assert report.status_code==200,report.text
    assert report.json()['snapshot']['stash_balance']>=100000
    assert report.json()['snapshot']['total_assets']==after['total_assets']
    from io import BytesIO
    from openpyxl import load_workbook
    excel=client.get('/api/reports.xlsx?end=2026-11&months=3')
    assert excel.status_code==200 and excel.content.startswith(b'PK')
    book=load_workbook(BytesIO(excel.content), read_only=True, data_only=True)
    assert any(row[0]=='Trong đó: Tiền tích để dành' and row[1]>=100000 for row in book['Tổng quan'].values)
    pdf=client.get('/api/reports.pdf?end=2026-11&months=3')
    assert pdf.status_code==200 and pdf.content.startswith(b'%PDF-')
    assert client.get('/api/security/integrity').json()['ok'] is True
    r=auth_post(client,f'/api/stashes/{fid}/movements',{**payload,'kind':'withdraw','amount':100000},csrf=csrf)
    assert r.status_code==200,r.text
    assert client.get('/api/dashboard?month=2026-11').json()['balance']==first['balance']
    assert auth_post(client,f'/api/stashes/{fid}',csrf=csrf,method='delete').status_code==409
    history=client.get('/api/stashes').json()['history']
    assert [h['kind'] for h in history[:3]]==['withdraw','withdraw','deposit']


def test_stashes_user_isolation(client):
    owner=auth_post(client,'/api/login',{'username':'owner','password':'SecurePassword@12345'})
    assert owner.status_code==200,owner.text
    csrf=owner.json()['csrf_token']
    stash=auth_post(client,'/api/stashes',{'name':'Quỹ riêng tư','note':''},csrf=csrf)
    assert stash.status_code==200,stash.text
    fid=stash.json()['id']
    account=auth_post(client,'/api/users',credentials('stash_member_19'),csrf=csrf)
    assert account.status_code==200,account.text
    from fastapi.testclient import TestClient
    with TestClient(app) as member:
        login=auth_post(member,'/api/login',{'username':'stash_member_19','password':'SecurePassword@12345'})
        assert login.status_code==200,login.text
        member_csrf=login.json()['csrf_token']
        assert member.get('/api/stashes').json()['items']==[]
        assert auth_post(member,f'/api/stashes/{fid}',{'name':'Đổi tên quỹ lạ','note':''},csrf=member_csrf,method='put').status_code==404
        assert auth_post(member,f'/api/stashes/{fid}/movements',{'kind':'deposit','wallet_id':1,'amount':100,'occurred_on':'2026-11-03'},csrf=member_csrf).status_code in (404,422)
        assert auth_post(member,f'/api/stashes/{fid}',csrf=member_csrf,method='delete').status_code==404


def test_auto_stash_percentage_fixed_after_debt_and_reversal(client):
    """v1.0.20: reserve net income, not gross; preserve assets and reversibility."""
    login=auth_post(client,'/api/login',{'username':'owner','password':'SecurePassword@12345'})
    assert login.status_code == 200, login.text
    r=auth_post(client,'/api/users',credentials('stashauto20'),csrf=login.json()['csrf_token'])
    assert r.status_code == 200,r.text
    r=auth_post(client,'/api/login',{'username':'stashauto20','password':'SecurePassword@12345'})
    assert r.status_code == 200,r.text
    csrf=r.json()['csrf_token']
    assert auth_post(client,'/api/settings/auto-debt',{'enabled':True},csrf=csrf,method='put').status_code==200
    cats=client.get('/api/categories').json()
    income_id=next(x['id'] for x in cats if x['kind']=='income')
    expense_id=next(x['id'] for x in cats if x['kind']=='expense')
    wid=client.get('/api/wallets').json()['items'][0]['id']
    daily=__import__('datetime').date.today().isoformat()
    wrong=auth_post(client,'/api/stashes',{'name':'Sai %','auto_mode':'percent','auto_value':101},csrf=csrf)
    assert wrong.status_code==422
    off=auth_post(client,'/api/stashes',{'name':'Sai off','auto_mode':'off','auto_value':500},csrf=csrf)
    assert off.status_code==422
    w=auth_post(client,'/api/stashes',{'name':'Sai ví','auto_mode':'fixed','auto_value':1,'auto_wallet_id':9999999},csrf=csrf)
    assert w.status_code==422
    percent=auth_post(client,'/api/stashes',{'name':'10 phần trăm','auto_mode':'percent','auto_value':20,'auto_wallet_id':wid},csrf=csrf)
    assert percent.status_code==200,percent.text
    fixed=auth_post(client,'/api/stashes',{'name':'Cố định 300','auto_mode':'fixed','auto_value':300},csrf=csrf)
    assert fixed.status_code==200,fixed.text
    percent_id,fixed_id=percent.json()['id'],fixed.json()['id']
    loan=auth_post(client,'/api/debts',{'name':'Nợ trả trước','principal':400,'direction':'payable'},csrf=csrf)
    assert loan.status_code==200,loan.text
    entry={'title':'Lương mới','kind':'income','amount':1000,'category_id':income_id,
           'wallet_id':wid,'occurred_on':daily,'note':''}
    added=auth_post(client,'/api/transactions',entry,csrf=csrf)
    assert added.status_code==200,added.text
    eid=added.json()['id']
    assert added.json()['debt_paid']==400
    assert added.json()['auto_saved']==420  # 20% of 600 (120) + fixed 300
    d=client.get('/api/dashboard?month='+daily[:7]).json()
    assert (d['balance'],d['stash_reserved'],d['total_assets'])==(180,420,600)
    assert client.get('/api/debts').json()['total_remaining']==0
    funds=client.get('/api/stashes').json()
    byid={f['id']:f for f in funds['items']}
    assert byid[percent_id]['saved_amount']==120
    assert byid[fixed_id]['saved_amount']==300
    history=funds['history']
    assert len(history)==2 and all(m['source']=='auto' and m['source_entry_id']==eid for m in history)
    # A small income cannot cause an overdraft: percentage of its net, fixed capped.
    small=auth_post(client,'/api/transactions',{**entry,'amount':100},csrf=csrf)
    assert small.status_code==200,small.text
    assert small.json()['auto_saved']==100
    assert client.get('/api/dashboard?month='+daily[:7]).json()['balance']==180
    # Reversing an auto-funded income restores the allocation; no new expense.
    assert auth_post(client,f'/api/transactions/{small.json()["id"]}',csrf=csrf,method='delete').status_code==200
    assert client.get('/api/stashes').json()['total_saved']==420
    edited=auth_post(client,f'/api/transactions/{eid}',{**entry,'amount':600},method='put',csrf=csrf)
    assert edited.status_code==200,edited.text
    assert (edited.json()['debt_paid'],edited.json()['auto_saved'])==(400,200)
    # fixed 300 is capped to remaining 160 after 20% of net 200 = 40.
    assert client.get('/api/dashboard?month='+daily[:7]).json()['balance']==0
    # Withdrawing auto savings prevents deleting the funding income if balance is too small.
    movement={'kind':'withdraw','wallet_id':wid,'amount':100,'occurred_on':daily}
    r=auth_post(client,f'/api/stashes/{fixed_id}/movements',movement,csrf=csrf)
    assert r.status_code==200,r.text
    blocked=auth_post(client,f'/api/transactions/{eid}',csrf=csrf,method='delete')
    assert blocked.status_code==409,blocked.text
    assert client.get('/api/debts').json()['total_remaining']==0  # rollback atomic
    # Return the withdrawn money to the fund and delete the source income.
    movement['kind']='deposit'
    assert auth_post(client,f'/api/stashes/{fixed_id}/movements',movement,csrf=csrf).status_code==200
    assert auth_post(client,f'/api/transactions/{eid}',csrf=csrf,method='delete').status_code==200
    final=client.get('/api/dashboard?month='+daily[:7]).json()
    assert (final['balance'],final['stash_reserved'],final['total_assets'])==(0,0,0)
    assert client.get('/api/debts').json()['total_remaining']==400
    # Scope rule to a particular wallet; a different wallet receives no auto deposit.
    bank=auth_post(client,'/api/wallets',{'name':'Ngân hàng khác','kind':'bank','opening_balance':0},csrf=csrf)
    assert bank.status_code==200,bank.text
    other_id=bank.json()['id']
    assert auth_post(client,f'/api/stashes/{fixed_id}',{'name':'Cố định 300','auto_mode':'off','auto_value':0},csrf=csrf,method='put').status_code==200
    extra=auth_post(client,'/api/transactions',{**entry,'amount':500,'wallet_id':other_id},csrf=csrf)
    assert extra.status_code==200 and extra.json()['auto_saved']==0
    # No additional ledger rows from auto reserve when income lands in another wallet.
    assert client.get('/api/stashes').json()['total_saved']==0
    # User isolation still enforced.
    owner2=auth_post(client,'/api/login',{'username':'owner','password':'SecurePassword@12345'})
    assert owner2.status_code==200
    cross=auth_post(client,f'/api/stashes/{percent_id}',{'name':'Không thuộc sở hữu','auto_mode':'percent','auto_value':10},csrf=owner2.json()['csrf_token'],method='put')
    assert cross.status_code==404


def test_auto_stash_recurring_income_and_forecast(client):
    admin=auth_post(client,'/api/login',{'username':'owner','password':'SecurePassword@12345'})
    assert admin.status_code==200,admin.text
    made=auth_post(client,'/api/users',credentials('stashrec20'),csrf=admin.json()['csrf_token'])
    assert made.status_code==200,made.text
    login=auth_post(client,'/api/login',{'username':'stashrec20','password':'SecurePassword@12345'})
    assert login.status_code==200,login.text
    csrf=login.json()['csrf_token']
    wid=client.get('/api/wallets').json()['items'][0]['id']
    inc=next(c['id'] for c in client.get('/api/categories').json() if c['kind']=='income')
    r=auth_post(client,'/api/stashes',{'name':'Dành 25%','auto_mode':'percent','auto_value':25},csrf=csrf)
    assert r.status_code==200,r.text
    due=__import__('datetime').date.today()
    rule={'title':'Lương định kỳ','kind':'income','amount':2000,'category_id':inc,
          'wallet_id':wid,'start_on':due.isoformat(),'frequency':'monthly','mode':'manual','remind_days':3}
    made=auth_post(client,'/api/recurring',rule,csrf=csrf)
    assert made.status_code==200,made.text
    rule_id=made.json()['id']
    outcome=auth_post(client,f'/api/recurring/{rule_id}/confirm',csrf=csrf)
    assert outcome.status_code==200,outcome.text
    assert outcome.json()['auto_saved']==500
    assert auth_post(client,f'/api/recurring/{rule_id}/confirm',csrf=csrf).status_code==409
    assert client.get('/api/stashes').json()['total_saved']==500
    assert client.get('/api/dashboard?month='+due.isoformat()[:7]).json()['balance']==1500
    before=client.get('/api/transactions').json()['total']
    forecast=client.get('/api/forecast?days=30')
    assert forecast.status_code==200,forecast.text
    assert forecast.json()['stash_allocated']>=0
    assert client.get('/api/transactions').json()['total']==before


def test_smart_budget_thresholds_forecast_and_isolation(client):
    """v1.0.21: 70/90/100 thresholds, safe projections and read-only isolation."""
    from datetime import date, timedelta
    from backend.app import SessionLocal, compute_budget_insights
    today_day=date.today()
    month=today_day.strftime('%Y-%m')
    admin_login=auth_post(client,'/api/login',{'username':'owner','password':'SecurePassword@12345'})
    assert admin_login.status_code==200,admin_login.text
    created=auth_post(client,'/api/users',credentials('smartbudget21'),csrf=admin_login.json()['csrf_token'])
    assert created.status_code==200,created.text
    login=auth_post(client,'/api/login',{'username':'smartbudget21','password':'SecurePassword@12345'})
    assert login.status_code==200,login.text
    csrf=login.json()['csrf_token']
    category=next(c for c in client.get('/api/categories').json() if c['kind']=='expense')
    wallet=client.get('/api/wallets').json()['items'][0]['id']
    assert auth_post(client,'/api/opening-balance',{'opening_balance':5000},method='put',csrf=csrf).status_code==200
    assert auth_post(client,'/api/budgets',{'month':month,'category_id':category['id'],'amount':1000},method='put',csrf=csrf).status_code==200
    def spend(n):
        r=auth_post(client,'/api/transactions',{'title':f'Chi {n}','kind':'expense',
                     'amount':n,'category_id':category['id'],'wallet_id':wallet,
                     'occurred_on':today_day.isoformat()},csrf=csrf)
        assert r.status_code==200,r.text
    response=client.get(f'/api/budgets/insights?month={month}')
    assert response.status_code==200,response.text
    assert response.headers['cache-control']=='no-store'
    assert response.json()['items'][0]['status']=='ok'
    spend(700)
    one=client.get(f'/api/budgets/insights?month={month}').json()['items'][0]
    assert one['status']=='warning' and one['spent_percent']==70.0
    assert one['projected_spent']>=one['spent']
    assert one['remaining']==300
    spend(200)
    assert client.get(f'/api/budgets/insights?month={month}').json()['items'][0]['status']=='critical'
    spend(100)
    assert client.get(f'/api/budgets/insights?month={month}').json()['items'][0]['status']=='limit'
    spend(50)
    result=client.get(f'/api/budgets/insights?month={month}').json()
    assert result['items'][0]['status']=='exceeded'
    assert result['summary']['critical_count']==1
    assert result['summary']['at_risk_count']==1
    assert result['alerts'][0]['over_by']==50
    assert client.get(f'/api/dashboard?month={month}').json()['budget_alerts'][0]['category']==category['name']
    assert client.get('/api/budgets/insights?month=2021-01').json()['is_current_month'] is False
    assert client.get('/api/budgets/insights?month=2021-01').json()['items']==[]
    assert client.get('/api/budgets/insights?month=invalid').status_code==422
    before=client.get('/api/transactions').json()['total']
    for _ in range(2):
        assert client.get(f'/api/budgets/insights?month={month}').status_code==200
    assert client.get('/api/transactions').json()['total']==before
    # 0-limit is meaningful, never divide by zero.
    assert auth_post(client,'/api/budgets',{'month':month,'category_id':category['id'],'amount':0},method='put',csrf=csrf).status_code==200
    assert client.get(f'/api/budgets/insights?month={month}').json()['items'][0]['status']=='exceeded'
    # Snapshot projection must never mutate data or create ledger entries.
    assert client.get('/api/transactions').json()['total']==before
    # Other users do not see the category's budget or warnings.
    assert auth_post(client,'/api/login',{'username':'owner','password':'SecurePassword@12345'}).status_code==200
    owner_budget=client.get(f'/api/budgets/insights?month={month}').json()
    assert all(b['category_id']!=category['id'] or b['amount']!=0 for b in owner_budget['items'])
    # Deterministic scenarios for past/future months must remain read-only.
    with SessionLocal() as db:
        future_month=(today_day.replace(day=1)+timedelta(days=40)).strftime('%Y-%m')
        from backend.app import User
        user=db.query(User).filter_by(username='smartbudget21').one()
        data=compute_budget_insights(db,user.id,future_month,as_of=today_day)
        assert data['is_current_month'] is False


def test_smart_budget_pending_recurring_not_double_counted(client):
    """Future due dates count once; already skipped/posted periods are excluded."""
    from datetime import date, timedelta
    from calendar import monthrange
    from sqlalchemy import select
    from backend.app import (SessionLocal, User, Budget, Category, Wallet,
                             RecurringRule, RecurringRun, compute_budget_insights)
    with SessionLocal() as db:
        user=db.scalar(select(User).where(User.username=='smartbudget21'))
        assert user is not None
        budget=db.scalar(select(Budget).where(Budget.user_id==user.id))
        assert budget is not None
        category=db.get(Category,budget.category_id)
        wallet=db.scalar(select(Wallet).where(Wallet.user_id==user.id))
        start=date.today().replace(day=1)
        last=monthrange(start.year,start.month)[1]
        budget.amount=1000000
        rule=RecurringRule(user_id=user.id,category_id=category.id,wallet_id=wallet.id,
                           kind='expense',title='Hóa đơn theo ngày',amount=2000,
                           frequency='daily',start_on=start+timedelta(days=1),
                           mode='manual',next_index=0,remind_days=1,active=True)
        db.add(rule)
        db.flush()
        month=start.strftime('%Y-%m')
        initial=compute_budget_insights(db,user.id,month,as_of=start)['items'][0]
        assert initial['scheduled_count']==last-1
        assert initial['scheduled_remaining']==(last-1)*2000
        db.add(RecurringRun(user_id=user.id,rule_id=rule.id,due_on=start+timedelta(days=1),status='skipped'))
        db.flush()
        updated=compute_budget_insights(db,user.id,month,as_of=start)['items'][0]
        assert updated['scheduled_count']==initial['scheduled_count']-1
        assert updated['scheduled_remaining']==initial['scheduled_remaining']-2000
        # Test uses transaction rollback, never posts a real schedule or payment.
        db.rollback()


def test_transaction_receipts_private_validated_and_removed(client, monkeypatch, tmp_path):
    """Evidence is private, immutable, format-checked and cleaned up with its entry."""
    import base64
    import hashlib
    import io
    from PIL import Image
    from fastapi.testclient import TestClient
    from backend import app as app_module
    from backend.app import SessionLocal, Receipt
    from sqlalchemy import select

    monkeypatch.setattr(app_module, 'RECEIPTS_DIR', tmp_path / 'private-evidence')
    login_admin = auth_post(client, '/api/login',
                            {'username':'owner','password':'SecurePassword@12345'})
    assert login_admin.status_code == 200, login_admin.text
    admin_csrf = login_admin.json()['csrf_token']
    for name in ('evidence22', 'evidence22b'):
        result = auth_post(client, '/api/users', credentials(name), csrf=admin_csrf)
        assert result.status_code == 200, result.text

    with TestClient(app) as first, TestClient(app) as other:
        response = auth_post(first, '/api/login',
                             {'username':'evidence22','password':'SecurePassword@12345'})
        assert response.status_code == 200
        csrf = response.json()['csrf_token']
        assert auth_post(other, '/api/login',
                         {'username':'evidence22b','password':'SecurePassword@12345'}).status_code == 200
        foreign_csrf = other.get('/api/me').json()['csrf_token']
        cat = next(c for c in first.get('/api/categories').json() if c['kind']=='income')
        entry = auth_post(first,'/api/transactions',{'title':'Tiền thưởng có hóa đơn',
            'kind':'income','amount':32000,'category_id':cat['id'], 'occurred_on':'2026-11-04'},csrf=csrf)
        assert entry.status_code == 200,entry.text
        entry_id = entry.json()['id']
        url = f'/api/transactions/{entry_id}/receipts'
        png = io.BytesIO()
        Image.new('RGB',(24,16),(45,120,200)).save(png,format='PNG')
        raw_png = png.getvalue()
        encoded = base64.b64encode(raw_png).decode()
        document={'name':'hoa-don.png', 'data_base64':encoded}
        assert auth_post(first,url,document).status_code == 403  # CSRF still mandatory
        assert auth_post(other,url,document,csrf=foreign_csrf).status_code == 404
        assert other.get(url).status_code == 404
        assert auth_post(first,url,{'name':'../../hoa-don.exe','data_base64':encoded},csrf=csrf).status_code == 415
        assert auth_post(first,url,{'name':'fake.png','data_base64':base64.b64encode(b'not an image').decode()},csrf=csrf).status_code == 415
        assert auth_post(first,url,{'name':'fake.pdf','data_base64':encoded},csrf=csrf).status_code == 415
        assert auth_post(first,url,{'name':'x.jpg','data_base64':'bad^^base64'},csrf=csrf).status_code == 422
        created=auth_post(first,url,document,csrf=csrf)
        assert created.status_code == 200,created.text
        obj=created.json()
        assert obj['name']=='hoa-don.png' and obj['sha256']==hashlib.sha256(raw_png).hexdigest()
        with SessionLocal() as db:
            row=db.scalar(select(Receipt).where(Receipt.id == obj['id']))
            assert row and row.storage_key != obj['name']
            saved=app_module.receipt_path(row.storage_key)
            assert saved.read_bytes()==raw_png
        listed=first.get(url)
        assert listed.status_code==200 and listed.json()['items'][0]['id']==obj['id']
        assert first.get('/api/transactions').json()['items'][0]['receipt_count']==1
        inventory=first.get('/api/receipts').json()
        assert inventory['total']==1 and inventory['items'][0]['entry_title']=='Tiền thưởng có hóa đơn'
        assert first.get('/api/receipts?kind=image&month=2026-11').json()['total']==1
        assert first.get('/api/receipts?q=hoa-don').json()['total']==1
        assert first.get('/api/receipts?kind=pdf').json()['total']==0
        assert first.get('/api/receipts?month=2025-01').json()['total']==0
        assert first.get('/api/receipts?month=not-a-month').status_code==422
        assert first.get('/api/receipts?kind=exe').status_code==422
        assert first.get('/api/receipts?page=-1').status_code==422
        assert other.get('/api/receipts').json()['total']==0
        download=first.get(f"/api/receipts/{obj['id']}/file")
        assert download.status_code==200 and download.content==raw_png
        assert 'attachment' in download.headers['content-disposition']
        assert download.headers['x-content-type-options']=='nosniff'
        # Altered bytes must not be served with the original file's trusted metadata.
        saved.write_bytes(b'corrupted evidence')
        assert first.get(f"/api/receipts/{obj['id']}/file").status_code==409
        saved.write_bytes(raw_png)
        too_large=base64.b64encode(b'x' * (8*1024*1024+1)).decode()
        assert auth_post(first,url,{'name':'big.png','data_base64':too_large},csrf=csrf).status_code==413
        assert other.get(f"/api/receipts/{obj['id']}/file").status_code==404
        assert auth_post(other,f"/api/receipts/{obj['id']}",csrf=foreign_csrf,method='delete').status_code==404
        # Multiple attachments and per-transaction limit.
        for i in range(7):
            assert auth_post(first,url,{'name':f'anh-{i}.png','data_base64':encoded},csrf=csrf).status_code==200
        assert auth_post(first,url,document,csrf=csrf).status_code==409
        assert len(first.get(url).json()['items'])==8
        assert auth_post(first,f"/api/receipts/{obj['id']}",csrf=csrf,method='delete').status_code==200
        assert not saved.exists()
        pdf=b'%PDF-1.4\n1 0 obj<<>>endobj\n%%EOF\n'
        pdf_result=auth_post(first,url,{'name':'chung-tu.pdf','data_base64':base64.b64encode(pdf).decode()},csrf=csrf)
        assert pdf_result.status_code==200,pdf_result.text
        assert first.get(f"/api/receipts/{pdf_result.json()['id']}/file").content==pdf
        assert auth_post(first,f'/api/transactions/{entry_id}',csrf=csrf,method='delete').status_code==200
        assert first.get(url).status_code==404
        assert first.get(f"/api/receipts/{pdf_result.json()['id']}/file").status_code==404
        assert not list((tmp_path / 'private-evidence').iterdir())
        # New user can have identical original filename without sharing files.
        foreign_cat=next(c for c in other.get('/api/categories').json() if c['kind']=='income')
        foreign_entry=auth_post(other,'/api/transactions',{'title':'Khác','kind':'income',
            'amount':100,'category_id':foreign_cat['id'],'occurred_on':'2026-11-04'},csrf=foreign_csrf)
        assert foreign_entry.status_code==200
        other_id=foreign_entry.json()['id']
        assert auth_post(other,f'/api/transactions/{other_id}/receipts',document,csrf=foreign_csrf).status_code==200
        assert first.get(f'/api/transactions/{other_id}/receipts').status_code==404
        with SessionLocal() as db:
            from backend.app import User
            foreign_user=db.scalar(select(User).where(User.username=='evidence22b'))
            foreign_user_id=foreign_user.id
        deletion=auth_post(client,f'/api/users/{foreign_user_id}',
                           {'confirm_username':'evidence22b'},method='delete',csrf=admin_csrf)
        assert deletion.status_code==200,deletion.text
        assert not list((tmp_path/'private-evidence').iterdir())


def test_reconciliation_manual_count_does_not_change_cash_and_is_private(client):
    """User-supplied physical/bank balance is evidence, not a book entry."""
    owner = auth_post(client, '/api/login',
        {'username':'owner','password':'SecurePassword@12345'})
    assert owner.status_code == 200, owner.text
    token = owner.json()['csrf_token']
    for uname in ('recon23a','recon23b'):
        made = auth_post(client, '/api/users', credentials(uname), csrf=token)
        assert made.status_code == 200, made.text

    with TestClient(app) as first, TestClient(app) as second:
        r = auth_post(first, '/api/login', {'username':'recon23a','password':'SecurePassword@12345'})
        assert r.status_code == 200
        csrf = r.json()['csrf_token']
        r = auth_post(second, '/api/login', {'username':'recon23b','password':'SecurePassword@12345'})
        assert r.status_code == 200
        other_csrf = r.json()['csrf_token']
        wallet_id = first.get('/api/wallets').json()['items'][0]['id']
        assert auth_post(first, '/api/opening-balance',
            {'opening_balance':1_000_000},csrf=csrf,method='put').status_code == 200
        second_wallet_id = second.get('/api/wallets').json()['items'][0]['id']
        from backend.app import WalletReconciliation, SessionLocal
        from sqlalchemy import select, func
        with SessionLocal() as db:
            before = db.scalar(select(func.count(WalletReconciliation.id)))
        initial=first.get('/api/reconciliation')
        assert initial.status_code == 200
        assert initial.headers['cache-control']=='no-store'
        assert initial.json()['wallets'][0]['book_balance'] == 1_000_000
        assert initial.json()['wallets'][0]['last_check'] is None
        with SessionLocal() as db:
            assert db.scalar(select(func.count(WalletReconciliation.id))) == before
        # CSRF, integer and cross-tenant wallet validation.
        payload={'wallet_id':wallet_id,'counted_balance':950_000,'note':'Kiem tra thuc te'}
        assert auth_post(first,'/api/reconciliation/check',payload).status_code == 403
        assert auth_post(first,'/api/reconciliation/check',
                         {**payload, 'counted_balance':-5},csrf=csrf).status_code == 422
        assert auth_post(first,'/api/reconciliation/check',
                         {**payload, 'counted_balance':1.2},csrf=csrf).status_code == 422
        assert auth_post(first,'/api/reconciliation/check',
                         {**payload, 'wallet_id':second_wallet_id},csrf=csrf).status_code == 422
        assert auth_post(second,'/api/reconciliation/check',
                         {**payload, 'wallet_id':wallet_id},csrf=other_csrf).status_code == 422
        posted = auth_post(first,'/api/reconciliation/check',payload,csrf=csrf)
        assert posted.status_code == 200, posted.text
        checked=posted.json()
        assert (checked['recorded_balance'],checked['counted_balance'],checked['difference']) == (1_000_000,950_000,-50_000)
        assert first.get('/api/wallets').json()['items'][0]['balance'] == 1_000_000
        assert first.get('/api/dashboard?month=2026-11').json()['balance'] == 1_000_000
        seen=first.get('/api/reconciliation').json()
        assert seen['summary']['latest_discrepancies']==1
        assert seen['checks'][0]['id']==checked['id']
        assert second.get('/api/reconciliation').json()['checks']==[]
        # A new transaction never rewrites the historical observation's book balance.
        inc_cat=next(x for x in first.get('/api/categories').json() if x['kind']=='income')
        tx={'title':'Luong thu bo sung', 'kind':'income', 'amount':20_000,
            'occurred_on':'2026-11-04', 'category_id':inc_cat['id'], 'wallet_id':wallet_id}
        assert auth_post(first,'/api/transactions',tx,csrf=csrf).status_code==200
        after=first.get('/api/reconciliation').json()
        assert after['wallets'][0]['book_balance']==1_020_000
        assert after['wallets'][0]['last_check']['recorded_balance']==1_000_000
        assert after['wallets'][0]['last_check']['difference']==-50_000
        assert after['summary']['book_total']==after['ledger_total']==1_020_000
        # Another wallet without a check must still be distinct.
        added=auth_post(first,'/api/wallets',{'name':'Ngan hang','kind':'bank','opening_balance':80_000},csrf=csrf)
        assert added.status_code==200,added.text
        after=first.get('/api/reconciliation').json()
        assert after['summary']['wallet_count']==2
        assert after['summary']['checked_wallets']==1
        assert after['summary']['book_total']==1_100_000


def test_reconciliation_detects_candidates_without_mutation(client):
    with TestClient(app) as first:
        r=auth_post(first,'/api/login',{'username':'recon23a','password':'SecurePassword@12345'})
        assert r.status_code==200
        csrf=r.json()['csrf_token']
        categories=first.get('/api/categories').json()
        income=next(x for x in categories if x['kind']=='income')
        expense=next(x for x in categories if x['kind']=='expense')
        wallet=first.get('/api/wallets').json()['items'][0]
        start=first.get('/api/dashboard?month=2026-11').json()['balance']
        # Repeat an identical payment; both rows must remain valid and unchanged.
        payment={'title':'Chi phi test trung', 'kind':'expense', 'amount':25_000,
                 'category_id':expense['id'], 'occurred_on':'2026-11-04', 'wallet_id':wallet['id']}
        for _ in range(2):
            r=auth_post(first,'/api/transactions',payment,csrf=csrf)
            assert r.status_code==200,r.text
        # Six peer entries allow robust median-based high-value warning.
        for n in (17_000,18_000,19_000,20_000,21_000,22_000):
            r=auth_post(first,'/api/transactions',{'title':f'Thu thuong {n}',
                'kind':'income','amount':n,'occurred_on':'2026-11-04',
                'wallet_id':wallet['id'],'category_id':income['id']},csrf=csrf)
            assert r.status_code==200,r.text
        r=auth_post(first,'/api/transactions',{'title':'Thu gia tri lon can doi soat',
            'kind':'income','amount':1_500_000,'occurred_on':'2026-11-04',
            'wallet_id':wallet['id'],'category_id':income['id']},csrf=csrf)
        assert r.status_code==200,r.text
        current=first.get('/api/dashboard?month=2026-11').json()['balance']
        alert=first.get('/api/reconciliation').json()
        assert alert['summary']['anomaly_candidates']>=2
        assert any(x['type']=='duplicate_candidate' and x['entry_title']=='Chi phi test trung' for x in alert['anomalies'])
        assert any(x['type']=='large_amount' and x['entry_title']=='Thu gia tri lon can doi soat' for x in alert['anomalies'])
        assert first.get('/api/dashboard?month=2026-11').json()['balance']==current
        assert current>start


def test_reconciliation_latest_wallet_check_survives_history_limit(client):
    """A quiet wallet's latest count must not disappear if another wallet is checked often."""
    from backend.app import WalletReconciliation, SessionLocal, User, Wallet
    from sqlalchemy import select
    with SessionLocal.begin() as db:
        account=db.scalar(select(User).where(User.username=='recon23a'))
        wallets=list(db.scalars(select(Wallet).where(Wallet.user_id==account.id).order_by(Wallet.id)))
        assert len(wallets)==2
        quiet=wallets[1]
        db.add(WalletReconciliation(user_id=account.id,wallet_id=quiet.id,
                    recorded_balance=80000,counted_balance=81000,difference=1000,note='Quiet wallet'))
        for i in range(62):
            db.add(WalletReconciliation(user_id=account.id,wallet_id=wallets[0].id,
                    recorded_balance=1000000,counted_balance=1000000,difference=0,note=f'Check {i}'))
    with TestClient(app) as c:
        r=auth_post(c,'/api/login',{'username':'recon23a','password':'SecurePassword@12345'})
        assert r.status_code==200
        report=c.get('/api/reconciliation').json()
        assert report['summary']['wallet_count']==2
        assert report['summary']['checked_wallets']==2
        assert report['summary']['latest_discrepancies']==1
        quiet_row=next(row for row in report['wallets'] if row['id']==quiet.id)
        assert quiet_row['last_check']['difference']==1000
        assert len(report['checks'])==60


# v1.0.24: annual report is read-only and supports year-specific exports.
def test_annual_finances_and_exports_no_side_effects(client):
    from io import BytesIO
    from openpyxl import load_workbook
    with TestClient(app) as c:
        res=auth_post(c, '/api/login', {'username':'recon23a','password':'SecurePassword@12345'})
        assert res.status_code==200,res.text
        before=c.get('/api/dashboard?month=2026-11').json()
        result=c.get('/api/reports/annual?year=2026')
        assert result.status_code==200,result.text
        obj=result.json()
        assert obj['year']==2026 and obj['monthly']
        assert len(obj['monthly'])==11
        assert obj['monthly'][-1]['month']=='2026-11'
        assert obj['totals']['income']==sum(m['income'] for m in obj['monthly'])
        assert obj['totals']['expense']==sum(m['expense'] for m in obj['monthly'])
        assert obj['totals']['net_cash']==obj['totals']['income']-obj['totals']['expense']-obj['totals']['debt_paid']+obj['totals']['debt_collected']
        assert obj['closing']['net_worth']==obj['closing']['assets']+obj['closing']['receivable']-obj['closing']['payable']
        assert obj['closing']['net_worth']==before['net_worth']
        assert 'no-store' in result.headers['cache-control']
        excel=c.get('/api/reports/annual.xlsx?year=2026')
        assert excel.status_code==200 and excel.content[:2]==b'PK'
        w=load_workbook(BytesIO(excel.content),read_only=True,data_only=False)
        assert w.sheetnames==['Tong quan nam','Bien dong 12 thang']
        assert w.worksheets[1].max_row==12
        w.close()
        pdf=c.get('/api/reports/annual.pdf?year=2026')
        assert pdf.status_code==200 and pdf.content.startswith(b'%PDF')
        assert c.get('/api/reports/annual?year=2027').status_code==422
        assert c.get('/api/reports/annual?year=1999').status_code==422
        after=c.get('/api/dashboard?month=2026-11').json()
        assert (before['balance'],before['net_worth'])==(after['balance'],after['net_worth'])
    with TestClient(app) as anonymous:
        assert anonymous.get('/api/reports/annual?year=2026').status_code==401
        assert anonymous.get('/api/reports/annual.pdf?year=2026').status_code==401
    with TestClient(app) as other:
        r=auth_post(other,'/api/login',{'username':'recon23b','password':'SecurePassword@12345'})
        assert r.status_code==200
        other_data=other.get('/api/reports/annual?year=2026').json()
        assert other_data['totals']['income']!=obj['totals']['income']


def test_pwa_static_is_public_only(client):
    """Install assets are explicitly allowlisted and do not reveal sensitive data."""
    import json
    from PIL import Image
    from io import BytesIO
    manifest_response = client.get('/manifest.webmanifest')
    assert manifest_response.status_code == 200
    assert 'application/manifest+json' in manifest_response.headers['content-type']
    manifest=json.loads(manifest_response.text)
    assert manifest['start_url']=='/' and manifest['scope']=='/'
    assert manifest['display']=='standalone'
    assert {x['sizes'] for x in manifest['icons']}=={'192x192','512x512'}
    assert any(icon.get('purpose')=='maskable' for icon in manifest['icons'])
    assert client.get('/icon-512-maskable.png').status_code == 200
    for size in [192,512]:
        response=client.get(f'/icon-{size}.png')
        assert response.status_code==200
        assert Image.open(BytesIO(response.content)).size==(size,size)
    for path in ['/pwa.js','/sw.js','/offline.html']:
        response=client.get(path)
        assert response.status_code==200
        assert response.headers.get('cache-control')=='no-store'
        assert 'nosniff'==response.headers.get('x-content-type-options')
    assert client.get('/sw.js').headers['service-worker-allowed']=='/'
    sw=client.get('/sw.js').text
    assert "url.pathname.startsWith('/api/')" in sw
    assert "url.pathname === '/reset'" in sw
    assert 'index.html' not in sw
    assert client.get('/backend/app.py').status_code==404
    assert client.get('/.env').status_code==404
    assert client.get('/frontend/pwa.js').status_code==404
    home=client.get('/').text
    assert 'rel="manifest"' in home
    assert '/pwa.js?v=1.0.29' in home
    assert '/app.js?v=1.0.29' in home


# v1.0.27: personalized suggestions & insights are owner-scoped, read-only heuristics.
def test_v126_suggestions_and_spending_privacy(client):
    from backend.app import (SessionLocal, User, Wallet, Category, Entry,
                             seed_categories, ph, add_months_clamped)
    from sqlalchemy import select
    from datetime import date
    now=date.today()
    with SessionLocal.begin() as db:
        created=[]
        for username in ('smart26a', 'smart26b'):
            user=User(username=username, display_name=username,
                      email=username+'@example.com', password_hash=ph.hash('SecurePassword@12345'),
                      role='member',active=True,opening_balance=0)
            db.add(user);db.flush()
            seed_categories(db,user)
            db.add(Wallet(user_id=user.id,name='Ví thử',kind='cash',opening_balance=80_000_000,
                          active=True,is_default=True))
            created.append(user.id)
    with TestClient(app) as a, TestClient(app) as b:
        assert auth_post(a,'/api/login',{'username':'smart26a','password':'SecurePassword@12345'}).status_code==200
        assert auth_post(b,'/api/login',{'username':'smart26b','password':'SecurePassword@12345'}).status_code==200
        a_categories=a.get('/api/categories').json()
        eat=next(c for c in a_categories if c['name']=='Ăn uống' and c['kind']=='expense')
        bills=next(c for c in a_categories if c['name']=='Hóa đơn' and c['kind']=='expense')
        a_wallet=a.get('/api/wallets').json()['items'][0]
        b_categories=b.get('/api/categories').json()
        b_expense=next(c for c in b_categories if c['kind']=='expense')
        b_wallet=b.get('/api/wallets').json()['items'][0]
        for shift in (-3,-2,-1):
            on=add_months_clamped(date(now.year,now.month,15),shift).isoformat()
            for title,cat,amount in [('Điện nước căn hộ',bills,220000),('Cơm văn phòng',eat,120000)]:
                data={'title':title,'kind':'expense','amount':amount,'occurred_on':on,
                      'category_id':cat['id'],'wallet_id':a_wallet['id']}
                res=auth_post(a,'/api/transactions',data,csrf=a.get('/api/me').json()['csrf_token'])
                assert res.status_code==200,res.text
        other_data={'title':'Điện nước căn hộ','kind':'expense','amount':100000,
                    'occurred_on':now.isoformat(),'category_id':b_expense['id'],
                    'wallet_id':b_wallet['id']}
        assert auth_post(b,'/api/transactions',other_data,
                         csrf=b.get('/api/me').json()['csrf_token']).status_code==200
        before=a.get('/api/dashboard?month='+now.strftime('%Y-%m')).json()['balance']
        search=a.get('/api/insights/category-suggestions',params={'title':'dien nuoc can ho','kind':'expense'})
        assert search.status_code==200,search.text
        assert search.json()['items'][0]['category_id']==bills['id']
        assert search.json()['items'][0]['examples']==3
        assert a.get('/api/insights/category-suggestions',params={'title':'x','kind':'expense'}).json()['items']==[]
        assert a.get('/api/insights/category-suggestions',params={'title':'dien nuoc can ho','kind':'income'}).json()['items']==[]
        assert a.get('/api/insights/category-suggestions',params={'title':'test','kind':'x'}).status_code==422
        assert a.get('/api/insights/category-suggestions',params={'title':'q'*130}).status_code==422
        assert a.get('/api/insights/category-suggestions',params={'title':'abc','limit':99}).status_code==422
        report=a.get('/api/insights/spending?months=6')
        assert report.status_code==200,report.text
        result=report.json()
        assert result['total_expense']==(220000+120000)*3
        assert result['transaction_count']==6
        assert result['monthly'][-1]['partial'] is True
        assert result['recurring_candidates'] and any(x['title']=='Điện nước căn hộ' and x['consecutive_months']>=3 for x in result['recurring_candidates'])
        assert a.get('/api/dashboard?month='+now.strftime('%Y-%m')).json()['balance']==before
        assert b.get('/api/insights/spending?months=6').json()['transaction_count']==1
        assert b.get('/api/insights/category-suggestions',params={'title':'Com van phong'}).json()['items']==[]
        assert a.get('/api/insights/spending?months=48').status_code==422
    with TestClient(app) as unknown:
        assert unknown.get('/api/insights/spending').status_code==401
        assert unknown.get('/api/insights/category-suggestions?title=DIEN').status_code==401


def test_v126_normalization_confidence_recurring_and_alert_logic():
    from backend.insights import score_titles, suggest_categories, spending_insights, normalize_title
    from datetime import date
    assert normalize_title('  Điện, NƯỚC  ')=='dien nuoc'
    assert score_titles('Điện nước căn hộ','dien nuoc can ho')==1
    assert score_titles('Uber','Bệnh viện')==0
    assert suggest_categories('random',[],{})==[]
    cats={1:{'name':'Hóa đơn','color':'#123456','active':True},2:{'name':'Không hoạt động','color':'#123456','active':False}}
    assert suggest_categories('dien nuoc',[{'title':'Điện nước','category_id':2}],cats)==[]
    rows=[]
    for month in (7,8,9,10):
        rows += [{'kind':'expense','title':'Cước mạng wifi','amount':200000,'category_id':1,'wallet_id':4,'occurred_on':date(2026,month,15)}]
    report=spending_insights(rows,cats,[],date(2026,11,6),6)
    assert report['recurring_candidates'][0]['months_seen']==4
    assert report['current_month_projection']==0
    scheduled=[{'title':'Cước mạng wifi','kind':'expense','category_id':1,'wallet_id':4,'active':True}]
    assert spending_insights(rows,cats,scheduled,date(2026,11,6),6)['recurring_candidates']==[]
    # More than 8000 expense records suppresses the risk alerts/repetition advice.
    limited=spending_insights(rows,cats,[],date(2026,11,6),6,sample_limited=True)
    assert limited['sample_limited'] and not limited['recurring_candidates'] and not limited['alerts']
    suspicious=[]
    for month in (8,9,10):
        suspicious.append({'kind':'expense','title':f'Mua luong thuc {month}', 'amount':200000,
                           'category_id':1,'wallet_id':4,'occurred_on':date(2026,month,15)})
    suspicious.append({'kind':'expense','title':'Mua luong thuc 11','amount':500000,
                       'category_id':1,'wallet_id':4,'occurred_on':date(2026,11,2)})
    r=spending_insights(suspicious,cats,[],date(2026,11,6),4)
    assert r['alerts'] and r['alerts'][0]['projected_monthly']>r['alerts'][0]['baseline_monthly']
    assert r['previous_month_average']==200000


def test_v128_optional_income_debt_percent_interest_and_wallet_removal(client):
    """v1.0.29: opt-in debt, manual interest in %, safe empty-wallet deletion."""
    admin_login=auth_post(client,'/api/login',{'username':'owner','password':'SecurePassword@12345'})
    assert admin_login.status_code==200
    username='v128'+uuid4().hex[:10]
    assert auth_post(client,'/api/users',credentials(username),csrf=admin_login.json()['csrf_token']).status_code==200
    login=auth_post(client,'/api/login',{'username':username,'password':'SecurePassword@12345'})
    assert login.status_code==200
    csrf=login.json()['csrf_token']
    assert client.get('/api/me').json()['user']['auto_repay_debts'] is False
    wid=client.get('/api/wallets').json()['items'][0]['id']
    assert auth_post(client,f'/api/wallets/{wid}',csrf=csrf,method='delete').status_code==409
    assert auth_post(client,'/api/opening-balance',{'opening_balance':1000000},csrf=csrf,method='put').status_code==200
    inc=next(c['id'] for c in client.get('/api/categories').json() if c['kind']=='income')
    loan=auth_post(client,'/api/debts',{'name':'Khoản nợ thử nghiệm','principal':300000},csrf=csrf)
    assert loan.status_code==200,loan.text
    did=loan.json()['id']
    def income(amount):
        return {'title':'Tiền lương','kind':'income','amount':amount,'category_id':inc,
                'wallet_id':wid,'occurred_on':'2026-11-09'}
    first=auth_post(client,'/api/transactions',income(500000),csrf=csrf)
    assert first.status_code==200 and first.json()['debt_paid']==0,first.text
    assert client.get('/api/debts').json()['total_remaining']==300000
    assert client.get('/api/wallets').json()['total_balance']==1500000
    assert auth_post(client,'/api/settings/auto-debt',{'enabled':'true'},csrf=csrf,method='put').status_code==422
    enabled=auth_post(client,'/api/settings/auto-debt',{'enabled':True},csrf=csrf,method='put')
    assert enabled.status_code==200 and enabled.json()['auto_repay_debts'] is True
    second=auth_post(client,'/api/transactions',income(200000),csrf=csrf)
    assert second.status_code==200 and second.json()['debt_paid']==200000,second.text
    assert client.get('/api/debts').json()['total_remaining']==100000
    assert client.get('/api/wallets').json()['total_balance']==1500000
    disabled=auth_post(client,'/api/settings/auto-debt',{'enabled':False},csrf=csrf,method='put')
    assert disabled.status_code==200
    third=auth_post(client,'/api/transactions',income(100000),csrf=csrf)
    assert third.status_code==200 and third.json()['debt_paid']==0
    assert client.get('/api/wallets').json()['total_balance']==1600000
    assert client.get('/api/debts').json()['total_remaining']==100000
    # Interest percent is on the principal of *this payment*, not on the annual rate.
    invalid=auth_post(client,f'/api/debts/{did}/payments',
          {'amount':100000,'interest_rate_pct':'10.00','interest_amount':1000,'wallet_id':wid},csrf=csrf)
    assert invalid.status_code==422
    paid=auth_post(client,f'/api/debts/{did}/payments',
         {'amount':100000,'interest_rate_pct':'10.00','wallet_id':wid,'paid_on':'2026-11-09'},csrf=csrf)
    assert paid.status_code==200,paid.text
    d=client.get('/api/debts').json()
    assert d['total_remaining']==0
    latest=next(x for x in d['payments'] if x['mode']=='manual' and x['debt_id']==did)
    assert latest['amount']==100000 and latest['interest_amount']==10000
    assert client.get('/api/wallets').json()['total_balance']==1490000
    assert auth_post(client,'/api/wallets',{'name':'Ví có tiền','opening_balance':200},csrf=csrf).status_code==200
    with_funds=next(x for x in client.get('/api/wallets').json()['items'] if x['name']=='Ví có tiền')
    assert auth_post(client,f"/api/wallets/{with_funds['id']}",csrf=csrf,method='delete').status_code==409
    empty=auth_post(client,'/api/wallets',{'name':'Ví phụ trống','opening_balance':0},csrf=csrf)
    assert empty.status_code==200
    empty_id=empty.json()['id']
    assert auth_post(client,f'/api/wallets/{empty_id}',csrf=csrf,method='delete').status_code==200
    assert all(w['id']!=empty_id for w in client.get('/api/wallets').json()['items'])
    once=auth_post(client,'/api/wallets',{'name':'Ví có chuyển tiền','opening_balance':0},csrf=csrf)
    assert once.status_code==200
    transfer=auth_post(client,'/api/wallet-transfers',{'from_wallet_id':wid,'to_wallet_id':once.json()['id'],
        'amount':1000,'occurred_on':'2026-11-09'},csrf=csrf)
    assert transfer.status_code==200
    assert auth_post(client,f'/api/wallet-transfers/{transfer.json()["id"]}',csrf=csrf,method='delete').status_code==200
    assert auth_post(client,f"/api/wallets/{once.json()['id']}",csrf=csrf,method='delete').status_code==200  # undone transfer removed from ledger


def test_v128_stash_keeps_wallet_minimum(client):
    """Deposit is capped to protect living funds, including between multiple rules."""
    admin=auth_post(client,'/api/login',{'username':'owner','password':'SecurePassword@12345'})
    username='v128stash'+uuid4().hex[:8]
    assert auth_post(client,'/api/users',credentials(username),csrf=admin.json()['csrf_token']).status_code==200
    login=auth_post(client,'/api/login',{'username':username,'password':'SecurePassword@12345'})
    assert login.status_code==200
    csrf=login.json()['csrf_token']
    wid=client.get('/api/wallets').json()['items'][0]['id']
    assert auth_post(client,'/api/opening-balance',{'opening_balance':100000},csrf=csrf,method='put').status_code==200
    # Never reserve money below a 100,000 minimum, even across two funds.
    bad=auth_post(client,'/api/stashes',{'name':'Sai','auto_mode':'off','auto_value':0,
                  'min_wallet_balance':1000},csrf=csrf)
    assert bad.status_code==422
    for n in ('Quỹ A','Quỹ B'):
        r=auth_post(client,'/api/stashes',{'name':n,'auto_mode':'fixed','auto_value':200000,
                  'min_wallet_balance':100000},csrf=csrf)
        assert r.status_code==200,r.text
    inc=next(c['id'] for c in client.get('/api/categories').json() if c['kind']=='income')
    r=auth_post(client,'/api/transactions',{'title':'Thưởng','kind':'income','amount':250000,
         'wallet_id':wid,'category_id':inc,'occurred_on':'2026-11-09'},csrf=csrf)
    assert r.status_code==200,r.text
    assert r.json()['debt_paid']==0 and r.json()['auto_saved']==250000
    assert client.get('/api/wallets').json()['total_balance']==100000
    assert client.get('/api/stashes').json()['total_saved']==250000
    assert client.get('/api/dashboard?month=2026-11').json()['total_assets']==350000


def test_v129_undo_auto_debt_payment_restores_principal_and_cash(client):
    """Deleting auto payment restores principal/cash but NOT original income.

    Mirrors a 3,020,582 VND auto payment against a debt with 20m remaining.
    """
    owner = auth_post(client, '/api/login', {'username':'owner','password':'SecurePassword@12345'})
    assert owner.status_code == 200
    name='v129'+uuid4().hex[:10]
    assert auth_post(client,'/api/users',credentials(name),csrf=owner.json()['csrf_token']).status_code==200
    login=auth_post(client,'/api/login',{'username':name,'password':'SecurePassword@12345'})
    csrf=login.json()['csrf_token']
    assert client.get('/api/me').json()['user']['auto_repay_debts'] is False
    wallet=client.get('/api/wallets').json()['items'][0]['id']
    inc=next(x['id'] for x in client.get('/api/categories').json() if x['kind']=='income')
    exp=next(x['id'] for x in client.get('/api/categories').json() if x['kind']=='expense')
    loan=auth_post(client,'/api/debts',{'name':'Mua feliz 2025','principal':23020582},csrf=csrf)
    assert loan.status_code==200,loan.text
    loan_id=loan.json()['id']
    assert auth_post(client,'/api/settings/auto-debt',{'enabled':True},csrf=csrf,method='put').status_code==200
    income={'title':'Lương tháng','kind':'income','amount':3020582,'wallet_id':wallet,
            'category_id':inc,'occurred_on':'2026-10-23'}
    r=auth_post(client,'/api/transactions',income,csrf=csrf)
    assert r.status_code==200 and r.json()['debt_paid']==3020582,r.text
    income_id=r.json()['id']
    debts=client.get('/api/debts').json()
    assert debts['total_remaining']==20000000 and debts['total_paid']==3020582
    assert client.get('/api/wallets').json()['total_balance']==0
    payment=next(p for p in debts['payments'] if p['entry_id']==income_id)
    assert payment['mode']=='auto' and payment['amount']==3020582
    # Another authenticated account may not reverse this owner's payment.
    owner_again=auth_post(client,'/api/login',{'username':'owner','password':'SecurePassword@12345'})
    denied=auth_post(client,f'/api/debt-payments/{payment["id"]}',csrf=owner_again.json()['csrf_token'],method='delete')
    assert denied.status_code==404
    login=auth_post(client,'/api/login',{'username':name,'password':'SecurePassword@12345'})
    csrf=login.json()['csrf_token']
    response=auth_post(client,f'/api/debt-payments/{payment["id"]}',csrf=csrf,method='delete')
    assert response.status_code==200,response.text
    outcome=response.json()
    assert outcome['source_income_kept'] is True
    assert outcome['restored_principal']==3020582
    assert outcome['new_remaining']==23020582
    assert outcome['wallet_delta']==3020582 and outcome['wallet_balance']==3020582
    assert client.get('/api/debts').json()['total_paid']==0
    assert client.get('/api/wallets').json()['total_balance']==3020582
    ledger=client.get('/api/debts').json()
    assert not any(p['id']==payment['id'] for p in ledger['payments'])
    assert len([p for p in ledger['reversals'] if p['original_payment_id']==payment['id']])==1
    assert next(p for p in ledger['reversals'] if p['original_payment_id']==payment['id'])['entry_id']==income_id
    transactions=client.get('/api/transactions?month=2026-10').json()['items']
    assert any(e['id']==income_id and e['kind']=='income' and e['amount']==3020582 for e in transactions)
    assert client.get('/api/dashboard?month=2026-10').json()['month_income']==3020582
    # A double-click/retry without a payment cannot refund any more cash.
    assert auth_post(client,f'/api/debt-payments/{payment["id"]}',csrf=csrf,method='delete').status_code==404
    assert client.get('/api/wallets').json()['total_balance']==3020582
    # Manual interest is also reversed from the wallet, but only principal restores debt.
    manual=auth_post(client,f'/api/debts/{loan_id}/payments',
       {'amount':1000000,'interest_rate_pct':10,'wallet_id':wallet,'paid_on':'2026-11-09'},csrf=csrf)
    assert manual.status_code==200,manual.text
    assert client.get('/api/wallets').json()['total_balance']==1920582
    mp=next(p for p in client.get('/api/debts').json()['payments'] if p['mode']=='manual' and p['debt_id']==loan_id)
    assert mp['interest_amount']==100000
    reversed_manual=auth_post(client,f'/api/debt-payments/{mp["id"]}',csrf=csrf,method='delete')
    assert reversed_manual.status_code==200,reversed_manual.text
    assert reversed_manual.json()['restored_principal']==1000000
    assert reversed_manual.json()['reversed_interest']==100000
    assert reversed_manual.json()['wallet_delta']==1100000
    assert client.get('/api/debts').json()['total_interest_paid']==0
    assert client.get('/api/wallets').json()['total_balance']==3020582
    # Receivable undo must not make a wallet negative or create an audit reversal.
    owed=auth_post(client,'/api/debts',{'name':'Tiền cho vay','direction':'receivable','principal':100000},csrf=csrf)
    assert owed.status_code==200
    rid=owed.json()['id']
    got=auth_post(client,f'/api/debts/{rid}/payments',
       {'amount':100000,'interest_rate_pct':0,'wallet_id':wallet,'paid_on':'2026-11-09'},csrf=csrf)
    assert got.status_code==200,got.text
    recv_p=next(p for p in client.get('/api/debts').json()['payments'] if p['debt_id']==rid)
    paid_out=auth_post(client,'/api/transactions',
       {'title':'Đã sử dụng tiền','kind':'expense','amount':3020582,'wallet_id':wallet,
        'category_id':exp,'occurred_on':'2026-11-09'},csrf=csrf)
    assert paid_out.status_code==200,paid_out.text
    assert client.get('/api/wallets').json()['total_balance']==100000
    assert auth_post(client,f'/api/debt-payments/{recv_p["id"]}',csrf=csrf,method='delete').status_code==200
    # Recreate and spend all cash so that undo cannot remove the collected 100k.
    got=auth_post(client,f'/api/debts/{rid}/payments',
       {'amount':100000,'interest_rate_pct':0,'wallet_id':wallet,'paid_on':'2026-11-09'},csrf=csrf)
    assert got.status_code==200,got.text
    current=next(p for p in client.get('/api/debts').json()['payments'] if p['debt_id']==rid)
    spent=auth_post(client,'/api/transactions',
       {'title':'Chi tiêu sau thu hồi','kind':'expense','amount':100000,'wallet_id':wallet,
        'category_id':exp,'occurred_on':'2026-11-09'},csrf=csrf)
    assert spent.status_code==200,spent.text
    assert client.get('/api/wallets').json()['total_balance']==0
    num_reversals=len(client.get('/api/debts').json()['reversals'])
    cannot=auth_post(client,f'/api/debt-payments/{current["id"]}',csrf=csrf,method='delete')
    assert cannot.status_code==409,cannot.text
    assert client.get('/api/debts').json()['total_receivable_remaining']==0
    assert len(client.get('/api/debts').json()['reversals'])==num_reversals
    assert auth_post(client,f'/api/transactions/{spent.json()["id"]}',csrf=csrf,method='delete').status_code==200
    assert auth_post(client,f'/api/debt-payments/{current["id"]}',csrf=csrf,method='delete').status_code==200
    assert client.get('/api/debts').json()['total_receivable_remaining']==100000
    # Original income remains deletable after its auto payment was manually reversed.
    assert auth_post(client,f'/api/transactions/{paid_out.json()["id"]}',csrf=csrf,method='delete').status_code==200
    assert auth_post(client,f'/api/transactions/{income_id}',csrf=csrf,method='delete').status_code==200
    assert client.get('/api/debts').json()['total_remaining']==23020582
    assert client.get('/api/wallets').json()['total_balance']==0
