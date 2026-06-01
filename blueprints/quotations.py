import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from auth import login_required
from sheets_client import get_sheet, append_row
from config import COMPANY_OPTIONS

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

@quotations_bp.route("/<int:idx>")
@login_required
def detail(idx):
    quotes = get_sheet("報價單記錄")
    if idx >= len(quotes):
        return redirect(url_for("quotations.list_quotes"))
    return render_template("quotations/detail.html", quote=quotes[idx], idx=idx)

@quotations_bp.route("/api/customer-lookup")
@login_required
def customer_lookup():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])
    customers = get_sheet("顧客資料")
    results = [c for c in customers if q in c.get("姓名", "") or q in c.get("電話", "")][:5]
    return jsonify(results)
