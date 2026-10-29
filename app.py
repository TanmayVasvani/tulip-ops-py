"""Tulip Ops. Run: python app.py  (serves on 0.0.0.0:3000)"""
from datetime import datetime
import json
import os
import time
from urllib.parse import quote
import urllib.request

from flask import Flask, g, redirect, render_template, request, make_response

import db as d
from i18n import DEFECTS, make_t, pick_name

app = Flask(__name__)

VISION_URL = os.environ.get("VISION_URL", "http://127.0.0.1:8600").rstrip("/")
_vision_cache = {"at": 0.0, "data": None}


# ---------- per-request plumbing ----------

@app.before_request
def before():
    g.con = d.get_db()
    g.lang = "en" if request.cookies.get("lang") == "en" else "gu"


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
                           products=d.get_products(g.con))


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
    return render_template("dispatch.html",
                           products=d.get_products(g.con),
                           orders=d.get_open_orders(g.con),
                           dispatches=dispatches, notes=notes)


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
        d.create_order(g.con, customer, pid, qty)
    return redirect("/dispatch")


@app.post("/dispatch/new")
def dispatch_new():
    oid, qty = form_id("orderId"), form_int("qty")
    if oid and qty > 0:
        vehicle = (request.form.get("vehicle") or "").strip() or None
        lr_no = (request.form.get("lrNo") or "").strip() or None
        d.create_dispatch(g.con, oid, qty, vehicle, lr_no)
    return redirect("/dispatch")


if __name__ == "__main__":
    from waitress import serve
    print("Tulip Ops running → http://0.0.0.0:3000  (open http://<laptop-ip>:3000 on phones)")
    serve(app, host="0.0.0.0", port=3000)
