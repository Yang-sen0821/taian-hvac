import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from auth import login_required
from db import db, Transaction

transactions_bp = Blueprint("transactions", __name__, url_prefix="/transactions")


def _parse_date(s):
    """把字串日期轉成 date 物件，失敗回 None。"""
    if not s:
        return None
    try:
        return datetime.date.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None


def _parse_amount(val):
    try:
        return float(str(val or "0").replace(",", "").strip() or "0")
    except (ValueError, TypeError):
        return 0.0


def _sum_between(txns, start, end, txn_type):
    """加總指定日期區間與類型的金額。start/end 為 date 物件（含端點）。"""
    total = 0.0
    for t in txns:
        d = _parse_date(t.date)
        if d is None:
            continue
        if start and d < start:
            continue
        if end and d > end:
            continue
        if t.type == txn_type:
            total += (t.amount or 0)
    return total


def compute_dashboard(start_str=None, end_str=None):
    """計算儀表板所需的所有統計數據。回傳 dict。

    - 今日 / 本週 / 本月 / 本年 收入、支出、淨利
    - 最近 6 個月趨勢（收入 vs 支出）
    - 自訂日期範圍（start_str / end_str，若提供）
    """
    today = datetime.date.today()
    week_start = today - datetime.timedelta(days=today.weekday())  # 本週一
    month_start = today.replace(day=1)
    year_start = today.replace(month=1, day=1)

    txns = Transaction.query.all()

    def block(start, end):
        inc = _sum_between(txns, start, end, "income")
        exp = _sum_between(txns, start, end, "expense")
        return {"income": inc, "expense": exp, "net": inc - exp}

    stats = {
        "today": block(today, today),
        "week": block(week_start, today),
        "month": block(month_start, today),
        "year": block(year_start, today),
    }

    # 最近 6 個月趨勢
    trend_labels = []
    trend_income = []
    trend_expense = []
    cursor = month_start
    months = []
    for _ in range(6):
        months.append(cursor)
        # 往前推一個月
        if cursor.month == 1:
            cursor = cursor.replace(year=cursor.year - 1, month=12)
        else:
            cursor = cursor.replace(month=cursor.month - 1)
    for m in reversed(months):
        # 該月最後一天
        if m.month == 12:
            nxt = m.replace(year=m.year + 1, month=1)
        else:
            nxt = m.replace(month=m.month + 1)
        m_end = nxt - datetime.timedelta(days=1)
        trend_labels.append("{}/{:02d}".format(m.year, m.month))
        trend_income.append(_sum_between(txns, m, m_end, "income"))
        trend_expense.append(_sum_between(txns, m, m_end, "expense"))

    stats["trend_labels"] = trend_labels
    stats["trend_income"] = trend_income
    stats["trend_expense"] = trend_expense

    # 自訂日期範圍
    rng_start = _parse_date(start_str)
    rng_end = _parse_date(end_str)
    if rng_start or rng_end:
        stats["custom_range"] = block(rng_start, rng_end)
        stats["custom_start"] = start_str or ""
        stats["custom_end"] = end_str or ""
    else:
        stats["custom_range"] = None
        stats["custom_start"] = ""
        stats["custom_end"] = ""

    return stats


@transactions_bp.route("/")
@login_required
def list_transactions():
    type_filter = request.args.get("type", "")
    month = request.args.get("month", "")          # YYYY-MM 月份篩選（操作者常用，比起訖日直覺）
    start_str = request.args.get("start", "")
    end_str = request.args.get("end", "")
    start = _parse_date(start_str)
    end = _parse_date(end_str)

    txns = Transaction.query.order_by(Transaction.id.desc()).all()
    # 月份下拉選項：資料中出現過的 YYYY-MM，新到舊
    months = sorted({(t.date or "")[:7] for t in txns if (t.date or "")[:7]}, reverse=True)

    rows = []
    total_income = 0.0
    total_expense = 0.0
    for t in txns:
        d = _parse_date(t.date)
        if month and not (t.date or "").startswith(month):
            continue
        if start and (d is None or d < start):
            continue
        if end and (d is None or d > end):
            continue
        if type_filter and t.type != type_filter:
            continue
        rows.append(t)
        if t.type == "income":
            total_income += (t.amount or 0)
        elif t.type == "expense":
            total_expense += (t.amount or 0)

    return render_template("transactions/list.html",
                           transactions=rows,
                           total_income=total_income,
                           total_expense=total_expense,
                           net=total_income - total_expense,
                           type_filter=type_filter,
                           month=month, months=months,
                           start=start_str, end=end_str)


@transactions_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_transaction():
    if request.method == "POST":
        f = request.form
        txn = Transaction(
            date=f.get("date", datetime.date.today().isoformat()),
            type=f.get("type", "income"),
            amount=_parse_amount(f.get("amount", "0")),
            category=f.get("category", ""),
            description=f.get("description", ""),
            ref_type="manual",
            ref_id=0,
        )
        db.session.add(txn)
        db.session.commit()
        flash("已新增{}記錄 NT${:,.0f}".format(
            "收入" if txn.type == "income" else "支出", txn.amount))
        return redirect(url_for("transactions.list_transactions"))
    return render_template("transactions/new.html",
                           today=datetime.date.today().isoformat())


@transactions_bp.route("/<int:txn_id>/delete", methods=["POST"])
@login_required
def delete_transaction(txn_id):
    txn = db.session.get(Transaction, txn_id)
    if not txn:
        flash("找不到該筆記錄")
        return redirect(url_for("transactions.list_transactions"))
    if txn.ref_type != "manual":
        flash("此記錄由出貨單/進貨自動產生，請至對應單據處理，不可直接刪除")
        return redirect(url_for("transactions.list_transactions"))
    db.session.delete(txn)
    db.session.commit()
    flash("記錄已刪除")
    return redirect(url_for("transactions.list_transactions"))


@transactions_bp.route("/<int:txn_id>/edit-date", methods=["POST"])
@login_required
def edit_transaction_date(txn_id):
    """修改既有進出帳紀錄的日期。前端在 modal 內已警告「會影響報表數據」，這裡再次於 flash 提醒。
    允許任何紀錄（含出貨/進貨自動產生）改日期，因客戶要求既有紀錄可改；不動來源單據日期。"""
    txn = db.session.get(Transaction, txn_id)
    if not txn:
        flash("找不到該筆記錄")
        return redirect(url_for("transactions.list_transactions"))
    new_date = (request.form.get("date") or "").strip()
    if not _parse_date(new_date):
        flash("日期格式不正確，未更動")
        return redirect(url_for("transactions.list_transactions"))
    old = txn.date
    txn.date = new_date
    db.session.commit()
    flash("日期已從 {} 改為 {}（提醒：此變動會影響報表相關數據）".format(old or "—", new_date))
    return redirect(url_for("transactions.list_transactions"))
