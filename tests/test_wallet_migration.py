"""End-to-end migration test for a real pre-wallet schema (v1.0.10 compatible)."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys


def test_legacy_wallet_migration_is_idempotent(tmp_path):
    db_file = tmp_path / 'old_version.sqlite'
    connection = sqlite3.connect(db_file)
    connection.executescript('''
      CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(32), display_name VARCHAR(80), email VARCHAR(254), phone VARCHAR(20), address VARCHAR(300), password_hash TEXT NOT NULL, role VARCHAR(12), active BOOLEAN, opening_balance BIGINT NOT NULL, failed_attempts INT, locked_until DATETIME, created_at DATETIME);
      CREATE TABLE categories (id INTEGER PRIMARY KEY, user_id INTEGER, name VARCHAR(60), kind VARCHAR(10), color VARCHAR(7), active BOOLEAN);
      CREATE TABLE entries (id INTEGER PRIMARY KEY, user_id INTEGER,kind VARCHAR(10),title VARCHAR(120),amount BIGINT,category_id INT,note VARCHAR(500),occurred_on DATE,created_at DATETIME);
      CREATE TABLE debts (id INTEGER PRIMARY KEY,user_id INTEGER,name VARCHAR(120),lender VARCHAR(120),principal BIGINT,remaining BIGINT,due_date DATE,note VARCHAR(500),created_at DATETIME);
      CREATE TABLE debt_payments (id INTEGER PRIMARY KEY,user_id INTEGER,debt_id INTEGER,entry_id INTEGER,amount BIGINT,mode VARCHAR(10),paid_on DATE,created_at DATETIME);
      INSERT INTO users (id,username,display_name,password_hash,role,active,opening_balance,failed_attempts,created_at)
        VALUES(20,'legacy','Legacy','hash','member',1,100000,0,'2026-01-01');
      INSERT INTO categories (id,user_id,name,kind,color,active)
        VALUES (1,20,'Lương','income','#777777',1),(2,20,'Ăn uống','expense','#888888',1);
      INSERT INTO entries (id,user_id,kind,title,amount,category_id,note,occurred_on,created_at)
        VALUES (11,20,'income','Salary',20000,1,'','2026-01-02','2026-01-02'),
               (12,20,'expense','Food',10000,2,'','2026-01-03','2026-01-03');
      INSERT INTO debts(id,user_id,name,principal,remaining,created_at)
        VALUES(4,20,'Loan',15000,10000,'2026-01-01');
      INSERT INTO debt_payments (id,user_id,debt_id,entry_id,amount,mode,paid_on,created_at)
        VALUES(6,20,4,11,5000,'auto','2026-01-02','2026-01-02');
    ''')
    connection.commit()
    connection.close()
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, 'DATABASE_URL': 'sqlite:///' + str(db_file), 'PYTHONPATH': str(root)}
    script = '''from fastapi.testclient import TestClient
from backend.app import app, SessionLocal, Wallet, Entry, Debt, DebtPayment, wallet_balance, current_balance, debt_schedule_rows, RecurringRule, RecurringRun, SavingsGoal, SavingsMovement, WalletReconciliation, FinancialOperation, TransactionRevision
from sqlalchemy import select
with TestClient(app):
 with SessionLocal() as db:
  wallets=list(db.scalars(select(Wallet).where(Wallet.user_id==20)))
  assert len(wallets)==1 and wallets[0].is_default and wallets[0].opening_balance==100000
  assert all(e.wallet_id==wallets[0].id for e in db.scalars(select(Entry)))
  assert all(p.wallet_id==wallets[0].id for p in db.scalars(select(DebtPayment)))
  assert wallet_balance(db,wallets[0])==105000
  assert current_balance(db,20)[0]==105000
  d=db.scalar(select(Debt).where(Debt.id==4))
  assert d.direction=='payable' and d.annual_rate_bps==0 and d.installment_count==1
  assert debt_schedule_rows(d)[0]['principal']==15000
  assert list(db.scalars(select(RecurringRule)))==[]
  assert list(db.scalars(select(RecurringRun)))==[]
  assert list(db.scalars(select(SavingsGoal)))==[]
  assert list(db.scalars(select(SavingsMovement)))==[]
  assert list(db.scalars(select(WalletReconciliation)))==[]
  assert list(db.scalars(select(FinancialOperation)))==[]
  assert list(db.scalars(select(TransactionRevision)))==[]
  p=db.scalar(select(DebtPayment).where(DebtPayment.id==6))
  assert p.interest_amount==0
'''
    for _ in range(2):
        result = subprocess.run([sys.executable, '-c', script], cwd=root,
                                env=env, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stdout + '\n' + result.stderr


def test_v115_user_and_session_columns_upgrade_without_data_loss(tmp_path):
    """Regression: PostgreSQL/SQLite v1.0.15 users and auth_sessions had no 2FA fields."""
    database = tmp_path / 'v115_existing.sqlite'
    con=sqlite3.connect(database)
    con.executescript('''
      CREATE TABLE users (
       id INTEGER PRIMARY KEY, username VARCHAR(32), display_name VARCHAR(80),
       email VARCHAR(254), phone VARCHAR(20), address VARCHAR(300),
       password_hash TEXT NOT NULL, role VARCHAR(12), active BOOLEAN,
       opening_balance BIGINT NOT NULL, failed_attempts INTEGER,
       locked_until DATETIME, created_at DATETIME);
      CREATE TABLE auth_sessions (
       id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
       token_hash VARCHAR(64), csrf_token VARCHAR(64), expires_at DATETIME);
      INSERT INTO users VALUES (33,'existing','Existing','existing@example.com',
       '0901234567','HCM','hashed','member',1,250000,0,NULL,'2026-11-01');
      INSERT INTO auth_sessions VALUES (55,33,'abc','csrf','2099-01-01');
    ''')
    con.commit(); con.close()
    root=Path(__file__).resolve().parents[1]
    env={**os.environ,'DATABASE_URL':'sqlite:///'+str(database),'PYTHONPATH':str(root)}
    code='''from fastapi.testclient import TestClient
from sqlalchemy import select
from backend.app import app,SessionLocal,User,AuthSession,Wallet,SavingsGoal,SavingsMovement
with TestClient(app):
 with SessionLocal() as db:
  u=db.get(User,33)
  assert u.username=='existing' and u.opening_balance==250000 and u.totp_secret is None
  assert u.totp_last_step==-1 and u.totp_failed_attempts==0
  old=db.get(AuthSession,55)
  assert old.user_id==33
  assert old.user_agent==''
  assert len(list(db.scalars(select(Wallet).where(Wallet.user_id==33))))==1
  assert list(db.scalars(select(SavingsGoal)))==[] and list(db.scalars(select(SavingsMovement)))==[]
'''
    for _ in range(2):
        result=subprocess.run([sys.executable,'-c',code],cwd=root,env=env,capture_output=True,text=True,timeout=30)
        assert result.returncode==0,result.stdout+'\n'+result.stderr


def test_v119_stash_auto_columns_are_added_without_resetting_funds(tmp_path):
    """v1.0.20 upgrade retains old money movements and remains idempotent."""
    db_file=tmp_path/'v119_existing.sqlite'
    con=sqlite3.connect(db_file)
    con.executescript('''
      CREATE TABLE stash_funds (id INTEGER PRIMARY KEY,user_id INTEGER,name VARCHAR(120),note VARCHAR(300),created_at DATETIME);
      CREATE TABLE stash_movements (id INTEGER PRIMARY KEY,user_id INTEGER,fund_id INTEGER,wallet_id INTEGER,kind VARCHAR(10),amount BIGINT,occurred_on DATE,note VARCHAR(300),created_at DATETIME);
      INSERT INTO stash_funds VALUES(7,1,'Quỹ cũ','Dữ liệu gốc','2026-11-02');
      INSERT INTO stash_movements VALUES(11,1,7,1,'deposit',300000,'2026-11-02','Trước khi nâng cấp','2026-11-02');
    ''')
    con.commit();con.close()
    root=Path(__file__).resolve().parents[1]
    env={**os.environ,'DATABASE_URL':'sqlite:///'+str(db_file),'PYTHONPATH':str(root)}
    code='''from fastapi.testclient import TestClient
from backend.app import app, SessionLocal, StashFund, StashMovement
with TestClient(app):
 with SessionLocal() as db:
  fund=db.get(StashFund,7)
  assert fund.name=='Quỹ cũ' and fund.auto_mode=='off' and fund.auto_value==0 and fund.auto_wallet_id is None
  m=db.get(StashMovement,11)
  assert m.amount==300000 and m.source_entry_id is None
'''
    for _ in range(2):
        result=subprocess.run([sys.executable,'-c',code],cwd=root,env=env,capture_output=True,text=True,timeout=30)
        assert result.returncode==0,result.stdout+'\n'+result.stderr
    with sqlite3.connect(db_file) as con:
        assert con.execute('SELECT COUNT(*) FROM stash_movements').fetchone()[0]==1
        assert con.execute('SELECT COUNT(*) FROM stash_funds').fetchone()[0]==1
        assert con.execute("SELECT count(*) FROM sqlite_master WHERE type='index' AND name='uq_stash_auto_entry_fund'").fetchone()[0]==1



def test_v129_reversals_acquire_cash_policy_without_changing_refunds(tmp_path):
    """Existing v1.0.29 refunds must NOT automatically turn into principal-only."""
    db_file=tmp_path/'v129_reversals.sqlite'
    con=sqlite3.connect(db_file)
    con.executescript('''
      CREATE TABLE debt_payment_reversals (
        id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, original_payment_id INTEGER NOT NULL,
        debt_id INTEGER NOT NULL, debt_name VARCHAR(120) NOT NULL,
        wallet_id INTEGER, entry_id INTEGER, principal_amount BIGINT NOT NULL,
        interest_amount BIGINT NOT NULL DEFAULT 0, mode VARCHAR(10) NOT NULL,
        direction VARCHAR(12) NOT NULL, paid_on DATE NOT NULL, reversed_at DATETIME);
      INSERT INTO debt_payment_reversals VALUES
        (77,10,88,99,'Mua feliz',1,100,3020582,0,'auto','payable','2026-10-23','2026-11-09');
    ''')
    con.commit();con.close()
    root=Path(__file__).resolve().parents[1]
    env={**os.environ,'DATABASE_URL':'sqlite:///'+str(db_file),'PYTHONPATH':str(root)}
    code='''from fastapi.testclient import TestClient
from backend.app import app, SessionLocal, DebtPaymentReversal
with TestClient(app):
 with SessionLocal() as db:
  item=db.get(DebtPaymentReversal,77)
  assert item.principal_amount==3020582
  assert item.cash_handling=='refund' and item.cash_adjustment==0
  assert item.cash_corrected_at is None
'''
    for _ in range(2):
        proc=subprocess.run([sys.executable,'-c',code],cwd=root,env=env,
                            capture_output=True,text=True,timeout=30)
        assert proc.returncode==0,proc.stdout+'\n'+proc.stderr
