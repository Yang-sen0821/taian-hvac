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

@inventory_bp.route("/ac/<int:item_id>/edit", methods=["GET", "POST"])
@login_required
def ac_edit(item_id):
    # 以資料庫 id 直接定位（原以位置索引定位，與模板的 item.id 不一致，
    # 導致更新到錯誤列或未更新——姵回報「編輯完數字不會變」的根因）
    from db import db as _db, ACInventory
    item = _db.session.get(ACInventory, item_id)
    if not item:
        flash("找不到該庫存品項", "warning")
        return redirect(url_for("inventory.ac_list"))
    if request.method == "POST":
        item.actual_qty = request.form.get("qty", "")
        item.note = request.form.get("note", "")
        _db.session.commit()
        flash(f"✅ 庫存已更新：{item.spec}")
        return redirect(url_for("inventory.ac_list"))
    return render_template("inventory/ac_edit.html", item=item)

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

@inventory_bp.route("/gifts/<int:item_id>/edit", methods=["GET", "POST"])
@login_required
def gift_edit(item_id):
    # 同 ac_edit：以 id 定位，修正模板 item.id 與位置索引不一致的問題
    from db import db as _db, GiftInventory
    item = _db.session.get(GiftInventory, item_id)
    if not item:
        flash("找不到該贈品品項", "warning")
        return redirect(url_for("inventory.gift_list"))
    if request.method == "POST":
        item.qty = request.form.get("qty", "")
        item.note = request.form.get("note", "")
        _db.session.commit()
        flash(f"✅ 庫存已更新：{item.name}")
        return redirect(url_for("inventory.gift_list"))
    return render_template("inventory/gift_edit.html", item=item)


@inventory_bp.route("/ac/new", methods=["GET", "POST"])
@login_required
def ac_new():
    from db import db as _db, ACInventory
    if request.method == "POST":
        qty = request.form.get("qty", "0")
        item = ACInventory(
            spec=request.form.get("spec", ""),
            system_qty=qty,      # 帳面與實際同步建立，UI 僅呈現單一庫存數
            actual_qty=qty,
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


# ===== 材料庫存（比照贈品，純新增，不影響冷氣/贈品流程） =====

@inventory_bp.route("/materials")
@login_required
def material_list():
    items = get_sheet("材料庫存")
    q = request.args.get("q", "").strip()
    for i, item in enumerate(items):
        qty = parse_qty(item.get("庫存數量"))
        item["_qty"] = qty
        item["_low"] = qty <= LOW_STOCK_THRESHOLD
        item["_idx"] = i
    if q:
        items = [it for it in items if q in str(it.get("名稱", ""))]
    low_count = sum(1 for it in get_sheet("材料庫存") if parse_qty(it.get("庫存數量")) <= LOW_STOCK_THRESHOLD)
    return render_template("inventory/materials.html", items=items, low_count=low_count, q=q)


@inventory_bp.route("/materials/new", methods=["GET", "POST"])
@login_required
def material_new():
    from db import db as _db, Material
    if request.method == "POST":
        item = Material(
            name=request.form.get("name", ""),
            qty=request.form.get("qty", "0"),
            note=request.form.get("note", "")
        )
        _db.session.add(item)
        _db.session.commit()
        flash("材料「{}」已新增".format(item.name))
        return redirect(url_for("inventory.material_list"))
    return render_template("inventory/material_new.html")


@inventory_bp.route("/materials/<int:idx>/edit", methods=["GET", "POST"])
@login_required
def material_edit(idx):
    items = get_sheet("材料庫存")
    if idx >= len(items):
        return redirect(url_for("inventory.material_list"))
    item = dict(items[idx])
    if request.method == "POST":
        new_name = request.form.get("name", "").strip()
        if new_name:                      # 空白不覆蓋，避免誤清品名
            item["名稱"] = new_name
        item["庫存數量"] = request.form.get("qty", "")
        item["備註"] = request.form.get("note", "")
        update_row("材料庫存", idx, item)
        flash(f"✅ 庫存已更新：{item.get('名稱','')}")
        return redirect(url_for("inventory.material_list"))
    return render_template("inventory/material_edit.html", item=item, idx=idx)
