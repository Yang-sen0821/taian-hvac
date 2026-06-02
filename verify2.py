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

print()
print('RESULT: {}/{} passed'.format(ok, ok + err))
sys.exit(0 if err == 0 else 1)
