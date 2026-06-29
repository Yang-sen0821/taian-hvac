import datetime
import json
import os
import base64
import uuid as _uuid
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from auth import login_required
from sheets_client import get_sheet, append_row
from config import COMPANY_OPTIONS
from db import db, parse_qty, ALLOWED_COLORS

_COLOR_FIELDS = ("name", "qty", "price", "amount", "note")
_ALLOWED_HEX = set(ALLOWED_COLORS.values())


def _clean_colors(raw):
    """把前端送的顏色 dict 消毒成 JSON 字串：僅留 name/qty/price/amount/note 五欄、
    且值必須是白名單 hex；全空回傳空字串。"""
    if not isinstance(raw, dict):
        return ""
    out = {}
    for f in _COLOR_FIELDS:
        v = (raw.get(f) or "").strip()
        if v in _ALLOWED_HEX:
            out[f] = v
    return json.dumps(out) if out else ""

quotations_bp = Blueprint("quotations", __name__, url_prefix="/quotations")


# 公司抬頭 -> 電子章檔名（空抬頭視為預設「泰安電器水電行」，與列印抬頭預設一致）
_STAMP_FILES = {
    "泰安電器水電行": "stamp_98811221_t.png",
    "泰安冷氣空調有限公司": "stamp_62193072_t.png",
}

# 三項補助選項：出現在品項打字下拉中（取代原備註勾選框）
SUBSIDY_OPTIONS = ["可申請貨物稅補助", "可申請汰舊換新補助", "可申請原廠補助"]

# 備註顏色白名單（#3）：值會直接進 inline style，必須後端驗證避免 CSS 注入（Codex 驗收）
_ALLOWED_NOTE_COLORS = {"", "#d32f2f", "#1565c0", "#2e7d32", "#111111"}


def _safe_note_color(v):
    v = (v or "").strip()
    return v if v in _ALLOWED_NOTE_COLORS else ""


def _stamp_data_uri(company):
    """把對應公司的電子章讀成 base64 data URI 內嵌（離線/列印/截圖都不掉圖）。
    讀不到檔回傳空字串。"""
    eff = (company or "").strip() or "泰安電器水電行"
    fname = _STAMP_FILES.get(eff)
    if not fname:
        return ""
    path = os.path.join(current_app.static_folder, "stamps", fname)
    try:
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        return "data:image/png;base64," + b64
    except OSError:
        return ""

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
                colors=_clean_colors(it.get("colors")),
            )
            group.items.append(item)
        q.groups.append(group)

