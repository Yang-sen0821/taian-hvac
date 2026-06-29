"""管材估算工具（takeoff）blueprint。

功能：上傳 CAD 圖面（JPG/PNG，PDF 由前端 PDF.js 逐頁渲染成圖上傳）→ 校準比例
→ 分色畫管線 → 自動算每種管材公尺數與不同管徑轉接頭 → 多圖總表 → 匯入/建立報價單。

設計重點（Cerberus 雙頭設計審查）：
- 圖檔存 DB（takeoff_images bytea）避開 Render ephemeral FS；與 metadata 分表。
- 長度與轉接頭一律由「後端從幾何 JSON 重算」為權威，前端數字只作即時顯示。
- 轉接頭只在「共用同一節點」且該節點交會不同管材時計，不因視覺交叉誤判。
"""

import json
import math
import re

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _safe_color(c):
    """只接受 #RRGGBB；否則回預設灰，避免 style/CSS 注入。"""
    c = str(c or "").strip()
    return c if _HEX_RE.match(c) else "#666666"

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, jsonify, Response, abort)
from auth import login_required
from db import db, round_half_up

takeoff_bp = Blueprint("takeoff", __name__, url_prefix="/takeoff")

# ---- 限制（防 DB 膨脹 / 濫用）----
MAX_SHEETS_PER_PROJECT = 40        # 單專案最多圖面數
MAX_IMAGE_BYTES = 12 * 1024 * 1024  # 單張圖最大 12MB（與 app MAX_CONTENT_LENGTH 對齊）
ALLOWED_IMAGE_MIME = {"image/png", "image/jpeg", "image/jpg"}
DEFAULT_PIPE_TYPES = [
    {"id": "t4", "name": "4分管", "color": "#e53935"},
    {"id": "t6", "name": "6分管", "color": "#1e88e5"},
]


# ======================================================================
# 後端權威計算
# ======================================================================

def _parse_data(sheet):
    """安全解析 sheet.data_json → dict（pipe_types/nodes/segments）。壞資料回空結構。"""
    if not sheet.data_json:
        return {"pipe_types": [], "nodes": [], "segments": []}
    try:
        d = json.loads(sheet.data_json)
    except (ValueError, TypeError):
        return {"pipe_types": [], "nodes": [], "segments": []}
    d.setdefault("pipe_types", [])
    d.setdefault("nodes", [])
    d.setdefault("segments", [])
    return d


def compute_sheet_summary(sheet):
    """從幾何 JSON 後端權威重算單一圖面結果。

    回傳：
      {
        "calibrated": bool,
        "types": [{"name","color","meters"} ...]   # 依管材名彙整
        "transitions": [{"pair","count"} ...]       # 不同管徑共節點的轉接頭
        "total_meters": float
      }
    """
    d = _parse_data(sheet)
    scale = sheet.scale_mm_per_px()   # mm per image-px；未校準=0
    calibrated = scale > 0

    nodes = {n.get("id"): n for n in d.get("nodes", []) if n.get("id")}
    types = {t.get("id"): t for t in d.get("pipe_types", []) if t.get("id")}

    # 各管材（依「名稱」彙整，因不同圖的 type id 各自獨立）
    meters_by_name = {}
    color_by_name = {}
    for seg in d.get("segments", []):
        a = nodes.get(seg.get("a"))
        b = nodes.get(seg.get("b"))
        t = types.get(seg.get("type"))
        if not a or not b or not t:
            continue
        name = (t.get("name") or "未命名").strip() or "未命名"
        color_by_name.setdefault(name, _safe_color(t.get("color")))   # 顏色輸出一律過白名單，擋歷史髒資料 CSS 注入
        if calibrated:
            length_px = math.hypot((a.get("x", 0) - b.get("x", 0)),
                                   (a.get("y", 0) - b.get("y", 0)))
            meters_by_name[name] = meters_by_name.get(name, 0.0) + length_px * scale / 1000.0
        else:
            meters_by_name.setdefault(name, 0.0)

    # 轉接頭：彙整每個節點上「不同管材名」，同節點 ≥2 種 → 每個不重複配對計一個轉接
    incident = {}   # node_id -> set(type_name)
    for seg in d.get("segments", []):
        t = types.get(seg.get("type"))
        if not t:
            continue
        name = (t.get("name") or "未命名").strip() or "未命名"
        for nid in (seg.get("a"), seg.get("b")):
            if nid in nodes:
                incident.setdefault(nid, set()).add(name)
    trans_count = {}
    for nid, tset in incident.items():
        if len(tset) >= 2:
            names = sorted(tset)
            for i in range(len(names)):
                for j in range(i + 1, len(names)):
                    pair = f"{names[i]}轉{names[j]}"
                    trans_count[pair] = trans_count.get(pair, 0) + 1

    types_out = [{"name": n, "color": color_by_name.get(n, "#666"),
                  "meters": round(meters_by_name[n], 2)}
                 for n in sorted(meters_by_name.keys())]
    transitions_out = [{"pair": p, "count": c} for p, c in sorted(trans_count.items())]
    total_meters = round(sum(meters_by_name.values()), 2)
    return {"calibrated": calibrated, "types": types_out,
            "transitions": transitions_out, "total_meters": total_meters}


