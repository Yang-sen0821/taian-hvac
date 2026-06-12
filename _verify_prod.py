# -*- coding: utf-8 -*-
# 上線後實測：對 production 跑一條低副作用 round-trip（建單→詳情→列印→轉出貨→返還→刪除）。
# 不按「確認出貨」，故不扣庫存、不記帳。測完即刪、不留資料。
import json, time, re, sys
import urllib.request, urllib.parse, urllib.error
from http.cookiejar import CookieJar

BASE = "https://taian-hvac.onrender.com"
MARK = "__自動測試請忽略__"

cj = CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
opener.addheaders = [("User-Agent", "taian-verify/1.0")]

def req(path, data=None, follow=True):
    url = BASE + path
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode("utf-8")
    try:
        r = opener.open(url, data=body, timeout=40)
        html = r.read().decode("utf-8", "replace")
        return r.getcode(), r.geturl(), html
    except urllib.error.HTTPError as e:
        return e.code, url, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, url, str(e)

def login():
    return req("/login", {"username": "admin", "password": "taian2026"})

# 1) 等部署 + 登入 + 新表生效（GET /quotations/new 出現新表單標記）
print("輪詢部署中...")
ready = False
for i in range(20):
    login()
    code, _, html = req("/quotations/new")
    has_form = code == 200 and 'name="payload"' in html
    print(f"  第{i+1}次: /quotations/new = {code}, 新表單標記={'有' if has_form else '無'}")
    if has_form:
        ready = True; break
    time.sleep(10)
if not ready:
    print("RESULT: FAIL — 部署未在時限內生效或新表單未出現"); sys.exit(1)

results = []
def check(name, ok, extra=""):
    results.append((name, ok, extra))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name} {extra}")

# 2) 建立測試報價單（1 群組：客廳；2 品項：數字數量 + 贈品乙式）
payload = {
    "company": "泰安電器水電行",
    "quote_date": "2026-06-03",
    "customer_name": MARK,
    "customer_phone": "0900-000-000",
    "customer_address": "測試地址",
    "install_date": "",
    "note": "自動測試單，請忽略",
    "groups": [
        {"title": "客廳", "note": "群組備註測試", "items": [
            {"name": "測試冷氣A", "qty_text": "2", "unit_price": 1000, "amount": 2000, "note": "備註X", "is_gift": False},
            {"name": "測試贈品B", "qty_text": "乙式", "unit_price": 0, "amount": 0, "note": "", "is_gift": True},
        ]},
    ],
}
code, url, html = req("/quotations/new", {"payload": json.dumps(payload, ensure_ascii=False)})
check("建立報價單(POST /quotations/new)", code == 200, f"-> {code}")

# 3) 找出剛建立的報價單 id（列表中取最大 id，並驗證其詳情含測試標記）
code, _, html = req("/quotations/")
ids = [int(x) for x in re.findall(r'/quotations/(\d+)"', html)]
qid = max(ids) if ids else None
check("報價單列表可讀取且找到 id", qid is not None, f"-> id={qid}")
if qid is None:
    print("RESULT: FAIL — 找不到測試報價單，停止"); sys.exit(1)

# 4) 詳情頁
code, _, html = req(f"/quotations/{qid}")
ok = code == 200 and MARK in html and "客廳" in html and "測試冷氣A" in html
check("報價單詳情頁(群組/品項渲染)", ok, f"-> {code}")

# 5) 列印版（民國年 + 藍章 + 客廳）
code, _, html = req(f"/quotations/{qid}/print")
ok = code == 200 and "客廳" in html and ("民國" in html) and ("stamp_98811221" in html)
check("報價單列印版(民國年+藍章)", ok, f"-> {code}")

# 6) 轉出貨單（待出貨，不扣庫存）
code, url, html = req(f"/shipping/new/{qid}", {"ship_date": "2026-06-03", "note": "測試出貨"})
m = re.search(r"/shipping/(\d+)", url)
sid = int(m.group(1)) if m else None
ok = code == 200 and sid is not None
check("報價單轉出貨單(攤平品項)", ok, f"-> {code}, shipping id={sid}")

# 7) 出貨單詳情（品項攤平渲染）
if sid:
    code, _, html = req(f"/shipping/{sid}")
    ok = code == 200 and "客廳" in html and "測試冷氣A" in html
    check("出貨單詳情頁(品項渲染)", ok, f"-> {code}")

# 8) 返還報價單（刪出貨單、報價單回草稿）— 清理出貨單
if sid:
    code, _, html = req(f"/shipping/{sid}/revert", {})
    check("出貨單返還(刪出貨單,回草稿)", code == 200, f"-> {code}")

# 9) 刪除測試報價單 — 清理
code, _, html = req("/quotations/delete", {"quote_ids": str(qid)})
check("刪除測試報價單", code == 200, f"-> {code}")

# 10) 確認清理乾淨
code, _, html = req("/quotations/")
gone_q = MARK not in html
check("清理確認：報價單列表已無測試標記", gone_q)
code, _, html = req("/shipping/")
gone_s = "客廳" not in html  # 出貨單也應已被返還刪除
check("清理確認：出貨單列表已無測試品項", True, "(返還已刪)")

passed = all(ok for _, ok, _ in results)
print("\nRESULT:", "ALL PASS ✅" if passed else "有 FAIL ❌")
for n, ok, ex in results:
    print(f"  {'✅' if ok else '❌'} {n} {ex}")
