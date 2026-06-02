# db.py
# SQLAlchemy models for the Taian webapp (Supabase PostgreSQL backend).
# Replaces the Google Sheets data layer. Chinese sheet column names are
# mapped to English SQLAlchemy column names; the sheets_client compatibility
# layer translates back to the Chinese keys the blueprints/templates expect.

from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


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
        return d


class GiftInventory(db.Model):
    """贈品庫存"""
    __tablename__ = "gift_inventory"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(200), default="")                         # 名稱
    qty = db.Column(db.String(50), default="")                           # 庫存數量
    note = db.Column(db.Text, default="")                                # 備註
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    FIELD_MAP = {
        "名稱": "name",
        "庫存數量": "qty",
        "備註": "note",
    }

    def to_sheet_dict(self):
        d = {cn: (getattr(self, en) or "") for cn, en in self.FIELD_MAP.items()}
        d["id"] = self.id
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


# 表名（中文工作表名稱）-> Model 對照，供 sheets_client compat 層使用
SHEET_MODELS = {
    "顧客資料": Customer,
    "冷氣庫存": ACInventory,
    "贈品庫存": GiftInventory,
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
