# db.py
# SQLAlchemy models for the Taian webapp (Supabase PostgreSQL backend).
# Replaces the Google Sheets data layer. Chinese sheet column names are
# mapped to English SQLAlchemy column names; the sheets_client compatibility
# layer translates back to the Chinese keys the blueprints/templates expect.

import json
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def round_half_up(value):
    """標準四捨五入取整（台灣商業習慣）。

    Python 內建 round() 是銀行家捨入（50.5 → 50），金額計算不可用；
    本函式 50.5 → 51。所有對外呈現的金額（品項金額/小計/稅金/總額）
    一律經此取整，確保未稅 + 稅金 = 總額 完全吻合。
    """
    try:
        return int(Decimal(str(value if value is not None else 0))
                   .quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except Exception:
        return 0

# 允許的文字顏色（白名單，避免 style 注入）；key=色名, value=hex
ALLOWED_COLORS = {
    "red": "#d32f2f",
    "blue": "#1565c0",
    "green": "#2e7d32",
    "black": "#111111",
}


def parse_qty(qty_text):
    """把數量文字解析成 float（扣庫存用）。

    純數字字串（含千分位逗號、前後空白）→ 轉成 float；
    例如 "乙式"、"一批" 等非數字文字 → 回傳 0.0。
    """
    if qty_text is None:
        return 0.0
    # 已是數字型別直接轉
    if isinstance(qty_text, (int, float)):
        try:
            return float(qty_text)
        except (TypeError, ValueError):
            return 0.0
    s = str(qty_text).strip().replace(",", "")  # 去除千分位逗號與空白
    if s == "":
        return 0.0
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


class Customer(db.Model):
    """顧客資料"""
    __tablename__ = "customers"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False, default="")          # 姓名
    model = db.Column(db.String(200), default="")                         # 廠牌型號
    phone = db.Column(db.String(50), default="")                          # 電話
    address = db.Column(db.String(300), default="")                       # 地址
    install_date = db.Column(db.String(50), default="")                   # 安裝日期
    note = db.Column(db.Text, default="")                                 # 備註
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # 中文欄位 <-> 英文 column 對照（compat 層使用）
    FIELD_MAP = {
        "姓名": "name",
        "廠牌型號": "model",
        "電話": "phone",
        "地址": "address",
        "安裝日期": "install_date",
        "備註": "note",
    }

    def to_sheet_dict(self):
        d = {cn: (getattr(self, en) or "") for cn, en in self.FIELD_MAP.items()}
        d["id"] = self.id
        return d


class ACInventory(db.Model):
    """冷氣庫存"""
    __tablename__ = "ac_inventory"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    spec = db.Column(db.String(200), default="")                          # 廠牌型號規格
    system_qty = db.Column(db.String(50), default="")                     # 庫存數量（系統/帳面）
    actual_qty = db.Column(db.String(50), default="")                     # 實際庫存
    note = db.Column(db.Text, default="")                                 # 備註
    sort_order = db.Column(db.Integer, default=0)                         # 手動排序（拖拉）
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    FIELD_MAP = {
        "廠牌型號規格": "spec",
        "庫存數量": "system_qty",
        "實際庫存": "actual_qty",
        "備註": "note",
    }

    def to_sheet_dict(self):
        d = {cn: (getattr(self, en) or "") for cn, en in self.FIELD_MAP.items()}
        d["id"] = self.id
        d["sort_order"] = self.sort_order or 0
        return d


class GiftInventory(db.Model):
    """贈品庫存"""
    __tablename__ = "gift_inventory"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(200), default="")                         # 名稱
    qty = db.Column(db.String(50), default="")                           # 庫存數量
    note = db.Column(db.Text, default="")                                # 備註
    sort_order = db.Column(db.Integer, default=0)                        # 手動排序（拖拉）
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    FIELD_MAP = {
        "名稱": "name",
        "庫存數量": "qty",
        "備註": "note",
    }

    def to_sheet_dict(self):
        d = {cn: (getattr(self, en) or "") for cn, en in self.FIELD_MAP.items()}
        d["id"] = self.id
        d["sort_order"] = self.sort_order or 0
        return d


