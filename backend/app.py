"""MoneyFlow local-first finance application API (single-origin FastAPI)."""
import csv
import base64
import hmac
import struct
import time
from urllib.parse import quote
import asyncio
import logging
import hashlib
import io
import json
import os
import re
import secrets
import smtplib
import ssl
from email.message import EmailMessage
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from calendar import monthrange
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Literal

from cryptography.fernet import Fernet, InvalidToken
import qrcode
from argon2 import PasswordHasher, Type
from argon2.exceptions import VerifyMismatchError, VerificationError
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, func, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.exc import IntegrityError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

DATABASE_URL = os.environ['DATABASE_URL']
IS_POSTGRES = DATABASE_URL.startswith('postgresql')
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args={} if IS_POSTGRES else {'check_same_thread': False})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2, hash_len=32, salt_len=16, type=Type.ID)
COOKIE = 'mf_session'
MAX_AMOUNT = 1_000_000_000_000
LOGIN_FAILURE_LIMIT = 5
PASSWORD_RULE = 'Mật khẩu cần 12-128 ký tự, có chữ hoa, chữ thường, số và ký tự đặc biệt.'
USER_PATTERN = re.compile(r'^[a-z0-9_.-]{3,32}$')
PHONE_PATTERN = re.compile(r'^\+?[0-9]{9,15}$')
EMAIL_PATTERN = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
RESET_MINUTES = 15
RESET_COOLDOWN_SECONDS = 60
RESET_HOURLY_LIMIT = 3
MONTH_PATTERN = re.compile(r'^\d{4}-(0[1-9]|1[0-2])$')
COLORS = ['#7567F8', '#00BFA6', '#FFB870', '#FC6B88', '#53B6FD', '#9875E8', '#9BD96D', '#FFC85E']
DEFAULT_EXPENSE = ['Ăn uống', 'Mua sắm', 'Di chuyển', 'Hóa đơn', 'Nhà cửa', 'Sức khỏe', 'Giải trí', 'Học tập', 'Khác']
DEFAULT_INCOME = ['Lương', 'Thưởng', 'Kinh doanh', 'Quà tặng', 'Thu khác']


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(80))  # legacy column kept for existing database compatibility
    email: Mapped[str | None] = mapped_column(String(254), unique=True, nullable=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    password_hash: Mapped[str] = mapped_column(Text)
    totp_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    totp_pending: Mapped[str | None] = mapped_column(Text, nullable=True)
    totp_pending_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    totp_last_step: Mapped[int] = mapped_column(Integer, default=-1, server_default="-1")
    totp_failed_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    totp_locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    role: Mapped[str] = mapped_column(String(12), default='member')
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    opening_balance: Mapped[int] = mapped_column(BigInteger, default=0)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    __table_args__ = (CheckConstraint('opening_balance >= 0'),)


class Wallet(Base):
    __tablename__ = 'wallets'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(20), default='cash')
    opening_balance: Mapped[int] = mapped_column(BigInteger, default=0)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    __table_args__ = (CheckConstraint('opening_balance >= 0', name='ck_wallet_opening'),)


