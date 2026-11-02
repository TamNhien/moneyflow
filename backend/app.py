"""MoneyFlow local-first finance application API (single-origin FastAPI)."""
import csv
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
from pathlib import Path
from typing import Literal

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
    role: Mapped[str] = mapped_column(String(12), default='member')
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    opening_balance: Mapped[int] = mapped_column(BigInteger, default=0)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    __table_args__ = (CheckConstraint('opening_balance >= 0'),)


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
    amount: Mapped[int] = mapped_column(BigInteger)
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


class AuthSession(Base):
    __tablename__ = 'auth_sessions'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


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
            conn.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email)'))
        else:
            columns = {row[1] for row in conn.execute(text('PRAGMA table_info(users)'))}
            for name, kind in [('email','VARCHAR(254)'),('phone','VARCHAR(20)'),('address','VARCHAR(300)')]:
                if name not in columns: conn.execute(text(f'ALTER TABLE users ADD COLUMN {name} {kind}'))
            conn.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email)'))
    yield


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


def normalized_phone(value: str) -> str:
    value = re.sub(r'[ .()-]', '', value.strip())
    if not PHONE_PATTERN.fullmatch(value):
        raise HTTPException(422, 'Số điện thoại phải gồm 9-15 chữ số, có thể bắt đầu bằng +.')
    return value


def normalized_address(value: str) -> str:
    value = value.strip()
    if not 5 <= len(value) <= 300:
        raise HTTPException(422, 'Địa chỉ cần 5-300 ký tự.')
    return value


def user_json(u):
    return {'id':u.id,'username':u.username,'email':u.email or '', 'phone':u.phone or '',
            'address':u.address or '', 'profile_complete':bool(u.email and u.phone and u.address),
            'role':u.role,'active':u.active,'opening_balance':u.opening_balance,
            'created_at':u.created_at.isoformat()}



def account_locked(db,user_id):
    return db.execute(select(User).where(User.id==user_id).with_for_update()).scalar_one()


def debt_paid_total(db, user_id, entry_id=None):
    stmt = select(func.coalesce(func.sum(DebtPayment.amount), 0)).where(DebtPayment.user_id == user_id)
    if entry_id is not None:
        stmt = stmt.where(DebtPayment.entry_id == entry_id)
    return int(db.scalar(stmt) or 0)


def current_balance(db, user_id, opening=None):
    inc = db.scalar(select(func.coalesce(func.sum(Entry.amount),0)).where(Entry.user_id==user_id,Entry.kind=='income')) or 0
    exp = db.scalar(select(func.coalesce(func.sum(Entry.amount),0)).where(Entry.user_id==user_id,Entry.kind=='expense')) or 0
    if opening is None:
        opening = db.scalar(select(User.opening_balance).where(User.id==user_id)) or 0
    # Debt principal payments are cash outflows, but not ordinary expense-category spending.
    return int(opening)+int(inc)-int(exp)-debt_paid_total(db,user_id),int(inc),int(exp)


def ensure_nonnegative(db, user_id):
    b,_,_ = current_balance(db,user_id)
    if b<0: raise HTTPException(409, f'Giao dịch khiến số dư âm ({b:,}đ). Vui lòng điều chỉnh số tiền.')


def allocate_income_to_debts(db, user_id, entry):
    """Repay active principals oldest first, atomically with the income entry."""
    if entry.kind != 'income':
        return 0
    available = int(entry.amount)
    paid = 0
    for debt in db.scalars(select(Debt).where(Debt.user_id==user_id,Debt.remaining>0).order_by(Debt.id).with_for_update()):
        if available == 0:
            break
        value = min(available, debt.remaining)
        debt.remaining -= value
        db.add(DebtPayment(user_id=user_id,debt_id=debt.id,entry_id=entry.id,amount=value,mode='auto',paid_on=entry.occurred_on))
        available -= value
        paid += value
    db.flush()
    return paid


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


