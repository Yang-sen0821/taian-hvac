# seed_materials.py — 一次性執行：新增預設材料/服務品項（已存在則略過）
# 用法：python seed_materials.py
import os
from flask import Flask
from db import db, Material

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise SystemExit("請先設定 DATABASE_URL 環境變數")

DEFAULT_MATERIALS = [
    "220v電源配置",
    "不鏽鋼安裝架",
    "冷媒填充",
    "南亞PVC配水含保溫",
    "保溫風管工程",
    "全機七年 壓縮機十年保固",
    "安裝費",
    "拆箱/定位/安裝",
    "洗洞",
    "無框線型出風口",
    "舊機拆除/回收",
    "集風箱/緩速箱",
    "鑿牆/水泥填縫",
    "銅管保護修飾套管",
    "配合裝潢多次施工",
]


def main():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    with app.app_context():
        existing = {m.name for m in Material.query.all()}
        added = 0
        for name in DEFAULT_MATERIALS:
            if name not in existing:
                db.session.add(Material(name=name, qty="0", note=""))
                added += 1
        db.session.commit()
        print(f"已新增 {added} 筆材料品項（重複略過）")
        print(f"目前材料庫存共 {Material.query.count()} 筆")


if __name__ == "__main__":
    main()