class Material(db.Model):
    """材料庫存（比照贈品庫存：名稱 / 庫存數量 / 備註）

    注意：prod 上已存在另一張結構不同的 `materials` 空表（brand/spec/price/
    supplier_email… 的材料目錄雛形）。為避免撞名導致欄位不符而報錯，本模型
    改用獨立表名 material_inventory。
    """
    __tablename__ = "material_inventory"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(200), default="")                         # 名稱
    qty = db.Column(db.String(50), default="")                           # 庫存數量
    note = db.Column(db.Text, default="")                                # 備註
    sort_order = db.Column(db.Integer, default=0)                        # 手動排序（拖拉）
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    FIELD_MAP = {
        "名稱": "name",
        "庫存數量": "qty",
        "備註": "note",
    }

    def to_sheet_dict(self):
        d = {cn: (getattr(self, en) or "") for cn, en in self.FIELD_MAP.items()}
        d["id"] = self.id
        d["sort_order"] = self.sort_order or 0
        return d


class Quotation(db.Model):
    """報價單記錄 — 三品項 + 工程費 + 稅額 + 雙公司抬頭"""
    __tablename__ = "quotations"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    quote_number = db.Column(db.String(50), default="")                  # 報價單編號
    quote_date = db.Column(db.String(50), default="")                    # 報價日期
    company = db.Column(db.String(100), default="")                      # 公司抬頭
    tax_id = db.Column(db.String(50), default="")                        # 統編
    customer_name = db.Column(db.String(100), default="")                # 客戶姓名
    customer_phone = db.Column(db.String(50), default="")                # 客戶電話
    customer_address = db.Column(db.String(300), default="")             # 客戶地址

    item1_name = db.Column(db.String(200), default="")                   # 品項1名稱
    item1_qty = db.Column(db.Float, default=0)                           # 品項1數量
    item1_price = db.Column(db.Float, default=0)                         # 品項1單價
    item1_sub = db.Column(db.Float, default=0)                           # 品項1小計

    item2_name = db.Column(db.String(200), default="")                   # 品項2名稱
    item2_qty = db.Column(db.Float, default=0)                           # 品項2數量
    item2_price = db.Column(db.Float, default=0)                         # 品項2單價
    item2_sub = db.Column(db.Float, default=0)                           # 品項2小計

    item3_name = db.Column(db.String(200), default="")                   # 品項3名稱
    item3_qty = db.Column(db.Float, default=0)                           # 品項3數量
    item3_price = db.Column(db.Float, default=0)                         # 品項3單價
    item3_sub = db.Column(db.Float, default=0)                           # 品項3小計

    engineering = db.Column(db.Float, default=0)                         # 工程費
    other = db.Column(db.Float, default=0)                               # 其他費用
    pretax = db.Column(db.Float, default=0)                              # 未稅合計
    tax = db.Column(db.Float, default=0)                                 # 稅額(5%)
    total = db.Column(db.Float, default=0)                               # 含稅總金額

    install_date = db.Column(db.String(50), default="")                  # 預計安裝日期
    note = db.Column(db.Text, default="")                                # 備註
    status = db.Column(db.String(20), default="草稿")                    # 狀態
    subsidy_done = db.Column(db.Boolean, default=False)                  # 補助是否已完成（補助清單打勾用）
    note_color = db.Column(db.String(20), default="")                    # 整單備註文字顏色（#3，空=預設黑）
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    FIELD_MAP = {
        "報價單編號": "quote_number",
        "報價日期": "quote_date",
        "公司抬頭": "company",
        "統編": "tax_id",
        "客戶姓名": "customer_name",
        "客戶電話": "customer_phone",
        "客戶地址": "customer_address",
        "品項1名稱": "item1_name",
        "品項1數量": "item1_qty",
        "品項1單價": "item1_price",
        "品項1小計": "item1_sub",
        "品項2名稱": "item2_name",
        "品項2數量": "item2_qty",
        "品項2單價": "item2_price",
        "品項2小計": "item2_sub",
        "品項3名稱": "item3_name",
        "品項3數量": "item3_qty",
        "品項3單價": "item3_price",
        "品項3小計": "item3_sub",
        "工程費": "engineering",
        "其他費用": "other",
        "未稅合計": "pretax",
        "稅額(5%)": "tax",
        "含稅總金額": "total",
        "預計安裝日期": "install_date",
        "備註": "note",
        "狀態": "status",
    }

    # 數值型欄位（compat 層寫入時做型別轉換）
    FLOAT_FIELDS = {
        "item1_qty", "item1_price", "item1_sub",
        "item2_qty", "item2_price", "item2_sub",
        "item3_qty", "item3_price", "item3_sub",
        "engineering", "other", "pretax", "tax", "total",
    }

    def to_sheet_dict(self):
        d = {}
        for cn, en in self.FIELD_MAP.items():
            val = getattr(self, en)
            d[cn] = "" if val is None else val
        d["id"] = self.id
        return d

    # 第二段資料模型：群組（空間標題）關係
    # cascade delete-orphan：刪報價單或從集合移除群組時，連帶刪除群組與其細項
    groups = db.relationship(
        "QuotationGroup",
        back_populates="quotation",
        cascade="all, delete-orphan",
        order_by="QuotationGroup.seq",
    )

    def recompute_totals(self, taxable=True):
        """後端權威重算：依各群組細項重算 group.subtotal 與 pretax/tax/total。

        規則：
          group.subtotal = sum(該群 item.amount)
          pretax = sum(group.subtotal)
          taxable=True  → tax = round(pretax * 0.05)；total = pretax + tax
          taxable=False → tax = 0（不含稅）；total = pretax
        含稅與否未另設欄位（避免動既有表結構）：以 tax>0 代表含稅、tax==0 代表不含稅。
        工程費 engineering / 雜項 other 已停用，固定設為 0。
        """
        pretax = 0
        for group in self.groups:
            pretax += group.recompute_subtotal()
        self.engineering = 0          # 停用，保留欄位歸零
        self.other = 0                # 停用，保留欄位歸零
        self.pretax = round_half_up(pretax)
        self.tax = round_half_up(self.pretax * 0.05) if taxable else 0
        self.total = self.pretax + self.tax
        return self.total


