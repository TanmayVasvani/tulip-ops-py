"""Tulip Ops. Run: python app.py  (serves on 0.0.0.0:3000)"""
from datetime import datetime, date
import csv
import io
import json
import os
import time
from urllib.parse import quote
import urllib.request

from flask import Flask, g, redirect, render_template, request, make_response, session, Response

import db as d
from i18n import DEFECTS, make_t, pick_name
from pdf import text_pdf

app = Flask(__name__)
app.secret_key = os.environ.get("TULIP_SECRET", "tulip-ops-lan")

VISION_URL = os.environ.get("VISION_URL", "http://127.0.0.1:8600").rstrip("/")
_vision_cache = {"at": 0.0, "data": None}


# ---------- per-request plumbing ----------

@app.before_request
def before():
    g.con = d.get_db()
    g.lang = "en" if request.cookies.get("lang") == "en" else "gu"
    g.user = d.get_user(g.con, session.get("uid"))
    open_paths = {"/login", "/setup", "/lang"}
    if request.path.startswith("/static") or request.path in open_paths:
        return
    if d.user_count(g.con) and not g.user:
        return redirect("/login")


def supervisor():
    return g.user and g.user["role"] == "supervisor"


@app.teardown_request
def teardown(exc):
    con = g.pop("con", None)
    if con is not None:
        con.close()


@app.context_processor
def inject():
    return {
        "t": make_t(g.lang),
        "lang": g.lang,
        "pick": lambda en, gu: pick_name(g.lang, en, gu),
        "fmt": d.fmt_in,
        "STAGES": d.STAGES,
        "DEFECTS": DEFECTS,
        "path": request.path,
        "user": getattr(g, "user", None),
        "is_supervisor": bool(getattr(g, "user", None) and g.user["role"] == "supervisor"),
    }


def form_int(name, default=0):
    try:
        return max(0, int(float(request.form.get(name, default))))
    except (TypeError, ValueError):
        return default


def form_id(name):
    v = form_int(name, 0)
    return v if v > 0 else None