def compute_project_summary(project):
    """彙整專案內所有圖面 → 管材公尺總表 + 轉接頭總表（後端權威）。"""
    meters_by_name = {}
    color_by_name = {}
    trans_count = {}
    any_uncalibrated = False
    for sheet in project.sheets:
        s = compute_sheet_summary(sheet)
        if not s["calibrated"] and (s["types"] or sheet.data_json):
            any_uncalibrated = True
        for t in s["types"]:
            meters_by_name[t["name"]] = meters_by_name.get(t["name"], 0.0) + t["meters"]
            color_by_name.setdefault(t["name"], t["color"])
        for tr in s["transitions"]:
            trans_count[tr["pair"]] = trans_count.get(tr["pair"], 0) + tr["count"]
    types_out = [{"name": n, "color": color_by_name.get(n, "#666"),
                  "meters": round(meters_by_name[n], 2)}
                 for n in sorted(meters_by_name.keys())]
    transitions_out = [{"pair": p, "count": c} for p, c in sorted(trans_count.items())]
    return {"types": types_out, "transitions": transitions_out,
            "any_uncalibrated": any_uncalibrated,
            "total_meters": round(sum(meters_by_name.values()), 2)}


# ======================================================================
# 專案 CRUD
# ======================================================================

@takeoff_bp.route("/")
@login_required
def list_projects():
    from db import TakeoffProject
    projects = TakeoffProject.query.order_by(TakeoffProject.created_at.desc()).all()
    rows = []
    for p in projects:
        rows.append({"p": p, "sheet_count": len(p.sheets)})
    return render_template("takeoff/list.html", rows=rows)


@takeoff_bp.route("/new", methods=["POST"])
@login_required
def new_project():
    from db import TakeoffProject
    name = (request.form.get("name") or "").strip() or "未命名估算"
    p = TakeoffProject(
        name=name,
        customer_name=(request.form.get("customer_name") or "").strip(),
        note=(request.form.get("note") or "").strip(),
    )
    db.session.add(p)
    db.session.commit()
    return redirect(url_for("takeoff.project_view", pid=p.id))


@takeoff_bp.route("/<int:pid>")
@login_required
def project_view(pid):
    from db import TakeoffProject, Quotation
    p = db.session.get(TakeoffProject, pid)
    if not p:
        flash("找不到該估算專案")
        return redirect(url_for("takeoff.list_projects"))
    sheets = [{"s": s, "summary": compute_sheet_summary(s)} for s in p.sheets]
    summary = compute_project_summary(p)
    linked_quote = db.session.get(Quotation, p.quotation_id) if p.quotation_id else None
    quotes = Quotation.query.order_by(Quotation.id.desc()).limit(200).all()
    return render_template("takeoff/project.html", p=p, sheets=sheets,
                           summary=summary, linked_quote=linked_quote, quotes=quotes)


@takeoff_bp.route("/<int:pid>/delete", methods=["POST"])
@login_required
def delete_project(pid):
    from db import TakeoffProject, TakeoffImage
    p = db.session.get(TakeoffProject, pid)
    if not p:
        flash("找不到該估算專案")
        return redirect(url_for("takeoff.list_projects"))
    # 先刪圖檔（無 FK，手動清理），再刪專案（cascade 刪 sheets）
    TakeoffImage.query.filter_by(project_id=pid).delete()
    db.session.delete(p)
    db.session.commit()
    flash("已刪除估算專案")
    return redirect(url_for("takeoff.list_projects"))


# ======================================================================
# 圖面上傳 / 圖檔 / 刪除
# ======================================================================