# 表名（中文工作表名稱）-> Model 對照，供 sheets_client compat 層使用
SHEET_MODELS = {
    "顧客資料": Customer,
    "冷氣庫存": ACInventory,
    "贈品庫存": GiftInventory,
    "材料庫存": Material,
    "報價單記錄": Quotation,
}


class ShippingOrder(db.Model):
    """出貨單 — 報價單確認後建立，確認出貨後扣庫存並產生收入交易"""
    __tablename__ = "shipping_orders"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    quotation_id = db.Column(db.Integer, db.ForeignKey("quotations.id"), nullable=True)
    quote_number = db.Column(db.String(50), default="")
    customer_name = db.Column(db.String(100), default="")
    company = db.Column(db.String(100), default="")
    ship_date = db.Column(db.String(50), default="")
    status = db.Column(db.String(20), default="待出貨")
    note = db.Column(db.Text, default="")
    item1_name = db.Column(db.String(200), default="")
    item1_qty = db.Column(db.Float, default=0)
    item1_price = db.Column(db.Float, default=0)
    item2_name = db.Column(db.String(200), default="")
    item2_qty = db.Column(db.Float, default=0)
    item2_price = db.Column(db.Float, default=0)
    item3_name = db.Column(db.String(200), default="")
    item3_qty = db.Column(db.Float, default=0)
    item3_price = db.Column(db.Float, default=0)
    engineering = db.Column(db.Float, default=0)
    other = db.Column(db.Float, default=0)
    pretax = db.Column(db.Float, default=0)
    tax = db.Column(db.Float, default=0)
    total = db.Column(db.Float, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # 第二段資料模型：出貨品項（攤平快照）關係
    items = db.relationship(
        "ShippingItem",
        back_populates="shipping_order",
        cascade="all, delete-orphan",
        order_by="ShippingItem.seq",
    )


class Purchase(db.Model):
    """進貨記錄 — 確認進貨後自動增加庫存"""
    __tablename__ = "purchases"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    purchase_date = db.Column(db.String(50), default="")
    item_name = db.Column(db.String(200), default="")
    item_type = db.Column(db.String(10), default="ac")
    quantity = db.Column(db.Float, default=0)
    unit_cost = db.Column(db.Float, default=0)
    total_cost = db.Column(db.Float, default=0)
    supplier = db.Column(db.String(200), default="")
    note = db.Column(db.Text, default="")
    status = db.Column(db.String(20), default="待確認")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Transaction(db.Model):
    """進出帳記錄"""
    __tablename__ = "transactions"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    date = db.Column(db.String(50), default="")
    type = db.Column(db.String(20), default="income")
    amount = db.Column(db.Float, default=0)
    category = db.Column(db.String(100), default="")
    description = db.Column(db.Text, default="")
    ref_type = db.Column(db.String(50), default="")
    ref_id = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ======================================================================
# 第二段資料模型：報價單群組 + 群組細項 + 出貨品項（三張新子表）
# 舊 quotations.item1~3 / engineering / other 欄位保留不刪，僅停用，
# 確保與線上正式系統共用的 Supabase 零破壞。
# ======================================================================


class QuotationGroup(db.Model):
    """報價單群組（＝空間標題，如「主臥」「客廳」）"""
    __tablename__ = "quotation_groups"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    quotation_id = db.Column(db.Integer, db.ForeignKey("quotations.id"), nullable=False)
    seq = db.Column(db.Integer, default=0)                                # 排序
    title = db.Column(db.String(200), default="")                        # 空間標題
    note = db.Column(db.Text, default="")                                # 群組備註
    subtotal = db.Column(db.Float, default=0)                            # 群組小計（後端算）

    quotation = db.relationship("Quotation", back_populates="groups")
    items = db.relationship(
        "QuotationItem",
        back_populates="group",
        cascade="all, delete-orphan",
        order_by="QuotationItem.seq",
    )

    def recompute_subtotal(self):
        """重算群組小計：sum(該群每個 item.amount)，回傳小計。

        每個細項 amount 先由 item.compute_amount() 重算：
          數量可轉 float → qty * unit_price
          數量為文字（如「乙式」）→ 採前端手填的 amount
          is_gift=True → amount 強制 0
        """
        subtotal = 0
        for item in self.items:
            subtotal += item.compute_amount()
        self.subtotal = round_half_up(subtotal)
        return self.subtotal


class QuotationItem(db.Model):
    """報價單群組內的細項"""
    __tablename__ = "quotation_items"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    group_id = db.Column(db.Integer, db.ForeignKey("quotation_groups.id"), nullable=False)
    seq = db.Column(db.Integer, default=0)                               # 排序
    name = db.Column(db.String(300), default="")                        # 品名
    qty_text = db.Column(db.String(50), default="")                     # 數量（可文字「乙式」或數字「2」）
    unit_price = db.Column(db.Float, default=0)                         # 單價（可 0）
    amount = db.Column(db.Float, default=0)                             # 金額
    note = db.Column(db.Text, default="")                              # 備註
    is_gift = db.Column(db.Boolean, default=False)                     # 是否為贈品
    colors = db.Column(db.Text, default="")                            # 各欄文字顏色 JSON：{name,qty,price,amount,note}

    group = db.relationship("QuotationGroup", back_populates="items")

    def color(self, field):
        """回傳某欄（name/qty/price/amount/note）的 hex 顏色字串；無則空字串。
        只回傳白名單內的 hex，避免 style 注入。"""
        if not self.colors:
            return ""
        try:
            d = json.loads(self.colors)
        except (ValueError, TypeError):
            return ""
        val = (d.get(field) or "").strip()
        return val if val in ALLOWED_COLORS.values() else ""

    def compute_amount(self):
        """後端權威算金額並寫回 self.amount，回傳金額。

        規則：
          is_gift=True → 0
          qty_text 可轉 float → qty * unit_price
          qty_text 為文字無法轉 → 採前端手填的 amount
        """
        if self.is_gift:
            self.amount = 0
            return 0.0
        s = "" if self.qty_text is None else str(self.qty_text).strip()
        # 僅在「可解析成數字」時用 qty*unit_price 覆蓋；否則沿用手填 amount
        parsed = parse_qty(s)
        # 區分「真的解析到數字」與「文字解析回 0」：空字串或非數字皆視為文字
        is_numeric = s != "" and s.replace(",", "").lstrip("-").replace(".", "", 1).isdigit()
        if is_numeric:
            self.amount = round_half_up(parsed * (self.unit_price or 0))
        else:
            self.amount = round_half_up(self.amount or 0)
        return self.amount


class ShippingItem(db.Model):
    """出貨單品項（攤平快照）— 從報價單群組細項攤平複製，扣庫存依 qty_num"""
    __tablename__ = "shipping_items"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    shipping_order_id = db.Column(db.Integer, db.ForeignKey("shipping_orders.id"), nullable=False)
    seq = db.Column(db.Integer, default=0)                              # 排序
    group_title = db.Column(db.String(200), default="")                # 來源群組標題（快照）
    name = db.Column(db.String(300), default="")                       # 品名
    qty_text = db.Column(db.String(50), default="")                    # 數量（原始文字）
    qty_num = db.Column(db.Float, default=0)                           # 解析出的數字數量（扣庫存用，非數字則 0）
    unit_price = db.Column(db.Float, default=0)                        # 單價
    amount = db.Column(db.Float, default=0)                            # 金額
    note = db.Column(db.Text, default="")                             # 備註
    is_gift = db.Column(db.Boolean, default=False)                    # 是否為贈品

    shipping_order = db.relationship("ShippingOrder", back_populates="items")


class QuoteSignature(db.Model):
    """報價單電子簽名記錄。

    生命週期：pending（連結已產生待簽）→ signed（已簽署，報價單鎖定）
              / voided（作廢，可重新產生連結）
    一張報價單同時間最多一筆 pending；signed 後報價單不可返回修改，
    需先作廢簽名（業務決策：簽的是當下金額，簽後改單需重簽）。
    """
    __tablename__ = "quote_signatures"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    quotation_id = db.Column(db.Integer, db.ForeignKey("quotations.id"), nullable=False)
    token = db.Column(db.String(64), unique=True, nullable=False)      # 公開簽名連結的亂數憑證
    status = db.Column(db.String(20), default="pending")               # pending / signed / voided
    signature_png = db.Column(db.Text, default="")                     # 簽名圖 data URI（base64 PNG）
    signer_ip = db.Column(db.String(64), default="")                   # 簽署來源 IP（存證）
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime)                                # 未簽過期時間（7 天）
    signed_at = db.Column(db.DateTime)                                 # 簽署時間（UTC，顯示時 +8）

    def is_expired(self):
        return (self.status == "pending" and self.expires_at is not None
                and datetime.utcnow() > self.expires_at)


