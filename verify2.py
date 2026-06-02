import requests, re, sys

BASE = 'http://localhost:5000'
s = requests.Session()
s.post(BASE + '/login', data={'username': 'admin', 'password': 'taian2026'})

tests = [
    ('Dashboard',        BASE + '/'),
    ('Customers',        BASE + '/customers/'),
    ('AC Inventory',     BASE + '/inventory/ac'),
    ('AC New Form',      BASE + '/inventory/ac/new'),
    ('Gift New Form',    BASE + '/inventory/gifts/new'),
    ('Quotation New',    BASE + '/quotations/new'),
    ('Quotation List',   BASE + '/quotations/'),
    ('Shipping List',    BASE + '/shipping/'),
    ('Purchases List',   BASE + '/purchases/'),
    ('Purchases New',    BASE + '/purchases/new'),
    ('Item Prices API',  BASE + '/quotations/api/item-prices?item=test'),
    ('Transactions List', BASE + '/transactions/'),
    ('Transactions New',  BASE + '/transactions/new'),
    ('Inventory Search API', BASE + '/quotations/api/inventory-search?q='),
    ('Inventory Check API',  BASE + '/quotations/api/inventory-check?name=test'),
]

ok = err = 0
for name, url in tests:
    r = s.get(url)
    if r.status_code >= 400:
        e = re.search(r'(UndefinedError|AttributeError|TypeError|TemplateNotFound)[^<\n]{0,60}', r.text)
        msg = e.group(0)[:60] if e else 'unknown error'
        print('FAIL  {}: {} — {}'.format(name, r.status_code, msg))
        err += 1
    else:
        print('OK    {}: {} ({:,} chars)'.format(name, r.status_code, len(r.text)))
        ok += 1

# 詳情頁動態驗收：從列表抓第一筆 id 來測（避免硬寫不存在的 id）
def probe_detail(name, list_url, link_re):
    global ok, err
    lst = s.get(list_url).text
    m = re.search(link_re, lst)
    if not m:
        print('SKIP  {}: 列表無資料可測'.format(name))
        return
    url = BASE + m.group(0)
    r = s.get(url)
    e = re.search(r'(UndefinedError|AttributeError|TypeError|TemplateNotFound)[^<\n]{0,60}', r.text)
    if r.status_code >= 400 or e:
        msg = e.group(0)[:60] if e else 'status {}'.format(r.status_code)
        print('FAIL  {}: {} — {}'.format(name, r.status_code, msg))
        err += 1
    else:
        print('OK    {}: {} ({:,} chars)'.format(name, r.status_code, len(r.text)))
        ok += 1

probe_detail('Quotation Detail', BASE + '/quotations/', r'/quotations/\d+')
probe_detail('Shipping Detail',  BASE + '/shipping/',   r'/shipping/\d+')

print()
print('RESULT: {}/{} passed'.format(ok, ok + err))
sys.exit(0 if err == 0 else 1)
