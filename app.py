import os
from flask import Flask, render_template, request, redirect, url_for, session, flash
from config import SECRET_KEY
from db import db
from auth import check_login
from sheets_client import get_sheet
from blueprints.customers import customers_bp
from blueprints.inventory import inventory_bp
from blueprints.quotations import quotations_bp, sign_bp
from blueprints.shipping import shipping_bp
from blueprints.purchases import purchases_bp
from blueprints.transactions import transactions_bp, compute_dashboard
from blueprints.takeoff import takeoff_bp

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'postgresql://postgres:H4m*zp.fX5ZkCyT@db.dosmfcgztoybstrydxkr.supabase.co:5432/postgres')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 12 * 1024 * 1024   # 上傳上限 12MB（管材估算圖面）
db.init_app(app)

# 啟動時確保資料表存在：新增表（quotation_groups/quotation_items/shipping_items）為非破壞性，
# 既有表 create_all 會自動略過、不改不刪。失敗不阻擋啟動（DB 暫時不可達時 app 仍能起來）。
with app.app_context():
    try:
        db.create_all()
    except Exception as e:
        print(f"[init] create_all skipped: {e}")

    # 自動補 sort_order 欄位（拖拉排序用）：create_all 不會為「既有表」加欄位，
    # 故以 ADD COLUMN IF NOT EXISTS 補上（冪等、非破壞、可逆）。首次補上後若全為 0，
    # 依顯示順序初始化 0,1,2...，之後拖拉即覆寫。失敗不阻擋啟動。
    try:
        from sqlalchemy import text
        from db import ACInventory, GiftInventory, Material
        _SORT_TABLES = [
            ("ac_inventory", ACInventory, lambda o: o.id),
            ("gift_inventory", GiftInventory, lambda o: o.id),
            ("material_inventory", Material, lambda o: (o.name or "").upper()),
        ]
        for _table, _m, _key in _SORT_TABLES:
            db.session.execute(text(
                f"ALTER TABLE {_table} ADD COLUMN IF NOT EXISTS sort_order INTEGER DEFAULT 0"
            ))
        db.session.commit()
        for _table, _m, _key in _SORT_TABLES:
            _rows = _m.query.all()
            if _rows and all((r.sort_order or 0) == 0 for r in _rows):
                for _idx, _obj in enumerate(sorted(_rows, key=_key)):
                    _obj.sort_order = _idx
                db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[init] sort_order migration skipped: {e}")

    # 自動補 subsidy_done 欄位（補助清單打勾用；冪等、非破壞、可逆）。失敗不阻擋啟動。
    try:
        from sqlalchemy import text
        db.session.execute(text(
            "ALTER TABLE quotations ADD COLUMN IF NOT EXISTS subsidy_done BOOLEAN DEFAULT FALSE"
        ))
        db.session.execute(text(
            "ALTER TABLE quotations ADD COLUMN IF NOT EXISTS note_color VARCHAR(20) DEFAULT ''"
        ))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[init] subsidy_done/note_color migration skipped: {e}")

app.register_blueprint(customers_bp)
app.register_blueprint(inventory_bp)
app.register_blueprint(quotations_bp)
app.register_blueprint(sign_bp)      # 公開簽名頁 /sign/<token>（免登入）
app.register_blueprint(shipping_bp)
app.register_blueprint(purchases_bp)
app.register_blueprint(transactions_bp)
app.register_blueprint(takeoff_bp)

@app.route("/")
def index():
    if "user" not in session:
        return redirect(url_for("login"))
    try:
        customer_count = len(get_sheet("顧客資料"))
        ac_count       = len(get_sheet("冷氣庫存"))
        gift_count     = len(get_sheet("贈品庫存"))
        quote_count    = len(get_sheet("報價單記錄"))
    except Exception:
        customer_count = ac_count = gift_count = quote_count = 0
    try:
        stats = compute_dashboard(request.args.get("start"), request.args.get("end"))
    except Exception:
        stats = {
            "today": {"income": 0, "expense": 0, "net": 0},
            "week": {"income": 0, "expense": 0, "net": 0},
            "month": {"income": 0, "expense": 0, "net": 0},
            "year": {"income": 0, "expense": 0, "net": 0},
            "trend_labels": [], "trend_income": [], "trend_expense": [],
            "custom_range": None, "custom_start": "", "custom_end": "",
        }
    return render_template("index.html",
        customer_count=customer_count, ac_count=ac_count,
        gift_count=gift_count, quote_count=quote_count,
        stats=stats)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = check_login(request.form.get("username", ""), request.form.get("password", ""))
        if user:
            session["user"] = user
            flash(f"歡迎回來，{user['name']}！")
            return redirect(url_for("index"))
        flash("帳號或密碼錯誤")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/health")
def health():
    from flask import jsonify
    try:
        from db import Customer
        count = Customer.query.count()
        return jsonify({"status": "ok", "customers": count}), 200
    except Exception as e:
        return jsonify({"status": "error", "detail": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
