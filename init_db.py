# init_db.py
# 一次性執行：建立 schema 並從三份 CSV 匯入初始資料。
#
# 用法：
#   python init_db.py
#
# 預期同目錄下的 CSV（UTF-8，含中文表頭）：
#   customers.csv   -> 顧客資料   欄位：姓名,廠牌型號,電話,地址,安裝日期,備註
#   ac.csv          -> 冷氣庫存   欄位：廠牌型號規格,庫存數量,實際庫存,備註
#   gifts.csv       -> 贈品庫存   欄位：名稱,庫存數量,備註
# 報價單記錄為交易資料，初始多半為空，故不匯入（如有 quotations.csv 會自動帶入）。

import csv
import os

from flask import Flask
from db import db, Customer, ACInventory, GiftInventory, Quotation

DATABASE_URL = "postgresql://postgres:H4m*zp.fX5ZkCyT@db.dosmfcgztoybstrydxkr.supabase.co:5432/postgres"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# (CSV 檔名, Model, 中文工作表名)
CSV_IMPORTS = [
    ("customers.csv", Customer, "顧客資料"),
    ("ac.csv", ACInventory, "冷氣庫存"),
    ("gifts.csv", GiftInventory, "贈品庫存"),
    ("quotations.csv", Quotation, "報價單記錄"),  # 選用，缺檔即跳過
]


def create_app():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    return app


def _coerce(model, en_field, value):
    float_fields = getattr(model, "FLOAT_FIELDS", set())
    if en_field in float_fields:
        try:
            return float(str(value if value is not None else "0")
                         .replace(",", "").strip() or "0")
        except (ValueError, TypeError):
            return 0.0
    return "" if value is None else str(value)


def import_csv(filename, model, sheet_name):
    path = os.path.join(BASE_DIR, filename)
    if not os.path.exists(path):
        print(f"  - 略過 {sheet_name}：找不到 {filename}")
        return 0

    count = 0
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for raw in reader:
            obj = model()
            for cn, en in model.FIELD_MAP.items():
                if cn in raw:
                    setattr(obj, en, _coerce(model, en, raw.get(cn)))
            db.session.add(obj)
            count += 1
    db.session.commit()
    print(f"  - {sheet_name}：匯入 {count} 筆（{filename}）")
    return count


def main():
    app = create_app()
    with app.app_context():
        print("建立資料表 schema ...")
        db.create_all()
        print("schema 建立完成。\n")

        print("開始匯入 CSV ...")
        for filename, model, sheet_name in CSV_IMPORTS:
            import_csv(filename, model, sheet_name)

        print("\n各表筆數確認：")
        for model, label in [
            (Customer, "顧客資料 (customers)"),
            (ACInventory, "冷氣庫存 (ac_inventory)"),
            (GiftInventory, "贈品庫存 (gift_inventory)"),
            (Quotation, "報價單記錄 (quotations)"),
        ]:
            print(f"  - {label}: {model.query.count()} 筆")

        print("\n完成。")


if __name__ == "__main__":
    main()
