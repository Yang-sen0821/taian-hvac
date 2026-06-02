import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from auth import login_required
from sheets_client import get_sheet, append_row
from config import COMPANY_OPTIONS
from db import db

quotations_bp = Blueprint("quotations", __name__, url_prefix="/quotations")

def next_quote_number():
    today = datetime.date.today().strftime("%Y%m%d")
    quotes = get_sheet("報價單記錄")
    prefix = f"Q-{today}-"
    count = sum(1 for q in quotes if str(q.get("報價單編號", "")).startswith(prefix))
    return f"{prefix}{count+1:03d}"

def safe_float(val):
    try:
        return float(str(val or "0").replace(",", "").strip() or "0")
    except:
        return 0.0

@quotations_bp.route("/")
@login_required
def list_quotes():
    quotes = get_sheet("報價單記錄")
    status_filter = request.args.get("status", "")
    if status_filter:
        quotes = [q for q in quotes if q.get("狀態", "") == status_filter]
    quotes = list(reversed(quotes))
    for i, q in enumerate(quotes):
        q["_idx"] = i
    return render_template("quotations/list.html", quotes=quotes, status_filter=status_filter,
                           statuses=["草稿", "已確認", "已完成", "已取消"])

@quotations_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_quote():
    if request.method == "POST":
        f = request.form
        company = f.get("company_title", "")
        tax_id = next((c["tax_id"] for c in COMPANY_OPTIONS if c["name"] == company), "")

        items_data = []
        for i in range(1, 4):
            name  = f.get(f"item{i}_name", "").strip()
            qty   = safe_float(f.get(f"item{i}_qty", "0"))
            price = safe_float(f.get(f"item{i}_price", "0"))
            sub   = qty * price
            items_data.append({"name": name, "qty": qty, "price": price, "sub": sub})

        engineering = safe_float(f.get("engineering", "0"))
        other       = safe_float(f.get("other", "0"))
        pretax      = sum(it["sub"] for it in items_data) + engineering + other
        tax         = round(pretax * 0.05)
        total       = pretax + tax

        data = {
            "報價單編號":  next_quote_number(),
            "報價日期":   f.get("quote_date", datetime.date.today().isoformat()),
            "公司抬頭":   company,
            "統編":      tax_id,
            "客戶姓名":   f.get("customer_name", ""),
            "客戶電話":   f.get("customer_phone", ""),
            "客戶地址":   f.get("customer_address", ""),
            "品項1名稱":  items_data[0]["name"],
            "品項1數量":  items_data[0]["qty"],
            "品項1單價":  items_data[0]["price"],
            "品項1小計":  items_data[0]["sub"],
            "品項2名稱":  items_data[1]["name"],
            "品項2數量":  items_data[1]["qty"],
            "品項2單價":  items_data[1]["price"],
            "品項2小計":  items_data[1]["sub"],
            "品項3名稱":  items_data[2]["name"],
            "品項3數量":  items_data[2]["qty"],
            "品項3單價":  items_data[2]["price"],
            "品項3小計":  items_data[2]["sub"],
            "工程費":     engineering,
            "其他費用":   other,
            "未稅合計":   pretax,
            "稅額(5%)":  tax,
            "含稅總金額":  total,
            "預計安裝日期": f.get("install_date", ""),
            "備註":      f.get("notes", ""),
            "狀態":      "草稿",
        }
        append_row("報價單記錄", data)
        flash(f"✅ 報價單 {data['報價單編號']} 已建立，含稅總金額 NT${total:,.0f}")
        return redirect(url_for("quotations.list_quotes"))

    customers = get_sheet("顧客資料")
    ac_items  = get_sheet("冷氣庫存")
    gift_items = get_sheet("贈品庫存")
    return render_template("quotations/new.html",
        customers=customers, ac_items=ac_items, gift_items=gift_items,
        companies=COMPANY_OPTIONS, today=datetime.date.today().isoformat())

@quotations_bp.route("/<int:quote_id>")
@login_required
def detail(quote_id):
    from db import Quotation
    q = db.session.get(Quotation, quote_id)
    if not q:
        flash("找不到該報價單（可能已被刪除）")
        return redirect(url_for("quotations.list_quotes"))
    return render_template("quotations/detail.html", q=q, idx=quote_id)


@quotations_bp.route("/delete", methods=["POST"])
@login_required
def delete_quotes():
    from db import Quotation
    ids = request.form.getlist("quote_ids")
    deleted = 0
    for qid in ids:
        try:
            q = db.session.get(Quotation, int(qid))
        except (ValueError, TypeError):
            q = None
        if q:
            db.session.delete(q)
            deleted += 1
    db.session.commit()
    flash(f"已刪除 {deleted} 筆報價單")
    return redirect(url_for("quotations.list_quotes"))


@quotations_bp.route("/api/inventory-search")
@login_required
def inventory_search():
    """打字篩選庫存品項，回傳符合的冷氣與贈品（含庫存量）。"""
    q = request.args.get("q", "").strip()
    from db import ACInventory, GiftInventory
    results = []
    for item in ACInventory.query.all():
        name = item.spec or ""
        if not q or q in name:
            stock = item.actual_qty or item.system_qty or "0"
            results.append({"name": name, "type": "冷氣", "stock": stock})
    for item in GiftInventory.query.all():
        name = item.name or ""
        if not q or q in name:
            results.append({"name": name, "type": "贈品", "stock": item.qty or "0"})
    return jsonify(results[:15])


@quotations_bp.route("/api/inventory-check")
@login_required
def inventory_check():
    """檢查品名是否存在於庫存，回傳 {exists: bool, stock: ...}。"""
    name = request.args.get("name", "").strip()
    if not name:
        return jsonify({"exists": True, "stock": None})
    from db import ACInventory, GiftInventory
    ac = ACInventory.query.filter(ACInventory.spec == name).first()
    if ac:
        return jsonify({"exists": True, "stock": ac.actual_qty or ac.system_qty or "0"})
    gift = GiftInventory.query.filter(GiftInventory.name == name).first()
    if gift:
        return jsonify({"exists": True, "stock": gift.qty or "0"})
    return jsonify({"exists": False, "stock": None})

@quotations_bp.route("/api/customer-lookup")
@login_required
def customer_lookup():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])
    customers = get_sheet("顧客資料")
    results = [c for c in customers if q in c.get("姓名", "") or q in c.get("電話", "")][:5]
    return jsonify(results)


@quotations_bp.route("/api/item-prices")
@login_required
def item_prices():
    item_name = request.args.get("item", "").strip()
    if not item_name:
        return jsonify([])
    from db import Quotation as Q
    results = []
    seen = set()
    quotes = Q.query.order_by(Q.id.desc()).limit(100).all()
    for q in quotes:
        for name_attr, price_attr in [
            ("item1_name", "item1_price"),
            ("item2_name", "item2_price"),
            ("item3_name", "item3_price"),
        ]:
            if getattr(q, name_attr, "") == item_name:
                price = getattr(q, price_attr, 0) or 0
                if price and price not in seen:
                    seen.add(price)
                    results.append({"price": price, "date": q.quote_date or ""})
        if len(results) >= 5:
            break
    return jsonify(results)
