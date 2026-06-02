from flask import Blueprint, render_template, request, redirect, url_for, flash
from auth import login_required
from sheets_client import get_sheet, update_row
from config import LOW_STOCK_THRESHOLD

inventory_bp = Blueprint("inventory", __name__, url_prefix="/inventory")

def parse_qty(val):
    try:
        return int(str(val or "0").replace(",", "").strip() or "0")
    except:
        return 0

@inventory_bp.route("/ac")
@login_required
def ac_list():
    items = get_sheet("冷氣庫存")
    q = request.args.get("q", "").strip()
    for i, item in enumerate(items):
        qty = parse_qty(item.get("實際庫存") or item.get("庫存數量"))
        item["_qty"] = qty
        item["_low"] = qty <= LOW_STOCK_THRESHOLD
        item["_idx"] = i
    if q:
        items = [it for it in items if q in str(it.get("廠牌型號規格", ""))]
    low_count = sum(1 for it in get_sheet("冷氣庫存") if parse_qty(it.get("實際庫存") or it.get("庫存數量")) <= LOW_STOCK_THRESHOLD)
    return render_template("inventory/ac.html", items=items, low_count=low_count, q=q)

@inventory_bp.route("/ac/<int:idx>/edit", methods=["GET", "POST"])
@login_required
def ac_edit(idx):
    items = get_sheet("冷氣庫存")
    if idx >= len(items):
        return redirect(url_for("inventory.ac_list"))
    item = dict(items[idx])
    if request.method == "POST":
        item["實際庫存"] = request.form.get("qty", "")
        item["備註"] = request.form.get("note", "")
        update_row("冷氣庫存", idx, item)
        flash(f"✅ 庫存已更新：{item.get('廠牌型號規格','')}")
        return redirect(url_for("inventory.ac_list"))
    return render_template("inventory/ac_edit.html", item=item, idx=idx)

@inventory_bp.route("/gifts")
@login_required
def gift_list():
    items = get_sheet("贈品庫存")
    for i, item in enumerate(items):
        qty = parse_qty(item.get("庫存數量"))
        item["_qty"] = qty
        item["_low"] = qty <= LOW_STOCK_THRESHOLD
        item["_idx"] = i
    low_count = sum(1 for it in items if it["_low"])
    return render_template("inventory/gifts.html", items=items, low_count=low_count)

@inventory_bp.route("/gifts/<int:idx>/edit", methods=["GET", "POST"])
@login_required
def gift_edit(idx):
    items = get_sheet("贈品庫存")
    if idx >= len(items):
        return redirect(url_for("inventory.gift_list"))
    item = dict(items[idx])
    if request.method == "POST":
        item["庫存數量"] = request.form.get("qty", "")
        item["備註"] = request.form.get("note", "")
        update_row("贈品庫存", idx, item)
        flash(f"✅ 庫存已更新：{item.get('名稱','')}")
        return redirect(url_for("inventory.gift_list"))
    return render_template("inventory/gift_edit.html", item=item, idx=idx)


@inventory_bp.route("/ac/new", methods=["GET", "POST"])
@login_required
def ac_new():
    from db import db as _db, ACInventory
    if request.method == "POST":
        item = ACInventory(
            spec=request.form.get("spec", ""),
            system_qty=request.form.get("system_qty", "0"),
            actual_qty=request.form.get("actual_qty", "0"),
            note=request.form.get("note", "")
        )
        _db.session.add(item)
        _db.session.commit()
        flash("冷氣品項「{}」已新增".format(item.spec))
        return redirect(url_for("inventory.ac_list"))
    return render_template("inventory/ac_new.html")


@inventory_bp.route("/gifts/new", methods=["GET", "POST"])
@login_required
def gift_new():
    from db import db as _db, GiftInventory
    if request.method == "POST":
        item = GiftInventory(
            name=request.form.get("name", ""),
            qty=request.form.get("qty", "0"),
            note=request.form.get("note", "")
        )
        _db.session.add(item)
        _db.session.commit()
        flash("贈品「{}」已新增".format(item.name))
        return redirect(url_for("inventory.gift_list"))
    return render_template("inventory/gift_new.html")
