import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from auth import login_required
from db import db, Purchase, Transaction, ACInventory, GiftInventory

purchases_bp = Blueprint("purchases", __name__, url_prefix="/purchases")


def _parse_qty(val):
    try:
        return float(str(val or "0").replace(",", "").strip() or "0")
    except Exception:
        return 0.0


def add_inventory(item_name, item_type, qty):
    if item_type == "ac":
        item = ACInventory.query.filter(ACInventory.spec == item_name).first()
        if item:
            current = _parse_qty(item.actual_qty or item.system_qty)
            item.actual_qty = str(int(current + qty))
            db.session.commit()
            return True
    else:
        item = GiftInventory.query.filter(GiftInventory.name == item_name).first()
        if item:
            current = _parse_qty(item.qty)
            item.qty = str(int(current + qty))
            db.session.commit()
            return True
    return False


@purchases_bp.route("/")
@login_required
def list_purchases():
    purchases = Purchase.query.order_by(Purchase.id.desc()).all()
    return render_template("purchases/list.html", purchases=purchases)


@purchases_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_purchase():
    ac_items = ACInventory.query.order_by(ACInventory.id.asc()).all()
    gift_items = GiftInventory.query.order_by(GiftInventory.id.asc()).all()
    if request.method == "POST":
        f = request.form
        qty = _parse_qty(f.get("quantity", "0"))
        unit_cost = _parse_qty(f.get("unit_cost", "0"))
        total_cost = qty * unit_cost
        purchase = Purchase(
            purchase_date=f.get("purchase_date", datetime.date.today().isoformat()),
            item_name=f.get("item_name", ""),
            item_type=f.get("item_type", "ac"),
            quantity=qty,
            unit_cost=unit_cost,
            total_cost=total_cost,
            supplier=f.get("supplier", ""),
            note=f.get("note", ""),
            status="待確認"
        )
        db.session.add(purchase)
        db.session.commit()
        flash("進貨記錄已建立：{} x {}".format(purchase.item_name, int(qty)))
        return redirect(url_for("purchases.list_purchases"))
    return render_template("purchases/new.html",
                           ac_items=ac_items, gift_items=gift_items,
                           today=datetime.date.today().isoformat())


@purchases_bp.route("/<int:purchase_id>/confirm", methods=["POST"])
@login_required
def confirm_purchase(purchase_id):
    p = db.session.get(Purchase, purchase_id)
    if not p or p.status == "已入庫":
        flash("進貨記錄不存在或已入庫")
        return redirect(url_for("purchases.list_purchases"))
    ok = add_inventory(p.item_name, p.item_type, p.quantity)
    p.status = "已入庫"
    txn = Transaction(
        date=p.purchase_date or datetime.date.today().isoformat(),
        type="expense",
        amount=p.total_cost,
        category="進貨成本",
        description="進貨#{} {} x{}".format(p.id, p.item_name, int(p.quantity)),
        ref_type="purchase",
        ref_id=p.id
    )
    db.session.add(txn)
    db.session.commit()
    if ok:
        flash("已入庫！庫存已更新")
    else:
        flash("已記錄，但找不到對應庫存品項，請手動更新庫存數量")
    return redirect(url_for("purchases.list_purchases"))