def start_session(db, response: Response, u: User):
    token=secrets.token_urlsafe(48)
    csrf=secrets.token_hex(32)
    db.add(AuthSession(user_id=u.id, token_hash=hashlib.sha256(token.encode()).hexdigest(),csrf_token=csrf,expires_at=utcnow()+timedelta(days=7)))
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


class Opening(BaseModel):
    opening_balance: int


class NewDebt(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    lender: str = Field(default='', max_length=120)
    principal: int
    due_date: date | None = None
    note: str = Field(default='', max_length=500)


class ManualDebtPayment(BaseModel):
    amount: int
    paid_on: date = Field(default_factory=date.today)


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
def setup(data:NewUser,response:Response,db:Session=Depends(get_db)):
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
        csrf=start_session(db,response,u)
        log(db,u.id,'setup','Khởi tạo quản trị viên')
        db.commit()
    except IntegrityError:
        db.rollback();raise HTTPException(409,'Tên đăng nhập hoặc email đã tồn tại.')
    return {'user':user_json(u),'csrf_token':csrf}


@app.post('/api/login')
def login(data:Login,response:Response,db:Session=Depends(get_db)):
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
    csrf=start_session(db,response,u)
    log(db,u.id,'login','Đăng nhập')
    db.commit()
    return {'user':user_json(u),'csrf_token':csrf}


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
    return {'id':e.id,'kind':e.kind,'title':e.title,'amount':e.amount,'category_id':e.category_id,'category':c.name if c else 'Không rõ','color':c.color if c else '#7567F8','note':e.note,'occurred_on':e.occurred_on.isoformat(),'created_at':e.created_at.isoformat(),'debt_paid':paid}


def debt_dict(d:Debt):
    return {'id':d.id,'name':d.name,'lender':d.lender,'principal':d.principal,
            'remaining':d.remaining,'paid':d.principal-d.remaining,
            'due_date':d.due_date.isoformat() if d.due_date else None,
            'note':d.note,'created_at':d.created_at.isoformat()}


@app.get('/api/debts')
def list_debts(u:User=Depends(current),db:Session=Depends(get_db)):
    debts=list(db.scalars(select(Debt).where(Debt.user_id==u.id).order_by(Debt.id)))
    payments=list(db.scalars(select(DebtPayment).where(DebtPayment.user_id==u.id).order_by(DebtPayment.paid_on.desc(),DebtPayment.id.desc()).limit(100)))
    names={debt.id:debt.name for debt in debts}
    return {'items':[debt_dict(d) for d in debts],
            'total_principal':sum(d.principal for d in debts),
            'total_remaining':sum(d.remaining for d in debts),
            'total_paid':sum(d.principal-d.remaining for d in debts),
            'payments':[{'id':p.id,'debt_id':p.debt_id,'debt':names.get(p.debt_id,''),
                         'entry_id':p.entry_id,'amount':p.amount,'mode':p.mode,
                         'paid_on':p.paid_on.isoformat()} for p in payments]}


@app.post('/api/debts')
def create_debt(data:NewDebt,u:User=Depends(current),db:Session=Depends(get_db)):
    check_amount(data.principal)
    if not data.name.strip():raise HTTPException(422,'Tên khoản nợ không được rỗng.')
    account_locked(db,u.id)
    d=Debt(user_id=u.id,name=data.name.strip(),lender=data.lender.strip(),
           principal=data.principal,remaining=data.principal,due_date=data.due_date,note=data.note.strip())
    db.add(d);db.flush();log(db,u.id,'debt_created',f'#{d.id}: {d.principal}');db.commit()
    return debt_dict(d)


@app.put('/api/debts/{debt_id}')
def edit_debt(debt_id:int,data:NewDebt,u:User=Depends(current),db:Session=Depends(get_db)):
    check_amount(data.principal)
    if not data.name.strip():raise HTTPException(422,'Tên khoản nợ không được rỗng.')
    account_locked(db,u.id)
    d=db.scalar(select(Debt).where(Debt.user_id==u.id,Debt.id==debt_id).with_for_update())
    if not d:raise HTTPException(404,'Không tìm thấy khoản nợ.')
    if data.principal != d.principal and db.scalar(select(func.count()).select_from(DebtPayment).where(DebtPayment.debt_id==d.id)):
        raise HTTPException(409,'Khoản nợ đã có lịch sử trả. Không thể đổi nợ gốc; hãy tạo khoản nợ điều chỉnh riêng.')
    if data.principal != d.principal:d.principal=data.principal;d.remaining=data.principal
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
    if data.paid_on>date.today()+timedelta(days=366):raise HTTPException(422,'Ngày thanh toán không hợp lệ.')
    account_locked(db,u.id)
    debt=db.scalar(select(Debt).where(Debt.user_id==u.id,Debt.id==debt_id).with_for_update())
    if not debt:raise HTTPException(404,'Không tìm thấy khoản nợ.')
    if amount>debt.remaining:raise HTTPException(409,'Số tiền trả vượt quá nợ gốc còn lại.')
    if amount>current_balance(db,u.id)[0]:raise HTTPException(409,'Số dư khả dụng không đủ để trả nợ.')
    debt.remaining-=amount
    db.add(DebtPayment(user_id=u.id,debt_id=debt.id,amount=amount,mode='manual',paid_on=data.paid_on))
    db.flush();ensure_nonnegative(db,u.id)
    log(db,u.id,'debt_manual_payment',f'#{debt.id}: {amount}');db.commit()
    return {'ok':True,'remaining':debt.remaining}


@app.delete('/api/debt-payments/{payment_id}')
def undo_manual_payment(payment_id:int,u:User=Depends(current),db:Session=Depends(get_db)):
    account_locked(db,u.id)
    p=db.scalar(select(DebtPayment).where(DebtPayment.user_id==u.id,DebtPayment.id==payment_id).with_for_update())
    if not p:raise HTTPException(404,'Không tìm thấy thanh toán.')
    if p.mode!='manual':raise HTTPException(409,'Thanh toán tự động chỉ có thể điều chỉnh bằng giao dịch thu nguồn.')
    d=db.scalar(select(Debt).where(Debt.id==p.debt_id,Debt.user_id==u.id).with_for_update())
    d.remaining+=p.amount;db.delete(p)
    db.flush();log(db,u.id,'debt_payment_undone',f'#{payment_id}');db.commit();return {'ok':True}


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
def transactions(month:str|None=None,kind:str|None=None,category_id:int|None=None,q:str='',page:int=1,size:int=15,u:User=Depends(current),db:Session=Depends(get_db)):
    if page<1 or size<1 or size>100:raise HTTPException(422,'Phân trang không hợp lệ.')
    stmt=select(Entry).where(Entry.user_id==u.id)
    if month:
        a,b=month_bounds(month);stmt=stmt.where(Entry.occurred_on>=a,Entry.occurred_on<b)
    if kind:
        if kind not in ('income','expense'):raise HTTPException(422,'Loại giao dịch không hợp lệ.')
        stmt=stmt.where(Entry.kind==kind)
    if category_id:stmt=stmt.where(Entry.category_id==category_id)
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
    e=Entry(user_id=u.id,title=data.title.strip(),kind=data.kind,amount=amount,category_id=data.category_id,note=data.note.strip(),occurred_on=data.occurred_on)
    db.add(e);db.flush();auto_paid=allocate_income_to_debts(db,u.id,e);ensure_nonnegative(db,u.id)
    log(db,u.id,'entry_added',f'{e.kind} #{e.id}: {e.amount}; debt_paid={auto_paid}')
    db.commit();return {'id':e.id,'ok':True,'debt_paid':auto_paid}


@app.put('/api/transactions/{entry_id}')
def edit_entry(entry_id:int,data:NewEntry,u:User=Depends(current),db:Session=Depends(get_db)):
    check_amount(data.amount)
    if not data.title.strip():raise HTTPException(422,'Nội dung không được rỗng.')
    account_locked(db,u.id)
    e=db.scalar(select(Entry).where(Entry.id==entry_id,Entry.user_id==u.id))
    if not e:raise HTTPException(404,'Không tìm thấy giao dịch.')
    category_for(db,u,data.category_id,data.kind)
    reverse_entry_payments(db,u.id,e.id)
    e.title=data.title.strip();e.kind=data.kind;e.amount=data.amount;e.category_id=data.category_id;e.note=data.note.strip();e.occurred_on=data.occurred_on
    db.flush();auto_paid=allocate_income_to_debts(db,u.id,e);ensure_nonnegative(db,u.id)
    log(db,u.id,'entry_edited',f'#{e.id}; debt_paid={auto_paid}');db.commit();return {'ok':True,'debt_paid':auto_paid}


@app.delete('/api/transactions/{entry_id}')
def delete_entry(entry_id:int,u:User=Depends(current),db:Session=Depends(get_db)):
    account_locked(db,u.id)
    e=db.scalar(select(Entry).where(Entry.id==entry_id,Entry.user_id==u.id))
    if not e:raise HTTPException(404,'Không tìm thấy giao dịch.')
    reverse_entry_payments(db,u.id,e.id);db.delete(e);db.flush();ensure_nonnegative(db,u.id)
    log(db,u.id,'entry_deleted',f'#{entry_id}');db.commit();return {'ok':True}


@app.put('/api/opening-balance')
def set_opening(data:Opening,u:User=Depends(current),db:Session=Depends(get_db)):
    check_amount(data.opening_balance,zero=True)
    locked=account_locked(db,u.id)
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
    debt_remaining=int(db.scalar(select(func.coalesce(func.sum(Debt.remaining),0)).where(Debt.user_id==u.id)) or 0)
    debt_paid=debt_paid_total(db,u.id)
    month_debt_paid=int(db.scalar(select(func.coalesce(func.sum(DebtPayment.amount),0)).where(DebtPayment.user_id==u.id,DebtPayment.paid_on>=a,DebtPayment.paid_on<b)) or 0)
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
    return {'balance':balance,'opening_balance':u.opening_balance,'total_income':all_income,'total_expense':all_expense,
            'month_income':inc,'month_expense':exp,'month_count':len(month_entries),'net':inc-exp,
            'categories':category_chart,'trend':trend,'recent':[entry_json(e,cats,int(allocations.get(e.id,0))) for e in recent],
            'budgets':budgets,'overspent_budgets':sum(1 for bb in budgets if bb['spent']>bb['amount']),
            'debt_remaining':debt_remaining,'debt_paid':debt_paid,'month_debt_paid':month_debt_paid,'net_worth':balance-debt_remaining}


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
    writer.writerow(['Ngày','Loại','Nội dung','Danh mục','Số tiền (VNĐ)','Ghi chú','Đã tự động trả nợ (VNĐ)'])
    for e in rows:
        # Prevent spreadsheet formula injection for arbitrary user-provided strings.
        def excel_text(value):
            value=str(value)
            return "'"+value if value.lstrip().startswith(('=','+','-','@','\t','\r')) else value
        writer.writerow([e.occurred_on.isoformat(),'Thu' if e.kind=='income' else 'Chi',excel_text(e.title),excel_text(cats.get(e.category_id,'')),e.amount,excel_text(e.note),int(allocations.get(e.id,0))])
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
        db.add(new);db.flush();seed_categories(db,new);log(db,u.id,'user_created',username);db.commit()
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
    db.query(PasswordResetToken).filter(PasswordResetToken.user_id==target.id).delete(synchronize_session=False)
    db.query(Budget).filter(Budget.user_id==target.id).delete(synchronize_session=False)
    db.query(DebtPayment).filter(DebtPayment.user_id==target.id).delete(synchronize_session=False)
    db.query(Debt).filter(Debt.user_id==target.id).delete(synchronize_session=False)
    db.query(Entry).filter(Entry.user_id==target.id).delete(synchronize_session=False)
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
