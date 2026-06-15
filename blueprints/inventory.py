from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from auth import login_required
from sheets_client import get_sheet, update_row
from config import LOW_STOCK_THRESHOLD

inventory_bp = Blueprint("inventory", __name__, url_prefix="/inventory")

def parse_qty(val):
    try:
        return int(str(val or "0").replace(",", "").strip() or "0")
    except:
        return 0


def _sorted_by_order(items):
    """依 sort_order（拖拉順序）排序，sort_order 相同再依 id。"""
    return sorted(items, key=lambda x: (x.get("sort_order") or 0, x.get("id") or 0))


def _next_sort_order(model):
    """新品項的 sort_order = 目前最大值 + 1，排到清單最後。"""
    from db import db as _db
    current = _db.session.query(_db.func.max(model.sort_order)).scalar()
    return (current or 0) + 1


def _reorder(model):
    """接收 {order: [id, id, ...]}，依序寫入 sort_order=0,1,2...。"""
    from db import db as _db
    data = request.get_json(silent=True) or {}
    ids = data.get("order", [])
    for idx, raw_id in enumerate(ids):
        try:
            obj = _db.session.get(model, int(raw_id))
        except (ValueError, TypeError):
            obj = None
        if obj:
            obj.sort_order = idx
    _db.session.commit()
    return jsonify({"ok": True, "count": len(ids)})

@inventory_bp.route("/ac")
@login_required
def ac_list():
    items = _sorted_by_order(get_sheet("冷氣庫存"))
    q = request.args.get("q", "").strip()
    low_count = 0
    for i, item in enumerate(items):
        qty = parse_qty(item.get("實際庫存") or item.get("庫存數量"))
        item["_qty"] = qty
        item["_low"] = qty <= LOW_STOCK_THRESHOLD
        item["_idx"] = i
        if item["_low"]:
            low_count += 1
    if q:
        items = [it for it in items if q in str(it.get("廠牌型號規格", ""))]
    return render_template("inventory/ac.html", items=items, low_count=low_count, q=q)


@inventory_bp.route("/ac/reorder", methods=["POST"])
@login_required
def ac_reorder():
    from db import ACInventory
    return _reorder(ACInventory)

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
    items = _sorted_by_order(get_sheet("贈品庫存"))
    for i, item in enumerate(items):
        qty = parse_qty(item.get("庫存數量"))
        item["_qty"] = qty
        item["_low"] = qty <= LOW_STOCK_THRESHOLD
        item["_idx"] = i
    low_count = sum(1 for it in items if it["_low"])
    return render_template("inventory/gifts.html", items=items, low_count=low_count)


@inventory_bp.route("/gifts/reorder", methods=["POST"])
@login_required
def gift_reorder():
    from db import GiftInventory
    return _reorder(GiftInventory)

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
            note=request.form.get("note", ""),
            sort_order=_next_sort_order(ACInventory),
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
            note=request.form.get("note", ""),
            sort_order=_next_sort_order(GiftInventory),
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
    all_items = get_sheet("材料庫存")
    low_count = sum(1 for it in all_items if parse_qty(it.get("庫存數量")) <= LOW_STOCK_THRESHOLD)
    # 依手動拖拉順序排序
    items = _sorted_by_order(all_items)
    q = request.args.get("q", "").strip()
    for item in items:
        qty = parse_qty(item.get("庫存數量"))
        item["_qty"] = qty
        item["_low"] = qty <= LOW_STOCK_THRESHOLD
    if q:
        items = [it for it in items if q in str(it.get("名稱", ""))]
    return render_template("inventory/materials.html", items=items, low_count=low_count, q=q)


@inventory_bp.route("/materials/reorder", methods=["POST"])
@login_required
def material_reorder():
    from db import Material
    return _reorder(Material)


@inventory_bp.route("/materials/new", methods=["GET", "POST"])
@login_required
def material_new():
    from db import db as _db, Material
    if request.method == "POST":
        item = Material(
            name=request.form.get("name", ""),
            qty=request.form.get("qty", "0"),
            note=request.form.get("note", ""),
            sort_order=_next_sort_order(Material),
        )
        _db.session.add(item)
        _db.session.commit()
        flash("材料「{}」已新增".format(item.name))
        return redirect(url_for("inventory.material_list"))
    return render_template("inventory/material_new.html")


@inventory_bp.route("/materials/<int:item_id>/edit", methods=["GET", "POST"])
@login_required
def material_edit(item_id):
    from db import db as _db, Material
    item = _db.session.get(Material, item_id)
    if not item:
        flash("找不到該材料品項", "warning")
        return redirect(url_for("inventory.material_list"))
    if request.method == "POST":
        new_name = request.form.get("name", "").strip()
        if new_name:
            item.name = new_name
        item.qty = request.form.get("qty", "")
        item.note = request.form.get("note", "")
        _db.session.commit()
        flash(f"✅ 庫存已更新：{item.name}")
        return redirect(url_for("inventory.material_list"))
    return render_template("inventory/material_edit.html", item=item.to_sheet_dict(), item_id=item_id)


@inventory_bp.route("/materials/<int:item_id>/delete", methods=["POST"])
@login_required
def material_delete(item_id):
    from db import db as _db, Material
    item = _db.session.get(Material, item_id)
    if not item:
        flash("找不到該材料品項", "warning")
        return redirect(url_for("inventory.material_list"))
    name = item.name
    _db.session.delete(item)
    _db.session.commit()
    flash(f"已刪除材料品項「{name}」")
    return redirect(url_for("inventory.material_list"))