def vision_stats():
    """Today's numbers from the Tulip Vision station. None if not configured.

    A down station returns {"offline": True} and is cached briefly, so a
    missing station never stalls the dashboard.
    """
    if not VISION_URL:
        return None
    now = time.monotonic()
    if now - _vision_cache["at"] < 15:
        return _vision_cache["data"]
    data = {"offline": True}
    try:
        req = urllib.request.Request(
            VISION_URL + "/api/stats", headers={"Accept": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=0.6) as resp:
            payload = json.loads(resp.read().decode())
        if isinstance(payload, dict) and "inspections" in payload:
            data = payload
    except (OSError, ValueError, json.JSONDecodeError):
        data = {"offline": True}
    _vision_cache["at"] = now
    _vision_cache["data"] = data
    return data


# ---------- pages ----------

@app.get("/")
def dashboard():
    t = make_t(g.lang)
    stats = d.get_today_stats(g.con)
    batches = d.get_active_batches(g.con)
    low = d.get_low_stock_materials(g.con)
    vision = vision_stats()
    date_str = datetime.now().strftime("%d %b %Y")

    lines = [
        f"🪥 {t('appName')} — {date_str}",
        f"{t('packedToday')}: {d.fmt_in(stats['packed_today'])} {t('pieces')}",
        *[f"• {t(s)}: {d.fmt_in(stats['stage_out'][s])} {t('pieces')}" for s in d.STAGES],
        f"{t('scrapToday')}: {d.fmt_in(stats['scrap_today'])} {t('pieces')}",
        f"{t('qcFailRate')}: {stats['qc_fail_pct']}% ({stats['qc_samples']} {t('samplesChecked')})",
        f"{t('activeBatches')}: {stats['active_batches']} | {t('pendingOrders')}: {stats['pending_orders']}",
    ]
    if vision and not vision.get("offline"):
        rate = round(vision.get("reject_rate", 0) * 100, 1)
        lines.append(
            f"{t('vision')}: {d.fmt_in(vision.get('inspections', 0))} {t('visionInspected')}, "
            f"{d.fmt_in(vision.get('rejects', 0))} {t('visionRejects')} ({rate}%)"
        )
    if low:
        names = ", ".join(pick_name(g.lang, m["name_en"], m["name_gu"]) for m in low)
        lines.append(f"⚠️ {t('lowStockItems')}: {names}")
    wa_href = "https://wa.me/?text=" + quote("\n".join(lines))

    return render_template("dashboard.html", stats=stats, batches=batches,
                           low=low, vision=vision, date_str=date_str, wa_href=wa_href)


@app.get("/production")
def production():
    hour = datetime.now().hour
    return render_template(
        "production.html",
        products=d.get_products(g.con),
        machines=d.get_machines(g.con),
        workers=d.get_workers(g.con),
        batches=d.get_active_batches(g.con),
        done_batches=d.get_recent_done_batches(g.con),
        default_shift="day" if 7 <= hour < 19 else "night",
    )


@app.get("/qc")
def qc():
    return render_template("qc.html",
                           batches=d.get_active_batches(g.con),
                           workers=d.get_workers(g.con),
                           checks=d.get_recent_qc_checks(g.con))


@app.get("/inventory")
def inventory():
    return render_template("inventory.html",
                           materials=d.get_materials(g.con),
                           products=d.get_products(g.con),
                           bom=d.get_bom(g.con))


@app.get("/dispatch")
def dispatch():
    dispatches = d.get_recent_dispatches(g.con)
    t = make_t(g.lang)
    notes = {}
    for row in dispatches:
        lines = [
            f"📦 {t('appName')} — {row['order_no']}",
            f"{t('customer')}: {row['customer']}",
            f"{t('product')}: {pick_name(g.lang, row['product_en'], row['product_gu'])}",
            f"{t('qty')}: {d.fmt_in(row['qty'])} {t('pieces')}",
        ]
        if row["vehicle"]:
            lines.append(f"{t('vehicle')}: {row['vehicle']}")
        if row["lr_no"]:
            lines.append(f"{t('lrNo')}: {row['lr_no']}")
        lines.append(row["created_at"])
        notes[row["id"]] = "https://wa.me/?text=" + quote("\n".join(lines))
    invoices = {
        row["id"]: d.get_invoice(g.con, row["id"])
        for row in dispatches
    }
    return render_template("dispatch.html",
                           products=d.get_products(g.con),
                           orders=d.get_open_orders(g.con),
                           dispatches=dispatches, notes=notes, invoices=invoices)


# ---------- actions ----------

@app.errorhandler(500)
def server_error(e):
    return ("<meta charset='utf-8'><body style='font-family:system-ui;padding:2rem'>"
            "<h2>કંઈક ખોટું થયું / Something went wrong</h2>"
            "<p><a href='/'>&larr; હોમ / Home</a></p></body>", 500)


@app.post("/lang")
def set_lang():
    lang = "en" if request.form.get("lang") == "en" else "gu"
    back = request.form.get("back", "/")
    if not back.startswith("/") or back.startswith("//"):
        back = "/"
    resp = make_response(redirect(back))
    resp.set_cookie("lang", lang, max_age=365 * 24 * 3600, path="/")
    return resp


@app.post("/batch/new")
def batch_new():
    pid, qty = form_id("productId"), form_int("targetQty")
    if pid and qty > 0:
        d.create_batch(g.con, pid, qty)
    return redirect("/production")


@app.post("/batch/log")
def batch_log():
    bid = form_id("batchId")
    ok, scrap = form_int("qtyOk"), form_int("qtyScrap")
    if bid and (ok > 0 or scrap > 0):
        shift = request.form.get("shift", "day")
        d.log_stage_work(g.con, bid, form_id("machineId"), form_id("workerId"),
                         shift if shift in ("day", "night") else "day", ok, scrap)
    return redirect("/production")


@app.post("/batch/advance")
def batch_advance():
    bid = form_id("batchId")
    if bid:
        d.advance_batch(g.con, bid)
    return redirect("/production")


@app.post("/qc/new")
def qc_new():
    bid, sample = form_id("batchId"), form_int("sampleSize")
    failed = min(form_int("failed"), sample)
    action = request.form.get("action", "pass")
    if bid and sample > 0 and action in ("pass", "rework", "reject"):
        defect = request.form.get("defectType") or None
        note = (request.form.get("note") or "").strip() or None
        d.add_qc_check(g.con, bid, form_id("workerId"), sample, failed,
                       defect if failed > 0 else None, action, note)
    return redirect("/qc")


@app.post("/stock/move")
def stock_move():
    mid = form_id("materialId")
    try:
        qty = float(request.form.get("qty", 0))
    except (TypeError, ValueError):
        qty = 0
    if mid and qty > 0:
        d.move_stock(g.con, mid, request.form.get("type", ""), qty)
    return redirect("/inventory")


@app.post("/order/new")
def order_new():
    customer = (request.form.get("customer") or "").strip()
    pid, qty = form_id("productId"), form_int("qty")
    if customer and pid and qty > 0:
        gstin = (request.form.get("gstin") or "").strip() or None
        state = (request.form.get("state") or "").strip() or None
        d.create_order(g.con, customer, pid, qty, gstin, state)
    return redirect("/dispatch")


@app.post("/dispatch/new")
def dispatch_new():
    oid, qty = form_id("orderId"), form_int("qty")
    if oid and qty > 0:
        vehicle = (request.form.get("vehicle") or "").strip() or None
        lr_no = (request.form.get("lrNo") or "").strip() or None
        d.create_dispatch(g.con, oid, qty, vehicle, lr_no)
    return redirect("/dispatch")


@app.get("/login")
def login():
    if g.user:
        return redirect("/")
    return render_template("login.html", error=None)


@app.post("/login")
def login_post():
    user = d.find_user(g.con, request.form.get("name", ""), request.form.get("pin", ""))
    if not user:
        return render_template("login.html", error=True)
    session["uid"] = user["id"]
    return redirect("/")


@app.post("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.get("/setup")
def setup():
    if d.user_count(g.con):
        return redirect("/login")
    return render_template("setup.html")


@app.post("/setup")
def setup_post():
    if d.user_count(g.con):
        return redirect("/login")
    name = (request.form.get("name") or "").strip()
    pin = (request.form.get("pin") or "").strip()
    if name and pin.isdigit() and len(pin) >= 4:
        with g.con:
            g.con.execute(
                "INSERT INTO users (name, pin_hash, role) VALUES (?,?,?)",
                (name, d.hash_pin(pin), "supervisor"),
            )
        return redirect("/login")
    return render_template("setup.html")


@app.get("/settings")
def settings():
    if not supervisor():
        return redirect("/")
    keys = ("company", "gstin", "address", "state_code")
    current = {k: d.get_setting(g.con, k, "24" if k == "state_code" else "") for k in keys}
    return render_template("settings.html", current=current, products=d.get_products(g.con))


@app.post("/settings")
def settings_post():
    if not supervisor():
        return redirect("/")
    for key in ("company", "gstin", "address", "state_code"):
        d.set_setting(g.con, key, (request.form.get(key) or "").strip())
    return redirect("/settings")


@app.post("/product/rate")
def product_rate():
    if not supervisor():
        return redirect("/")
    pid = form_id("productId")
    if pid:
        try:
            rate = float(request.form.get("rate") or 0)
            gst = float(request.form.get("gstRate") or 18)
        except ValueError:
            rate, gst = 0, 18
        hsn = (request.form.get("hsn") or "").strip() or None
        with g.con:
            g.con.execute(
                "UPDATE products SET rate=?, gst_rate=?, hsn=? WHERE id=?",
                (rate, gst, hsn, pid),
            )
    return redirect("/settings")


@app.post("/bom")
def bom_save():
    if not supervisor():
        return redirect("/")
    pid, mid = form_id("productId"), form_id("materialId")
    try:
        qty = float(request.form.get("qtyPer1000") or 0)
    except ValueError:
        qty = 0
    if pid and mid:
        d.set_bom_line(g.con, pid, mid, qty)
    return redirect("/inventory")


@app.get("/invoice/<int:dispatch_id>")
def invoice(dispatch_id):
    row = d.get_invoice(g.con, dispatch_id)
    if not row:
        return redirect("/dispatch")
    company = {
        "name": d.get_setting(g.con, "company", "Tulip Enterprise"),
        "gstin": d.get_setting(g.con, "gstin", ""),
        "address": d.get_setting(g.con, "address", "Vadodara, Gujarat"),
        "state": d.get_setting(g.con, "state_code", "24"),
    }
    return render_template("invoice.html", inv=row, company=company)


@app.get("/invoice/<int:dispatch_id>.pdf")
def invoice_pdf(dispatch_id):
    row = d.get_invoice(g.con, dispatch_id)
    if not row:
        return redirect("/dispatch")
    lines = [
        d.get_setting(g.con, "company", "Tulip Enterprise"),
        d.get_setting(g.con, "address", "Vadodara, Gujarat"),
        "GSTIN " + d.get_setting(g.con, "gstin", "-"),
        "",
        f"Tax invoice {row['invoice_no']}",
        f"Order {row['order_no']}  {row['dispatched_at']}",
        f"Customer: {row['customer']}",
        f"Customer GSTIN: {row['customer_gstin'] or '-'}",
        "",
        f"{row['sku']}  HSN {row['hsn'] or '-'}",
        f"Qty {row['qty']}  Rate {row['rate']:.2f}  GST {row['gst_rate']:.0f}%",
        f"Taxable {row['taxable']:.2f}",
        f"CGST {row['cgst']:.2f}  SGST {row['sgst']:.2f}  IGST {row['igst']:.2f}",
        f"Total {row['total']:.2f}",
    ]
    body = text_pdf(lines)
    return Response(body, mimetype="application/pdf",
                    headers={"Content-Disposition": f"inline; filename={row['invoice_no']}.pdf"})


def _dates():
    today = date.today().isoformat()
    start = request.args.get("from") or today
    end = request.args.get("to") or today
    return start, end


@app.get("/reports")
def reports():
    if not supervisor():
        return redirect("/")
    start, end = _dates()
    return render_template(
        "reports.html", start=start, end=end,
        production=d.report_production(g.con, start, end),
        qc=d.report_qc(g.con, start, end),
        stock=d.report_stock(g.con, start, end),
        dispatch=d.report_dispatch(g.con, start, end),
    )


def _csv(name, header, rows):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    return Response(
        buf.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={name}.csv"},
    )


@app.get("/reports/<kind>.csv")
def report_csv(kind):
    if not supervisor():
        return redirect("/")
    start, end = _dates()
    if kind == "production":
        rows = d.report_production(g.con, start, end)
        return _csv("production", ["day", "stage", "qty_ok", "qty_scrap"],
                    [(r["day"], r["stage"], r["qty_ok"], r["qty_scrap"]) for r in rows])
    if kind == "qc":
        rows = d.report_qc(g.con, start, end)
        return _csv("qc", ["day", "stage", "action", "samples", "failed"],
                    [(r["day"], r["stage"], r["action"], r["samples"], r["failed"]) for r in rows])
    if kind == "stock":
        rows = d.report_stock(g.con, start, end)
        return _csv("stock", ["day", "material", "unit", "type", "qty"],
                    [(r["day"], r["name_en"], r["unit"], r["type"], r["qty"]) for r in rows])
    if kind == "dispatch":
        rows = d.report_dispatch(g.con, start, end)
        return _csv("dispatch", ["day", "order", "customer", "sku", "qty", "invoice", "total"],
                    [(r["day"], r["order_no"], r["customer"], r["sku"], r["qty"], r["invoice_no"], r["total"]) for r in rows])
    return redirect("/reports")


@app.get("/reports.pdf")
def reports_pdf():
    if not supervisor():
        return redirect("/")
    start, end = _dates()
    lines = [f"Tulip Ops  {start} to {end}", ""]
    lines.append("Production")
    for r in d.report_production(g.con, start, end):
        lines.append(f"  {r['day']}  {r['stage']}  ok {r['qty_ok']}  scrap {r['qty_scrap']}")
    lines.append("")
    lines.append("QC")
    for r in d.report_qc(g.con, start, end):
        lines.append(f"  {r['day']}  {r['stage']}  {r['action']}  {r['failed']}/{r['samples']}")
    lines.append("")
    lines.append("Dispatch")
    for r in d.report_dispatch(g.con, start, end):
        lines.append(f"  {r['day']}  {r['order_no']}  {r['sku']}  {r['qty']}  {r['invoice_no'] or '-'}")
    body = text_pdf(lines)
    return Response(body, mimetype="application/pdf",
                    headers={"Content-Disposition": "inline; filename=report.pdf"})


if __name__ == "__main__":
    from waitress import serve
    print("Tulip Ops running → http://0.0.0.0:3000  (open http://<laptop-ip>:3000 on phones)")
    serve(app, host="0.0.0.0", port=3000)
