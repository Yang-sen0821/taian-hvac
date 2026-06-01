from flask import Blueprint, render_template, request, redirect, url_for, flash
from auth import login_required
from sheets_client import get_sheet, append_row, update_row

customers_bp = Blueprint("customers", __name__, url_prefix="/customers")

PAGE_SIZE = 20

@customers_bp.route("/")
@login_required
def list_customers():
    q = request.args.get("q", "").strip()
    page = int(request.args.get("page", 1))
    all_customers = get_sheet("顧客資料")
    if q:
        filtered = [c for c in all_customers if
                    q in str(c.get("姓名","")) or
                    q in str(c.get("電話","")) or
                    q in str(c.get("地址",""))]
    else:
        filtered = all_customers
    total = len(filtered)
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, min(page, pages))
    customers = filtered[(page-1)*PAGE_SIZE : page*PAGE_SIZE]
    for i, c in enumerate(customers):
        c["_idx"] = all_customers.index(c) if c in all_customers else -1
    return render_template("customers/list.html",
        customers=customers, q=q, page=page, pages=pages,
        total=total, total_all=len(all_customers))

@customers_bp.route("/<int:idx>")
@login_required
def detail(idx):
    customers = get_sheet("顧客資料")
    if idx >= len(customers):
        flash("找不到客戶")
        return redirect(url_for("customers.list_customers"))
    return render_template("customers/detail.html", customer=customers[idx], idx=idx)

@customers_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_customer():
    if request.method == "POST":
        data = {
            "姓名":    request.form.get("name", ""),
            "廠牌型號": request.form.get("model", ""),
            "電話":    request.form.get("phone", ""),
            "地址":    request.form.get("address", ""),
            "安裝日期": request.form.get("install_date", ""),
            "備註":    request.form.get("note", ""),
        }
        append_row("顧客資料", data)
        flash(f"✅ 客戶「{data['姓名']}」已新增")
        return redirect(url_for("customers.list_customers"))
    return render_template("customers/new.html")

@customers_bp.route("/<int:idx>/edit", methods=["GET", "POST"])
@login_required
def edit_customer(idx):
    customers = get_sheet("顧客資料")
    if idx >= len(customers):
        return redirect(url_for("customers.list_customers"))
    customer = customers[idx]
    if request.method == "POST":
        data = {
            "姓名":    request.form.get("name", ""),
            "廠牌型號": request.form.get("model", ""),
            "電話":    request.form.get("phone", ""),
            "地址":    request.form.get("address", ""),
            "安裝日期": request.form.get("install_date", ""),
            "備註":    request.form.get("note", ""),
        }
        update_row("顧客資料", idx, data)
        flash("✅ 客戶資料已更新")
        return redirect(url_for("customers.detail", idx=idx))
    return render_template("customers/edit.html", customer=customer, idx=idx)
