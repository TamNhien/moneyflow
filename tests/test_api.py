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
    assert auth_post(client,'/api/users',credentials('member'),csrf=token).status_code==200
    assert auth_post(client,'/api/users',{**credentials('another'),'email':'member@example.com'},csrf=token).status_code==409
    users=client.get('/api/users').json();member=next(x for x in users if x['username']=='member')
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
