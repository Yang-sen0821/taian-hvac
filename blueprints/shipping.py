import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from auth import login_required
from db import db, ShippingOrder, ShippingItem, Transaction, ACInventory, GiftInventory, Quotation, parse_qty

shipping_bp = Blueprint("shipping", __name__, url_prefix="/shipping")


def deduct_inventory(item_name, qty):
    """依品名比對 ACInventory.spec 或 GiftInventory.name 扣減庫存。
    找到並扣減成功回傳 True；找不到完全相符名稱回傳 False。"""
    if not item_name or qty <= 0:
        return True
    ac = ACInventory.query.filter(ACInventory.spec == item_name).first()
    if ac:
        try:
            current = float(str(ac.actual_qty or ac.system_qty or "0").replace(",", "").strip() or "0")
        except (TypeError, ValueError):
            current = 0.0
        ac.actual_qty = str(max(0, int(current - qty)))
        return True
    gift = GiftInventory.query.filter(GiftInventory.name == item_name).first()
    if gift:
        try:
            current = float(str(gift.qty or "0").replace(",", "").strip() or "0")
        except (TypeError, ValueError):
            current = 0.0
        gift.qty = str(max(0, int(current - qty)))
        return True
    return False


@shipping_bp.route("/")
@login_required
def list_shipping():
    from flask import request as req
    status_filter = req.args.get("status", "")
    orders = ShippingOrder.query.order_by(ShippingOrder.id.desc()).all()
    return render_template("shipping/list.html", orders=orders, status_filter=status_filter)


@shipping_bp.route("/new/<int:quotation_id>", methods=["GET", "POST"])
@login_required
def new_shipping(quotation_id):
    q = db.session.get(Quotation, quotation_id)
    if not q:
        flash("找不到報價單")
        return redirect(url_for("quotations.list_quotes"))
    if request.method == "POST":
        # 建立出貨單主記錄
        order = ShippingOrder(
            quotation_id=quotation_id,
            quote_number=q.quote_number,
            customer_name=q.customer_name,
            company=q.company,
            ship_date=request.form.get("ship_date", datetime.date.today().isoformat()),
            note=request.form.get("note", ""),
            status="待出貨",
        )
        db.session.add(order)
        db.session.flush()  # 讓 order.id 可用，才能建立 ShippingItem FK

        # 攤平所有群組品項為 ShippingItem（快照）
        seq = 0
        total_amount = 0.0
        for group in q.groups:
            for item in group.items:
                qty_num = parse_qty(item.qty_text)
                si = ShippingItem(
                    shipping_order_id=order.id,
                    seq=seq,
                    group_title=group.title or "",
                    name=item.name or "",
                    qty_text=item.qty_text or "",
                    qty_num=qty_num,
                    unit_price=item.unit_price or 0,
                    amount=item.amount or 0,
                    note=item.note or "",
                    is_gift=bool(item.is_gift),
                )
                db.session.add(si)
                total_amount += si.amount
                seq += 1

        # 出貨單總金額 = 所有品項 amount 之和（含稅，沿用報價單總計）
        order.total = q.total if q.total else total_amount
        # pretax/tax 也沿用報價單
        order.pretax = q.pretax or 0
        order.tax = q.tax or 0

        # 報價單狀態改為已確認
        q.status = "已確認"
        db.session.commit()
        flash("出貨單已建立，報價單狀態更新為「已確認」")
        return redirect(url_for("shipping.detail_shipping", order_id=order.id))

    # GET：把攤平後品項清單預先組好，依 group_title 分組傳給模板預覽
    preview_groups = []
    for group in q.groups:
        preview_groups.append({
            "title": group.title or "（無標題）",
            "items": group.items,
        })
    return render_template("shipping/new.html", quote=q,
                           preview_groups=preview_groups,
                           today=datetime.date.today().isoformat())


@shipping_bp.route("/<int:order_id>")
@login_required
def detail_shipping(order_id):
    order = db.session.get(ShippingOrder, order_id)
    if not order:
        return redirect(url_for("shipping.list_shipping"))
    # 依 group_title 分組後傳給模板
    grouped = _group_items(order.items)
    return render_template("shipping/detail.html", order=order, grouped=grouped)


def _group_items(items):
    """把 ShippingItem 清單依 group_title 分組，保留原始出現順序。
    回傳 list of dict: [{"title": str, "items": [ShippingItem]}]"""
    seen = {}   # title -> index in result
    result = []
    for item in items:
        title = item.group_title or "（無標題）"
        if title not in seen:
            seen[title] = len(result)
            result.append({"title": title, "items": []})
        result[seen[title]]["items"].append(item)
    return result


@shipping_bp.route("/<int:order_id>/confirm", methods=["POST"])
@login_required
def confirm_shipping(order_id):
    order = db.session.get(ShippingOrder, order_id)
    if not order or order.status == "已出貨":
        flash("出貨單不存在或已出貨")
        return redirect(url_for("shipping.list_shipping"))

    # 扣庫存：只處理 is_gift=False 且 qty_num > 0 的品項
    failed_items = []
    for si in order.items:
        if not si.is_gift and si.qty_num > 0:
            if not deduct_inventory(si.name, si.qty_num):
                failed_items.append(si.name)

    order.status = "已出貨"
    if not order.ship_date:
        order.ship_date = datetime.date.today().isoformat()

    # 自動入帳：金額使用出貨單 total
    txn = Transaction(
        date=order.ship_date,
        type="income",
        amount=order.total,
        category="銷售收入",
        description="出貨單#{} {} {}".format(order.id, order.quote_number, order.customer_name),
        ref_type="shipping_order",
        ref_id=order.id,
    )
    db.session.add(txn)
    db.session.commit()

    total_fmt = "{:,.0f}".format(order.total)
    flash("出貨確認完成！庫存已扣減，收入 NT${} 已記帳".format(total_fmt))
    if failed_items:
        flash("⚠️ 下列品項在庫存中找不到完全相符的名稱，未扣減庫存，請至庫存頁手動調整：{}".format("、".join(failed_items)), "warning")
    return redirect(url_for("shipping.detail_shipping", order_id=order_id))


@shipping_bp.route("/<int:order_id>/revert", methods=["POST"])
@login_required
def revert_shipping(order_id):
    """返還出貨單：僅限【待出貨】（尚未扣庫存）的單可操作，刪除出貨單並將報價單狀態改回草稿。"""
    order = db.session.get(ShippingOrder, order_id)
    if not order or order.status != "待出貨":
        flash("僅待出貨的出貨單可返還")
        if order:
            return redirect(url_for("shipping.detail_shipping", order_id=order_id))
        return redirect(url_for("shipping.list_shipping"))

    quotation_id = order.quotation_id
    # 把對應報價單狀態改回草稿，讓業務可重新編輯
    quote = db.session.get(Quotation, quotation_id)
    if quote:
        quote.status = "草稿"

    db.session.delete(order)
    db.session.commit()
    flash("已返還為報價單草稿，可重新編輯")
    return redirect(url_for("quotations.detail", quote_id=quotation_id))