@quotations_bp.route("/")
@login_required
def list_quotes():
    from db import Quotation, QuotationGroup, QuotationItem
    from sqlalchemy import or_
    quotes = get_sheet("報價單記錄")
    status_filter = request.args.get("status", "")
    subsidy_filter = request.args.get("subsidy", "")   # "" | "all" | "undone"
    if status_filter:
        quotes = [q for q in quotes if q.get("狀態", "") == status_filter]

    # 哪些報價單「含補助品項」：一次 join 查出（避免 N+1，Codex 驗收），再取其 subsidy_done
    sub_q_ids = {r[0] for r in db.session.query(QuotationGroup.quotation_id)
                 .join(QuotationItem, QuotationItem.group_id == QuotationGroup.id)
                 .filter(or_(*[QuotationItem.name.like("%" + opt + "%") for opt in SUBSIDY_OPTIONS]))
                 .distinct().all()}
    sub_done = {}
    if sub_q_ids:
        for qo in Quotation.query.filter(Quotation.id.in_(sub_q_ids)).all():
            sub_done[qo.id] = bool(qo.subsidy_done)
    for q in quotes:
        qid = q.get("id")
        q["_subsidy"] = qid in sub_done
        q["_subsidy_done"] = sub_done.get(qid, False)
    if subsidy_filter == "all":
        quotes = [q for q in quotes if q["_subsidy"]]
    elif subsidy_filter == "undone":
        quotes = [q for q in quotes if q["_subsidy"] and not q["_subsidy_done"]]

    quotes = list(reversed(quotes))
    for i, q in enumerate(quotes):
        q["_idx"] = i
    return render_template("quotations/list.html", quotes=quotes, status_filter=status_filter,
                           subsidy_filter=subsidy_filter,
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
        q.note_color = _safe_note_color(payload.get("note_color"))   # 整單備註顏色（#3，後端白名單）
        # 建立群組與細項，金額由後端權威重算（含稅與否由 payload 決定）
        _build_groups_from_payload(q, payload)
        q.recompute_totals(bool(payload.get("taxable", False)))

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
    sig = _sig_for(quote_id)
    return render_template("quotations/detail.html", q=q, idx=quote_id,
                           stamp_uri=_stamp_data_uri(q.company),
                           sig=sig, sig_date=_tw_time(sig.signed_at) if sig else "")


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
        q.note_color       = _safe_note_color(payload.get("note_color"))   # 整單備註顏色（#3，後端白名單）

        # 先刪掉舊群組（cascade 連帶刪除細項），再依 payload 重建
        q.groups.clear()
        db.session.flush()   # 確保 delete-orphan 先生效，避免新舊 seq 衝突
        _build_groups_from_payload(q, payload)
        q.recompute_totals(bool(payload.get("taxable", False)))

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
    sig = _sig_for(quote_id)
    return render_template("quotations/print.html", q=q, roc_date=roc_date,
                           pdf_filename=_pdf_filename(q),
                           stamp_uri=_stamp_data_uri(q.company),
                           sig=sig, sig_date=_tw_time(sig.signed_at) if sig else "")


def _pdf_filename(q):
    """PDF 預設檔名：「YYYYMMDD-客戶名估價單-公司」。
    瀏覽器列印/儲存 PDF 時取文件 <title> 為預設檔名，故列印頁標題設為此字串。
    例：20260629-蔡小姐（小兒子）估價單-泰安電器水電行
    """
    import re
    s = str(q.quote_date or "").strip().replace("/", "-")
    parts = s.split("-")
    try:
        ymd = f"{int(parts[0]):04d}{int(parts[1]):02d}{int(parts[2]):02d}"
    except (ValueError, IndexError):
        ymd = ""
    name = (q.customer_name or "").strip() or "客戶"
    company = (q.company or "泰安電器水電行").strip()
    base = f"{(ymd + '-') if ymd else ''}{name}估價單-{company}"
    # 移除檔名非法字元（保留中文與全形括號）
    return re.sub(r'[\\/:*?"<>|\r\n\t]', '', base)


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


def _sig_for(quote_id):
    """取報價單目前有效簽名記錄：signed 優先，否則未過期的 pending；無則 None。"""
    from db import QuoteSignature
    signed = (QuoteSignature.query.filter_by(quotation_id=quote_id, status="signed")
              .order_by(QuoteSignature.id.desc()).first())
    if signed:
        return signed
    pending = (QuoteSignature.query.filter_by(quotation_id=quote_id, status="pending")
               .order_by(QuoteSignature.id.desc()).first())
    if pending and not pending.is_expired():
        return pending
    return None


def _tw_time(dt):
    """UTC datetime → 台灣時間字串（簽署日期顯示用）。"""
    if not dt:
        return ""
    return (dt + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")


@quotations_bp.route("/<int:quote_id>/sign-link", methods=["POST"])
@login_required
def create_sign_link(quote_id):
    """產生（或重新產生）客戶簽名連結：7 天有效，重新產生時舊連結即失效。"""
    from db import Quotation, QuoteSignature
    q = db.session.get(Quotation, quote_id)
    if not q:
        flash("找不到該報價單")
        return redirect(url_for("quotations.list_quotes"))
    if QuoteSignature.query.filter_by(quotation_id=quote_id, status="signed").count() > 0:
        flash("此報價單已簽署；如需重簽請先按「作廢簽名」", "warning")
        return redirect(url_for("quotations.detail", quote_id=quote_id))
    for s in QuoteSignature.query.filter_by(quotation_id=quote_id, status="pending").all():
        s.status = "voided"
    sig = QuoteSignature(
        quotation_id=quote_id,
        token=_uuid.uuid4().hex,
        expires_at=datetime.datetime.utcnow() + datetime.timedelta(days=7),
    )
    db.session.add(sig)
    db.session.commit()
    flash("簽名連結已產生（7 天內有效），請複製傳給客戶")
    return redirect(url_for("quotations.detail", quote_id=quote_id))


# 舊 /void-signature 已移除（Codex 驗收）：作廢簽名一律走 /void-and-edit（作廢即退回草稿），
# 避免「只作廢不退回」造成狀態不一致。

@quotations_bp.route("/<int:quote_id>/reopen", methods=["POST"])
@login_required
def reopen_quote(quote_id):
    """已確認/已取消的報價單退回草稿以重新編輯。
    已轉出貨單者擋下（涉及出貨/帳務），提示先到出貨單按「返還報價單」；
    客戶已簽署者擋下（簽的是當下金額），提示先作廢簽名。"""
    from db import Quotation, ShippingOrder, QuoteSignature
    q = db.session.get(Quotation, quote_id)
    if not q:
        flash("找不到該報價單")
        return redirect(url_for("quotations.list_quotes"))
    if q.status not in ("已確認", "已取消"):
        flash("目前狀態（{}）不可返回修改".format(q.status), "warning")
        return redirect(url_for("quotations.detail", quote_id=quote_id))
    if ShippingOrder.query.filter_by(quotation_id=q.id).count() > 0:
        flash("此報價單已轉出貨單，請先到該出貨單按「返還報價單」，返還後即可重新編輯", "warning")
        return redirect(url_for("quotations.detail", quote_id=quote_id))
    if QuoteSignature.query.filter_by(quotation_id=q.id, status="signed").count() > 0:
        flash("此報價單客戶已簽署（簽署即鎖定金額）；如確定要修改，請先按「作廢簽名」再返回修改，修改後需請客戶重簽", "warning")
        return redirect(url_for("quotations.detail", quote_id=quote_id))
    q.status = "草稿"
    db.session.commit()
    flash(f"報價單 {q.quote_number} 已退回草稿，可重新編輯")
    return redirect(url_for("quotations.edit_quote", quote_id=quote_id))


@quotations_bp.route("/<int:quote_id>/void-and-edit", methods=["POST"])
@login_required
def void_and_edit(quote_id):
    """作廢簽名並退回編輯（一鍵，#1）：作廢所有簽名/連結 → 退回草稿 → 進編輯頁（品項自動帶入，
    不需重打）。已轉出貨單者擋下（保護帳務對應）。"""
    from db import Quotation, ShippingOrder, QuoteSignature
    q = db.session.get(Quotation, quote_id)
    if not q:
        flash("找不到該報價單")
        return redirect(url_for("quotations.list_quotes"))
    if ShippingOrder.query.filter_by(quotation_id=q.id).count() > 0:
        flash("此報價單已轉出貨單，請先到該出貨單按「返還報價單」再修改", "warning")
        return redirect(url_for("quotations.detail", quote_id=quote_id))
    if q.status not in ("草稿", "已確認", "已取消"):
        flash("目前狀態（{}）不可退回編輯".format(q.status), "warning")
        return redirect(url_for("quotations.detail", quote_id=quote_id))
    # 前置守衛（Codex 驗收）：必須真的有 pending/signed 簽名才作廢，避免任意單被直接改草稿
    sigs = (QuoteSignature.query.filter_by(quotation_id=quote_id)
            .filter(QuoteSignature.status.in_(("pending", "signed"))).all())
    if not sigs:
        flash("目前沒有可作廢的簽名；如需編輯請用「退回編輯」", "warning")
        return redirect(url_for("quotations.detail", quote_id=quote_id))
    for s in sigs:
        s.status = "voided"
    q.status = "草稿"
    db.session.commit()
    flash("已作廢簽名並退回草稿，原品項已帶入，可直接修改（修改後需請客戶重新簽名）")
    return redirect(url_for("quotations.edit_quote", quote_id=quote_id))


@quotations_bp.route("/delete", methods=["POST"])
@login_required
def delete_quotes():
    from db import Quotation, ShippingOrder, QuoteSignature
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
        # 真刪除：先刪簽名記錄（quote_signatures FK 無 cascade，不先刪 Postgres 擋下 → 500）
        QuoteSignature.query.filter_by(quotation_id=q.id).delete()
        db.session.delete(q)        # 群組/細項由 cascade 連帶刪除
        deleted += 1
    db.session.commit()
    if deleted:
        flash(f"已刪除 {deleted} 筆報價單")
    if blocked:
        flash("下列報價單已轉出貨單，請先到該出貨單按「返還報價單」再刪除：{}".format("、".join(blocked)), "warning")
    return redirect(url_for("quotations.list_quotes"))


@quotations_bp.route("/<int:quote_id>/subsidy-toggle", methods=["POST"])
@login_required
def subsidy_toggle(quote_id):
    """補助清單打勾：切換該報價單補助完成狀態，回 JSON（前端 checkbox 即時存檔，無儲存鈕）。"""
    from db import Quotation
    q = db.session.get(Quotation, quote_id)
    if not q:
        return jsonify({"ok": False, "error": "not found"}), 404
    # 依前端送來的明確布林值設定（非盲反轉，避免雙擊/多分頁/retry 把狀態寫反）— Codex 驗收
    q.subsidy_done = (request.form.get("done", "") == "true")
    db.session.commit()
    return jsonify({"ok": True, "subsidy_done": q.subsidy_done})


@quotations_bp.route("/api/inventory-search")
@login_required
def inventory_search():
    """打字篩選庫存品項，回傳符合的冷氣與贈品（含庫存量）。"""
    q = request.args.get("q", "").strip()
    from db import ACInventory, GiftInventory, Material
    results = []
    # 三項補助選項排最前，確保打「補助」時不被下方 results[:15] 截斷（Codex 驗收）
    for s in SUBSIDY_OPTIONS:
        if not q or q.lower() in s.lower():
            results.append({"name": s, "type": "補助", "stock": ""})
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


# ══ 公開簽名頁（客戶端，免登入，由 app.py 另行註冊） ══════════════
sign_bp = Blueprint("signing", __name__, url_prefix="/sign")


@sign_bp.route("/<token>", methods=["GET", "POST"])
def sign_page(token):
    """客戶簽名頁：以 token 開啟合約版全文，底部簽名板。

    GET  pending → 合約 + 簽名板；signed → 完整簽署憑證畫面（提示截圖）
    POST 接收簽名 data URI → 存檔、記時間與 IP、報價單鎖定為「已確認」
    無效/過期/作廢 token → 404 友善頁
    """
    from db import Quotation, QuoteSignature
    sig = QuoteSignature.query.filter_by(token=token).first()
    if not sig or sig.status == "voided" or sig.is_expired():
        return render_template("quotations/sign_invalid.html"), 404
    q = db.session.get(Quotation, sig.quotation_id)
    if not q:
        return render_template("quotations/sign_invalid.html"), 404

    if request.method == "POST" and sig.status == "pending":
        data = request.form.get("signature", "")
        valid = data.startswith("data:image/png;base64,") and len(data) <= 800_000
        if valid:
            try:
                base64.b64decode(data.split(",", 1)[1], validate=True)
            except Exception:
                valid = False
        if not valid:
            # 資料異常（空簽名由前端擋）：回到簽名頁重試
            return redirect(url_for("signing.sign_page", token=token))
        sig.signature_png = data
        sig.status = "signed"
        sig.signed_at = datetime.datetime.utcnow()
        fwd = request.headers.get("X-Forwarded-For", "")
        sig.signer_ip = (fwd.split(",")[0].strip() if fwd else (request.remote_addr or ""))[:64]
        q.status = "已確認"   # 簽署即鎖單：未作廢簽名前不可返回修改
        db.session.commit()
        return redirect(url_for("signing.sign_page", token=token))

    mode = "signed" if sig.status == "signed" else "sign"
    return render_template("quotations/print.html", q=q,
                           roc_date=_to_roc_date(q.quote_date),
                           stamp_uri=_stamp_data_uri(q.company),
                           sig=sig, sig_date=_tw_time(sig.signed_at),
                           sign_mode=mode, sign_token=token)
