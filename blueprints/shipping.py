import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from auth import login_required
from db import db, ShippingOrder, Transaction, ACInventory, GiftInventory, Quotation

shipping_bp = Blueprint("shipping", __name__, url_prefix="/shipping")


def _parse_qty(val):
    try:
        return float(str(val or "0").replace(",", "").strip() or "0")
    except Exception:
        return 0.0


def deduct_inventory(item_name, qty):
    if not item_name or qty <= 0:
        return True
    ac = ACInventory.query.filter(ACInventory.spec == item_name).first()
    if ac:
        current = _parse_qty(ac.actual_qty or ac.system_qty)
        ac.actual_qty = str(max(0, int(current - qty)))
        return True
    gift = GiftInventory.query.filter(GiftInventory.name == item_name).first()
    if gift:
        current = _parse_qty(gift.qty)
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
        order = ShippingOrder(
            quotation_id=quotation_id,
            quote_number=q.quote_number,
            customer_name=q.customer_name,
            company=q.company,
            ship_date=request.form.get("ship_date", datetime.date.today().isoformat()),
            note=request.form.get("note", ""),
            item1_name=q.item1_name, item1_qty=q.item1_qty, item1_price=q.item1_price,
            item2_name=q.item2_name, item2_qty=q.item2_qty, item2_price=q.item2_price,
            item3_name=q.item3_name, item3_qty=q.item3_qty, item3_price=q.item3_price,
            engineering=q.engineering, other=q.other,
            pretax=q.pretax, tax=q.tax, total=q.total,
            status="待出貨"
        )
        db.session.add(order)
        q.status = "已確認"
        db.session.commit()
        flash("出貨單已建立，報價單狀態更新為「已確認」")
        return redirect(url_for("shipping.detail_shipping", order_id=order.id))
    return render_template("shipping/new.html", quote=q,
                           today=datetime.date.today().isoformat())


@shipping_bp.route("/<int:order_id>")
@login_required
def detail_shipping(order_id):
    order = db.session.get(ShippingOrder, order_id)
    if not order:
        return redirect(url_for("shipping.list_shipping"))
    return render_template("shipping/detail.html", order=order)


@shipping_bp.route("/<int:order_id>/confirm", methods=["POST"])
@login_required
def confirm_shipping(order_id):
    order = db.session.get(ShippingOrder, order_id)
    if not order or order.status == "已出貨":
        flash("出貨單不存在或已出貨")
        return redirect(url_for("shipping.list_shipping"))
    failed_items = []
    for name, qty in [(order.item1_name, order.item1_qty),
                      (order.item2_name, order.item2_qty),
                      (order.item3_name, order.item3_qty)]:
        if name and qty:
            if not deduct_inventory(name, qty):
                failed_items.append(name)
    order.status = "已出貨"
    if not order.ship_date:
        order.ship_date = datetime.date.today().isoformat()
    txn = Transaction(
        date=order.ship_date,
        type="income",
        amount=order.total,
        category="銷售收入",
        description="出貨單#{} {} {}".format(order.id, order.quote_number, order.customer_name),
        ref_type="shipping_order",
        ref_id=order.id
    )
    db.session.add(txn)
    db.session.commit()
    total_fmt = "{:,.0f}".format(order.total)
    flash("出貨確認完成！庫存已扣減，收入 NT${} 已記帳".format(total_fmt))
    if failed_items:
        flash("⚠️ 下列品項在庫存中找不到完全相符的名稱，未扣減庫存，請至庫存頁手動調整：{}".format("、".join(failed_items)))
    return redirect(url_for("shipping.detail_shipping", order_id=order_id))