# ======================================================================
# 管材估算工具（takeoff）：專案 / 圖面 / 圖檔
# 新增表，create_all 自動建立、對既有 Supabase 零破壞。
# 圖檔存 DB（bytea 獨立表）避開 Render ephemeral 檔案系統重啟遺失；
# 並與圖面 metadata 分表，避免專案/總表列表查詢時連大圖一起載出（Codex 設計審查）。
# ======================================================================


class TakeoffProject(db.Model):
    """管材估算專案（一份資料＝一個案子，可含多張圖面）"""
    __tablename__ = "takeoff_projects"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(200), default="")
    customer_name = db.Column(db.String(100), default="")
    note = db.Column(db.Text, default="")
    quotation_id = db.Column(db.Integer, default=0)     # 關聯報價單 id（0=未關聯；不設 FK 避免跨表刪除耦合）
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    sheets = db.relationship(
        "TakeoffSheet",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="TakeoffSheet.page_index",
    )


class TakeoffSheet(db.Model):
    """單一圖面：底圖 metadata + 校準 + 管線幾何 JSON。圖檔本身存 takeoff_images。"""
    __tablename__ = "takeoff_sheets"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    project_id = db.Column(db.Integer, db.ForeignKey("takeoff_projects.id"), nullable=False)
    page_index = db.Column(db.Integer, default=0)          # 在專案內排序（PDF 多頁＝多 sheet）
    name = db.Column(db.String(200), default="")
    source_filename = db.Column(db.String(300), default="")
    img_w = db.Column(db.Integer, default=0)               # 底圖原始寬（image px）
    img_h = db.Column(db.Integer, default=0)               # 底圖原始高（image px）
    calib_px = db.Column(db.Float, default=0)              # 校準：兩點像素距離（image px）
    calib_real_mm = db.Column(db.Float, default=0)         # 校準：兩點實際長度（mm）
    data_json = db.Column(db.Text, default="")            # pipe_types[]/nodes[]/segments[] JSON
    schema_version = db.Column(db.Integer, default=1)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = db.relationship("TakeoffProject", back_populates="sheets")

    def scale_mm_per_px(self):
        """每 image px 對應的實際 mm；未校準回 0。"""
        if self.calib_px and self.calib_px > 0 and self.calib_real_mm and self.calib_real_mm > 0:
            return self.calib_real_mm / self.calib_px
        return 0.0


class TakeoffImage(db.Model):
    """圖檔位元組（bytea）。kind=page 渲染頁面圖（綁 sheet）；kind=original 原始上傳檔（綁專案，供向量重用）。
    刻意不設 FK，刪除時由端點手動清理，避免刪除順序的 FK 衝突（比照 Transaction.ref_id 風格）。"""
    __tablename__ = "takeoff_images"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    project_id = db.Column(db.Integer, index=True, default=0)
    sheet_id = db.Column(db.Integer, index=True, default=0)   # 0=非頁面圖（原始檔）
    kind = db.Column(db.String(20), default="page")           # page | original
    mime = db.Column(db.String(80), default="image/png")
    data = db.Column(db.LargeBinary)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