@takeoff_bp.route("/<int:pid>/sheet/add", methods=["POST"])
@login_required
def add_sheet(pid):
    """新增一張圖面：接收一張渲染後的頁面圖（PNG/JPEG）+ metadata。
    PDF 由前端逐頁渲染後逐頁呼叫本端點；單張影像則呼叫一次。"""
    from db import TakeoffProject, TakeoffSheet, TakeoffImage
    p = db.session.get(TakeoffProject, pid)
    if not p:
        return jsonify({"ok": False, "error": "專案不存在"}), 404
    if len(p.sheets) >= MAX_SHEETS_PER_PROJECT:
        return jsonify({"ok": False, "error": f"已達單專案上限 {MAX_SHEETS_PER_PROJECT} 張圖"}), 400
    f = request.files.get("file")
    if not f:
        return jsonify({"ok": False, "error": "缺少圖檔"}), 400
    mime = (f.mimetype or "").lower()
    if mime not in ALLOWED_IMAGE_MIME:
        return jsonify({"ok": False, "error": f"圖檔格式不支援：{mime}"}), 400
    blob = f.read()
    if not blob:
        return jsonify({"ok": False, "error": "空檔案"}), 400
    if len(blob) > MAX_IMAGE_BYTES:
        return jsonify({"ok": False, "error": "圖檔過大（上限 12MB）"}), 400

    def _int(v, d=0):
        try:
            return int(float(v))
        except (ValueError, TypeError):
            return d
    sheet = TakeoffSheet(
        project_id=pid,
        page_index=_int(request.form.get("page_index"), len(p.sheets)),
        name=(request.form.get("name") or f"圖面 {len(p.sheets)+1}").strip(),
        source_filename=(request.form.get("source_filename") or "").strip()[:300],
        img_w=_int(request.form.get("img_w")),
        img_h=_int(request.form.get("img_h")),
        data_json=json.dumps({"schema_version": 1, "pipe_types": DEFAULT_PIPE_TYPES,
                              "nodes": [], "segments": []}, ensure_ascii=False),
        schema_version=1,
    )
    db.session.add(sheet)
    db.session.flush()   # 取得 sheet.id
    img = TakeoffImage(project_id=pid, sheet_id=sheet.id, kind="page",
                       mime=("image/png" if mime == "image/jpg" else mime), data=blob)
    db.session.add(img)
    db.session.commit()
    return jsonify({"ok": True, "sheet_id": sheet.id,
                    "editor_url": url_for("takeoff.editor", sid=sheet.id)})


@takeoff_bp.route("/sheet/<int:sid>/image")
@login_required
def sheet_image(sid):
    from db import TakeoffImage
    img = (TakeoffImage.query.filter_by(sheet_id=sid, kind="page")
           .order_by(TakeoffImage.id.desc()).first())
    if not img or not img.data:
        abort(404)
    return Response(bytes(img.data), mimetype=img.mime or "image/png",
                    headers={"Cache-Control": "private, max-age=3600"})


@takeoff_bp.route("/sheet/<int:sid>/delete", methods=["POST"])
@login_required
def delete_sheet(sid):
    from db import TakeoffSheet, TakeoffImage
    s = db.session.get(TakeoffSheet, sid)
    if not s:
        flash("找不到該圖面")
        return redirect(url_for("takeoff.list_projects"))
    pid = s.project_id
    TakeoffImage.query.filter_by(sheet_id=sid).delete()
    db.session.delete(s)
    db.session.commit()
    flash("已刪除圖面")
    return redirect(url_for("takeoff.project_view", pid=pid))


# ======================================================================
# 編輯器 / 存檔
# ======================================================================

@takeoff_bp.route("/sheet/<int:sid>")
@login_required
def editor(sid):
    from db import TakeoffSheet
    s = db.session.get(TakeoffSheet, sid)
    if not s:
        flash("找不到該圖面")
        return redirect(url_for("takeoff.list_projects"))
    data = _parse_data(s)
    # 以 dict 傳入，模板用 |tojson 安全注入（避免 |safe 直塞 <script> 的持久化 XSS）
    return render_template("takeoff/editor.html", s=s, data=data,
                           summary=compute_sheet_summary(s))


@takeoff_bp.route("/sheet/<int:sid>/save", methods=["POST"])
@login_required
def save_sheet(sid):
    """存校準 + 幾何 JSON。回傳後端權威重算的單圖摘要。"""
    from db import TakeoffSheet
    s = db.session.get(TakeoffSheet, sid)
    if not s:
        return jsonify({"ok": False, "error": "圖面不存在"}), 404
    try:
        body = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"ok": False, "error": "JSON 格式錯誤"}), 400

    def _f(v):
        try:
            return float(v)
        except (ValueError, TypeError):
            return 0.0
    s.calib_px = max(0.0, _f(body.get("calib_px")))
    s.calib_real_mm = max(0.0, _f(body.get("calib_real_mm")))
    data = body.get("data") or {}
    # 只存白名單結構，避免塞入雜物
    clean = {
        "schema_version": 1,
        "pipe_types": [{"id": str(t.get("id")), "name": str(t.get("name") or "")[:40],
                        "color": _safe_color(t.get("color"))}
                       for t in (data.get("pipe_types") or []) if t.get("id")],
        "nodes": [{"id": str(n.get("id")), "x": _f(n.get("x")), "y": _f(n.get("y"))}
                  for n in (data.get("nodes") or []) if n.get("id")],
        "segments": [{"id": str(g.get("id")), "type": str(g.get("type") or ""),
                      "a": str(g.get("a") or ""), "b": str(g.get("b") or "")}
                     for g in (data.get("segments") or []) if g.get("id")],
    }
    s.data_json = json.dumps(clean, ensure_ascii=False)
    s.schema_version = 1
    db.session.commit()
    return jsonify({"ok": True, "summary": compute_sheet_summary(s)})


