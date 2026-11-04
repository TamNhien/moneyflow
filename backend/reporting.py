"""Read-only reporting and downloadable finance statements.

Cash movement equals income - expense - all payable debt cash payments
+ receivable collections. Transfers between one's wallets never count as cash flow.
Current balances and net worth are snapshots, not historical month-end balances.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from io import BytesIO
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select


def report_months(end: str, count: int):
    import re
    if not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', end or '') or not 1900 <= int(end[:4]) <= 2099:
        raise HTTPException(422, 'Tháng báo cáo không hợp lệ (YYYY-MM).')
    if count not in (3, 6, 12, 24):
        raise HTTPException(422, 'Chỉ hỗ trợ 3, 6, 12 hoặc 24 tháng.')
    year, month = map(int, end.split('-'))
    ending = year * 12 + month - 1
    start = ending - count + 1
    if start < 1900 * 12:
        raise HTTPException(422, 'Khoảng thời gian báo cáo không hợp lệ.')
    keys = [f'{n // 12}-{n % 12 + 1:02d}' for n in range(start, ending + 1)]
    last = ending + 1
    limit = date(last // 12, last % 12 + 1, 1)
    return keys, date(start // 12, start % 12 + 1, 1), limit


def build_report(db, user_id: int, end: str, count: int):
    from backend.app import (Category, Entry, Debt, DebtPayment, Wallet, WalletTransfer,
                             wallet_balance, current_balance, total_reserved_savings, total_stash_funds)
    months, start, until = report_months(end, count)
    trend = {key: dict(month=key, income=0, expense=0,
                       payable_principal=0, payable_interest=0,
                       receivable_principal=0, receivable_interest=0,
                       debt_paid=0, debt_collected=0, net_cash=0) for key in months}
    cats = {c.id: c for c in db.scalars(select(Category).where(Category.user_id == user_id))}
    wallets = list(db.scalars(select(Wallet).where(Wallet.user_id == user_id).order_by(Wallet.id)))
    wallet_names = {w.id: w.name for w in wallets}
    entries = list(db.scalars(select(Entry).where(Entry.user_id == user_id,
                           Entry.occurred_on >= start, Entry.occurred_on < until)
                           .order_by(Entry.occurred_on.desc(), Entry.id.desc())))
    payments = list(db.execute(select(DebtPayment, Debt).join(Debt, DebtPayment.debt_id == Debt.id)
                 .where(DebtPayment.user_id == user_id, Debt.user_id == user_id,
                        DebtPayment.paid_on >= start, DebtPayment.paid_on < until)
                 .order_by(DebtPayment.paid_on.desc(), DebtPayment.id.desc())))
    categories = defaultdict(int)
    for entry in entries:
        key = entry.occurred_on.strftime('%Y-%m')
        trend[key][entry.kind] += int(entry.amount)
        if entry.kind == 'expense':
            categories[(entry.category_id, key)] += int(entry.amount)
    for payment, debt in payments:
        key = payment.paid_on.strftime('%Y-%m')
        prefix = 'payable' if debt.direction == 'payable' else 'receivable'
        trend[key][prefix + '_principal'] += int(payment.amount)
        trend[key][prefix + '_interest'] += int(payment.interest_amount or 0)
    for r in trend.values():
        r['debt_paid'] = r['payable_principal'] + r['payable_interest']
        r['debt_collected'] = r['receivable_principal'] + r['receivable_interest']
        r['net_cash'] = r['income'] - r['expense'] - r['debt_paid'] + r['debt_collected']
    total = {field: sum(r[field] for r in trend.values()) for field in
             ('income','expense','debt_paid','debt_collected','net_cash',
              'payable_principal','payable_interest','receivable_principal','receivable_interest')}
    selected, previous = trend[months[-1]], trend[months[-2]]
    comparison = {k: {'current': selected[k], 'previous': previous[k],
                      'difference': selected[k] - previous[k],
                      'percentage': round((selected[k] - previous[k]) * 100 / abs(previous[k]), 1) if previous[k] else None}
                  for k in ('income','expense','debt_paid','debt_collected','net_cash')}
    cash, _, _ = current_balance(db, user_id)
    saved_goals = total_reserved_savings(db, user_id)
    saved_stash = total_stash_funds(db, user_id)
    saved_funds = saved_goals + saved_stash
    debts = list(db.scalars(select(Debt).where(Debt.user_id == user_id)))
    payable = sum(int(d.remaining) for d in debts if d.direction == 'payable')
    receivable = sum(int(d.remaining) for d in debts if d.direction == 'receivable')
    transfers = list(db.scalars(select(WalletTransfer).where(
        WalletTransfer.user_id == user_id, WalletTransfer.occurred_on >= start,
        WalletTransfer.occurred_on < until)))
    category_rows = [{'name': cats[id].name if id in cats else 'Khác',
                      'color': cats[id].color if id in cats else '#7567F8',
                      'amount': amount}
                     for (id, m), amount in categories.items() if m == end]
    category_rows.sort(key=lambda x: (-x['amount'], x['name']))
    auto_paid = defaultdict(int)
    for p, d in payments:
        if p.entry_id and d.direction == 'payable':
            auto_paid[p.entry_id] += int(p.amount)
    transaction_rows = [{'date':e.occurred_on.isoformat(), 'kind':e.kind, 'title':e.title,
                         'amount':int(e.amount), 'category':cats[e.category_id].name if e.category_id in cats else 'Khác',
                         'wallet':wallet_names.get(e.wallet_id, 'Ví chính'), 'note':e.note,
                         'auto_debt_paid':auto_paid[e.id]} for e in entries]
    payment_rows = [{'date':p.paid_on.isoformat(), 'direction':d.direction,
                     'debt':d.name, 'principal':int(p.amount), 'interest':int(p.interest_amount or 0),
                     'wallet':wallet_names.get(p.wallet_id, 'Ví chính'), 'mode':p.mode}
                    for p, d in payments]
    return {'end_month':end, 'months_count':count, 'from_month':months[0], 'to_month':months[-1],
            'monthly':[trend[m] for m in months], 'totals':total,
            'selected_month':selected, 'comparison':comparison,
            'snapshot':{'cash_balance':cash,'savings_balance':saved_funds,'goal_savings_balance':saved_goals,'stash_balance':saved_stash,'total_assets':cash+saved_funds,'payable':payable,'receivable':receivable,
                        'net_worth':cash + saved_funds + receivable - payable,
                        'wallets':[{'name':w.name, 'kind':w.kind, 'balance':wallet_balance(db,w)} for w in wallets]},
            'categories':category_rows, 'transactions':transaction_rows, 'payments':payment_rows,
            'transfer_count':len(transfers), 'transfer_amount':sum(int(t.amount) for t in transfers)}


def as_public_report(data):
    """Keep detailed transactions server-side unless exporting a report."""
    return {key:value for key,value in data.items() if key not in ('transactions','payments')}


def currency(n):
    return f'{int(n):,}'.replace(',', '.') + ' đ'


def safe_cell(value):
    """Never interpret names/notes entered by a user as Excel formulas."""
    value = str(value if value is not None else '')
    return "'" + value if value.lstrip(' \t\r\n').startswith(('=', '+', '-', '@')) else value


def excel_bytes(data):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    wb.remove(wb.active)
    navy = '182442'; lavender = '7869F6'; teal = '17BCA4'
    money_fmt = '#,##0" đ";[Red](#,##0" đ");–'
    def sheet(title, cols, items, widths=None, money_cols=()):
        ws = wb.create_sheet(title)
        ws.append([safe_cell(v) for v in cols])
        ws.freeze_panes='A2'
        for c in ws[1]:
            c.font = Font(name='Calibri', size=11, bold=True, color='FFFFFF')
            c.fill = PatternFill('solid', fgColor=navy)
            c.alignment = Alignment(vertical='center', wrap_text=True)
        ws.row_dimensions[1].height=30
        for j,row in enumerate(items, 2):
            ws.append([safe_cell(x) if isinstance(x,str) else x for x in row])
            if j%2==0:
                for c in ws[j]: c.fill=PatternFill('solid', fgColor='F1F4FA')
            for i in money_cols:
                ws.cell(j,i).number_format=money_fmt
        ws.auto_filter.ref = ws.dimensions
        for i in range(1,len(cols)+1):
            ws.column_dimensions[get_column_letter(i)].width=(widths or {}).get(i, 22)
        ws.sheet_view.showGridLines=False
        return ws
    s=data['snapshot']; t=data['totals']
    sheet('Tổng quan',['Chỉ tiêu','Giá trị (VNĐ)'],[
        ('Khoảng báo cáo', f"{data['from_month']} → {data['to_month']}"),
        ('Tổng thu nhập',t['income']),('Chi tiêu',t['expense']),
        ('Trả nợ gốc + lãi',t['debt_paid']),('Thu hồi nợ gốc + lãi',t['debt_collected']),
        ('Dòng tiền thuần trong kỳ',t['net_cash']),
        ('Số dư khả dụng trong ví',s['cash_balance']),('Tiết kiệm dành riêng',s['savings_balance']),('Trong đó: Tiền tích để dành',s['stash_balance']),('Nợ phải thu hiện tại',s['receivable']),
        ('Nợ phải trả hiện tại',s['payable']),('Tài sản ròng hiện tại',s['net_worth']),
        ('Chuyển ví nội bộ (không tính vào dòng tiền)',data['transfer_amount'])],
        widths={1:49,2:34},money_cols=(2,))
    sheet('Theo tháng',['Tháng','Thu nhập','Chi tiêu','Trả gốc','Trả lãi',
          'Thu hồi gốc','Thu hồi lãi','Dòng tiền thuần'],[
          (r['month'],r['income'],r['expense'],r['payable_principal'],r['payable_interest'],
           r['receivable_principal'],r['receivable_interest'],r['net_cash']) for r in data['monthly']],
          widths={1:17,2:23,3:23,4:23,5:23,6:23,7:23,8:26},money_cols=(2,3,4,5,6,7,8))
    sheet('Danh mục chi',['Danh mục','Chi tháng chọn (VNĐ)'],
          [(r['name'],r['amount']) for r in data['categories']], widths={1:40,2:28},money_cols=(2,))
    sheet('Các ví',['Tên ví','Loại','Số dư hiện tại'],[
          (w['name'],w['kind'],w['balance']) for w in s['wallets']],
          widths={1:36,2:20,3:28},money_cols=(3,))
    sheet('Giao dịch',['Ngày','Loại','Nội dung','Danh mục','Số tiền','Ví','Ghi chú','Tự trả nợ gốc'],[
          (e['date'],'Thu' if e['kind']=='income' else 'Chi',e['title'],e['category'],e['amount'],
           e['wallet'],e['note'],e['auto_debt_paid']) for e in data['transactions']],
          widths={1:16,2:14,3:38,4:25,5:24,6:25,7:48,8:27},money_cols=(5,8))
    sheet('Thanh toán nợ',['Ngày','Loại nợ','Tên khoản nợ','Tiền gốc','Tiền lãi','Ví','Cách ghi'],[
          (p['date'],'Nợ phải trả' if p['direction']=='payable' else 'Nợ phải thu',
           p['debt'],p['principal'],p['interest'],p['wallet'],p['mode']) for p in data['payments']],
          widths={1:16,2:22,3:36,4:25,5:25,6:28,7:20},money_cols=(4,5))
    out=BytesIO();wb.save(out);return out.getvalue()


def pdf_bytes(data):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
    from reportlab.graphics.shapes import Drawing, Rect, String
    font_root=Path('/usr/share/fonts/truetype/dejavu')
    font_file=font_root/'DejaVuSans.ttf';bold_file=font_root/'DejaVuSans-Bold.ttf'
    if not font_file.exists() or not bold_file.exists():
        raise RuntimeError('Thiếu font Unicode DejaVu trong Docker image.')
    if 'MFDejaVu' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('MFDejaVu',str(font_file)))
        pdfmetrics.registerFont(TTFont('MFDejaVuBold',str(bold_file)))
    out=BytesIO()
    doc=SimpleDocTemplate(out,pagesize=A4, leftMargin=18*mm,rightMargin=18*mm,
                          topMargin=16*mm,bottomMargin=17*mm,title='MoneyFlow - Báo cáo tài chính')
    navy=colors.HexColor('#17213B');violet=colors.HexColor('#7667F8');muted=colors.HexColor('#64748B')
    green=colors.HexColor('#16B8A4');white=colors.white
    title=ParagraphStyle('mf-title',fontName='MFDejaVuBold',fontSize=17,leading=23,textColor=navy,spaceAfter=8)
    text=ParagraphStyle('mf-text',fontName='MFDejaVu',fontSize=8.5,leading=13,textColor=navy)
    section=ParagraphStyle('mf-section',parent=text,fontName='MFDejaVuBold',fontSize=11,spaceBefore=12,spaceAfter=7)
    note=ParagraphStyle('mf-note',parent=text,fontSize=7.5,textColor=muted)
    story=[Paragraph('MONEYFLOW  |  BÁO CÁO TÀI CHÍNH',title),
           Paragraph('Khoảng báo cáo: '+data['from_month']+' đến '+data['to_month']+' · Đơn vị: VNĐ',text),Spacer(1,7*mm)]
    def table(headers,rows,col_widths, money_cols=()):
        cells=[[Paragraph(str(s),ParagraphStyle('hd',parent=text,fontName='MFDejaVuBold',fontSize=7,leading=10,textColor=white)) for s in headers]]
        for row in rows:
            cells.append([Paragraph(currency(v) if j in money_cols else str(v),text) for j,v in enumerate(row)])
        tb=Table(cells,colWidths=col_widths,repeatRows=1,hAlign='LEFT')
        tb.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),navy),
               ('ROWBACKGROUNDS',(0,1),(-1,-1),[white,colors.HexColor('#F0F3FA')]),
               ('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LEFTPADDING',(0,0),(-1,-1),8),
               ('RIGHTPADDING',(0,0),(-1,-1),7),('TOPPADDING',(0,0),(-1,-1),7),
               ('BOTTOMPADDING',(0,0),(-1,-1),7)]))
        return tb
    t=data['totals'];s=data['snapshot']
    story.append(Paragraph('Tổng quan dòng tiền',section))
    story.append(table(['Chỉ tiêu','Giá trị'],[
        ('Tổng thu nhập',t['income']),('Chi tiêu',t['expense']),
        ('Trả nợ (gốc + lãi)',t['debt_paid']),('Thu hồi nợ (gốc + lãi)',t['debt_collected']),
        ('Biến động tiền thuần trong kỳ',t['net_cash'])], [96*mm,78*mm],(1,)))
    story.append(Paragraph('Tình hình tài chính hiện tại',section))
    story.append(table(['Chỉ tiêu','Giá trị'],[
        ('Số dư khả dụng các ví',s['cash_balance']),('Tiết kiệm dành riêng',s['savings_balance']),('Trong đó: Tiền tích để dành',s['stash_balance']),('Nợ phải thu',s['receivable']),
        ('Nợ phải trả',s['payable']),('Tài sản ròng',s['net_worth'])], [96*mm,78*mm],(1,)))
    story.append(Paragraph('Biến động thu và chi theo tháng',section))
    monthly=data['monthly'];maximum=max(1,*[max(r['income'],r['expense']) for r in monthly])
    chart=Drawing(485,135); spacing=480/max(1,len(monthly)); height=88; base=28
    for i,r in enumerate(monthly):
        x=i*spacing+6;bar_width=max(3,min(12,spacing*.24));
        chart.add(Rect(x,base,bar_width,height*r['income']/maximum,fillColor=violet,strokeColor=None))
        chart.add(Rect(x+bar_width+2,base,bar_width,height*r['expense']/maximum,fillColor=green,strokeColor=None))
        chart.add(String(x,12,r['month'][5:]+'/'+r['month'][2:4],fontName='MFDejaVu',fontSize=6,fillColor=muted))
    story.extend([chart,Paragraph('Tím: thu nhập · Xanh: chi tiêu. Trả nợ được thống kê riêng, không tính trùng vào chi tiêu.',note)])
    story.append(Paragraph('Bảng biến động tiền theo tháng',section))
    story.append(table(['Tháng','Thu','Chi','Trả nợ','Thu hồi nợ','Tiền thuần'],[
        (r['month'],r['income'],r['expense'],r['debt_paid'],r['debt_collected'],r['net_cash']) for r in monthly],
        [23*mm,30*mm,30*mm,30*mm,30*mm,31*mm],(1,2,3,4,5)))
    story.extend([Spacer(1,4*mm),Paragraph('Chuyển tiền giữa các ví không tạo thu nhập hoặc chi phí. '
        'Các số dư và tài sản ròng là thời điểm xuất báo cáo, không phải số dư cuối mỗi tháng trong quá khứ.',note)])
    def footer(canvas,doc):
        canvas.setFont('MFDejaVu',7);canvas.setFillColor(muted)
        canvas.drawString(18*mm,11*mm,'MoneyFlow · Báo cáo nội bộ từ dữ liệu tài khoản hiện tại')
        canvas.drawRightString(A4[0]-18*mm,11*mm,f'Trang {doc.page}')
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return out.getvalue()


# v1.0.24: annual financial timeline based on the CURRENT editable ledger.
# Entries can be backdated or edited, so past month-end amounts are reconstructed
# estimates, not immutable audited snapshots.
def annual_finances(db, user_id: int, year: int):
    from calendar import monthrange
    from backend.app import (Entry, Debt, DebtPayment, Wallet, SavingsMovement,
                             StashMovement)
    today = date.today()
    if year < 2000 or year > today.year:
        raise HTTPException(422, 'Nam bao cao phai tu 2000 den nam hien tai.')
    first = date(year, 1, 1)
    cutoff = min(date(year, 12, 31), today)
    all_entries = list(db.scalars(select(Entry).where(Entry.user_id == user_id, Entry.occurred_on <= cutoff)))
    all_payments = list(db.execute(select(DebtPayment, Debt).join(Debt, DebtPayment.debt_id == Debt.id)
                  .where(DebtPayment.user_id == user_id, Debt.user_id == user_id,
                         DebtPayment.paid_on <= cutoff)))
    all_savings = list(db.scalars(select(SavingsMovement).where(
        SavingsMovement.user_id == user_id, SavingsMovement.occurred_on <= cutoff)))
    all_stash = list(db.scalars(select(StashMovement).where(
        StashMovement.user_id == user_id, StashMovement.occurred_on <= cutoff)))
    wallets = list(db.scalars(select(Wallet).where(Wallet.user_id == user_id)))
    debts = list(db.scalars(select(Debt).where(Debt.user_id == user_id)))
    # When an older account was migrated to wallets after its transactions,
    # wallet.created_at is not a trustworthy opening-balance start date.
    # Assume the opening balance existed from its earliest dated wallet entry.
    # This is an estimate and is explicitly disclosed to the user.
    wallet_first_activity={}
    for item in all_entries:
        if item.wallet_id is not None:
            old=wallet_first_activity.get(item.wallet_id)
            if old is None or item.occurred_on < old:
                wallet_first_activity[item.wallet_id]=item.occurred_on
    for item in all_savings + all_stash:
        old=wallet_first_activity.get(item.wallet_id)
        if old is None or item.occurred_on < old:
            wallet_first_activity[item.wallet_id]=item.occurred_on
    monthly = []
    def day_of(obj):
        d = obj.created_at
        return d.date() if hasattr(d, 'date') else d
    for m in range(1, 13):
        start_month = date(year, m, 1)
        if start_month > today:
            break
        last = min(date(year, m, monthrange(year,m)[1]), today)
        income=expense=payable_paid=receivable_collected=0
        all_income=all_expense=0
        for e in all_entries:
            if e.occurred_on <= last:
                amt = int(e.amount)
                if e.kind == 'income':
                    all_income += amt
                    if e.occurred_on >= first and e.occurred_on.month == m: income += amt
                else:
                    all_expense += amt
                    if e.occurred_on >= first and e.occurred_on.month == m: expense += amt
        debt_payable_cash=debt_receivable_cash=0
        paid_by_debt={}
        for payment,debt in all_payments:
            if payment.paid_on > last: continue
            amount=int(payment.amount)
            cash=amount+int(payment.interest_amount or 0)
            paid_by_debt[debt.id]=paid_by_debt.get(debt.id,0)+amount
            if debt.direction=='payable':
                debt_payable_cash += cash
                if payment.paid_on >= first and payment.paid_on.month == m: payable_paid+=cash
            else:
                debt_receivable_cash += cash
                if payment.paid_on >= first and payment.paid_on.month == m: receivable_collected+=cash
        reserved_goals=sum((1 if move.kind=='deposit' else -1)*int(move.amount)
                           for move in all_savings if move.occurred_on<=last)
        reserved_stash=sum((1 if move.kind=='deposit' else -1)*int(move.amount)
                           for move in all_stash if move.occurred_on<=last)
        # Wallet creation dates predate ledger migration only when originally recorded;
        # historical opening balances can be amended, hence estimate disclaimer.
        opening=sum(int(w.opening_balance) for w in wallets
                    if min(day_of(w),wallet_first_activity.get(w.id,day_of(w)))<=last)
        available=(opening + all_income - all_expense - debt_payable_cash
                   + debt_receivable_cash - reserved_goals - reserved_stash)
        payable=receivable=0
        for debt in debts:
            if day_of(debt)>last: continue
            remaining=max(0, int(debt.principal)-paid_by_debt.get(debt.id,0))
            if debt.direction=='payable':payable+=remaining
            else:receivable+=remaining
        saved=reserved_goals+reserved_stash
        monthly.append({'month':f'{year}-{m:02d}', 'income':income,'expense':expense,
                'debt_paid':payable_paid,'debt_collected':receivable_collected,
                'net_cash':income-expense-payable_paid+receivable_collected,
                'available':available,'reserved':saved,'assets':available+saved,
                'payable':payable,'receivable':receivable,
                'net_worth':available+saved+receivable-payable})
    fields=('income','expense','debt_paid','debt_collected','net_cash')
    totals={key:sum(int(x[key]) for x in monthly) for key in fields}
    # Previous year: compute only activity in that year. This avoids using previous
    # results as a fake past balance snapshot.
    prev_start=date(year-1,1,1)
    prev_end=date(year,1,1)
    prev_income=sum(int(e.amount) for e in db.scalars(select(Entry).where(
        Entry.user_id==user_id,Entry.kind=='income',Entry.occurred_on>=prev_start,Entry.occurred_on<prev_end)))
    prev_expense=sum(int(e.amount) for e in db.scalars(select(Entry).where(
        Entry.user_id==user_id,Entry.kind=='expense',Entry.occurred_on>=prev_start,Entry.occurred_on<prev_end)))
    previous={'income':prev_income,'expense':prev_expense}
    previous['net_basic']=prev_income-prev_expense
    comparison={k:{'current':totals[k],'previous':previous[k],
        'difference':totals[k]-previous[k],
        'percentage':round((totals[k]-previous[k])*100/abs(previous[k]),1)
                     if previous[k] else None} for k in ('income','expense')}
    return {'year':year,'as_of':cutoff.isoformat(),'monthly':monthly,'totals':totals,
            'previous_year':year-1,'comparison':comparison,
            'closing': monthly[-1] if monthly else None,
            'disclaimer':'Du lieu tai san cuoi thang duoc uoc tinh tu so goc va so giao dich hien co; '
                         'gia dinh so dau ky da co tu lan hoat dong dau tien; '
                         'giao dich sua/xoa/ghi lui ngay va thay doi so goc co the lam doi so lieu lich su. '
                         'Khong phai anh chup so du tai thoi diem da khoa so.'}


def annual_excel_bytes(data):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    wb=Workbook();ws=wb.active;ws.title='Tong quan nam'
    ws.append(['MoneyFlow', 'Bao cao tai chinh '+str(data['year'])])
    ws.append(['Ngay chot',data['as_of']])
    for k,label in [('income','Tong thu nhap'),('expense','Tong chi tieu'),
                    ('debt_paid','Tra no'),('debt_collected','Thu hoi no'),
                    ('net_cash','Dong tien thuan')]: ws.append([label,data['totals'][k]])
    ws.append(['Ghi chu',data['disclaimer']])
    ws.column_dimensions['A'].width=34;ws.column_dimensions['B'].width=105
    for cell in ws[1]: cell.font=Font(bold=True,color='FFFFFF');cell.fill=PatternFill('solid',fgColor='202A49')
    w=wb.create_sheet('Bien dong 12 thang');w.freeze_panes='B2'
    w.append(['Thang','Thu nhap','Chi tieu','Tra no','Thu hoi no','Tien thuan',
              'So du kha dung (uoc tinh)','Tien danh rieng (uoc tinh)',
              'Tai san tien (uoc tinh)','No phai thu','No phai tra','Tai san rong (uoc tinh)'])
    keys=['month','income','expense','debt_paid','debt_collected','net_cash',
          'available','reserved','assets','receivable','payable','net_worth']
    for row in data['monthly']:w.append([row[k] for k in keys])
    w.auto_filter.ref=w.dimensions
    for col in w[1]: col.font=Font(bold=True,color='FFFFFF');col.fill=PatternFill('solid',fgColor='202A49');col.alignment=Alignment(wrap_text=True)
    w.row_dimensions[1].height=34
    for j in range(1,len(keys)+1):w.column_dimensions[get_column_letter(j)].width=18 if j==1 else 25
    for row in w.iter_rows(min_row=2,min_col=2):
        for c in row:c.number_format='#,##0" d";[Red](#,##0" d");-'
    w.sheet_view.showGridLines=False
    from io import BytesIO
    output=BytesIO();wb.save(output);return output.getvalue()


def annual_pdf_bytes(data):
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    root=Path('/usr/share/fonts/truetype/dejavu')
    # Local test fallback: the Debian image provides the same font path.
    if not (root/'DejaVuSans.ttf').exists():
        root=Path('/usr/share/fonts/truetype/dejavu')
    if 'MFAnnual' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('MFAnnual',str(root/'DejaVuSans.ttf')))
        pdfmetrics.registerFont(TTFont('MFAnnualBold',str(root/'DejaVuSans-Bold.ttf')))
    out=BytesIO()
    doc=SimpleDocTemplate(out,pagesize=A4,leftMargin=14*mm,rightMargin=14*mm,
                          topMargin=15*mm,bottomMargin=15*mm,
                          title=f'MoneyFlow - Bao cao nam {data["year"]}')
    style=ParagraphStyle('mfy',fontName='MFAnnual',fontSize=8,leading=12)
    hd=ParagraphStyle('mfyh',parent=style,fontName='MFAnnualBold',fontSize=16,leading=24,spaceAfter=12)
    story=[Paragraph('MONEYFLOW  |  BÁO CÁO TÀI CHÍNH NĂM '+str(data['year']),hd),
           Paragraph('Tổng hợp dòng tiền và lịch sử tài sản (ước tính)',style),Spacer(1,8*mm)]
    def tb(rows,widths,header=False):
        t=Table(rows,colWidths=widths,repeatRows=1 if header else 0)
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#232D50')),
          ('TEXTCOLOR',(0,0),(-1,0),colors.white),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#F2F4FA')]),
          ('VALIGN',(0,0),(-1,-1),'MIDDLE'),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)]))
        return t
    head_style=ParagraphStyle('mfyhead',parent=style,textColor=colors.white,fontName='MFAnnualBold')
    def P(s):return Paragraph(str(s),style)
    def H(s):return Paragraph(str(s),head_style)
    story.append(tb([[H('Chỉ tiêu'),H('Giá trị')]]+[[P(label),P(currency(data['totals'][key]))] for key,label in
          [('income','Thu nhập'),('expense','Chi tiêu'),('debt_paid','Trả nợ'),('debt_collected','Thu hồi nợ'),('net_cash','Dòng tiền thuần')]], [93*mm,89*mm],True))
    story.extend([Spacer(1,8*mm),P('TÀI SẢN RÒNG THEO THÁNG (ƯỚC TÍNH)'),Spacer(1,3*mm)])
    rows=[[H('Tháng'),H('Thu'),H('Chi'),H('Tiền thuần'),H('Tài sản ròng')]]
    for r in data['monthly']:
        rows.append([P(r['month']),P(currency(r['income'])),P(currency(r['expense'])),P(currency(r['net_cash'])),P(currency(r['net_worth']))])
    story.append(tb(rows,[23*mm,36*mm,36*mm,42*mm,45*mm],True))
    story.extend([Spacer(1,6*mm),P('Lưu ý: Lịch sử được tái lập từ sổ giao dịch hiện có; không phải số dư đã khóa sổ.')])
    doc.build(story)
    return out.getvalue()
