from functools import wraps
from flask import session, redirect, url_for
from config import USERS

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def check_login(username, password):
    user = USERS.get(username)
    if user and user["password"] == password:
        return {"username": username, **user}
    return None