class WalletTransfer(Base):
    __tablename__ = 'wallet_transfers'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    from_wallet_id: Mapped[int] = mapped_column(ForeignKey('wallets.id'), index=True)
    to_wallet_id: Mapped[int] = mapped_column(ForeignKey('wallets.id'), index=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    occurred_on: Mapped[date] = mapped_column(Date, index=True)
    note: Mapped[str] = mapped_column(String(300), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    __table_args__ = (CheckConstraint('amount > 0', name='ck_transfer_positive'),
                      CheckConstraint('from_wallet_id <> to_wallet_id', name='ck_transfer_distinct'))


class SavingsGoal(Base):
    """Reserved money is still an asset; it is excluded from spendable wallet funds."""
    __tablename__ = 'savings_goals'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    name: Mapped[str] = mapped_column(String(120))
    target_amount: Mapped[int] = mapped_column(BigInteger)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str] = mapped_column(String(300), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    __table_args__ = (CheckConstraint('target_amount > 0', name='ck_savings_target_positive'),)


class SavingsMovement(Base):
    """Immutable deposit/withdrawal ledger; allocation is not an income/expense."""
    __tablename__ = 'savings_movements'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey('savings_goals.id'), index=True)
    wallet_id: Mapped[int] = mapped_column(ForeignKey('wallets.id'), index=True)
    kind: Mapped[str] = mapped_column(String(10))
    amount: Mapped[int] = mapped_column(BigInteger)
    occurred_on: Mapped[date] = mapped_column(Date, index=True)
    note: Mapped[str] = mapped_column(String(300), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    __table_args__ = (CheckConstraint('amount > 0', name='ck_savings_move_positive'),
                      CheckConstraint("kind IN ('deposit', 'withdraw')", name='ck_savings_move_kind'))


class StashFund(Base):
    """Flexible reserved funds; optional auto-reserve rules on incoming money."""
    __tablename__ = 'stash_funds'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    name: Mapped[str] = mapped_column(String(120))
    note: Mapped[str] = mapped_column(String(300), default='')
    auto_mode: Mapped[str] = mapped_column(String(10), default='off', server_default='off')
    auto_value: Mapped[int] = mapped_column(BigInteger, default=0, server_default='0')
    auto_wallet_id: Mapped[int | None] = mapped_column(ForeignKey('wallets.id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class StashMovement(Base):
    """Immutable deposit/withdrawal ledger; auto allocation references its income entry."""
    __tablename__ = 'stash_movements'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    fund_id: Mapped[int] = mapped_column(ForeignKey('stash_funds.id'), index=True)
    wallet_id: Mapped[int] = mapped_column(ForeignKey('wallets.id'), index=True)
    source_entry_id: Mapped[int | None] = mapped_column(ForeignKey('entries.id'), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(10))
    amount: Mapped[int] = mapped_column(BigInteger)
    occurred_on: Mapped[date] = mapped_column(Date, index=True)
    note: Mapped[str] = mapped_column(String(300), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    __table_args__ = (CheckConstraint('amount > 0', name='ck_stash_move_positive'),
                      CheckConstraint("kind IN ('deposit', 'withdraw')", name='ck_stash_move_kind'))


class Category(Base):
    __tablename__ = 'categories'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    name: Mapped[str] = mapped_column(String(60))
    kind: Mapped[str] = mapped_column(String(10))
    color: Mapped[str] = mapped_column(String(7), default='#7567F8')
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint('user_id','name','kind',name='uq_category_name_kind'),)


class Entry(Base):
    __tablename__ = 'entries'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    kind: Mapped[str] = mapped_column(String(10))
    title: Mapped[str] = mapped_column(String(120))
    amount: Mapped[int] = mapped_column(BigInteger)
    category_id: Mapped[int] = mapped_column(ForeignKey('categories.id'))
    wallet_id: Mapped[int | None] = mapped_column(ForeignKey('wallets.id'), nullable=True, index=True)
    note: Mapped[str] = mapped_column(String(500), default='')
    occurred_on: Mapped[date] = mapped_column(Date, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    __table_args__ = (CheckConstraint('amount > 0'),)


class Debt(Base):
    """Principal still owed. Creating a debt never changes the cash balance."""
    __tablename__ = 'debts'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    name: Mapped[str] = mapped_column(String(120))
    lender: Mapped[str] = mapped_column(String(120), default='')
    principal: Mapped[int] = mapped_column(BigInteger)
    remaining: Mapped[int] = mapped_column(BigInteger)
    direction: Mapped[str] = mapped_column(String(12), default='payable', server_default='payable')
    annual_rate_bps: Mapped[int] = mapped_column(Integer, default=0, server_default='0')
    installment_count: Mapped[int] = mapped_column(Integer, default=1, server_default='1')
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str] = mapped_column(String(500), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    __table_args__ = (CheckConstraint('principal > 0'), CheckConstraint('remaining >= 0'),)


class DebtPayment(Base):
    __tablename__ = 'debt_payments'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    debt_id: Mapped[int] = mapped_column(ForeignKey('debts.id'), index=True)
    entry_id: Mapped[int | None] = mapped_column(ForeignKey('entries.id'), nullable=True, index=True)
    wallet_id: Mapped[int | None] = mapped_column(ForeignKey('wallets.id'), nullable=True, index=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    interest_amount: Mapped[int] = mapped_column(BigInteger, default=0, server_default='0')
    mode: Mapped[str] = mapped_column(String(10))  # auto: from an income; manual: from available balance
    paid_on: Mapped[date] = mapped_column(Date, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    __table_args__ = (CheckConstraint('amount > 0'), CheckConstraint("mode IN ('auto','manual')"),)


class Budget(Base):
    __tablename__ = 'budgets'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey('categories.id'))
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    amount: Mapped[int] = mapped_column(BigInteger)
    __table_args__ = (UniqueConstraint('user_id','category_id','year','month',name='uq_budget_month'), CheckConstraint('amount >= 0'))


class RecurringRule(Base):
    """Scheduled income/expense. One calendar occurrence is processed at most once."""
    __tablename__ = 'recurring_rules'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    wallet_id: Mapped[int] = mapped_column(ForeignKey('wallets.id'), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey('categories.id'))
    title: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(10))
    amount: Mapped[int] = mapped_column(BigInteger)
    note: Mapped[str] = mapped_column(String(500), default='')
    frequency: Mapped[str] = mapped_column(String(10))
    start_on: Mapped[date] = mapped_column(Date)
    next_index: Mapped[int] = mapped_column(Integer, default=0)
    mode: Mapped[str] = mapped_column(String(10), default='manual')
    remind_days: Mapped[int] = mapped_column(Integer, default=3)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    __table_args__ = (CheckConstraint('amount > 0', name='ck_recurring_amount_positive'),
                      CheckConstraint('next_index >= 0', name='ck_recurring_index_nonnegative'),)


class RecurringRun(Base):
    __tablename__ = 'recurring_runs'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey('recurring_rules.id'), index=True)
    due_on: Mapped[date] = mapped_column(Date)
    entry_id: Mapped[int | None] = mapped_column(ForeignKey('entries.id'), nullable=True)
    status: Mapped[str] = mapped_column(String(12))  # posted, skipped, deleted
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    __table_args__ = (UniqueConstraint('rule_id','due_on', name='uq_recurring_once'),)


class AuthSession(Base):
    __tablename__ = 'auth_sessions'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    user_agent: Mapped[str] = mapped_column(String(180), default="")


class LoginChallenge(Base):
    __tablename__ = "auth_login_challenges"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TotpRecoveryCode(Base):
    __tablename__ = "auth_recovery_codes"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64), index=True)


class PasswordResetToken(Base):
    __tablename__ = 'password_reset_tokens'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Audit(Base):
    __tablename__ = 'audit_logs'
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    action: Mapped[str] = mapped_column(String(80))
    detail: Mapped[str] = mapped_column(String(240), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Non-destructive compatibility migration for databases created in v1.0.0/v1.0.1.
    # create_all() does not add columns to an existing table.
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        if IS_POSTGRES:
            conn.execute(text('ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(254)'))
            conn.execute(text('ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(20)'))
            conn.execute(text('ALTER TABLE users ADD COLUMN IF NOT EXISTS address VARCHAR(300)'))
            conn.execute(text('ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_secret TEXT'))
            conn.execute(text('ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_pending TEXT'))
            conn.execute(text('ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_pending_until TIMESTAMPTZ'))
            conn.execute(text('ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_last_step INTEGER NOT NULL DEFAULT -1'))
            conn.execute(text('ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_failed_attempts INTEGER NOT NULL DEFAULT 0'))
            conn.execute(text('ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_locked_until TIMESTAMPTZ'))
            conn.execute(text('ALTER TABLE auth_sessions ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now()'))
            conn.execute(text("ALTER TABLE auth_sessions ADD COLUMN IF NOT EXISTS user_agent VARCHAR(180) NOT NULL DEFAULT ''"))
            conn.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email)'))
            conn.execute(text('ALTER TABLE entries ADD COLUMN IF NOT EXISTS wallet_id INTEGER REFERENCES wallets(id)'))
            conn.execute(text('ALTER TABLE debt_payments ADD COLUMN IF NOT EXISTS wallet_id INTEGER REFERENCES wallets(id)'))
            conn.execute(text('CREATE INDEX IF NOT EXISTS ix_entries_wallet_id ON entries (wallet_id)'))
            conn.execute(text('CREATE INDEX IF NOT EXISTS ix_debt_payments_wallet_id ON debt_payments (wallet_id)'))
            conn.execute(text("ALTER TABLE debts ADD COLUMN IF NOT EXISTS direction VARCHAR(12) NOT NULL DEFAULT 'payable'"))
            conn.execute(text('ALTER TABLE debts ADD COLUMN IF NOT EXISTS annual_rate_bps INTEGER NOT NULL DEFAULT 0'))
            conn.execute(text('ALTER TABLE debts ADD COLUMN IF NOT EXISTS installment_count INTEGER NOT NULL DEFAULT 1'))
            conn.execute(text('ALTER TABLE debt_payments ADD COLUMN IF NOT EXISTS interest_amount BIGINT NOT NULL DEFAULT 0'))
            conn.execute(text("ALTER TABLE stash_funds ADD COLUMN IF NOT EXISTS auto_mode VARCHAR(10) NOT NULL DEFAULT 'off'"))
            conn.execute(text('ALTER TABLE stash_funds ADD COLUMN IF NOT EXISTS auto_value BIGINT NOT NULL DEFAULT 0'))
            conn.execute(text('ALTER TABLE stash_funds ADD COLUMN IF NOT EXISTS auto_wallet_id INTEGER REFERENCES wallets(id)'))
            conn.execute(text('ALTER TABLE stash_movements ADD COLUMN IF NOT EXISTS source_entry_id INTEGER REFERENCES entries(id)'))
            conn.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS uq_stash_auto_entry_fund ON stash_movements (fund_id, source_entry_id) WHERE source_entry_id IS NOT NULL'))
        else:
            columns = {row[1] for row in conn.execute(text('PRAGMA table_info(users)'))}
            for name, kind in [('email','VARCHAR(254)'),('phone','VARCHAR(20)'),('address','VARCHAR(300'),('totp_secret','TEXT'),('totp_pending','TEXT'),('totp_pending_until','DATETIME'),('totp_last_step','INTEGER NOT NULL DEFAULT -1'),('totp_failed_attempts','INTEGER NOT NULL DEFAULT 0'),('totp_locked_until','DATETIME')]:
                if name not in columns: conn.execute(text(f'ALTER TABLE users ADD COLUMN {name} {kind}'))
            existing_sessions = {row[1] for row in conn.execute(text('PRAGMA table_info(auth_sessions)'))}
            for col, definition in [('created_at', 'DATETIME'), ('user_agent', "VARCHAR(180) NOT NULL DEFAULT ''")]:
                if col not in existing_sessions:
                    conn.execute(text(f'ALTER TABLE auth_sessions ADD COLUMN {col} {definition}'))
            conn.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email)'))
            for table in ('entries', 'debt_payments'):
                existing = {row[1] for row in conn.execute(text(f'PRAGMA table_info({table})'))}
                if 'wallet_id' not in existing:
                    conn.execute(text(f'ALTER TABLE {table} ADD COLUMN wallet_id INTEGER REFERENCES wallets(id)'))
            conn.execute(text('CREATE INDEX IF NOT EXISTS ix_entries_wallet_id ON entries (wallet_id)'))
            conn.execute(text('CREATE INDEX IF NOT EXISTS ix_debt_payments_wallet_id ON debt_payments (wallet_id)'))
            for table, columns in {
                'debts':[('direction',"VARCHAR(12) NOT NULL DEFAULT 'payable'"),('annual_rate_bps','INTEGER NOT NULL DEFAULT 0'),('installment_count','INTEGER NOT NULL DEFAULT 1')],
                'debt_payments':[('interest_amount','BIGINT NOT NULL DEFAULT 0')],
            }.items():
                existing = {row[1] for row in conn.execute(text(f'PRAGMA table_info({table})'))}
                for col, definition in columns:
                    if col not in existing:
                        conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {col} {definition}'))
            for table, columns in {
                'stash_funds': [('auto_mode', "VARCHAR(10) NOT NULL DEFAULT 'off'"),
                                ('auto_value', 'BIGINT NOT NULL DEFAULT 0'),
                                ('auto_wallet_id', 'INTEGER REFERENCES wallets(id)')],
                'stash_movements': [('source_entry_id', 'INTEGER REFERENCES entries(id)')],
            }.items():
                existing = {row[1] for row in conn.execute(text(f'PRAGMA table_info({table})'))}
                for col, definition in columns:
                    if col not in existing:
                        conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {col} {definition}'))
            conn.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS uq_stash_auto_entry_fund ON stash_movements (fund_id, source_entry_id) WHERE source_entry_id IS NOT NULL'))
    # Idempotent upgrade: create exactly one default wallet for each legacy account.
    # Existing opening_balance, entries and debt payments are reassigned, not copied.
    with SessionLocal.begin() as db:
        for u in db.scalars(select(User).order_by(User.id)):
            primary = db.scalar(select(Wallet).where(Wallet.user_id == u.id, Wallet.is_default == True).order_by(Wallet.id))
            if primary is None:
                primary = Wallet(user_id=u.id, name='Ví chính', kind='cash',
                                 opening_balance=u.opening_balance or 0, is_default=True)
                db.add(primary)
                db.flush()
            db.execute(text('UPDATE entries SET wallet_id = :wallet WHERE user_id = :user AND wallet_id IS NULL'),
                       {'wallet': primary.id, 'user':u.id})
            db.execute(text('UPDATE debt_payments SET wallet_id = :wallet WHERE user_id = :user AND wallet_id IS NULL'),
                       {'wallet': primary.id, 'user':u.id})
    worker = asyncio.create_task(recurring_scheduler())
    try:
        yield
    finally:
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass


app = FastAPI(title='MoneyFlow API', docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
STATIC = Path(__file__).resolve().parent.parent / 'frontend'


class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith('/api/') and request.method not in ('GET','HEAD','OPTIONS'):
            origin = request.headers.get('origin')
            base_origin = f'{request.url.scheme}://{request.headers.get("host", "")}'
            if origin and origin != base_origin:
                return Response(content=json.dumps({'detail':'Nguồn yêu cầu không hợp lệ'}), status_code=403, media_type='application/json')
            if request.headers.get('content-type','').split(';')[0].strip().lower() != 'application/json':
                return Response(content=json.dumps({'detail':'Yêu cầu phải dùng JSON'}), status_code=415, media_type='application/json')
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        response.headers['Cache-Control'] = 'no-store'
        return response


app.add_middleware(SecurityMiddleware)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1','localhost','testserver'])



def get_db():
    with SessionLocal() as db:
        yield db


def utcnow():
    return datetime.now(timezone.utc)


def safe_password(password: str):
    if not (12 <= len(password) <= 128 and re.search(r'[a-z]',password) and re.search(r'[A-Z]',password) and re.search(r'\d',password) and re.search(r'[^\w\s]|_',password)):
        raise HTTPException(422, PASSWORD_RULE)


def username_clean(username):
    username = username.strip().lower()
    if not USER_PATTERN.fullmatch(username):
        raise HTTPException(422, 'Tên đăng nhập gồm 3-32 ký tự: a-z, 0-9, dấu chấm, gạch dưới hoặc gạch ngang.')
    return username


def check_amount(amount, zero=False):
    if isinstance(amount, bool) or not isinstance(amount,int) or amount < (0 if zero else 1) or amount > MAX_AMOUNT:
        raise HTTPException(422, f'Số tiền phải là số nguyên VNĐ từ {0 if zero else 1} đến {MAX_AMOUNT:,}.')
    return amount


def log(db, actor, action, detail=''):
    db.add(Audit(actor_id=actor, action=action, detail=detail[:240]))


def seed_categories(db, user):
    for kind, names in [('expense',DEFAULT_EXPENSE),('income',DEFAULT_INCOME)]:
        for i,name in enumerate(names):
            db.add(Category(user_id=user.id, name=name, kind=kind, color=COLORS[i % len(COLORS)]))


def normalized_email(value: str) -> str:
    value = value.strip().lower()
    if len(value) > 254 or not EMAIL_PATTERN.fullmatch(value):
        raise HTTPException(422, 'Email không hợp lệ.')
    return value


def local_vietnam_phone(value: str | None) -> str:
    """Display Vietnamese numbers as 0...; preserve other international prefixes."""
    if not value:
        return ''
    compact = re.sub(r'[\s.()-]', '', value.strip())
    match = re.fullmatch(r'(?:\+84|0084|84)([1-9][0-9]{8,9})', compact)
    return '0' + match.group(1) if match else compact


def normalized_phone(value: str) -> str:
    value = local_vietnam_phone(value)
    if not PHONE_PATTERN.fullmatch(value):
        raise HTTPException(422, 'Số điện thoại phải gồm 9-15 chữ số, có thể bắt đầu bằng +.')
    return value


def normalized_address(value: str) -> str:
    value = value.strip()
    if not 5 <= len(value) <= 300:
        raise HTTPException(422, 'Địa chỉ cần 5-300 ký tự.')
    return value


def user_json(u):
    return {'id':u.id,'username':u.username,'email':u.email or '', 'phone':local_vietnam_phone(u.phone),
            'address':u.address or '', 'profile_complete':bool(u.email and u.phone and u.address),
            'role':u.role,'active':u.active,'totp_enabled':bool(u.totp_secret),'opening_balance':u.opening_balance,
            'created_at':u.created_at.isoformat()}



def account_locked(db,user_id):
    return db.execute(select(User).where(User.id==user_id).with_for_update()).scalar_one()


def debt_paid_total(db, user_id, entry_id=None):
    """Payable PRINCIPAL repaid; receivable collection isn't a debt expense."""
    stmt = select(func.coalesce(func.sum(DebtPayment.amount), 0)).join(
        Debt, Debt.id == DebtPayment.debt_id).where(
        DebtPayment.user_id == user_id, Debt.direction == 'payable')
    if entry_id is not None:
        stmt = stmt.where(DebtPayment.entry_id == entry_id)
    return int(db.scalar(stmt) or 0)


def debt_cash_delta(db, user_id, wallet_id=None):
    """Debt repayments affect cash once; principal itself is not an expense."""
    stmt = select(DebtPayment.amount, DebtPayment.interest_amount, Debt.direction).join(
        Debt, Debt.id == DebtPayment.debt_id).where(DebtPayment.user_id == user_id)
    if wallet_id is not None:
        stmt = stmt.where(DebtPayment.wallet_id == wallet_id)
    return sum((int(principal) + int(interest or 0)) * (1 if direction == 'receivable' else -1)
               for principal, interest, direction in db.execute(stmt))


def add_months_clamped(value: date, months: int) -> date:
    index = value.year * 12 + value.month - 1 + months
    year, month = divmod(index, 12)
    return date(year, month + 1, min(value.day, monthrange(year, month + 1)[1]))


def debt_schedule_rows(d: Debt) -> list[dict]:
    """Illustrative declining-balance equal-principal installments; no auto interest posting."""
    count = int(d.installment_count or 1)
    base, remainder = divmod(int(d.principal), count)
    remaining = int(d.principal)
    paid = int(d.principal) - int(d.remaining)
    first_date = d.due_date
    rows = []
    for i in range(count):
        principal = base + (1 if i < remainder else 0)
        interest = int((Decimal(remaining) * Decimal(d.annual_rate_bps or 0) / Decimal(120000)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        deadline = add_months_clamped(first_date, i) if first_date else None
        paid_on_installment = min(max(paid, 0), principal)
        paid -= paid_on_installment
        rows.append({'period':i+1,'due_date':deadline.isoformat() if deadline else None,
                     'principal':principal,'estimated_interest':interest,'estimated_total':principal+interest,
                     'principal_paid':paid_on_installment,
                     'status':'paid' if paid_on_installment >= principal else ('overdue' if deadline and deadline < date.today() else 'upcoming')})
        remaining -= principal
    return rows


def default_wallet(db: Session, user_id: int) -> Wallet:
    wallet = db.scalar(select(Wallet).where(Wallet.user_id == user_id, Wallet.is_default == True).order_by(Wallet.id))
    if wallet is None:
        # Handles accounts created manually or by older database tools since startup.
        user = db.get(User, user_id)
        wallet = Wallet(user_id=user_id, name='Ví chính',kind='cash',
                        opening_balance=user.opening_balance or 0, is_default=True)
        db.add(wallet)
        db.flush()
    return wallet


def wallet_for(db: Session, user_id: int, wallet_id: int | None = None, require_active: bool = False) -> Wallet:
    wallet = default_wallet(db,user_id) if wallet_id is None else db.scalar(
        select(Wallet).where(Wallet.user_id == user_id, Wallet.id == wallet_id))
    if wallet is None or (require_active and not wallet.active):
        raise HTTPException(422,'Ví không tồn tại, đã khóa hoặc không thuộc tài khoản của bạn.')
    return wallet


def wallet_balance(db: Session, wallet: Wallet) -> int:
    user_id, wallet_id = wallet.user_id, wallet.id
    income = db.scalar(select(func.coalesce(func.sum(Entry.amount),0)).where(
        Entry.user_id == user_id, Entry.wallet_id == wallet_id, Entry.kind == 'income')) or 0
    expense = db.scalar(select(func.coalesce(func.sum(Entry.amount),0)).where(
        Entry.user_id == user_id, Entry.wallet_id == wallet_id, Entry.kind == 'expense')) or 0
    debt_delta = debt_cash_delta(db, user_id, wallet_id)
    incoming = db.scalar(select(func.coalesce(func.sum(WalletTransfer.amount),0)).where(
        WalletTransfer.user_id == user_id, WalletTransfer.to_wallet_id == wallet_id)) or 0
    outgoing = db.scalar(select(func.coalesce(func.sum(WalletTransfer.amount),0)).where(
        WalletTransfer.user_id == user_id, WalletTransfer.from_wallet_id == wallet_id)) or 0
    savings_delta = db.scalar(select(func.coalesce(func.sum(SavingsMovement.amount), 0)).where(
        SavingsMovement.user_id == user_id, SavingsMovement.wallet_id == wallet_id,
        SavingsMovement.kind == 'withdraw')) or 0
    savings_allocated = db.scalar(select(func.coalesce(func.sum(SavingsMovement.amount), 0)).where(
        SavingsMovement.user_id == user_id, SavingsMovement.wallet_id == wallet_id,
        SavingsMovement.kind == 'deposit')) or 0
    stash_withdrawn = db.scalar(select(func.coalesce(func.sum(StashMovement.amount), 0)).where(
        StashMovement.user_id == user_id, StashMovement.wallet_id == wallet_id,
        StashMovement.kind == 'withdraw')) or 0
    stash_deposited = db.scalar(select(func.coalesce(func.sum(StashMovement.amount), 0)).where(
        StashMovement.user_id == user_id, StashMovement.wallet_id == wallet_id,
        StashMovement.kind == 'deposit')) or 0
    return (int(wallet.opening_balance) + int(income) - int(expense) + int(debt_delta)
            + int(incoming) - int(outgoing) + int(savings_delta) - int(savings_allocated)
            + int(stash_withdrawn) - int(stash_deposited))


def total_reserved_savings(db: Session, user_id: int) -> int:
    deposits = db.scalar(select(func.coalesce(func.sum(SavingsMovement.amount), 0)).where(
        SavingsMovement.user_id == user_id, SavingsMovement.kind == 'deposit')) or 0
    withdrawals = db.scalar(select(func.coalesce(func.sum(SavingsMovement.amount), 0)).where(
        SavingsMovement.user_id == user_id, SavingsMovement.kind == 'withdraw')) or 0
    return int(deposits) - int(withdrawals)


def savings_goal_balance(db: Session, goal_id: int, user_id: int) -> int:
    rows = db.execute(select(SavingsMovement.kind, SavingsMovement.amount).where(
        SavingsMovement.user_id == user_id, SavingsMovement.goal_id == goal_id))
    return sum(int(amount) * (1 if kind == 'deposit' else -1) for kind, amount in rows)


def total_stash_funds(db: Session, user_id: int) -> int:
    deposited = db.scalar(select(func.coalesce(func.sum(StashMovement.amount), 0)).where(
        StashMovement.user_id == user_id, StashMovement.kind == 'deposit')) or 0
    withdrawn = db.scalar(select(func.coalesce(func.sum(StashMovement.amount), 0)).where(
        StashMovement.user_id == user_id, StashMovement.kind == 'withdraw')) or 0
    return int(deposited) - int(withdrawn)


def stash_fund_balance(db: Session, fund_id: int, user_id: int) -> int:
    rows = db.execute(select(StashMovement.kind, StashMovement.amount).where(
        StashMovement.user_id == user_id, StashMovement.fund_id == fund_id))
    return sum(int(amount) * (1 if kind == 'deposit' else -1) for kind, amount in rows)


def current_balance(db, user_id, opening=None):
    inc = db.scalar(select(func.coalesce(func.sum(Entry.amount),0)).where(Entry.user_id==user_id,Entry.kind=='income')) or 0
    exp = db.scalar(select(func.coalesce(func.sum(Entry.amount),0)).where(Entry.user_id==user_id,Entry.kind=='expense')) or 0
    wallets = list(db.scalars(select(Wallet).where(Wallet.user_id == user_id)))
    opening_sum = sum(w.opening_balance for w in wallets)
    if opening is not None:
        opening_sum += int(opening) - default_wallet(db, user_id).opening_balance
    available = int(opening_sum) + int(inc) - int(exp) + debt_cash_delta(db, user_id)
    return available - total_reserved_savings(db, user_id) - total_stash_funds(db, user_id), int(inc), int(exp)


def ensure_nonnegative(db, user_id):
    # Guard each wallet independently, not only the global sum.
    db.flush()
    for wallet in db.scalars(select(Wallet).where(Wallet.user_id == user_id)):
        balance=wallet_balance(db,wallet)
        if balance < 0:
            raise HTTPException(409, f'Ví "{wallet.name}" không đủ tiền ({balance:,}đ).')


def wallet_json(db: Session, wallet: Wallet) -> dict:
    return {'id':wallet.id,'name':wallet.name,'kind':wallet.kind,'active':wallet.active,
            'is_default':wallet.is_default,'opening_balance':wallet.opening_balance,
            'balance':wallet_balance(db,wallet),'created_at':wallet.created_at.isoformat()}


def allocate_income_to_debts(db, user_id, entry):
    """Repay active principals oldest first, atomically with the income entry."""
    if entry.kind != 'income':
        return 0
    available = int(entry.amount)
    paid = 0
    for debt in db.scalars(select(Debt).where(Debt.user_id==user_id,Debt.direction=='payable',Debt.remaining>0).order_by(Debt.id).with_for_update()):
        if available == 0:
            break
        value = min(available, debt.remaining)
        debt.remaining -= value
        db.add(DebtPayment(user_id=user_id,debt_id=debt.id,entry_id=entry.id,wallet_id=entry.wallet_id,amount=value,mode='auto',paid_on=entry.occurred_on))
        available -= value
        paid += value
    db.flush()
    return paid


def allocate_income_to_stashes(db: Session, user_id: int, entry: Entry, debt_paid: int = 0) -> int:
    """Reserve only remaining incoming cash *after* principal repayment.

    Fund rules run in deterministic creation order. Percentage is calculated on
    the original net income (gross minus repaid principal); amounts are capped
    by the unallocated remainder. All movements are part of the entry transaction.
    """
    if entry.kind != 'income':
        return 0
    net_income = max(0, int(entry.amount) - int(debt_paid))
    remaining = net_income
    total = 0
    funds = list(db.scalars(select(StashFund).where(
        StashFund.user_id == user_id, StashFund.auto_mode != 'off'
    ).order_by(StashFund.id).with_for_update()))
    for fund in funds:
        if remaining <= 0:
            break
        if fund.auto_wallet_id is not None and fund.auto_wallet_id != entry.wallet_id:
            continue
        # Unique (fund, income) guards against duplicate auto-reserves.
        existing = db.scalar(select(StashMovement.id).where(
            StashMovement.fund_id == fund.id, StashMovement.source_entry_id == entry.id))
        if existing:
            continue
        target = (net_income * int(fund.auto_value) // 100 if fund.auto_mode == 'percent'
                  else int(fund.auto_value))
        amount = min(remaining, target)
        if amount <= 0:
            continue
        db.add(StashMovement(user_id=user_id, fund_id=fund.id, wallet_id=entry.wallet_id,
                             source_entry_id=entry.id, kind='deposit', amount=amount,
                             occurred_on=entry.occurred_on,
                             note='Tự động tích từ thu nhập #' + str(entry.id)))
        remaining -= amount
        total += amount
    db.flush()
    return total


def reverse_entry_stash_allocations(db: Session, user_id: int, entry_id: int) -> int:
    """Prevent editing/deleting income when auto-deposits have since been withdrawn.

    The entire caller transaction rolls back if a reversal is impossible.
    """
    movements = list(db.scalars(select(StashMovement).where(
        StashMovement.user_id == user_id, StashMovement.source_entry_id == entry_id
    ).order_by(StashMovement.id).with_for_update()))
    for m in movements:
        fund = stash_fund_for(db, user_id, m.fund_id, True)
        if stash_fund_balance(db, fund.id, user_id) < m.amount:
            raise HTTPException(409, 'Quỹ đã rút bớt tiền tự động từ khoản thu này. Hãy hoàn tiền vào quỹ trước khi sửa hoặc xóa thu nhập.')
        db.delete(m)
        db.flush()
    return sum(m.amount for m in movements)


def reverse_entry_payments(db, user_id, entry_id):
    """Revert only allocations belonging to this entry (for editing/deletion)."""
    payments = list(db.scalars(select(DebtPayment).where(DebtPayment.user_id==user_id,DebtPayment.entry_id==entry_id).order_by(DebtPayment.id).with_for_update()))
    for payment in payments:
        debt = db.scalar(select(Debt).where(Debt.id==payment.debt_id,Debt.user_id==user_id).with_for_update())
        if not debt:
            raise HTTPException(409, 'Khoản nợ của giao dịch không còn tồn tại.')
        debt.remaining += payment.amount
        db.delete(payment)
    db.flush()
    return sum(p.amount for p in payments)


def session_lookup(request: Request, db: Session):
    token = request.cookies.get(COOKIE)
    if not token: raise HTTPException(401, 'Bạn cần đăng nhập.')
    hashed = hashlib.sha256(token.encode()).hexdigest()
    s = db.scalar(select(AuthSession).where(AuthSession.token_hash==hashed))
    if not s or as_utc(s.expires_at) <= utcnow(): raise HTTPException(401, 'Phiên đăng nhập hết hạn.')
    u = db.get(User,s.user_id)
    if not u or not u.active: raise HTTPException(401, 'Tài khoản không còn hoạt động.')
    if request.method not in ('GET','HEAD') and request.headers.get('x-csrf-token') != s.csrf_token:
        raise HTTPException(403, 'CSRF token không hợp lệ. Vui lòng tải lại trang.')
    return u,s


def as_utc(dt):
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def current(request: Request,db: Session=Depends(get_db)):
    return session_lookup(request,db)[0]


def admin(u: User=Depends(current)):
    if u.role!='admin': raise HTTPException(403, 'Chỉ quản trị viên có quyền thực hiện.')
    return u


def start_session(db, response: Response, u: User, request: Request | None = None):
    token=secrets.token_urlsafe(48)
    csrf=secrets.token_hex(32)
    db.add(AuthSession(user_id=u.id, token_hash=hashlib.sha256(token.encode()).hexdigest(),csrf_token=csrf,expires_at=utcnow()+timedelta(days=7),user_agent=((request.headers.get('user-agent','') if request else '')[:180])))
    response.set_cookie(COOKIE, token, httponly=True, secure=os.environ.get('COOKIE_SECURE','false').lower()=='true', samesite='strict',max_age=604800,path='/')
    return csrf


class NewUser(BaseModel):
    username: str
    email: str = Field(min_length=5,max_length=254)
    phone: str = Field(min_length=9,max_length=25)
    address: str = Field(min_length=5,max_length=300)
    password: str
    confirm_password: str

    @model_validator(mode='after')
    def confirm_new_password(self):
        if self.password != self.confirm_password:
            raise ValueError('Xác nhận mật khẩu không khớp.')
        return self


class Login(BaseModel):
    username: str = Field(min_length=1,max_length=128)
    password: str = Field(min_length=1,max_length=128)


class ConfirmNewPassword(BaseModel):
    new_password: str
    confirm_password: str

    @model_validator(mode='after')
    def confirm_new_password(self):
        if self.new_password != self.confirm_password:
            raise ValueError('Xác nhận mật khẩu không khớp.')
        return self


class ChangePassword(ConfirmNewPassword):
    old_password: str


class NewEntry(BaseModel):
    title: str=Field(min_length=1,max_length=120)
    kind: Literal['income','expense']
    amount: int
    category_id: int
    occurred_on: date
    note: str=Field(default='',max_length=500)
    wallet_id: int | None = None


class Opening(BaseModel):
    opening_balance: int


class NewDebt(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    lender: str = Field(default='', max_length=120)
    direction: Literal['payable','receivable'] = 'payable'
    principal: int
    interest_rate_pct: Decimal = Field(default=Decimal('0'), ge=0, le=100, decimal_places=2)
    installment_count: int = Field(default=1, ge=1, le=360)
    due_date: date | None = None  # first scheduled due date
    note: str = Field(default='', max_length=500)



class ManualDebtPayment(BaseModel):
    amount: int
    interest_amount: int = 0
    paid_on: date = Field(default_factory=date.today)
    wallet_id: int | None = None


class NewWallet(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal['cash','bank','ewallet'] = 'cash'
    opening_balance: int = 0


class EditWallet(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal['cash','bank','ewallet']


class TransferWallet(BaseModel):
    from_wallet_id: int
    to_wallet_id: int
    amount: int
    occurred_on: date = Field(default_factory=date.today)
    note: str = Field(default='', max_length=300)


class NewSavingsGoal(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    target_amount: int
    due_date: date | None = None
    note: str = Field(default='', max_length=300)


class NewSavingsMovement(BaseModel):
    kind: Literal['deposit', 'withdraw']
    wallet_id: int
    amount: int
    occurred_on: date = Field(default_factory=date.today)
    note: str = Field(default='', max_length=300)


class NewStashFund(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    note: str = Field(default='', max_length=300)
    auto_mode: Literal['off', 'percent', 'fixed'] = 'off'
    auto_value: int = 0
    auto_wallet_id: int | None = None  # None: income arriving at any wallet

    @model_validator(mode='after')
    def validate_auto_rule(self):
        if self.auto_mode == 'off' and self.auto_value != 0:
            raise ValueError('Khi tắt tự động, số tiền/tỷ lệ phải bằng 0.')
        if self.auto_mode == 'percent' and not 1 <= self.auto_value <= 100:
            raise ValueError('Tỷ lệ tích lũy phải từ 1 đến 100%.')
        if self.auto_mode == 'fixed' and not 1 <= self.auto_value <= MAX_AMOUNT:
            raise ValueError('Số tiền tích lũy cố định không hợp lệ.')
        return self


class NewStashMovement(BaseModel):
    kind: Literal['deposit', 'withdraw']
    wallet_id: int
    amount: int
    occurred_on: date = Field(default_factory=date.today)
    note: str = Field(default='', max_length=300)


class NewRecurring(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    kind: Literal['income','expense']
    amount: int
    category_id: int
    wallet_id: int
    note: str = Field(default='', max_length=500)
    frequency: Literal['daily','weekly','monthly','yearly'] = 'monthly'
    start_on: date = Field(default_factory=date.today)
    mode: Literal['manual','auto'] = 'manual'
    remind_days: int = Field(default=3, ge=0, le=30)


class EditRecurring(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    amount: int
    category_id: int
    wallet_id: int
    note: str = Field(default='', max_length=500)
    mode: Literal['manual','auto'] = 'manual'
    remind_days: int = Field(default=3, ge=0, le=30)


class NewCategory(BaseModel):
    name: str=Field(min_length=1,max_length=60)
    kind: Literal['income','expense']
    color: str='#7567F8'


class NewBudget(BaseModel):
    category_id: int
    month: str
    amount: int


class UserEdit(BaseModel):
    email: str|None=None
    phone: str|None=None
    address: str|None=None
    role: Literal['admin','member']|None=None
    active: bool|None=None


class ProfileEdit(BaseModel):
    email: str
    phone: str
    address: str
    current_password: str


class ForgotPassword(BaseModel):
    email: str = Field(min_length=5,max_length=254)


class CompleteReset(ConfirmNewPassword):
    token: str = Field(min_length=20,max_length=200)


class ResetPassword(ConfirmNewPassword):
    pass


class DeleteUser(BaseModel):
    confirm_username: str


@app.get('/api/setup-status')
def setup_status(db:Session=Depends(get_db)):
    return {'needs_setup': db.scalar(select(func.count(User.id)))==0}


@app.post('/api/setup')
def setup(data:NewUser,response:Response,request:Request,db:Session=Depends(get_db)):
    # Serialize first-time setup across concurrent requests on PostgreSQL.
    if IS_POSTGRES:
        db.execute(text('SELECT pg_advisory_xact_lock(817262091)'))
    if db.scalar(select(func.count(User.id))) != 0: raise HTTPException(403,'Ứng dụng đã được khởi tạo.')
    safe_password(data.password)
    username=username_clean(data.username)
    u=User(username=username,display_name=username,email=normalized_email(data.email),
           phone=normalized_phone(data.phone),address=normalized_address(data.address),
           password_hash=ph.hash(data.password),role='admin')
    try:
        db.add(u);db.flush()
        seed_categories(db,u)
        default_wallet(db,u.id)
        csrf=start_session(db,response,u,request)
        log(db,u.id,'setup','Khởi tạo quản trị viên')
        db.commit()
    except IntegrityError:
        db.rollback();raise HTTPException(409,'Tên đăng nhập hoặc email đã tồn tại.')
    return {'user':user_json(u),'csrf_token':csrf}


@app.post('/api/login')
def login(data:Login,response:Response,request:Request,db:Session=Depends(get_db)):
    username=data.username.strip().lower()
    u=db.scalar(select(User).where(User.username==username).with_for_update())
    if not u:
        ph.hash(data.password[:128])  # comparable cost for unknown usernames
        raise HTTPException(401,'Thông tin đăng nhập không đúng.')
    if not u.active: raise HTTPException(403,'Tài khoản đã bị khóa.')
    if u.locked_until and as_utc(u.locked_until)>utcnow(): raise HTTPException(429,'Sai mật khẩu quá số lần cho phép. Vui lòng thử lại sau 15 phút.')
    try:
        correct=ph.verify(u.password_hash,data.password)
    except (VerifyMismatchError,VerificationError):
        correct=False
    if not correct:
        u.failed_attempts+=1
        if u.failed_attempts>=LOGIN_FAILURE_LIMIT:
            u.failed_attempts=0;u.locked_until=utcnow()+timedelta(minutes=15)
        log(db,u.id,'login_failed','Sai mật khẩu')
        db.commit();raise HTTPException(401,'Thông tin đăng nhập không đúng.')
    u.failed_attempts=0;u.locked_until=None
    if ph.check_needs_rehash(u.password_hash): u.password_hash=ph.hash(data.password)
    if u.totp_secret:
        if u.totp_locked_until and as_utc(u.totp_locked_until)>utcnow():
            raise HTTPException(429,'Quá nhiều mã xác thực sai. Vui lòng thử lại sau 15 phút.')
        ticket=secrets.token_urlsafe(40)
        db.query(LoginChallenge).filter(LoginChallenge.user_id==u.id).delete(synchronize_session=False)
        db.add(LoginChallenge(user_id=u.id,token_hash=hashlib.sha256(ticket.encode()).hexdigest(),
                              attempts=0,expires_at=utcnow()+timedelta(minutes=5)))
        log(db,u.id,'login_2fa_required','Yêu cầu mã xác thực thứ hai')
        db.commit()
        return {'two_factor_required':True,'login_ticket':ticket}
    csrf=start_session(db,response,u,request)
    log(db,u.id,'login','Đăng nhập')
    db.commit()
    return {'user':user_json(u),'csrf_token':csrf}


# TOTP uses standard RFC 6238 HMAC-SHA1 with 30-second steps.
# Secrets are encrypted at rest with a random Fernet key stored in .env, NOT in the database.
def totp_cipher():
    key=os.environ.get('TOTP_ENCRYPTION_KEY','').strip()
    if not key:
        raise HTTPException(503,'Chưa có khóa TOTP. Khởi động bằng scripts/start.ps1 để tạo khóa vào .env.')
    try:
        return Fernet(key.encode('ascii'))
    except (ValueError,TypeError):
        raise HTTPException(503,'Khóa TOTP không hợp lệ. Kiểm tra .env.')


def totp_decrypt(encrypted):
    try:
        return totp_cipher().decrypt(encrypted.encode('ascii')).decode('ascii')
    except (InvalidToken,ValueError):
        raise HTTPException(503,'Không thể giải mã TOTP. Kiểm tra khóa TOTP trong .env cũ.')


def totp_value(secret, step):
    raw=base64.b32decode(secret,casefold=True)
    digest=hmac.new(raw,struct.pack('>Q',step),hashlib.sha1).digest()
    offset=digest[-1]&0x0f
    value=(struct.unpack('>I',digest[offset:offset+4])[0]&0x7fffffff)%1_000_000
    return f'{value:06d}'


def totp_check(secret, code, last_step=-1):
    if not re.fullmatch(r'\d{6}',code):
        return None
    now_step=int(time.time())//30
    for step in (now_step-1,now_step,now_step+1):
        if step>last_step and hmac.compare_digest(totp_value(secret,step),code):
            return step
    return None


def recovery_hash(code):
    return hashlib.sha256(code.replace('-','').replace(' ','').upper().encode('ascii')).hexdigest()


def validate_totp_or_recovery(db,u,code):
    code=code.strip().replace(' ','').replace('-','')
    if not u.totp_secret: return False
    # Recovery codes must remain usable if a user's TOTP encryption key was lost.
    # Lookup is constant-format and uses a high-entropy, one-time SHA-256 hash.
    if re.fullmatch(r'[0-9A-Fa-f]{20}',code):
        hsh=recovery_hash(code)
        found=db.scalar(select(TotpRecoveryCode).where(TotpRecoveryCode.user_id==u.id,TotpRecoveryCode.code_hash==hsh).with_for_update())
        if found:
            db.delete(found)
            return True
        return False
    if not re.fullmatch(r'\d{6}',code): return False
    step=totp_check(totp_decrypt(u.totp_secret),code,int(u.totp_last_step or -1))
    if step is not None:
        u.totp_last_step=step
        return True
    return False


class TotpCode(BaseModel):
    code: str = Field(min_length=6,max_length=32)


class LoginOtp(TotpCode):
    login_ticket: str = Field(min_length=32,max_length=200)


class DisableTotp(TotpCode):
    password: str


class TotpSetupPassword(BaseModel):
    password: str


@app.post('/api/login-otp')
def verify_login_otp(data:LoginOtp,request:Request,response:Response,db:Session=Depends(get_db)):
    hashed=hashlib.sha256(data.login_ticket.encode()).hexdigest()
    challenge=db.scalar(select(LoginChallenge).where(LoginChallenge.token_hash==hashed).with_for_update())
    if not challenge or as_utc(challenge.expires_at)<=utcnow() or challenge.attempts>=5:
        raise HTTPException(401,'Mã đăng nhập hết hạn. Hãy đăng nhập lại bằng mật khẩu.')
    u=db.scalar(select(User).where(User.id==challenge.user_id).with_for_update())
    if not u or not u.active or not u.totp_secret:
        raise HTTPException(401,'Không thể xác minh đăng nhập.')
    if u.totp_locked_until and as_utc(u.totp_locked_until)>utcnow():
        raise HTTPException(429,'Quá nhiều mã xác thực sai. Vui lòng thử lại sau 15 phút.')
    if not validate_totp_or_recovery(db,u,data.code):
        u.totp_failed_attempts+=1
        if u.totp_failed_attempts>=5:
            u.totp_failed_attempts=0
            u.totp_locked_until=utcnow()+timedelta(minutes=15)
        challenge.attempts+=1
        if challenge.attempts>=5: db.delete(challenge)
        log(db,u.id,'login_2fa_failed','Sai mã 2FA')
        db.commit()
        raise HTTPException(401,'Mã xác thực không hợp lệ hoặc đã dùng. Tối đa 5 lần thử.')
    u.totp_failed_attempts=0;u.totp_locked_until=None
    db.query(LoginChallenge).filter(LoginChallenge.user_id==u.id).delete(synchronize_session=False)
    csrf=start_session(db,response,u,request)
    log(db,u.id,'login_2fa_success','Xác thực hai bước thành công')
    db.commit()
    return {'user':user_json(u),'csrf_token':csrf}


@app.get('/api/security/status')
def security_status(request:Request,db:Session=Depends(get_db)):
    u,_=session_lookup(request,db)
    return {'totp_enabled':bool(u.totp_secret),'totp_configured':bool(os.environ.get('TOTP_ENCRYPTION_KEY','').strip()),
            'recovery_codes_remaining':db.scalar(select(func.count(TotpRecoveryCode.id)).where(TotpRecoveryCode.user_id==u.id))}


@app.post('/api/security/totp/setup')
def totp_setup(data:TotpSetupPassword,request:Request,db:Session=Depends(get_db)):
    u,_=session_lookup(request,db)
    try: password_ok=ph.verify(u.password_hash,data.password)
    except (VerifyMismatchError,VerificationError): password_ok=False
    if not password_ok: raise HTTPException(403,'Mật khẩu hiện tại không đúng.')
    if u.totp_secret: raise HTTPException(409,'TOTP đã được bật.')
    secret=base64.b32encode(secrets.token_bytes(20)).decode('ascii').rstrip('=')
    u.totp_pending=totp_cipher().encrypt(secret.encode()).decode('ascii')
    u.totp_pending_until=utcnow()+timedelta(minutes=10)
    db.commit()
    uri=f'otpauth://totp/{quote("MoneyFlow:"+u.username)}?secret={secret}&issuer=MoneyFlow&algorithm=SHA1&digits=6&period=30'
    qr=qrcode.QRCode(box_size=5,border=3);qr.add_data(uri);qr.make(fit=True)
    output=io.BytesIO();qr.make_image(fill_color='#131c31',back_color='#ffffff').save(output,format='PNG')
    return {'secret':secret,'qr_data_url':'data:image/png;base64,'+base64.b64encode(output.getvalue()).decode(),
            'expires_in_seconds':600}


@app.post('/api/security/totp/enable')
def totp_enable(data:TotpCode,request:Request,db:Session=Depends(get_db)):
    u,_=session_lookup(request,db)
    if u.totp_secret: raise HTTPException(409,'TOTP đã bật.')
    if not u.totp_pending or not u.totp_pending_until or as_utc(u.totp_pending_until)<utcnow():
        raise HTTPException(410,'Mã QR đã hết hạn. Hãy bắt đầu thiết lập lại.')
    secret=totp_decrypt(u.totp_pending)
    step=totp_check(secret,data.code.strip())
    if step is None:raise HTTPException(422,'Mã 6 số không hợp lệ.')
    u.totp_secret=u.totp_pending
    u.totp_pending=None;u.totp_pending_until=None;u.totp_last_step=step;u.totp_failed_attempts=0;u.totp_locked_until=None
    codes=[secrets.token_hex(10).upper() for _ in range(8)]
    db.query(TotpRecoveryCode).filter(TotpRecoveryCode.user_id==u.id).delete(synchronize_session=False)
    for code in codes:
        db.add(TotpRecoveryCode(user_id=u.id,code_hash=recovery_hash(code)))
    db.query(AuthSession).filter(AuthSession.user_id==u.id,
        AuthSession.token_hash!=hashlib.sha256(request.cookies[COOKIE].encode()).hexdigest()).delete(synchronize_session=False)
    log(db,u.id,'totp_enabled','Đã bật xác thực hai bước và thu hồi phiên khác')
    db.commit()
    return {'ok':True,'recovery_codes':codes}


@app.post('/api/security/totp/disable')
def totp_disable(data:DisableTotp,request:Request,db:Session=Depends(get_db)):
    u,s=session_lookup(request,db)
    if not u.totp_secret: raise HTTPException(409,'TOTP chưa bật.')
    try: ok=ph.verify(u.password_hash,data.password)
    except (VerifyMismatchError,VerificationError): ok=False
    if not ok or not validate_totp_or_recovery(db,u,data.code):
        raise HTTPException(403,'Mật khẩu hoặc mã TOTP/mã dự phòng không chính xác.')
    u.totp_secret=None;u.totp_pending=None;u.totp_pending_until=None;u.totp_last_step=-1;u.totp_failed_attempts=0;u.totp_locked_until=None
    db.query(TotpRecoveryCode).filter(TotpRecoveryCode.user_id==u.id).delete(synchronize_session=False)
    db.query(LoginChallenge).filter(LoginChallenge.user_id==u.id).delete(synchronize_session=False)
    db.query(AuthSession).filter(AuthSession.user_id==u.id,AuthSession.id!=s.id).delete(synchronize_session=False)
    log(db,u.id,'totp_disabled','Đã tắt 2FA và thu hồi phiên khác')
    db.commit()
    return {'ok':True}


@app.get('/api/security/sessions')
def security_sessions(request:Request,db:Session=Depends(get_db)):
    u,current_session=session_lookup(request,db)
    rows=list(db.scalars(select(AuthSession).where(AuthSession.user_id==u.id).order_by(AuthSession.id.desc())))
    return {'items':[{'id':x.id,'current':x.id==current_session.id,'user_agent':x.user_agent or 'Thiết bị chưa rõ',
             'created_at':(x.created_at or utcnow()).isoformat(), 'expires_at':x.expires_at.isoformat()} for x in rows]}


@app.delete('/api/security/sessions/{session_id}')
def security_revoke_session(session_id:int,request:Request,db:Session=Depends(get_db)):
    u,s=session_lookup(request,db)
    target=db.scalar(select(AuthSession).where(AuthSession.id==session_id,AuthSession.user_id==u.id))
    if not target:raise HTTPException(404,'Không tìm thấy phiên đăng nhập.')
    if target.id==s.id: raise HTTPException(409,'Dùng nút Đăng xuất để đóng phiên hiện tại.')
    db.delete(target);log(db,u.id,'session_revoked',str(session_id));db.commit()
    return {'ok':True}


@app.post('/api/security/sessions/revoke-others')
def security_revoke_others(request:Request,db:Session=Depends(get_db)):
    u,s=session_lookup(request,db)
    result=db.query(AuthSession).filter(AuthSession.user_id==u.id,AuthSession.id!=s.id).delete(synchronize_session=False)
    log(db,u.id,'sessions_revoked',str(result));db.commit()
    return {'ok':True,'revoked':result}


@app.get('/api/security/integrity')
def security_integrity(request:Request,db:Session=Depends(get_db)):
    u,_=session_lookup(request,db)
    checks=[]
    wallets=list(db.scalars(select(Wallet).where(Wallet.user_id==u.id)))
    for w in wallets:
        balance=wallet_balance(db,w)
        if balance<0: checks.append({'kind':'negative_wallet','detail':f'Ví {w.id} có số dư âm: {balance}'})
    for d in db.scalars(select(Debt).where(Debt.user_id==u.id)):
        paid=db.scalar(select(func.coalesce(func.sum(DebtPayment.amount),0)).where(DebtPayment.debt_id==d.id,DebtPayment.user_id==u.id)) or 0
        if d.remaining<0 or d.remaining>d.principal or d.principal-int(paid)!=d.remaining:
            checks.append({'kind':'invalid_debt','detail':f'Khoản nợ #{d.id} có số gốc hoặc lịch sử thanh toán không khớp.'})
    # Validate saved reserves without mutating financial records.
    total_checked_savings = 0
    for goal in db.scalars(select(SavingsGoal).where(SavingsGoal.user_id==u.id)):
        saved=savings_goal_balance(db,goal.id,u.id)
        total_checked_savings+=saved
        if saved<0 or saved>goal.target_amount:
            checks.append({'kind':'invalid_savings_goal','detail':f'Mục tiêu #{goal.id} có số dư dành riêng không hợp lệ.'})
    if total_checked_savings != total_reserved_savings(db,u.id):
        checks.append({'kind':'invalid_savings_total','detail':'Tổng tiền dành riêng không khớp sổ mục tiêu.'})
    for mid,wuid,guid in db.execute(select(SavingsMovement.id,Wallet.user_id,SavingsGoal.user_id)
            .outerjoin(Wallet,Wallet.id==SavingsMovement.wallet_id)
            .outerjoin(SavingsGoal,SavingsGoal.id==SavingsMovement.goal_id)
            .where(SavingsMovement.user_id==u.id)):
        if wuid!=u.id or guid!=u.id:
            checks.append({'kind':'invalid_savings_link','detail':f'Khoản dành riêng #{mid} liên kết ví/mục tiêu không hợp lệ.'})
    checked_stash = 0
    for fund in db.scalars(select(StashFund).where(StashFund.user_id == u.id)):
        reserved = stash_fund_balance(db, fund.id, u.id)
        checked_stash += reserved
        if reserved < 0:
            checks.append({'kind':'negative_stash_fund','detail':f'Quỹ tích lũy #{fund.id} có số dư âm.'})
    if checked_stash != total_stash_funds(db,u.id):
        checks.append({'kind':'invalid_stash_total','detail':'Số dư quỹ tích lũy không khớp lịch sử.'})
    for fund in db.scalars(select(StashFund).where(StashFund.user_id == u.id)):
        mode,value=fund.auto_mode,int(fund.auto_value or 0)
        if mode not in ('off','percent','fixed') or (mode=='off' and value!=0) or \
           (mode=='percent' and not 1<=value<=100) or \
           (mode=='fixed' and not 1<=value<=MAX_AMOUNT):
            checks.append({'kind':'invalid_stash_auto_rule','detail':f'Quỹ #{fund.id} có quy tắc tự động không hợp lệ.'})
        if fund.auto_wallet_id is not None and not db.scalar(select(Wallet.id).where(Wallet.id==fund.auto_wallet_id, Wallet.user_id==u.id)):
            checks.append({'kind':'invalid_stash_auto_wallet','detail':f'Quỹ #{fund.id} gắn sai ví tự động.'})
    for m in db.scalars(select(StashMovement).where(StashMovement.user_id==u.id,StashMovement.source_entry_id.is_not(None))):
        source=db.scalar(select(Entry).where(Entry.id==m.source_entry_id,Entry.user_id==u.id))
        if source is None or source.kind!='income' or source.wallet_id!=m.wallet_id or m.kind!='deposit':
            checks.append({'kind':'invalid_stash_auto_source','detail':f'Bút toán tự góp #{m.id} không khớp khoản thu nguồn.'})
    for mid, wuid, fuid in db.execute(select(StashMovement.id,Wallet.user_id,StashFund.user_id)
            .outerjoin(Wallet,Wallet.id==StashMovement.wallet_id)
            .outerjoin(StashFund,StashFund.id==StashMovement.fund_id)
            .where(StashMovement.user_id==u.id)):
        if wuid != u.id or fuid != u.id:
            checks.append({'kind':'invalid_stash_link','detail':f'Giao dịch tích lũy #{mid} có liên kết sai.'})
    linked=db.execute(select(Entry.id,Entry.wallet_id,Wallet.user_id).outerjoin(Wallet,Entry.wallet_id==Wallet.id).where(Entry.user_id==u.id)).all()
    for eid,wid,wuid in linked:
        if wid is None or wuid!=u.id:
            checks.append({'kind':'invalid_wallet_link','detail':f'Giao dịch #{eid} không liên kết đúng ví.'})
    return {'ok':not checks,'checked_wallets':len(wallets),'checked_entries':len(linked),'issues':checks[:100]}


@app.get('/api/me')
def me(request:Request,db:Session=Depends(get_db)):
    u,s=session_lookup(request,db)
    return {'user':user_json(u),'csrf_token':s.csrf_token}


@app.post('/api/logout')
def logout(request:Request,response:Response,db:Session=Depends(get_db)):
    u,s=session_lookup(request,db)
    db.delete(s);log(db,u.id,'logout');db.commit()
    response.delete_cookie(COOKIE,path='/')
    return {'ok':True}


@app.post('/api/change-password')
def change_password(data:ChangePassword,request:Request,db:Session=Depends(get_db)):
    u,s=session_lookup(request,db)
    try: valid=ph.verify(u.password_hash,data.old_password)
    except (VerifyMismatchError,VerificationError): valid=False
    if not valid: raise HTTPException(422,'Mật khẩu hiện tại không đúng.')
    safe_password(data.new_password)
    if data.old_password==data.new_password: raise HTTPException(422,'Mật khẩu mới phải khác mật khẩu cũ.')
    u.password_hash=ph.hash(data.new_password)
    db.query(LoginChallenge).filter(LoginChallenge.user_id==u.id).delete(synchronize_session=False)
    db.query(PasswordResetToken).filter(PasswordResetToken.user_id==u.id).delete(synchronize_session=False)
    db.query(AuthSession).filter(AuthSession.user_id==u.id,AuthSession.id!=s.id).delete(synchronize_session=False)
    log(db,u.id,'password_changed','Đã đổi mật khẩu và thu hồi phiên khác')
    db.commit();return {'ok':True}


@app.put('/api/profile')
def update_profile(data:ProfileEdit,request:Request,db:Session=Depends(get_db)):
    u,_=session_lookup(request,db)
    try: ok=ph.verify(u.password_hash,data.current_password)
    except (VerifyMismatchError,VerificationError): ok=False
    if not ok: raise HTTPException(403,'Mật khẩu xác nhận không chính xác.')
    u.email=normalized_email(data.email)
    u.phone=normalized_phone(data.phone)
    u.address=normalized_address(data.address)
    try:
        log(db,u.id,'profile_updated','Cập nhật thông tin liên hệ')
        db.commit()
    except IntegrityError:
        db.rollback();raise HTTPException(409,'Email đã được sử dụng.')
    return user_json(u)


def email_enabled():
    return bool(os.environ.get('SMTP_HOST','').strip() and
                os.environ.get('SMTP_FROM','').strip())


def send_reset_email(address: str, token: str):
    host=os.environ['SMTP_HOST'].strip()
    port=int(os.environ.get('SMTP_PORT','587'))
    mode=os.environ.get('SMTP_SECURITY','starttls').strip().lower()
    if mode not in ('starttls','ssl'): raise ValueError('SMTP_SECURITY cần starttls hoặc ssl')
    sender=os.environ['SMTP_FROM'].strip()
    user=os.environ.get('SMTP_USER','').strip()
    password=os.environ.get('SMTP_PASSWORD','')
    link=f"{os.environ.get('APP_BASE_URL','http://127.0.0.1:8765').rstrip('/')}/reset?token={token}"
    message=EmailMessage()
    message['From']=sender
    message['To']=address
    message['Subject']='MoneyFlow - Yeu cau dat lai mat khau'
    message.set_content(f'Ban da yeu cau dat lai mat khau MoneyFlow.\n\nMo lien ket tren may cai MoneyFlow trong 15 phut:\n{link}\n\nNeu ban khong yeu cau, hay bo qua email nay.\n')
    ctx=ssl.create_default_context()
    if mode=='ssl':
        with smtplib.SMTP_SSL(host,port,timeout=12,context=ctx) as smtp:
            if user: smtp.login(user,password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(host,port,timeout=12) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ctx)
            smtp.ehlo()
            if user: smtp.login(user,password)
            smtp.send_message(message)


@app.get('/api/recovery-config')
def recovery_config():
    return {'email_configured':email_enabled()}


@app.post('/api/forgot-password')
def forgot_password(data:ForgotPassword,db:Session=Depends(get_db)):
    email=normalized_email(data.email)
    if not email_enabled():
        raise HTTPException(503,'Chưa cấu hình SMTP gửi email. Xem mục Khôi phục mật khẩu trong README.')
    generic={'ok':True,'message':'Nếu email đã đăng ký, bạn sẽ nhận được liên kết đặt lại mật khẩu trong ít phút.'}
    u=db.scalar(select(User).where(User.email==email,User.active==True))
    if not u: return generic
    cutoff=utcnow()-timedelta(hours=1)
    reqs=list(db.scalars(select(PasswordResetToken).where(PasswordResetToken.user_id==u.id,
                   PasswordResetToken.created_at>=cutoff).order_by(PasswordResetToken.created_at.desc())))
    if len(reqs)>=RESET_HOURLY_LIMIT or (reqs and as_utc(reqs[0].created_at)>utcnow()-timedelta(seconds=RESET_COOLDOWN_SECONDS)):
        return generic
    token=secrets.token_urlsafe(48)
    db.add(PasswordResetToken(user_id=u.id,token_hash=hashlib.sha256(token.encode()).hexdigest(),
                              created_at=utcnow(),expires_at=utcnow()+timedelta(minutes=RESET_MINUTES)))
    db.commit()
    try:
        send_reset_email(u.email,token)
    except (smtplib.SMTPException,OSError,ValueError):
        # Never leak a recovery token into UI or logs; failed delivery invalidates this token.
        db.query(PasswordResetToken).filter(PasswordResetToken.token_hash==hashlib.sha256(token.encode()).hexdigest()).delete()
        db.commit()
        raise HTTPException(503,'Không thể gửi email khôi phục. Kiểm tra cài đặt SMTP và kết nối mạng.')
    return generic


@app.post('/api/reset-password-by-email')
def reset_password_by_email(data:CompleteReset,db:Session=Depends(get_db)):
    safe_password(data.new_password)
    hashed=hashlib.sha256(data.token.encode()).hexdigest()
    reset=db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash==hashed).with_for_update())
    if not reset or reset.used_at or as_utc(reset.expires_at)<=utcnow():
        raise HTTPException(422,'Liên kết đã hết hạn hoặc đã sử dụng. Vui lòng yêu cầu liên kết mới.')
    u=db.get(User,reset.user_id)
    if not u or not u.active:raise HTTPException(422,'Liên kết không hợp lệ.')
    u.password_hash=ph.hash(data.new_password)
    u.failed_attempts=0
    u.locked_until=None
    reset.used_at=utcnow()
    db.query(PasswordResetToken).filter(PasswordResetToken.user_id==u.id,
            PasswordResetToken.id!=reset.id).delete(synchronize_session=False)
    db.query(LoginChallenge).filter(LoginChallenge.user_id==u.id).delete(synchronize_session=False)
    db.query(AuthSession).filter(AuthSession.user_id==u.id).delete(synchronize_session=False)
    log(db,u.id,'password_recovered','Đặt lại mật khẩu qua email; thu hồi mọi phiên')
    db.commit()
    return {'ok':True}

def valid_month(value):
    if not MONTH_PATTERN.fullmatch(value): raise HTTPException(422,'Tháng phải có dạng YYYY-MM.')
    y, m = int(value[:4]), int(value[5:])
    if not (2000 <= y <= 2099): raise HTTPException(422, 'Năm phải nằm từ 2000 đến 2099.')
    return y, m


def month_bounds(value):
    y,m=valid_month(value)
    return date(y,m,1),date(y+1,1,1) if m==12 else date(y,m+1,1)


def category_for(db,u,cat_id,kind=None,require_active=False):
    cat=db.scalar(select(Category).where(Category.id==cat_id,Category.user_id==u.id))
    if not cat or (kind and cat.kind!=kind) or (require_active and not cat.active): raise HTTPException(422,'Danh mục không hợp lệ hoặc không thuộc tài khoản này.')
    return cat


def entry_json(e,cats,paid=0):
    c=cats.get(e.category_id)
    return {'id':e.id,'kind':e.kind,'wallet_id':e.wallet_id,'title':e.title,'amount':e.amount,'category_id':e.category_id,'category':c.name if c else 'Không rõ','color':c.color if c else '#7567F8','note':e.note,'occurred_on':e.occurred_on.isoformat(),'created_at':e.created_at.isoformat(),'debt_paid':paid}


def debt_dict(d: Debt):
    return {'id':d.id,'name':d.name,'lender':d.lender,'principal':d.principal,
            'remaining':d.remaining,'paid':d.principal-d.remaining,
            'direction':d.direction,'interest_rate_pct':float(Decimal(d.annual_rate_bps or 0)/100),
            'installment_count':d.installment_count,
            'due_date':d.due_date.isoformat() if d.due_date else None,
            'note':d.note,'created_at':d.created_at.isoformat()}


@app.get('/api/debts')
def list_debts(u:User=Depends(current),db:Session=Depends(get_db)):
    debts=list(db.scalars(select(Debt).where(Debt.user_id==u.id).order_by(Debt.id)))
    payments=list(db.scalars(select(DebtPayment).where(DebtPayment.user_id==u.id).order_by(DebtPayment.paid_on.desc(),DebtPayment.id.desc()).limit(100)))
    names={debt.id:debt.name for debt in debts}
    directions={debt.id:debt.direction for debt in debts}
    payables=[d for d in debts if d.direction=='payable']
    receivables=[d for d in debts if d.direction=='receivable']
    return {'items':[debt_dict(d) for d in debts],
            'total_principal':sum(d.principal for d in payables),
            'total_remaining':sum(d.remaining for d in payables),
            'total_paid':sum(d.principal-d.remaining for d in payables),
            'total_receivable_principal':sum(d.principal for d in receivables),
            'total_receivable_remaining':sum(d.remaining for d in receivables),
            'total_receivable_collected':sum(d.principal-d.remaining for d in receivables),
            'total_interest_paid':int(db.scalar(select(func.coalesce(func.sum(DebtPayment.interest_amount),0)).join(Debt, Debt.id==DebtPayment.debt_id).where(DebtPayment.user_id==u.id,Debt.direction=='payable')) or 0),
            'total_interest_received':int(db.scalar(select(func.coalesce(func.sum(DebtPayment.interest_amount),0)).join(Debt, Debt.id==DebtPayment.debt_id).where(DebtPayment.user_id==u.id,Debt.direction=='receivable')) or 0),
            'payments':[{'id':p.id,'debt_id':p.debt_id,'debt':names.get(p.debt_id,''),
                         'direction':directions.get(p.debt_id,'payable'),
                         'entry_id':p.entry_id,'wallet_id':p.wallet_id,'amount':p.amount,
                         'interest_amount':p.interest_amount or 0,'mode':p.mode,
                         'paid_on':p.paid_on.isoformat()} for p in payments]}


@app.get('/api/debts/{debt_id}/schedule')
def get_debt_schedule(debt_id:int,u:User=Depends(current),db:Session=Depends(get_db)):
    d=db.scalar(select(Debt).where(Debt.user_id==u.id,Debt.id==debt_id))
    if not d:raise HTTPException(404,'Không tìm thấy khoản nợ.')
    rows=debt_schedule_rows(d)
    interest_paid=int(db.scalar(select(func.coalesce(func.sum(DebtPayment.interest_amount),0)).where(
        DebtPayment.user_id==u.id,DebtPayment.debt_id==d.id)) or 0)
    return {'debt':debt_dict(d),'schedule':rows,
            'estimated_total_interest':sum(x['estimated_interest'] for x in rows),
            'actual_interest_recorded':interest_paid,
            'disclaimer':'Lịch dự tính theo dư nợ giảm dần, gốc chia đều mỗi kỳ; chưa tự động ghi nhận lãi hoặc tạo giao dịch.'}


@app.post('/api/debts')
def create_debt(data:NewDebt,u:User=Depends(current),db:Session=Depends(get_db)):
    check_amount(data.principal)
    if not data.name.strip():raise HTTPException(422,'Tên khoản nợ không được rỗng.')
    if data.installment_count > 1 and not data.due_date:
        raise HTTPException(422,'Cần ngày đến hạn kỳ đầu để lập lịch trả góp.')
    if data.installment_count > data.principal:
        raise HTTPException(422,'Số kỳ không thể lớn hơn số đơn vị tiền gốc (VNĐ).')
    account_locked(db,u.id)
    d=Debt(user_id=u.id,name=data.name.strip(),lender=data.lender.strip(),
           principal=data.principal,remaining=data.principal,due_date=data.due_date,
           direction=data.direction,
           annual_rate_bps=int(data.interest_rate_pct * 100),installment_count=data.installment_count,
           note=data.note.strip())
    db.add(d);db.flush();log(db,u.id,'debt_created',f'#{d.id}: {d.principal} {d.direction}');db.commit()
    return debt_dict(d)


@app.put('/api/debts/{debt_id}')
def edit_debt(debt_id:int,data:NewDebt,u:User=Depends(current),db:Session=Depends(get_db)):
    check_amount(data.principal)
    if not data.name.strip():raise HTTPException(422,'Tên khoản nợ không được rỗng.')
    if data.installment_count > 1 and not data.due_date:
        raise HTTPException(422,'Cần ngày đến hạn kỳ đầu để lập lịch trả góp.')
    if data.installment_count > data.principal:
        raise HTTPException(422,'Số kỳ không thể lớn hơn số đơn vị tiền gốc (VNĐ).')
    account_locked(db,u.id)
    d=db.scalar(select(Debt).where(Debt.user_id==u.id,Debt.id==debt_id).with_for_update())
    if not d:raise HTTPException(404,'Không tìm thấy khoản nợ.')
    paid=db.scalar(select(func.count()).select_from(DebtPayment).where(DebtPayment.debt_id==d.id))
    new_bps=int(data.interest_rate_pct*100)
    if paid and (data.principal!=d.principal or data.direction!=d.direction or
                 new_bps!=(d.annual_rate_bps or 0) or data.installment_count!=d.installment_count or data.due_date!=d.due_date):
        raise HTTPException(409,'Khoản nợ đã có thanh toán: không thể đổi gốc, chiều nợ, lãi suất hay lịch trả góp.')
    if data.principal!=d.principal:d.principal=data.principal;d.remaining=data.principal
    d.direction=data.direction;d.annual_rate_bps=new_bps;d.installment_count=data.installment_count
    d.name=data.name.strip();d.lender=data.lender.strip();d.due_date=data.due_date;d.note=data.note.strip()
    db.flush();log(db,u.id,'debt_edited',f'#{d.id}');db.commit();return debt_dict(d)


@app.delete('/api/debts/{debt_id}')
def delete_debt(debt_id:int,u:User=Depends(current),db:Session=Depends(get_db)):
    account_locked(db,u.id)
    d=db.scalar(select(Debt).where(Debt.user_id==u.id,Debt.id==debt_id).with_for_update())
    if not d:raise HTTPException(404,'Không tìm thấy khoản nợ.')
    if db.scalar(select(func.count()).select_from(DebtPayment).where(DebtPayment.debt_id==d.id)):
        raise HTTPException(409,'Khoản nợ đã có lịch sử thanh toán. Không thể xóa để bảo toàn sổ sách.')
    db.delete(d);log(db,u.id,'debt_deleted',f'#{debt_id}');db.commit();return {'ok':True}


@app.post('/api/debts/{debt_id}/payments')
def pay_debt_manual(debt_id:int,data:ManualDebtPayment,u:User=Depends(current),db:Session=Depends(get_db)):
    amount=check_amount(data.amount)
    interest=check_amount(data.interest_amount,zero=True)
    if amount+interest>MAX_AMOUNT:raise HTTPException(422,'Tổng tiền vượt hạn mức.')
    if data.paid_on>date.today()+timedelta(days=366):raise HTTPException(422,'Ngày thanh toán không hợp lệ.')
    account_locked(db,u.id)
    debt=db.scalar(select(Debt).where(Debt.user_id==u.id,Debt.id==debt_id).with_for_update())
    if not debt:raise HTTPException(404,'Không tìm thấy khoản nợ.')
    if amount>debt.remaining:raise HTTPException(409,'Số tiền gốc vượt quá số dư nợ còn lại.')
    wallet=wallet_for(db,u.id,data.wallet_id,require_active=True)
    if debt.direction=='payable' and amount+interest>wallet_balance(db,wallet):
        raise HTTPException(409,'Ví đã chọn không đủ tiền để trả gốc và lãi.')
    debt.remaining-=amount
    db.add(DebtPayment(user_id=u.id,debt_id=debt.id,wallet_id=wallet.id,amount=amount,
                       interest_amount=interest,mode='manual',paid_on=data.paid_on))
    db.flush();ensure_nonnegative(db,u.id)
    log(db,u.id,'debt_manual_payment',f'#{debt.id}: principal={amount}, interest={interest}');db.commit()
    return {'ok':True,'remaining':debt.remaining}


@app.delete('/api/debt-payments/{payment_id}')
def undo_manual_payment(payment_id:int,u:User=Depends(current),db:Session=Depends(get_db)):
    account_locked(db,u.id)
    p=db.scalar(select(DebtPayment).where(DebtPayment.user_id==u.id,DebtPayment.id==payment_id).with_for_update())
    if not p:raise HTTPException(404,'Không tìm thấy thanh toán.')
    if p.mode!='manual':raise HTTPException(409,'Thanh toán tự động chỉ có thể điều chỉnh bằng giao dịch thu nguồn.')
    d=db.scalar(select(Debt).where(Debt.id==p.debt_id,Debt.user_id==u.id).with_for_update())
    d.remaining+=p.amount;db.delete(p)
    db.flush();ensure_nonnegative(db,u.id)
    log(db,u.id,'debt_payment_undone',f'#{payment_id}');db.commit();return {'ok':True}



# v1.0.17 - Savings goals: ledger transfers between wallet availability and
# reserved funds, never posted as earnings/expenses. Saved funds remain assets.
def savings_goal_for(db: Session, user_id: int, goal_id: int, lock: bool = False) -> SavingsGoal:
    stmt = select(SavingsGoal).where(SavingsGoal.id == goal_id, SavingsGoal.user_id == user_id)
    if lock:
        stmt = stmt.with_for_update()
    goal = db.scalar(stmt)
    if goal is None:
        raise HTTPException(404, 'Không tìm thấy mục tiêu tiết kiệm.')
    return goal


def savings_goal_json(db: Session, goal: SavingsGoal) -> dict:
    saved = savings_goal_balance(db, goal.id, goal.user_id)
    return {'id': goal.id, 'name': goal.name, 'target_amount': goal.target_amount,
            'saved_amount': saved, 'remaining_amount': max(0, goal.target_amount - saved),
            'progress_pct': round(min(100, saved * 100 / goal.target_amount), 1),
            'complete': saved >= goal.target_amount,
            'due_date': goal.due_date.isoformat() if goal.due_date else None,
            'note': goal.note, 'created_at': goal.created_at.isoformat()}


@app.get('/api/savings')
def list_savings(u: User = Depends(current), db: Session = Depends(get_db)):
    goals = list(db.scalars(select(SavingsGoal).where(SavingsGoal.user_id == u.id).order_by(SavingsGoal.id.desc())))
    items = [savings_goal_json(db, g) for g in goals]
    moves = list(db.scalars(select(SavingsMovement).where(SavingsMovement.user_id == u.id)
                            .order_by(SavingsMovement.occurred_on.desc(), SavingsMovement.id.desc()).limit(100)))
    names = {g.id:g.name for g in goals}
    wallets = {w.id:w.name for w in db.scalars(select(Wallet).where(Wallet.user_id == u.id))}
    return {'items': items, 'total_saved': sum(g['saved_amount'] for g in items),
            'total_targets': sum(g['target_amount'] for g in items),
            'history': [{'id':m.id,'goal_id':m.goal_id,'goal':names.get(m.goal_id,''),
                         'wallet_id':m.wallet_id,'wallet':wallets.get(m.wallet_id,''),
                         'kind':m.kind,'amount':m.amount,'occurred_on':m.occurred_on.isoformat(),
                         'note':m.note} for m in moves]}


@app.post('/api/savings')
def create_savings_goal(data: NewSavingsGoal, u: User = Depends(current), db: Session = Depends(get_db)):
    account_locked(db, u.id)
    name = data.name.strip()
    if not name:
        raise HTTPException(422, 'Tên mục tiêu không được rỗng.')
    target = check_amount(data.target_amount)
    if data.due_date and data.due_date.year > 2099:
        raise HTTPException(422, 'Ngày mục tiêu không hợp lệ.')
    if (db.scalar(select(func.count(SavingsGoal.id)).where(SavingsGoal.user_id == u.id)) or 0) >= 50:
        raise HTTPException(409, 'Mỗi tài khoản tối đa 50 mục tiêu.')
    goal = SavingsGoal(user_id=u.id,name=name,target_amount=target,due_date=data.due_date,note=data.note.strip())
    db.add(goal);db.flush();log(db,u.id,'savings_created',f'#{goal.id}: {name}');db.commit()
    return savings_goal_json(db,goal)


@app.put('/api/savings/{goal_id}')
def update_savings_goal(goal_id: int, data: NewSavingsGoal, u: User = Depends(current), db: Session = Depends(get_db)):
    account_locked(db,u.id)
    goal = savings_goal_for(db,u.id,goal_id,True)
    if not data.name.strip():
        raise HTTPException(422,'Tên mục tiêu không được rỗng.')
    target = check_amount(data.target_amount)
    if target < savings_goal_balance(db,goal.id,u.id):
        raise HTTPException(409,'Mục tiêu mới không thể nhỏ hơn số tiền đã dành riêng.')
    goal.name=data.name.strip();goal.target_amount=target;goal.due_date=data.due_date;goal.note=data.note.strip()
    log(db,u.id,'savings_updated',f'#{goal.id}');db.commit()
    return savings_goal_json(db,goal)


@app.delete('/api/savings/{goal_id}')
def delete_savings_goal(goal_id: int, u: User = Depends(current), db: Session = Depends(get_db)):
    account_locked(db,u.id)
    goal = savings_goal_for(db,u.id,goal_id,True)
    if savings_goal_balance(db,goal.id,u.id) != 0:
        raise HTTPException(409,'Cần rút hết tiền dành riêng trước khi xóa mục tiêu.')
    # Delete historical movements only when zero balance; logs preserve account-level audit.
    db.query(SavingsMovement).filter(SavingsMovement.goal_id == goal.id, SavingsMovement.user_id == u.id).delete(synchronize_session=False)
    db.delete(goal);log(db,u.id,'savings_deleted',f'#{goal_id}');db.commit()
    return {'ok':True}


@app.post('/api/savings/{goal_id}/movements')
def move_savings(goal_id: int,data: NewSavingsMovement,u: User = Depends(current),db: Session = Depends(get_db)):
    amount=check_amount(data.amount)
    if data.occurred_on > date.today() + timedelta(days=366):
        raise HTTPException(422,'Ngày giao dịch không hợp lệ.')
    account_locked(db,u.id)
    goal=savings_goal_for(db,u.id,goal_id,True)
    wallet=wallet_for(db,u.id,data.wallet_id,require_active=True)
    saved=savings_goal_balance(db,goal.id,u.id)
    if data.kind == 'deposit':
        if amount > goal.target_amount - saved:
            raise HTTPException(409,'Số tiền góp vượt mức mục tiêu còn thiếu.')
        if wallet_balance(db,wallet) < amount:
            raise HTTPException(409,'Ví không đủ tiền khả dụng để dành riêng.')
    elif amount > saved:
        raise HTTPException(409,'Không thể rút quá tiền đã dành riêng trong mục tiêu.')
    move=SavingsMovement(user_id=u.id,goal_id=goal.id,wallet_id=wallet.id,
                         kind=data.kind,amount=amount,occurred_on=data.occurred_on,note=data.note.strip())
    db.add(move);db.flush();ensure_nonnegative(db,u.id)
    log(db,u.id,'savings_'+data.kind,f'#{goal.id} wallet:{wallet.id} {amount}')
    db.commit()
    return {'ok':True,'movement_id':move.id,'saved_amount':savings_goal_balance(db,goal.id,u.id)}


def stash_fund_for(db: Session, user_id: int, fund_id: int, lock: bool = False) -> StashFund:
    stmt = select(StashFund).where(StashFund.id == fund_id, StashFund.user_id == user_id)
    if lock:
        stmt = stmt.with_for_update()
    fund = db.scalar(stmt)
    if not fund:
        raise HTTPException(404, 'Quỹ tích để dành không tồn tại.')
    return fund


def validate_stash_auto_wallet(db: Session, user_id: int, data: NewStashFund) -> None:
    if data.auto_mode != 'off' and data.auto_wallet_id is not None:
        wallet_for(db, user_id, data.auto_wallet_id, require_active=True)
    if data.auto_mode == 'off' and data.auto_wallet_id is not None:
        raise HTTPException(422, 'Không chọn ví khi đã tắt tích lũy tự động.')


def stash_fund_json(db: Session, fund: StashFund) -> dict:
    return {'id':fund.id, 'name':fund.name, 'note':fund.note,
            'auto_mode':fund.auto_mode, 'auto_value':fund.auto_value, 'auto_wallet_id':fund.auto_wallet_id,
            'saved_amount':stash_fund_balance(db,fund.id,fund.user_id),
            'created_at':fund.created_at.isoformat()}


@app.get('/api/stashes')
def list_stashes(u: User = Depends(current), db: Session = Depends(get_db)):
    funds = list(db.scalars(select(StashFund).where(StashFund.user_id == u.id).order_by(StashFund.id.desc())))
    wallets = {w.id:w.name for w in db.scalars(select(Wallet).where(Wallet.user_id == u.id))}
    history = list(db.scalars(select(StashMovement).where(StashMovement.user_id == u.id)
                              .order_by(StashMovement.occurred_on.desc(), StashMovement.id.desc()).limit(100)))
    names = {f.id:f.name for f in funds}
    items = [stash_fund_json(db,f) for f in funds]
    return {'items':items, 'total_saved':sum(f['saved_amount'] for f in items),
            'history':[{'id':m.id,'fund_id':m.fund_id,'fund':names.get(m.fund_id,''),
                        'wallet_id':m.wallet_id,'wallet':wallets.get(m.wallet_id,''),
                        'kind':m.kind,'amount':m.amount,'occurred_on':m.occurred_on.isoformat(),
                        'source': 'auto' if m.source_entry_id is not None else 'manual',
                        'source_entry_id':m.source_entry_id,
                        'note':m.note} for m in history]}


@app.post('/api/stashes')
def create_stash(data: NewStashFund, u: User = Depends(current), db: Session = Depends(get_db)):
    account_locked(db,u.id)
    name=data.name.strip()
    if not name:
        raise HTTPException(422,'Tên quỹ không được để trống.')
    if (db.scalar(select(func.count(StashFund.id)).where(StashFund.user_id==u.id)) or 0)>=50:
        raise HTTPException(409,'Mỗi tài khoản tối đa 50 quỹ tích để dành.')
    validate_stash_auto_wallet(db,u.id,data)
    fund=StashFund(user_id=u.id,name=name,note=data.note.strip(),
                   auto_mode=data.auto_mode,auto_value=data.auto_value,
                   auto_wallet_id=data.auto_wallet_id)
    db.add(fund);db.flush();log(db,u.id,'stash_created',f'#{fund.id}: {name}');db.commit()
    return stash_fund_json(db,fund)


@app.put('/api/stashes/{fund_id}')
def update_stash(fund_id:int,data:NewStashFund,u:User=Depends(current),db:Session=Depends(get_db)):
    account_locked(db,u.id)
    fund=stash_fund_for(db,u.id,fund_id,True)
    name=data.name.strip()
    if not name:
        raise HTTPException(422,'Tên quỹ không được để trống.')
    validate_stash_auto_wallet(db,u.id,data)
    fund.name=name;fund.note=data.note.strip()
    fund.auto_mode=data.auto_mode;fund.auto_value=data.auto_value
    fund.auto_wallet_id=data.auto_wallet_id
    log(db,u.id,'stash_updated',f'#{fund.id}; auto={data.auto_mode}/{data.auto_value}');db.commit()
    return stash_fund_json(db,fund)


@app.delete('/api/stashes/{fund_id}')
def delete_stash(fund_id:int,u:User=Depends(current),db:Session=Depends(get_db)):
    account_locked(db,u.id)
    fund=stash_fund_for(db,u.id,fund_id,True)
    if stash_fund_balance(db,fund.id,u.id) != 0:
        raise HTTPException(409,'Phải rút hết tiền trước khi xóa quỹ.')
    if db.scalar(select(func.count(StashMovement.id)).where(StashMovement.fund_id==fund.id)):
        raise HTTPException(409,'Quỹ đã có lịch sử góp/rút. Để bảo toàn sổ giao dịch, chỉ được đổi tên.')
    db.delete(fund);log(db,u.id,'stash_deleted',f'#{fund_id}');db.commit()
    return {'ok':True}


@app.post('/api/stashes/{fund_id}/movements')
def move_stash(fund_id:int,data:NewStashMovement,u:User=Depends(current),db:Session=Depends(get_db)):
    amount=check_amount(data.amount)
    if data.occurred_on > date.today() + timedelta(days=366):
        raise HTTPException(422,'Ngày giao dịch không hợp lệ.')
    # Serialize every wallet mutation for this user; keeps balance checks atomic on PostgreSQL.
    account_locked(db,u.id)
    fund=stash_fund_for(db,u.id,fund_id,True)
    wallet=wallet_for(db,u.id,data.wallet_id,require_active=True)
    saved=stash_fund_balance(db,fund.id,u.id)
    if data.kind=='deposit':
        if wallet_balance(db,wallet)<amount:
            raise HTTPException(409,'Ví không đủ số dư khả dụng để tích lũy.')
    elif amount>saved:
        raise HTTPException(409,'Không thể rút nhiều hơn số tiền đang để dành.')
    movement=StashMovement(user_id=u.id,fund_id=fund.id,wallet_id=wallet.id,kind=data.kind,
                            amount=amount,occurred_on=data.occurred_on,note=data.note.strip())
    db.add(movement);db.flush();ensure_nonnegative(db,u.id)
    log(db,u.id,'stash_'+data.kind,f'#{fund.id} wallet:{wallet.id} {amount}')
    db.commit()
    return {'ok':True,'movement_id':movement.id,'saved_amount':stash_fund_balance(db,fund.id,u.id)}


@app.get('/api/wallets')
def list_wallets(u:User=Depends(current),db:Session=Depends(get_db)):
    default_wallet(db,u.id)
    wallets=list(db.scalars(select(Wallet).where(Wallet.user_id==u.id).order_by(Wallet.id)))
    items=[wallet_json(db,w) for w in wallets]
    transfers=list(db.scalars(select(WalletTransfer).where(WalletTransfer.user_id==u.id).order_by(WalletTransfer.occurred_on.desc(),WalletTransfer.id.desc()).limit(100)))
    names={w.id:w.name for w in wallets}
    return {'items':items,'total_balance':sum(w['balance'] for w in items),
            'transfers':[{'id':t.id,'from_wallet_id':t.from_wallet_id,'to_wallet_id':t.to_wallet_id,
                          'from_wallet':names.get(t.from_wallet_id,''),'to_wallet':names.get(t.to_wallet_id,''),
                          'amount':t.amount,'occurred_on':t.occurred_on.isoformat(),'note':t.note}
                         for t in transfers]}


@app.post('/api/wallets')
def create_wallet(data:NewWallet,u:User=Depends(current),db:Session=Depends(get_db)):
    name=data.name.strip()
    if not name:raise HTTPException(422,'Tên ví không được rỗng.')
    check_amount(data.opening_balance,zero=True)
    account_locked(db,u.id)
    default_wallet(db,u.id)
    if db.scalar(select(func.count(Wallet.id)).where(Wallet.user_id==u.id)) >= 30:
        raise HTTPException(409,'Mỗi tài khoản tối đa 30 ví.')
    w=Wallet(user_id=u.id,name=name,kind=data.kind,opening_balance=data.opening_balance)
    db.add(w);db.flush();log(db,u.id,'wallet_created',f'#{w.id}: {name}');db.commit()
    return wallet_json(db,w)


@app.put('/api/wallets/{wallet_id}')
def edit_wallet(wallet_id:int,data:EditWallet,u:User=Depends(current),db:Session=Depends(get_db)):
    if not data.name.strip():raise HTTPException(422,'Tên ví không được rỗng.')
    account_locked(db,u.id)
    w=wallet_for(db,u.id,wallet_id)
    w.name=data.name.strip();w.kind=data.kind
    log(db,u.id,'wallet_edited',f'#{w.id}');db.commit()
    return wallet_json(db,w)


@app.post('/api/wallets/{wallet_id}/toggle')
def toggle_wallet(wallet_id:int,u:User=Depends(current),db:Session=Depends(get_db)):
    account_locked(db,u.id)
    w=wallet_for(db,u.id,wallet_id)
    if w.is_default:raise HTTPException(409,'Không thể vô hiệu hóa ví chính.')
    if w.active and wallet_balance(db,w)!=0:raise HTTPException(409,'Chỉ có thể khóa ví khi số dư bằng 0.')
    w.active=not w.active
    log(db,u.id,'wallet_toggled',f'#{w.id}: {w.active}');db.commit()
    return wallet_json(db,w)


@app.post('/api/wallet-transfers')
def create_wallet_transfer(data:TransferWallet,u:User=Depends(current),db:Session=Depends(get_db)):
    amount=check_amount(data.amount)
    if data.from_wallet_id==data.to_wallet_id:raise HTTPException(422,'Ví gửi và ví nhận phải khác nhau.')
    if data.occurred_on>date.today()+timedelta(days=366):raise HTTPException(422,'Ngày giao dịch không hợp lệ.')
    account_locked(db,u.id)
    src=wallet_for(db,u.id,data.from_wallet_id,require_active=True)
    dst=wallet_for(db,u.id,data.to_wallet_id,require_active=True)
    if wallet_balance(db,src)<amount:raise HTTPException(409,'Ví gửi không đủ tiền.')
    t=WalletTransfer(user_id=u.id,from_wallet_id=src.id,to_wallet_id=dst.id,
                     amount=amount,occurred_on=data.occurred_on,note=data.note.strip())
    db.add(t);db.flush();ensure_nonnegative(db,u.id)
    log(db,u.id,'wallet_transfer',f'#{t.id}: {src.id}->{dst.id} {amount}');db.commit()
    return {'ok':True,'id':t.id}


@app.delete('/api/wallet-transfers/{transfer_id}')
def undo_wallet_transfer(transfer_id:int,u:User=Depends(current),db:Session=Depends(get_db)):
    account_locked(db,u.id)
    t=db.scalar(select(WalletTransfer).where(WalletTransfer.user_id==u.id,WalletTransfer.id==transfer_id).with_for_update())
    if not t:raise HTTPException(404,'Không tìm thấy chuyển tiền.')
    db.delete(t);db.flush();ensure_nonnegative(db,u.id)
    log(db,u.id,'wallet_transfer_undone',f'#{transfer_id}');db.commit()
    return {'ok':True}


# v1.0.14 - Periodic rules, idempotent posting and local reminders.
# No external email or background cloud process. Scheduler works while FastAPI is running.
RECURRENCE_STEPS = {'daily': 1, 'weekly': 7, 'monthly': 1, 'yearly': 12}


def scheduled_date(rule: RecurringRule) -> date:
    i = rule.next_index
    if rule.frequency == 'daily':
        return rule.start_on + timedelta(days=i)
    if rule.frequency == 'weekly':
        return rule.start_on + timedelta(weeks=i)
    if rule.frequency in ('monthly', 'yearly'):
        return add_months_clamped(rule.start_on, i * (12 if rule.frequency == 'yearly' else 1))
    raise ValueError('Tần suất không hợp lệ.')


def recurring_json(db: Session, rule: RecurringRule) -> dict:
    return {'id':rule.id,'title':rule.title,'kind':rule.kind,'amount':rule.amount,
            'category_id':rule.category_id,'wallet_id':rule.wallet_id,'note':rule.note,
            'frequency':rule.frequency,'start_on':rule.start_on.isoformat(),
            'next_due':scheduled_date(rule).isoformat(),'mode':rule.mode,
            'remind_days':rule.remind_days,'active':rule.active,'processed_count':rule.next_index}


def post_recurring_once(db: Session, rule: RecurringRule, due: date, skip=False) -> dict:
    """Called only in a write transaction after locking a rule (on PostgreSQL).

    entry and run are committed together; rollback on insufficient balance or errors.
    """
    if scheduled_date(rule) != due:
        raise HTTPException(409, 'Lịch đã thay đổi, vui lòng tải lại.')
    if due > date.today():
        raise HTTPException(409, 'Chưa tới ngày của kỳ thanh toán.')
    if not rule.active:
        raise HTTPException(409, 'Lịch đang tạm dừng.')
    owner=db.get(User,rule.user_id)
    if owner is None or not owner.active:
        raise HTTPException(409, 'Tài khoản đang bị khóa hoặc không tồn tại.')
    existing = db.scalar(select(RecurringRun).where(RecurringRun.rule_id == rule.id, RecurringRun.due_on == due))
    if existing:
        raise HTTPException(409, 'Kỳ này đã được xử lý.')
    entry_id = None
    auto_paid = 0
    auto_saved = 0
    if not skip:
        # Existing business rules: pay only *payable* debt principal from new income.
        category_for(db, db.get(User,rule.user_id), rule.category_id,rule.kind,True)
        wallet_for(db,rule.user_id,rule.wallet_id,True)
        e = Entry(user_id=rule.user_id, title=rule.title,kind=rule.kind,amount=rule.amount,
                  wallet_id=rule.wallet_id,category_id=rule.category_id, note=rule.note,
                  occurred_on=due)
        db.add(e)
        db.flush()
        auto_paid=allocate_income_to_debts(db,rule.user_id,e)
        auto_saved=allocate_income_to_stashes(db,rule.user_id,e,auto_paid)
        ensure_nonnegative(db,rule.user_id)
        entry_id=e.id
    db.add(RecurringRun(user_id=rule.user_id,rule_id=rule.id,due_on=due,
                        entry_id=entry_id,status='skipped' if skip else 'posted'))
    rule.next_index+=1
    log(db,rule.user_id,'recurring_skipped' if skip else 'recurring_posted',
        f'#{rule.id} {due.isoformat()}; entry={entry_id}; debt_paid={auto_paid}; auto_saved={auto_saved}')
    db.flush()
    return {'ok':True,'entry_id':entry_id,'due_on':due.isoformat(),'debt_paid':auto_paid,'auto_saved':auto_saved}


def process_auto_recurring():
    """Runs outside HTTP in a dedicated session; incomplete payments are retried later.

    A row lock protects cursor advancement under concurrent scheduler/HTTP calls.
    Do not catch financial exceptions inside the transaction: rollback all postings.
    """
    with SessionLocal() as db:
        ids=list(db.scalars(select(RecurringRule.id).where(
            RecurringRule.active == True, RecurringRule.mode == 'auto').order_by(RecurringRule.id)))
    for rule_id in ids:
        for _ in range(30):  # bounded catch-up per tick, no unlimited loop
            try:
                with SessionLocal.begin() as db:
                    # Lock the user BEFORE the rule, matching manual changes and
                    # all wallet/stash mutations; avoids reversed lock ordering.
                    owner_id=db.scalar(select(RecurringRule.user_id).where(RecurringRule.id == rule_id))
                    if owner_id is None:
                        break
                    account_locked(db, owner_id)
                    rule=db.scalar(select(RecurringRule).where(RecurringRule.id == rule_id).with_for_update())
                    if not rule or not rule.active or rule.mode!='auto':
                        break
                    due=scheduled_date(rule)
                    if due > date.today():
                        break
                    post_recurring_once(db,rule,due)
            except HTTPException as exc:
                logging.getLogger('moneyflow.recurring').warning('Lịch #%s tạm hoãn: %s',rule_id,exc.detail)
                break
            except IntegrityError:
                # Unique occurrence guard in case of concurrent requests.
                break
            except Exception:
                logging.getLogger('moneyflow.recurring').exception('Không xử lý được lịch #%s',rule_id)
                break


async def recurring_scheduler():
    # The local app must remain running to execute automatically. If stopped,
    # outstanding dates are processed on the next start, bounded per cycle.
    while True:
        try:
            await asyncio.to_thread(process_auto_recurring)
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.getLogger('moneyflow.recurring').exception('Lỗi lập lịch')
        await asyncio.sleep(60)


@app.get('/api/recurring')
def list_recurring(u:User=Depends(current),db:Session=Depends(get_db)):
    rules=list(db.scalars(select(RecurringRule).where(RecurringRule.user_id==u.id).order_by(RecurringRule.id.desc())))
    runs=list(db.scalars(select(RecurringRun).where(RecurringRun.user_id==u.id).order_by(RecurringRun.id.desc()).limit(100)))
    return {'items':[recurring_json(db,r) for r in rules],
            'history':[{'id':r.id,'rule_id':r.rule_id,'due_on':r.due_on.isoformat(),
                        'entry_id':r.entry_id,'status':r.status} for r in runs]}


@app.post('/api/recurring')
def create_recurring(data:NewRecurring,u:User=Depends(current),db:Session=Depends(get_db)):
    check_amount(data.amount)
    if not data.title.strip():raise HTTPException(422,'Nội dung không được rỗng.')
    if data.start_on.year<2000 or data.start_on.year>2099:raise HTTPException(422,'Ngày bắt đầu không hợp lệ.')
    if data.mode=='auto' and data.start_on<date.today():
        raise HTTPException(422,'Lịch tự động mới phải bắt đầu từ hôm nay trở đi.')
    account_locked(db,u.id)
    category_for(db,u,data.category_id,data.kind,True)
    wallet_for(db,u.id,data.wallet_id,True)
    if (db.scalar(select(func.count()).select_from(RecurringRule).where(RecurringRule.user_id==u.id)) or 0)>=100:
        raise HTTPException(422,'Tối đa 100 lịch định kỳ mỗi tài khoản.')
    obj=RecurringRule(user_id=u.id,title=data.title.strip(),kind=data.kind,amount=data.amount,
                      wallet_id=data.wallet_id,category_id=data.category_id,note=data.note.strip(),
                      frequency=data.frequency,start_on=data.start_on,mode=data.mode,
                      remind_days=data.remind_days)
    db.add(obj);db.flush();log(db,u.id,'recurring_created',f'#{obj.id}')
    db.commit();return recurring_json(db,obj)


@app.put('/api/recurring/{rule_id}')
def update_recurring(rule_id:int,data:EditRecurring,u:User=Depends(current),db:Session=Depends(get_db)):
    check_amount(data.amount)
    if not data.title.strip():raise HTTPException(422,'Nội dung không được rỗng.')
    account_locked(db,u.id)
    r=db.scalar(select(RecurringRule).where(RecurringRule.id==rule_id,RecurringRule.user_id==u.id).with_for_update())
    if r is None:raise HTTPException(404,'Không tìm thấy lịch định kỳ.')
    category_for(db,u,data.category_id,r.kind,True)
    wallet_for(db,u.id,data.wallet_id,True)
    for key in ('title','amount','category_id','wallet_id','note','mode','remind_days'):
        setattr(r,key, getattr(data,key).strip() if key in ('title','note') else getattr(data,key))
    log(db,u.id,'recurring_edited',f'#{r.id}');db.commit();return recurring_json(db,r)


@app.post('/api/recurring/{rule_id}/toggle')
def toggle_recurring(rule_id:int,u:User=Depends(current),db:Session=Depends(get_db)):
    account_locked(db,u.id)
    r=db.scalar(select(RecurringRule).where(RecurringRule.id==rule_id,RecurringRule.user_id==u.id).with_for_update())
    if not r:raise HTTPException(404,'Không tìm thấy lịch định kỳ.')
    r.active=not r.active;log(db,u.id,'recurring_toggled',f'#{r.id}: {r.active}')
    db.commit();return recurring_json(db,r)


@app.delete('/api/recurring/{rule_id}')
def delete_recurring(rule_id:int,u:User=Depends(current),db:Session=Depends(get_db)):
    account_locked(db,u.id)
    r=db.scalar(select(RecurringRule).where(RecurringRule.id==rule_id,RecurringRule.user_id==u.id).with_for_update())
    if not r:raise HTTPException(404,'Không tìm thấy lịch định kỳ.')
    if db.scalar(select(RecurringRun.id).where(RecurringRun.rule_id==rule_id).limit(1)):
        raise HTTPException(409,'Lịch đã có lịch sử. Hãy tạm dừng thay vì xóa.')
    db.delete(r);log(db,u.id,'recurring_deleted',f'#{rule_id}');db.commit()
    return {'ok':True}


def complete_recurring(rule_id:int,skip:bool,u:User,db:Session):
    account_locked(db,u.id)
    r=db.scalar(select(RecurringRule).where(RecurringRule.id==rule_id,RecurringRule.user_id==u.id).with_for_update())
    if not r:raise HTTPException(404,'Không tìm thấy lịch định kỳ.')
    if r.mode != 'manual':raise HTTPException(409,'Lịch tự động do hệ thống xử lý. Hãy tạm dừng hoặc đổi chế độ.')
    due=scheduled_date(r)
    result=post_recurring_once(db,r,due,skip=skip)
    db.commit();return result


@app.post('/api/recurring/{rule_id}/confirm')
def confirm_recurring(rule_id:int,u:User=Depends(current),db:Session=Depends(get_db)):
    return complete_recurring(rule_id,False,u,db)


@app.post('/api/recurring/{rule_id}/skip')
def skip_recurring(rule_id:int,u:User=Depends(current),db:Session=Depends(get_db)):
    return complete_recurring(rule_id,True,u,db)


@app.get('/api/reminders')
def list_reminders(u:User=Depends(current),db:Session=Depends(get_db)):
    today_day=date.today()
    items=[]
    for r in db.scalars(select(RecurringRule).where(RecurringRule.user_id==u.id,RecurringRule.active==True)):
        due=scheduled_date(r)
        delta=(due-today_day).days
        if delta<=r.remind_days:
            items.append({'kind':'recurring','ref_id':r.id,'title':r.title,
                          'direction':r.kind,'due_on':due.isoformat(),'days_left':delta,
                          'amount':r.amount,'mode':r.mode})
    for debt in db.scalars(select(Debt).where(Debt.user_id==u.id,Debt.remaining>0)):
        for row in debt_schedule_rows(debt):
            if row['principal_paid']>=row['principal'] or not row['due_date']:
                continue
            deadline=date.fromisoformat(row['due_date'])
            delta=(deadline-today_day).days
            if delta<=7:
                items.append({'kind':'debt','ref_id':debt.id,'title':debt.name,
                              'direction':debt.direction,'due_on':row['due_date'],
                              'days_left':delta,'amount':row['principal']-row['principal_paid'],
                              'period':row['period']})
    items.sort(key=lambda r:(r['days_left'],r['kind'],r['ref_id']))
    return {'items':items[:100], 'overdue_count':sum(1 for i in items if i['days_left']<0),
            'upcoming_count':sum(1 for i in items if i['days_left']>=0)}


@app.get('/api/categories')
def list_categories(u:User=Depends(current),db:Session=Depends(get_db)):
    return [{'id':c.id,'name':c.name,'kind':c.kind,'color':c.color,'active':c.active} for c in db.scalars(select(Category).where(Category.user_id==u.id).order_by(Category.kind,Category.id))]


@app.post('/api/categories')
def add_category(data:NewCategory,u:User=Depends(current),db:Session=Depends(get_db)):
    name=data.name.strip()
    if not name:raise HTTPException(422,'Tên danh mục không được rỗng.')
    if not re.fullmatch('#[0-9a-fA-F]{6}',data.color):raise HTTPException(422,'Mã màu không hợp lệ.')
    existing=db.scalar(select(Category).where(Category.user_id==u.id,Category.kind==data.kind,func.lower(Category.name)==name.lower()))
    if existing: raise HTTPException(409,'Danh mục đã tồn tại.')
    c=Category(user_id=u.id,name=name,kind=data.kind,color=data.color)
    try:
        db.add(c);db.flush();log(db,u.id,'category_added',name);db.commit()
    except IntegrityError:
        db.rollback();raise HTTPException(409,'Danh mục đã tồn tại.')
    return {'id':c.id,'name':c.name,'kind':c.kind,'color':c.color,'active':True}


@app.post('/api/categories/{category_id}/toggle')
def toggle_category(category_id:int,u:User=Depends(current),db:Session=Depends(get_db)):
    c=category_for(db,u,category_id)
    c.active=not c.active
    log(db,u.id,'category_toggled',f'{c.id}: {c.active}');db.commit()
    return {'active':c.active}


@app.get('/api/transactions')
def transactions(month:str|None=None,kind:str|None=None,category_id:int|None=None,wallet_id:int|None=None,q:str='',page:int=1,size:int=15,u:User=Depends(current),db:Session=Depends(get_db)):
    if page<1 or size<1 or size>100:raise HTTPException(422,'Phân trang không hợp lệ.')
    stmt=select(Entry).where(Entry.user_id==u.id)
    if month:
        a,b=month_bounds(month);stmt=stmt.where(Entry.occurred_on>=a,Entry.occurred_on<b)
    if kind:
        if kind not in ('income','expense'):raise HTTPException(422,'Loại giao dịch không hợp lệ.')
        stmt=stmt.where(Entry.kind==kind)
    if category_id:stmt=stmt.where(Entry.category_id==category_id)
    if wallet_id:
        wallet_for(db,u.id,wallet_id)
        stmt=stmt.where(Entry.wallet_id==wallet_id)
    if q.strip():stmt=stmt.where(Entry.title.ilike(f'%{escape_like(q.strip())}%',escape='\\'))
    total=db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    entries=list(db.scalars(stmt.order_by(Entry.occurred_on.desc(),Entry.id.desc()).offset((page-1)*size).limit(size)))
    cats={c.id:c for c in db.scalars(select(Category).where(Category.user_id==u.id))}
    ids=[e.id for e in entries]
    allocations=dict(db.execute(select(DebtPayment.entry_id,func.sum(DebtPayment.amount)).where(DebtPayment.user_id==u.id,DebtPayment.entry_id.in_(ids)).group_by(DebtPayment.entry_id)).all()) if ids else {}
    return {'items':[entry_json(e,cats,int(allocations.get(e.id,0))) for e in entries],'total':total,'page':page,'pages':max(1,(total+size-1)//size)}


def escape_like(q):
    return q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')


@app.post('/api/transactions')
def add_entry(data:NewEntry,u:User=Depends(current),db:Session=Depends(get_db)):
    amount=check_amount(data.amount)
    if not data.title.strip():raise HTTPException(422,'Nội dung không được rỗng.')
    if data.occurred_on>date.today()+timedelta(days=366):raise HTTPException(422,'Ngày giao dịch không hợp lệ.')
    account_locked(db,u.id)
    category_for(db,u,data.category_id,data.kind,True)
    wallet=wallet_for(db,u.id,data.wallet_id,require_active=True)
    e=Entry(user_id=u.id,title=data.title.strip(),kind=data.kind,amount=amount,category_id=data.category_id,wallet_id=wallet.id,note=data.note.strip(),occurred_on=data.occurred_on)
    db.add(e);db.flush();auto_paid=allocate_income_to_debts(db,u.id,e)
    auto_saved=allocate_income_to_stashes(db,u.id,e,auto_paid)
    ensure_nonnegative(db,u.id)
    log(db,u.id,'entry_added',f'{e.kind} #{e.id}: {e.amount}; debt_paid={auto_paid}; auto_saved={auto_saved}')
    db.commit();return {'id':e.id,'ok':True,'debt_paid':auto_paid,'auto_saved':auto_saved}


@app.put('/api/transactions/{entry_id}')
def edit_entry(entry_id:int,data:NewEntry,u:User=Depends(current),db:Session=Depends(get_db)):
    check_amount(data.amount)
    if not data.title.strip():raise HTTPException(422,'Nội dung không được rỗng.')
    account_locked(db,u.id)
    e=db.scalar(select(Entry).where(Entry.id==entry_id,Entry.user_id==u.id))
    if not e:raise HTTPException(404,'Không tìm thấy giao dịch.')
    category_for(db,u,data.category_id,data.kind)
    wallet=wallet_for(db,u.id,data.wallet_id,require_active=True)
    reverse_entry_stash_allocations(db,u.id,e.id)
    reverse_entry_payments(db,u.id,e.id)
    e.wallet_id=wallet.id
    e.title=data.title.strip();e.kind=data.kind;e.amount=data.amount;e.category_id=data.category_id;e.note=data.note.strip();e.occurred_on=data.occurred_on
    db.flush();auto_paid=allocate_income_to_debts(db,u.id,e)
    auto_saved=allocate_income_to_stashes(db,u.id,e,auto_paid)
    ensure_nonnegative(db,u.id)
    log(db,u.id,'entry_edited',f'#{e.id}; debt_paid={auto_paid}; auto_saved={auto_saved}')
    db.commit();return {'ok':True,'debt_paid':auto_paid,'auto_saved':auto_saved}


@app.delete('/api/transactions/{entry_id}')
def delete_entry(entry_id:int,u:User=Depends(current),db:Session=Depends(get_db)):
    account_locked(db,u.id)
    e=db.scalar(select(Entry).where(Entry.id==entry_id,Entry.user_id==u.id))
    if not e:raise HTTPException(404,'Không tìm thấy giao dịch.')
    reverse_entry_stash_allocations(db,u.id,e.id)
    reverse_entry_payments(db,u.id,e.id)
    for run in db.scalars(select(RecurringRun).where(RecurringRun.user_id==u.id,RecurringRun.entry_id==e.id)):
        run.entry_id=None;run.status='deleted'
    db.flush();db.delete(e);db.flush();ensure_nonnegative(db,u.id)
    log(db,u.id,'entry_deleted',f'#{entry_id}');db.commit();return {'ok':True}


@app.put('/api/opening-balance')
def set_opening(data:Opening,u:User=Depends(current),db:Session=Depends(get_db)):
    check_amount(data.opening_balance,zero=True)
    locked=account_locked(db,u.id)
    wallet=default_wallet(db,u.id)
    wallet.opening_balance=data.opening_balance
    locked.opening_balance=data.opening_balance;db.flush();ensure_nonnegative(db,u.id)
    log(db,u.id,'opening_changed',str(data.opening_balance));db.commit();return {'ok':True}


@app.get('/api/budgets')
def list_budgets(month:str,u:User=Depends(current),db:Session=Depends(get_db)):
    y,m=valid_month(month);a,b=month_bounds(month)
    cats={c.id:c for c in db.scalars(select(Category).where(Category.user_id==u.id,Category.kind=='expense'))}
    spent={cid:int(v) for cid,v in db.execute(select(Entry.category_id,func.sum(Entry.amount)).where(Entry.user_id==u.id,Entry.kind=='expense',Entry.occurred_on>=a,Entry.occurred_on<b).group_by(Entry.category_id))}
    rows=[]
    for bu in db.scalars(select(Budget).where(Budget.user_id==u.id,Budget.year==y,Budget.month==m)):
        c=cats.get(bu.category_id)
        if c:rows.append({'category_id':c.id,'category':c.name,'color':c.color,'amount':bu.amount,'spent':spent.get(c.id,0)})
    return rows


@app.put('/api/budgets')
def upsert_budget(data:NewBudget,u:User=Depends(current),db:Session=Depends(get_db)):
    y,m=valid_month(data.month);check_amount(data.amount,zero=True)
    category_for(db,u,data.category_id,'expense')
    b=db.scalar(select(Budget).where(Budget.user_id==u.id,Budget.category_id==data.category_id,Budget.year==y,Budget.month==m))
    if b:b.amount=data.amount
    else:db.add(Budget(user_id=u.id,category_id=data.category_id,year=y,month=m,amount=data.amount))
    log(db,u.id,'budget_saved',f'{data.category_id} {data.month}: {data.amount}');db.commit();return {'ok':True}


@app.get('/api/dashboard')
def dashboard(month:str,u:User=Depends(current),db:Session=Depends(get_db)):
    y,m=valid_month(month);a,b=month_bounds(month)
    balance,all_income,all_expense=current_balance(db,u.id)
    wallets=list(db.scalars(select(Wallet).where(Wallet.user_id==u.id).order_by(Wallet.id)))
    debt_remaining=int(db.scalar(select(func.coalesce(func.sum(Debt.remaining),0)).where(Debt.user_id==u.id,Debt.direction=='payable')) or 0)
    receivable_remaining=int(db.scalar(select(func.coalesce(func.sum(Debt.remaining),0)).where(Debt.user_id==u.id,Debt.direction=='receivable')) or 0)
    debt_paid=debt_paid_total(db,u.id)
    month_debt_paid=int(db.scalar(select(func.coalesce(func.sum(DebtPayment.amount),0)).where(DebtPayment.user_id==u.id,DebtPayment.paid_on>=a,DebtPayment.paid_on<b,DebtPayment.debt_id.in_(select(Debt.id).where(Debt.direction=='payable')))) or 0)
    month_entries=list(db.scalars(select(Entry).where(Entry.user_id==u.id,Entry.occurred_on>=a,Entry.occurred_on<b)))
    inc=sum(e.amount for e in month_entries if e.kind=='income')
    exp=sum(e.amount for e in month_entries if e.kind=='expense')
    cats={c.id:c for c in db.scalars(select(Category).where(Category.user_id==u.id))}
    sums=defaultdict(int)
    for e in month_entries:
        if e.kind=='expense':sums[e.category_id]+=e.amount
    category_chart=[{'category_id':k,'name':cats[k].name if k in cats else 'Khác','color':cats[k].color if k in cats else '#7567F8','value':v} for k,v in sorted(sums.items(),key=lambda x:x[1],reverse=True)]
    firstm=(y*12+m-1)-5
    start=date(firstm//12,firstm%12+1,1)
    hist=list(db.scalars(select(Entry).where(Entry.user_id==u.id,Entry.occurred_on>=start,Entry.occurred_on<b)))
    map_hist=defaultdict(lambda:{'income':0,'expense':0})
    for e in hist:map_hist[e.occurred_on.strftime('%Y-%m')][e.kind]+=e.amount
    trend=[]
    for i in range(6):
        idx=firstm+i;key=f'{idx//12}-{idx%12+1:02d}'
        trend.append({'month':key,'income':map_hist[key]['income'],'expense':map_hist[key]['expense']})
    recent=list(db.scalars(select(Entry).where(Entry.user_id==u.id).order_by(Entry.occurred_on.desc(),Entry.id.desc()).limit(6)))
    budgets=list_budgets(month,u,db)
    ids=[e.id for e in recent]
    allocations=dict(db.execute(select(DebtPayment.entry_id,func.sum(DebtPayment.amount)).where(DebtPayment.user_id==u.id,DebtPayment.entry_id.in_(ids)).group_by(DebtPayment.entry_id)).all()) if ids else {}
    savings_reserved=total_reserved_savings(db,u.id)
    stash_reserved=total_stash_funds(db,u.id)
    reserved_total=savings_reserved+stash_reserved
    return {'savings_reserved':savings_reserved,'stash_reserved':stash_reserved,'reserved_total':reserved_total,'total_assets':balance+reserved_total,'balance':balance,'opening_balance':default_wallet(db,u.id).opening_balance,'total_opening_balance':sum(w.opening_balance for w in wallets),'wallet_count':len(wallets),'wallets':[wallet_json(db,w) for w in wallets],'total_income':all_income,'total_expense':all_expense,
            'month_income':inc,'month_expense':exp,'month_count':len(month_entries),'net':inc-exp,
            'categories':category_chart,'trend':trend,'recent':[entry_json(e,cats,int(allocations.get(e.id,0))) for e in recent],
            'budgets':budgets,'overspent_budgets':sum(1 for bb in budgets if bb['spent']>bb['amount']),
            'debt_remaining':debt_remaining,'receivable_remaining':receivable_remaining,'debt_paid':debt_paid,'month_debt_paid':month_debt_paid,'net_worth':balance+reserved_total-debt_remaining+receivable_remaining}


# v1.0.18 – Read-only scenario forecast based ONLY on registered recurring rules.
# This is not a transaction ledger, bank integration, or automatic debt payment.
def forecast_rule_date(rule: RecurringRule, index: int) -> date:
    if rule.frequency == 'daily':
        return rule.start_on + timedelta(days=index)
    if rule.frequency == 'weekly':
        return rule.start_on + timedelta(weeks=index)
    if rule.frequency in ('monthly', 'yearly'):
        return add_months_clamped(rule.start_on, index * (12 if rule.frequency == 'yearly' else 1))
    raise ValueError('Tần suất không hợp lệ.')


def forecast_due_dates(rule: RecurringRule, start: date, finish: date):
    """Non-mutating recurrence iterator; use next_index to exclude posted/skipped periods.

    Skip old occurrences efficiently to bound forecast work even for daily rules
    created many years ago. An overdue first period is a warning, NOT projected
    as if it had already been paid today.
    """
    index = max(0, int(rule.next_index or 0))
    if rule.frequency in ('daily', 'weekly'):
        days_per = 1 if rule.frequency == 'daily' else 7
        delta = (start - rule.start_on).days
        index = max(index, max(0, (delta + days_per - 1) // days_per))
    else:
        delta_months = (start.year-rule.start_on.year)*12 + start.month-rule.start_on.month
        step = 12 if rule.frequency == 'yearly' else 1
        index = max(index, max(0, delta_months // step - 1))
    # At most 91 days' events; no database writes or scheduler side effects.
    for _ in range(110):
        try:
            due = forecast_rule_date(rule,index)
        except (OverflowError,ValueError):
            return
        if due > finish:
            return
        if due >= start:
            yield due
        index += 1


def compute_cash_forecast(db: Session, user_id: int, horizon_days: int = 30,
                          as_of: date | None = None) -> dict:
    if horizon_days not in (30,60,90):
        raise HTTPException(422,'Chỉ hỗ trợ dự báo 30, 60 hoặc 90 ngày.')
    start=as_of or date.today()
    finish=start+timedelta(days=horizon_days)
    wallets=list(db.scalars(select(Wallet).where(Wallet.user_id==user_id).order_by(Wallet.id)))
    wallet_info={w.id:{'id':w.id,'name':w.name,'active':w.active,
        'start_balance':wallet_balance(db,w),'projected_balance':wallet_balance(db,w),
        'lowest_balance':wallet_balance(db,w),'first_shortfall_on':None} for w in wallets}
    debt_balances=[int(d.remaining) for d in db.scalars(select(Debt).where(
        Debt.user_id==user_id,Debt.direction=='payable',Debt.remaining>0).order_by(Debt.id))]
    stash_rules = list(db.scalars(select(StashFund).where(StashFund.user_id == user_id,
        StashFund.auto_mode != 'off').order_by(StashFund.id)))
    rules=list(db.scalars(select(RecurringRule).where(
        RecurringRule.user_id==user_id, RecurringRule.active==True).order_by(RecurringRule.id)))
    pending_past=[];paused_wallet_rules=[];planned=[]
    for rule in rules:
        wallet=wallet_info.get(rule.wallet_id)
        if not wallet or not wallet['active']:
            paused_wallet_rules.append({'id':rule.id,'title':rule.title})
            continue
        if forecast_rule_date(rule,int(rule.next_index or 0)) < start:
            pending_past.append({'id':rule.id,'title':rule.title,
                                 'due_on':forecast_rule_date(rule,int(rule.next_index or 0)).isoformat()})
        for due in forecast_due_dates(rule,start,finish):
            planned.append((due,0 if rule.kind=='income' else 1,rule.id,rule))
    planned.sort(key=lambda row:(row[0],row[1],row[2]))
    by_day=defaultdict(list)
    for due,_,__,rule in planned:by_day[due].append(rule)
    events=[];timeline=[];total_income=total_expense=total_debt=total_stash=0
    first_shortfall_on=None
    min_total=sum(w['start_balance'] for w in wallet_info.values())
    for offset in range(horizon_days+1):
        day=start+timedelta(days=offset)
        income=expense=debt_paid=stash_reserved=0
        for rule in by_day.get(day,[]):
            wallet=wallet_info[rule.wallet_id]
            gross=int(rule.amount)
            allocated=auto_reserve=0
            if rule.kind=='income':
                income+=gross
                remainder=gross
                for ix,amount in enumerate(debt_balances):
                    if not remainder:break
                    repay=min(remainder,amount)
                    debt_balances[ix]-=repay
                    remainder-=repay
                    allocated+=repay
                debt_paid+=allocated
                net_income=gross-allocated
                available=net_income
                for fund in stash_rules:
                    if available<=0:break
                    if fund.auto_wallet_id is not None and fund.auto_wallet_id!=rule.wallet_id:continue
                    suggested=(net_income*int(fund.auto_value)//100 if fund.auto_mode=='percent' else int(fund.auto_value))
                    reserve=min(available,suggested)
                    available-=reserve
                    auto_reserve+=reserve
                stash_reserved+=auto_reserve
                delta=gross-allocated-auto_reserve
            else:
                expense+=gross
                delta=-gross
            wallet['projected_balance']+=delta
            events.append({'due_on':day.isoformat(),'title':rule.title,'rule_id':rule.id,
                           'wallet_id':rule.wallet_id,'wallet_name':wallet['name'],'kind':rule.kind,
                           'mode':rule.mode,'amount':gross,'allocated_to_debt':allocated,
                           'allocated_to_stash':auto_reserve,
                           'net_wallet_delta':delta,'wallet_after':wallet['projected_balance']})
        total_income+=income;total_expense+=expense;total_debt+=debt_paid;total_stash+=stash_reserved
        total=sum(w['projected_balance'] for w in wallet_info.values())
        min_total=min(min_total,total)
        risk=False
        for wallet in wallet_info.values():
            wallet['lowest_balance']=min(wallet['lowest_balance'],wallet['projected_balance'])
            if wallet['projected_balance']<0:
                risk=True
                if wallet['first_shortfall_on'] is None:
                    wallet['first_shortfall_on']=day.isoformat()
        if risk and first_shortfall_on is None:first_shortfall_on=day.isoformat()
        timeline.append({'date':day.isoformat(),'balance':total,'income':income,
                         'expense':expense,'debt_paid':debt_paid,'stash_reserved':stash_reserved,'shortfall':risk})
    start_balance=sum(w['start_balance'] for w in wallet_info.values())
    end_balance=sum(w['projected_balance'] for w in wallet_info.values())
    return {'as_of':start.isoformat(),'through':finish.isoformat(),'horizon_days':horizon_days,
            'start_balance':start_balance,'end_balance':end_balance,
            'net_change':end_balance-start_balance,'income_gross':total_income,
            'expense':total_expense,'debt_allocated':total_debt,'stash_allocated':total_stash,
            'min_total_balance':min_total,'first_shortfall_on':first_shortfall_on,
            'risk_wallet_count':sum(1 for w in wallet_info.values() if w['first_shortfall_on']),
            'overdue_rules':pending_past,'inactive_wallet_rules':paused_wallet_rules,
            'payable_remaining_scenario':sum(debt_balances),
            'wallets':list(wallet_info.values()),'timeline':timeline,
            'total_events':len(events),'events':events[:160],
            'truncated_events':len(events)>160,
            'assumptions':['Chỉ dự báo lịch định kỳ đang hoạt động; không tự tạo giao dịch.',
                           'Khoản thu dự kiến ưu tiên trả nợ gốc; phần còn lại được tự tích vào quỹ theo quy tắc đang bật.',
                           'Lịch trả góp/nợ đến hạn chỉ là nhắc nhở, không tự trừ thêm.',
                           'Các khoản chuyển ví và góp/rút quỹ tiết kiệm không phải thu chi.',
                           'Chi vượt số dư được cảnh báo; ứng dụng thực tế vẫn chặn ghi âm ví.']}


@app.get('/api/forecast')
def cash_forecast(response: Response, days: int = 30,
                  u: User = Depends(current), db: Session = Depends(get_db)):
    response.headers['Cache-Control']='no-store'
    return compute_cash_forecast(db,u.id,days)


@app.get('/api/reports')
def reports(end: str, response: Response, months: int = 12, u: User = Depends(current), db: Session = Depends(get_db)):
    from backend.reporting import build_report, as_public_report
    response.headers['Cache-Control'] = 'no-store'
    return as_public_report(build_report(db, u.id, end, months))


@app.get('/api/reports.xlsx')
def reports_excel(end: str, months: int = 12, u: User = Depends(current), db: Session = Depends(get_db)):
    from backend.reporting import build_report, excel_bytes
    content = excel_bytes(build_report(db, u.id, end, months))
    return Response(content=content,
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f'attachment; filename="moneyflow-report-{end}.xlsx"',
                 'Cache-Control': 'no-store'})


@app.get('/api/reports.pdf')
def reports_pdf(end: str, months: int = 12, u: User = Depends(current), db: Session = Depends(get_db)):
    from backend.reporting import build_report, pdf_bytes
    content = pdf_bytes(build_report(db, u.id, end, months))
    return Response(content=content, media_type='application/pdf',
        headers={'Content-Disposition': f'attachment; filename="moneyflow-report-{end}.pdf"',
                 'Cache-Control': 'no-store'})


@app.get('/api/export.csv')
def export_csv(month:str|None=None,u:User=Depends(current),db:Session=Depends(get_db)):
    stmt=select(Entry).where(Entry.user_id==u.id)
    if month:
        a,b=month_bounds(month);stmt=stmt.where(Entry.occurred_on>=a,Entry.occurred_on<b)
    rows=list(db.scalars(stmt.order_by(Entry.occurred_on.desc(),Entry.id.desc())))
    cats={c.id:c.name for c in db.scalars(select(Category).where(Category.user_id==u.id))}
    output=io.StringIO();output.write('\ufeff')
    writer=csv.writer(output)
    ids=[e.id for e in rows]
    allocations=dict(db.execute(select(DebtPayment.entry_id,func.sum(DebtPayment.amount)).where(DebtPayment.user_id==u.id,DebtPayment.entry_id.in_(ids)).group_by(DebtPayment.entry_id)).all()) if ids else {}
    wallet_names={w.id:w.name for w in db.scalars(select(Wallet).where(Wallet.user_id==u.id))}
    writer.writerow(['Ngày','Loại','Nội dung','Danh mục','Số tiền (VNĐ)','Ví tiền','Ghi chú','Đã tự động trả nợ (VNĐ)'])
    for e in rows:
        # Prevent spreadsheet formula injection for arbitrary user-provided strings.
        def excel_text(value):
            value=str(value)
            return "'"+value if value.lstrip().startswith(('=','+','-','@','\t','\r')) else value
        writer.writerow([e.occurred_on.isoformat(),'Thu' if e.kind=='income' else 'Chi',excel_text(e.title),excel_text(cats.get(e.category_id,'')),e.amount,excel_text(wallet_names.get(e.wallet_id,'')),excel_text(e.note),int(allocations.get(e.id,0))])
    content=output.getvalue().encode('utf-8')
    return Response(content=content,media_type='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="moneyflow-{month or "tat-ca"}.csv"'})


@app.get('/api/users')
def users(u:User=Depends(admin),db:Session=Depends(get_db)):
    return [user_json(x) for x in db.scalars(select(User).order_by(User.id))]


@app.post('/api/users')
def create_user(data:NewUser,u:User=Depends(admin),db:Session=Depends(get_db)):
    safe_password(data.password);username=username_clean(data.username)
    new=User(username=username,display_name=username,email=normalized_email(data.email),
             phone=normalized_phone(data.phone),address=normalized_address(data.address),
             password_hash=ph.hash(data.password),role='member')
    try:
        db.add(new);db.flush();seed_categories(db,new);default_wallet(db,new.id);log(db,u.id,'user_created',username);db.commit()
    except IntegrityError:
        db.rollback();raise HTTPException(409,'Tên đăng nhập hoặc email đã tồn tại.')
    return user_json(new)


def cannot_remove_last_admin(db, target):
    if target.role=='admin' and target.active:
        count=db.scalar(select(func.count(User.id)).where(User.role=='admin',User.active==True))
        if count<=1:raise HTTPException(409,'Phải duy trì ít nhất một quản trị viên đang hoạt động.')


@app.put('/api/users/{user_id}')
def update_user(user_id:int,data:UserEdit,u:User=Depends(admin),db:Session=Depends(get_db)):
    target=db.get(User,user_id)
    if not target:raise HTTPException(404,'Không tìm thấy người dùng.')
    if (data.role=='member' or data.active is False) and target.role=='admin' and target.active:
        cannot_remove_last_admin(db,target)
    if target.id==u.id and (data.role=='member' or data.active is False):
        raise HTTPException(409,'Không thể tự hạ quyền hoặc khóa tài khoản đang đăng nhập.')
    if data.email is not None: target.email=normalized_email(data.email)
    if data.phone is not None: target.phone=normalized_phone(data.phone)
    if data.address is not None: target.address=normalized_address(data.address)
    if data.role is not None:target.role=data.role
    if data.active is not None:
        target.active=data.active
        if not target.active:db.query(AuthSession).filter(AuthSession.user_id==target.id).delete(synchronize_session=False)
    try:
        log(db,u.id,'user_updated',str(user_id));db.commit()
    except IntegrityError:
        db.rollback();raise HTTPException(409,'Email đã được sử dụng.')
    return user_json(target)


@app.post('/api/users/{user_id}/reset-password')
def reset_user_password(user_id:int,data:ResetPassword,u:User=Depends(admin),db:Session=Depends(get_db)):
    safe_password(data.new_password)
    target=db.get(User,user_id)
    if not target:raise HTTPException(404,'Không tìm thấy người dùng.')
    target.password_hash=ph.hash(data.new_password)
    db.query(PasswordResetToken).filter(PasswordResetToken.user_id==target.id).delete(synchronize_session=False)
    target.failed_attempts=0
    target.locked_until=None
    db.query(LoginChallenge).filter(LoginChallenge.user_id==target.id).delete(synchronize_session=False)
    db.query(AuthSession).filter(AuthSession.user_id==target.id).delete(synchronize_session=False)
    log(db,u.id,'user_password_reset',str(user_id));db.commit();return {'ok':True}


@app.delete('/api/users/{user_id}')
def remove_user(user_id:int,data:DeleteUser,u:User=Depends(admin),db:Session=Depends(get_db)):
    if user_id==u.id: raise HTTPException(409, 'Không thể xóa tài khoản đang đăng nhập.')
    target=db.get(User,user_id)
    if not target: raise HTTPException(404, 'Không tìm thấy người dùng.')
    if data.confirm_username != target.username:
        raise HTTPException(422, 'Tên đăng nhập xác nhận không trùng khớp.')
    if target.role=='admin' and target.active: cannot_remove_last_admin(db,target)
    # Delete dependents in FK-safe order; anonymous audit records preserve chronology.
    db.query(AuthSession).filter(AuthSession.user_id==target.id).delete(synchronize_session=False)
    db.query(LoginChallenge).filter(LoginChallenge.user_id==target.id).delete(synchronize_session=False)
    db.query(TotpRecoveryCode).filter(TotpRecoveryCode.user_id==target.id).delete(synchronize_session=False)
    db.query(PasswordResetToken).filter(PasswordResetToken.user_id==target.id).delete(synchronize_session=False)
    db.query(RecurringRun).filter(RecurringRun.user_id==target.id).delete(synchronize_session=False)
    db.query(RecurringRule).filter(RecurringRule.user_id==target.id).delete(synchronize_session=False)
    db.query(Budget).filter(Budget.user_id==target.id).delete(synchronize_session=False)
    db.query(DebtPayment).filter(DebtPayment.user_id==target.id).delete(synchronize_session=False)
    db.query(Debt).filter(Debt.user_id==target.id).delete(synchronize_session=False)
    db.query(StashMovement).filter(StashMovement.user_id==target.id).delete(synchronize_session=False)
    db.query(StashFund).filter(StashFund.user_id==target.id).delete(synchronize_session=False)
    db.query(Entry).filter(Entry.user_id==target.id).delete(synchronize_session=False)
    db.query(WalletTransfer).filter(WalletTransfer.user_id==target.id).delete(synchronize_session=False)
    db.query(SavingsMovement).filter(SavingsMovement.user_id==target.id).delete(synchronize_session=False)
    db.query(SavingsGoal).filter(SavingsGoal.user_id==target.id).delete(synchronize_session=False)
    db.query(Wallet).filter(Wallet.user_id==target.id).delete(synchronize_session=False)
    db.query(Category).filter(Category.user_id==target.id).delete(synchronize_session=False)
    db.query(Audit).filter(Audit.actor_id==target.id).update({Audit.actor_id:None},synchronize_session=False)
    username=target.username
    db.delete(target)
    log(db,u.id,'user_deleted',username)
    db.commit()
    return {'ok':True}


@app.get('/api/audit')
def audit(limit:int=80,u:User=Depends(admin),db:Session=Depends(get_db)):
    if not 1<=limit<=200:raise HTTPException(422,'Giới hạn không hợp lệ.')
    people={p.id:p.username for p in db.scalars(select(User))}
    return [{'id':x.id,'actor':people.get(x.actor_id,'Hệ thống'),'action':x.action,'detail':x.detail,'at':x.created_at.isoformat()} for x in db.scalars(select(Audit).order_by(Audit.id.desc()).limit(limit))]


@app.get('/health')
def health(db:Session=Depends(get_db)):
    db.execute(select(1))
    return {'status':'ok'}


@app.get('/reset')
def reset_page():
    return FileResponse(STATIC/'index.html')


@app.get('/')
def root():
    return FileResponse(STATIC/'index.html')


@app.get('/{asset:path}')
def static_assets(asset:str):
    if asset not in {'main.css','app.js','favicon.svg','logo.svg','apple-touch-icon.png'}:raise HTTPException(404,'Không tìm thấy tệp.')
    return FileResponse(STATIC/asset)
