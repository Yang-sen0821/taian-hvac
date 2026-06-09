import datetime
import json
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from auth import login_required
from sheets_client import get_sheet, append_row
from config import COMPANY_OPTIONS
from db import db, parse_qty

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


def _build_groups_from_payload(q, payload):
    """依 payload 的 groups 結構，為報價單 q 建立 QuotationGroup + QuotationItem。

    後端權威：金額一律由 model 的 compute_amount / recompute_totals 重算，
    前端送的 amount 僅在「數量為非數字文字（如乙式）」時才被採用。
    呼叫前 q 的 groups 應已清空（或為新建未 append）。
    """
    from db import QuotationGroup, QuotationItem
    groups = payload.get("groups") or []
    for gi, g in enumerate(groups):
        title = (g.get("title") or "").strip()
        items = g.get("items") or []
        # 標題與品項皆空的群組略過，避免存入空群組
        if not title and not items:
            continue
        group = QuotationGroup(
            seq=gi,
            title=title,
            note=(g.get("note") or "").strip(),
        )
        for ii, it in enumerate(items):
            name = (it.get("name") or "").strip()
            qty_text = str(it.get("qty_text") or "").strip()
            # 名稱與數量皆空 → 視為空白列，略過
            if not name and not qty_text:
                continue
            item = QuotationItem(
                seq=ii,
                name=name,
                qty_text=qty_text,
                unit_price=safe_float(it.get("unit_price")),
                amount=safe_float(it.get("amount")),   # 僅在數量為文字時會被採用
                note=(it.get("note") or "").strip(),
                is_gift=bool(it.get("is_gift")),
            )
            group.items.append(item)
        q.groups.append(group)

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
        from db import Quotation
        # 第二段：前端動態表單序列化成 hidden input name="payload" 的 JSON
        try:
            payload = json.loads(request.form.get("payload", "") or "{}")
        except (ValueError, TypeError):
            flash("❌ 報價單資料格式錯誤，請重新送出")
            return redirect(url_for("quotations.new_quote"))

        company = (payload.get("company") or "").strip()
        tax_id = next((c["tax_id"] for c in COMPANY_OPTIONS if c["name"] == company), "")

        q = Quotation(
            quote_number=next_quote_number(),
            quote_date=(payload.get("quote_date") or datetime.date.today().isoformat()),
            company=company,
            tax_id=tax_id,
            customer_name=(payload.get("customer_name") or "").strip(),
            customer_phone=(payload.get("customer_phone") or "").strip(),
            customer_address=(payload.get("customer_address") or "").strip(),
            install_date=(payload.get("install_date") or "").strip(),
            note=(payload.get("note") or "").strip(),
            status="草稿",
        )
        # 建立群組與細項，金額由後端權威重算
        _build_groups_from_payload(q, payload)
        q.recompute_totals()

        db.session.add(q)
        db.session.commit()
        flash(f"✅ 報價單 {q.quote_number} 已建立，含稅總金額 NT${q.total:,.0f}")
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


@quotations_bp.route("/<int:quote_id>/edit", methods=["GET", "POST"])
@login_required
def edit_quote(quote_id):
    """草稿報價單編輯 — 僅 status == '草稿' 可進入。"""
    from db import Quotation
    q = db.session.get(Quotation, quote_id)
    if not q:
        flash("找不到該報價單")
        return redirect(url_for("quotations.list_quotes"))

    if q.status != "草稿":
        flash("僅草稿可編輯")
        return redirect(url_for("quotations.detail", quote_id=quote_id))

    if request.method == "POST":
        # 第二段：同樣解析 payload JSON
        try:
            payload = json.loads(request.form.get("payload", "") or "{}")
        except (ValueError, TypeError):
            flash("❌ 報價單資料格式錯誤，請重新送出")
            return redirect(url_for("quotations.edit_quote", quote_id=quote_id))

        # 公司抬頭與統編
        company = (payload.get("company") or "").strip()
        tax_id = next((c["tax_id"] for c in COMPANY_OPTIONS if c["name"] == company), "")

        # 更新報價單表頭欄位
        q.company          = company
        q.tax_id           = tax_id
        q.quote_date       = (payload.get("quote_date") or q.quote_date)
        q.customer_name    = (payload.get("customer_name") or "").strip()
        q.customer_phone   = (payload.get("customer_phone") or "").strip()
        q.customer_address = (payload.get("customer_address") or "").strip()
        q.install_date     = (payload.get("install_date") or "").strip()
        q.note             = (payload.get("note") or "").strip()

        # 先刪掉舊群組（cascade 連帶刪除細項），再依 payload 重建
        q.groups.clear()
        db.session.flush()   # 確保 delete-orphan 先生效，避免新舊 seq 衝突
        _build_groups_from_payload(q, payload)
        q.recompute_totals()

        # 狀態：允許在草稿編輯頁直接定案（例如改為「已確認」）；僅接受合法值
        new_status = (payload.get("status") or "").strip()
        if new_status in ("草稿", "已確認", "已完成", "已取消"):
            q.status = new_status

        db.session.commit()
        flash(f"✅ 報價單 {q.quote_number} 已更新，含稅總金額 NT${q.total:,.0f}")
        return redirect(url_for("quotations.detail", quote_id=quote_id))

    # GET：提供下拉選單資料（比照 new_quote）
    customers  = get_sheet("顧客資料")
    ac_items   = get_sheet("冷氣庫存")
    gift_items = get_sheet("贈品庫存")
    return render_template("quotations/edit.html",
        q=q, customers=customers, ac_items=ac_items,
        gift_items=gift_items, companies=COMPANY_OPTIONS)


