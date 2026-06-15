# migrate_sort_order.py — 一次性執行：為三張庫存表加上 sort_order 欄位並初始化順序。
#
# create_all() 只會建立缺少的「表」，不會為既有表補欄位，故手動 ALTER TABLE。
# ADD COLUMN IF NOT EXISTS + 預設 0 為非破壞性、可逆（drop column 即還原）。
#
# 用法（本機對 Supabase 執行）：
#   $env:DATABASE_URL="postgresql://..."; python migrate_sort_order.py
import os
from flask import Flask
from sqlalchemy import text
from db import db, ACInventory, GiftInventory, Material

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise SystemExit("請先設定 DATABASE_URL 環境變數")

# (表名, Model, 初始排序鍵) — 冷氣/贈品依 id；材料依名稱（維持同類相鄰）
TABLES = [
    ("ac_inventory", ACInventory, lambda o: o.id),
    ("gift_inventory", GiftInventory, lambda o: o.id),
    ("material_inventory", Material, lambda o: (o.name or "").upper()),
]


def main():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    with app.app_context():
        # 1. 補欄位（冪等）
        for table, _model, _key in TABLES:
            db.session.execute(text(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS sort_order INTEGER DEFAULT 0"
            ))
        db.session.commit()
        print("欄位確認完成。")

        # 2. 初始化順序：依顯示順序給 0,1,2...（僅當全為 0 時才初始化，避免覆蓋已排好的）
        for table, model, key in TABLES:
            rows = model.query.all()
            if rows and all((r.sort_order or 0) == 0 for r in rows):
                for idx, obj in enumerate(sorted(rows, key=key)):
                    obj.sort_order = idx
                db.session.commit()
                print(f"  - {table}：初始化 {len(rows)} 筆排序")
            else:
                print(f"  - {table}：已有排序值，略過初始化")

        print("\n完成。")


if __name__ == "__main__":
    main()
