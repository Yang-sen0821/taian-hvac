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

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'postgresql://postgres:H4m*zp.fX5ZkCyT@db.dosmfcgztoybstrydxkr.supabase.co:5432/postgres')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

app.register_blueprint(customers_bp)
app.register_blueprint(inventory_bp)
app.register_blueprint(quotations_bp)
app.register_blueprint(shipping_bp)
app.register_blueprint(purchases_bp)

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
    return render_template("index.html",
        customer_count=customer_count, ac_count=ac_count,
        gift_count=gift_count, quote_count=quote_count)

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