@quotations_bp.route("/<int:quote_id>/print")
@login_required
def print_quote(quote_id):
    """報價單列印版（合約＋藍章＋簽名框）。"""
    from db import Quotation
    q = db.session.get(Quotation, quote_id)
    if not q:
        flash("找不到該報價單")
        return redirect(url_for("quotations.list_quotes"))
    # 報價日期轉民國年（格式「民國 NNN/M/D」）；解析失敗則回傳原字串
    roc_date = _to_roc_date(q.quote_date)
    return render_template("quotations/print.html", q=q, roc_date=roc_date)


def _to_roc_date(date_str):
    """把西元日期字串（YYYY-MM-DD 或 YYYY/M/D）轉成「民國 NNN/M/D」。

    無法解析時回傳原字串（避免列印頁出錯）。
    """
    if not date_str:
        return ""
    s = str(date_str).strip().replace("/", "-")
    parts = s.split("-")
    try:
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        return f"民國 {y - 1911}/{m}/{d}"
    except (ValueError, IndexError):
        return str(date_str)


@quotations_bp.route("/delete", methods=["POST"])
@login_required
def delete_quotes():
    from db import Quotation, ShippingOrder
    ids = request.form.getlist("quote_ids")
    deleted = 0
    blocked = []   # 已轉出貨單、不可直接刪除的報價單號
    for qid in ids:
        try:
            q = db.session.get(Quotation, int(qid))
        except (ValueError, TypeError):
            q = None
        if not q:
            continue
        # 報價單若已轉出貨單，外鍵會擋下刪除（且涉及出貨/帳務），改提醒先返還
        if ShippingOrder.query.filter_by(quotation_id=q.id).count() > 0:
            blocked.append(q.quote_number or f"#{q.id}")
            continue
        db.session.delete(q)        # 群組/細項由 cascade 連帶刪除
        deleted += 1
    db.session.commit()
    if deleted:
        flash(f"已刪除 {deleted} 筆報價單")
    if blocked:
        flash("下列報價單已轉出貨單，請先到該出貨單按「返還報價單」再刪除：{}".format("、".join(blocked)), "warning")
    return redirect(url_for("quotations.list_quotes"))


@quotations_bp.route("/api/inventory-search")
@login_required
def inventory_search():
    """打字篩選庫存品項，回傳符合的冷氣與贈品（含庫存量）。"""
    q = request.args.get("q", "").strip()
    from db import ACInventory, GiftInventory, Material
    results = []
    for item in ACInventory.query.all():
        name = item.spec or ""
        if not q or q.lower() in name.lower():
            stock = item.actual_qty or item.system_qty or "0"
            results.append({"name": name, "type": "冷氣", "stock": stock})
    for item in GiftInventory.query.all():
        name = item.name or ""
        if not q or q.lower() in name.lower():
            results.append({"name": name, "type": "贈品", "stock": item.qty or "0"})
    # 材料庫存為新表，表尚未建立時不可拖垮整支搜尋（冷氣/贈品仍須正常）
    try:
        for item in Material.query.all():
            name = item.name or ""
            if not q or q.lower() in name.lower():
                results.append({"name": name, "type": "材料", "stock": item.qty or "0"})
    except Exception:
        db.session.rollback()
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
    # 第二段：改查 QuotationItem 歷史單價（依品名比對），不再查舊 item1~3 欄位
    from db import QuotationItem, QuotationGroup, Quotation as Q
    results = []
    seen = set()
    # 依細項 id 由新到舊，join 回報價單取報價日期
    rows = (
        db.session.query(QuotationItem, Q.quote_date)
        .join(QuotationGroup, QuotationItem.group_id == QuotationGroup.id)
        .join(Q, QuotationGroup.quotation_id == Q.id)
        .filter(QuotationItem.name == item_name)
        .order_by(QuotationItem.id.desc())
        .limit(100)
        .all()
    )
    for item, quote_date in rows:
        price = item.unit_price or 0
        if price and price not in seen:
            seen.add(price)
            results.append({"price": price, "date": quote_date or ""})
        if len(results) >= 5:
            break
    return jsonify(results)
