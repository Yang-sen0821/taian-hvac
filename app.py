import os
from flask import Flask, render_template, request, redirect, url_for, session, flash
from config import SECRET_KEY
from db import db
from auth import check_login
from sheets_client import get_sheet
from blueprints.customers import customers_bp
from blueprints.inventory import inventory_bp
from blueprints.quotations import quotations_bp
from blueprints.shipping import shipping_bp
from blueprints.purchases import purchases_bp
from blueprints.transactions import transactions_bp, compute_dashboard

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'postgresql://postgres:H4m*zp.fX5ZkCyT@db.dosmfcgztoybstrydxkr.supabase.co:5432/postgres')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

# 啟動時確保資料表存在：新增表（quotation_groups/quotation_items/shipping_items）為非破壞性，
# 既有表 create_all 會自動略過、不改不刪。失敗不阻擋啟動（DB 暫時不可達時 app 仍能起來）。
with app.app_context():
    try:
        db.create_all()
    except Exception as e:
        print(f"[init] create_all skipped: {e}")

app.register_blueprint(customers_bp)
app.register_blueprint(inventory_bp)
app.register_blueprint(quotations_bp)
app.register_blueprint(shipping_bp)
app.register_blueprint(purchases_bp)
app.register_blueprint(transactions_bp)

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