# ======================================================================
# 匯入 / 建立報價單
# ======================================================================

@takeoff_bp.route("/<int:pid>/to-quote", methods=["POST"])
@login_required
def to_quote(pid):
    """把專案管材總表帶進報價單：mode=new 建新單；mode=existing 加到指定報價單。
    一律以後端權威 compute_project_summary 為準（不信前端數字）。"""
    from db import TakeoffProject, Quotation, QuotationGroup, QuotationItem
    p = db.session.get(TakeoffProject, pid)
    if not p:
        flash("找不到該估算專案")
        return redirect(url_for("takeoff.list_projects"))
    summary = compute_project_summary(p)
    if not summary["types"] and not summary["transitions"]:
        flash("此專案尚無可帶入的管材資料（請先校準並畫線）")
        return redirect(url_for("takeoff.project_view", pid=pid))
    if summary["any_uncalibrated"]:
        flash("⚠️ 提醒：有圖面尚未校準，未校準圖面的長度以 0 計入，請確認。")

    mode = request.form.get("mode", "new")

    # 組裝群組：每種管材一列（公尺）、每種轉接頭一列（個）
    def _build_group(seq):
        # 不設群組備註：避免「由管材估算工具自動帶入」這類內部字樣印到列印/合約版（森哥 2026-06-29）
        g = QuotationGroup(seq=seq, title=f"管材估算（{p.name}）", note="")
        ii = 0
        for t in summary["types"]:
            g.items.append(QuotationItem(
                seq=ii, name=t["name"], qty_text=f"{t['meters']:.1f}",
                unit_price=0, amount=0, note="公尺（單價待填）"))
            ii += 1
        for tr in summary["transitions"]:
            g.items.append(QuotationItem(
                seq=ii, name=f"{tr['pair']}轉接頭", qty_text=str(tr["count"]),
                unit_price=0, amount=0, note="個（單價待填）"))
            ii += 1
        return g

    if mode == "existing":
        try:
            qid = int(request.form.get("quotation_id") or 0)
        except (ValueError, TypeError):
            qid = 0
        q = db.session.get(Quotation, qid)
        if not q:
            flash("找不到指定的報價單")
            return redirect(url_for("takeoff.project_view", pid=pid))
        next_seq = max([g.seq for g in q.groups], default=-1) + 1
        q.groups.append(_build_group(next_seq))
        q.recompute_totals(bool((q.tax or 0) > 0))
        p.quotation_id = q.id
        db.session.commit()
        flash(f"✅ 已把管材估算帶入報價單 {q.quote_number}")
        return redirect(url_for("quotations.detail", quote_id=q.id)
                        if _has_quote_detail() else url_for("takeoff.project_view", pid=pid))

    # mode == new：建立新報價單
    from blueprints.quotations import next_quote_number
    from config import COMPANY_OPTIONS
    import datetime as _dt
    company = COMPANY_OPTIONS[0]["name"] if COMPANY_OPTIONS else ""
    tax_id = COMPANY_OPTIONS[0]["tax_id"] if COMPANY_OPTIONS else ""
    q = Quotation(
        quote_number=next_quote_number(),
        quote_date=_dt.date.today().isoformat(),
        company=company, tax_id=tax_id,
        customer_name=p.customer_name or "",
        status="草稿",
    )
    q.groups.append(_build_group(0))
    q.recompute_totals(False)
    db.session.add(q)
    db.session.commit()
    p.quotation_id = q.id
    db.session.commit()
    flash(f"✅ 已用管材估算建立新報價單 {q.quote_number}")
    return redirect(url_for("quotations.detail", quote_id=q.id)
                    if _has_quote_detail() else url_for("takeoff.project_view", pid=pid))


def _has_quote_detail():
    """報價單明細 endpoint 名稱在不同版本可能不同，存在才導向，否則回估算專案頁。"""
    from flask import current_app
    return "quotations.detail" in current_app.view_functions
