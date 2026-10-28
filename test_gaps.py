"""Tests against a live Tulip Ops server on :3000."""
import sqlite3
import threading
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "http://localhost:3000"
DB = Path(__file__).resolve().parent / "data" / "factory.db"

# Guard: this suite INJECTS test batches/orders. Never run it against real factory data.
import os
if DB.exists():
    _c = sqlite3.connect(DB)
    _has = _c.execute("SELECT name FROM sqlite_master WHERE name='batches'").fetchone()
    _n = _c.execute("SELECT COUNT(*) FROM batches").fetchone()[0] if _has else 0
    _c.close()
    if _n and not os.environ.get("TULIP_TEST_FORCE"):
        raise SystemExit(
            f"Refusing to run: data/factory.db already has {_n} batches and this suite writes test data.\n"
            "Delete/point at a scratch database, or set TULIP_TEST_FORCE=1 if you are sure.")
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not cond else ""))


def get(path, lang=None):
    req = urllib.request.Request(BASE + path)
    if lang:
        req.add_header("Cookie", f"lang={lang}")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")


def post(path, data):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(BASE + path, data=body, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def q(sql, *a):
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    try:
        return con.execute(sql, a).fetchall()
    finally:
        con.close()


print("== 1. Pages on EMPTY database ==")
for p in ["/", "/production", "/qc", "/inventory", "/dispatch"]:
    code, html = get(p)
    check(f"empty-db GET {p}", code == 200, f"got {code}")
code, html = get("/")
check("empty-db qc rate no div-by-zero", "0%" in html or "0.0%" in html)

print("== 2. Garbage / hostile inputs (server must not 500, DB must not corrupt) ==")
check("batch: no product", post("/batch/new", {"targetQty": "500"}) in (302, 200))
check("batch: negative qty", post("/batch/new", {"productId": "1", "targetQty": "-99"}) in (302, 200))
check("batch: qty is text", post("/batch/new", {"productId": "1", "targetQty": "lots"}) in (302, 200))
check("batch: nonexistent product id", post("/batch/new", {"productId": "999", "targetQty": "100"}) in (302, 200))
check("no batches created by garbage", len(q("SELECT * FROM batches")) == 0, str(len(q("SELECT * FROM batches"))))
check("log: nonexistent batch", post("/batch/log", {"batchId": "42", "qtyOk": "10", "shift": "day"}) in (302, 200))
check("advance: nonexistent batch", post("/batch/advance", {"batchId": "42"}) in (302, 200))
check("qc: nonexistent batch", post("/qc/new", {"batchId": "42", "sampleSize": "10", "action": "pass"}) in (302, 200))
check("qc: bogus action", post("/qc/new", {"batchId": "1", "sampleSize": "10", "action": "explode"}) in (302, 200))
check("stock: bogus type", post("/stock/move", {"materialId": "1", "qty": "5", "type": "sideways"}) in (302, 200))
check("stock: NaN qty", post("/stock/move", {"materialId": "1", "qty": "NaN", "type": "in"}) in (302, 200))
check("order: empty customer", post("/order/new", {"customer": "  ", "productId": "1", "qty": "10"}) in (302, 200))
check("dispatch: nonexistent order", post("/dispatch/new", {"orderId": "9", "qty": "10"}) in (302, 200))
nan_rows = q("SELECT * FROM stock_moves")
check("no stock moves from garbage", len(nan_rows) == 0, str(len(nan_rows)))

print("== 3. Real flow + XSS + unicode ==")
post("/batch/new", {"productId": "1", "targetQty": "1000"})  # needs a product: seed minimal
# seed one product/machine/worker/material directly for flow tests
con = sqlite3.connect(DB)
with con:
    if not con.execute("SELECT 1 FROM products LIMIT 1").fetchone():
        con.execute("INSERT INTO products (sku,name_en,name_gu,stock_qty) VALUES ('T-1','Test Brush','ટેસ્ટ બ્રશ',100)")
        con.execute("INSERT INTO machines (code,stage) VALUES ('IM-01','molding'),('PK-01','packing')")
        con.execute("INSERT INTO workers (name) VALUES ('રમેશભાઈ')")
        con.execute("INSERT INTO materials (name_en,name_gu,unit,current_qty,reorder_level) VALUES ('PP','PP દાણા','kg',100,10)")
con.close()
check("create real batch", post("/batch/new", {"productId": "1", "targetQty": "1000"}) in (200, 302))
bid = q("SELECT id FROM batches ORDER BY id DESC LIMIT 1")[0]["id"]
check("log work on it", post("/batch/log", {"batchId": bid, "machineId": "1", "workerId": "1", "shift": "day", "qtyOk": "300", "qtyScrap": "5"}) in (200, 302))
xss = "<script>alert(1)</script> Traders"
post("/order/new", {"customer": xss, "productId": "1", "qty": "50"})
code, html = get("/dispatch")
check("XSS customer escaped in HTML", "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html)
post("/dispatch/new", {"orderId": q("SELECT id FROM orders ORDER BY id DESC LIMIT 1")[0]["id"], "qty": "20", "vehicle": "GJ-06-A-1"})
code, html = get("/dispatch", lang="gu")
check("wa.me link present + percent-encoded unicode", "wa.me/?text=" in html and "%E0%AA" in html)
code, html = get("/", lang="en")
check("EN toggle renders", "Packed today" in html)
code, html = get("/", lang="gu")
check("GU default renders", "આજે પેક થયું" in html)

print("== 4. Concurrency: 12 parallel batch creates (the race) ==")
errors = []
def hammer(i):
    try:
        c = post("/batch/new", {"productId": "1", "targetQty": str(100 + i)})
        if c >= 500:
            errors.append(c)
    except Exception as e:
        errors.append(str(e))

threads = [threading.Thread(target=hammer, args=(i,)) for i in range(12)]
[t.start() for t in threads]
[t.join() for t in threads]
rows = q("SELECT batch_no, COUNT(*) c FROM batches GROUP BY batch_no HAVING c > 1")
made = q("SELECT COUNT(*) n FROM batches")[0]["n"]
check("no 5xx under parallel creates", not errors, f"errors={errors}")
check("no duplicate batch numbers", len(rows) == 0, f"dupes={[dict(r) for r in rows]}")
check("all 12 batches landed (+2 earlier)", made >= 13, f"made={made}")

print("== 5. Open-redirect probe on /lang ==")
import http.client
conn = http.client.HTTPConnection("localhost", 3000, timeout=10)
conn.request("POST", "/lang", body=urllib.parse.urlencode({"lang": "en", "back": "https://evil.example.com"}),
             headers={"Content-Type": "application/x-www-form-urlencoded"})
resp = conn.getresponse()
loc = resp.getheader("Location") or ""
check("/lang refuses external redirect", "evil.example.com" not in loc, f"Location={loc}")

print()
fails = [r for r in results if not r[1]]
print(f"{len(results) - len(fails)}/{len(results)} passed, {len(fails)} FAILED")
for name, _, detail in fails:
    print(f"  FAIL: {name} {detail}")
