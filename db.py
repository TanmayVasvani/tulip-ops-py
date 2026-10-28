"""Database layer for Tulip Ops. All reads and transactional writes."""
import sqlite3
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
DATA.mkdir(exist_ok=True)
DB_PATH = DATA / "factory.db"

STAGES = ["molding", "tufting", "trimming", "packing"]


def _init_schema():
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA journal_mode = WAL")
    con.executescript((BASE / "schema.sql").read_text(encoding="utf-8"))
    con.close()


_init_schema()  # once at import — never per request


def get_db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 15000")
    return con


def _exists(con, table, id_):
    if id_ is None:
        return None
    row = con.execute(f"SELECT 1 FROM {table} WHERE id=?", (id_,)).fetchone()
    return id_ if row else None


# ---------- reads ----------

def get_products(con):
    return con.execute("SELECT * FROM products WHERE active=1 ORDER BY sku").fetchall()


def get_machines(con):
    return con.execute("SELECT * FROM machines ORDER BY code").fetchall()


def get_workers(con):
    return con.execute("SELECT * FROM workers WHERE active=1 ORDER BY name").fetchall()


def get_materials(con):
    return con.execute("SELECT * FROM materials ORDER BY name_en").fetchall()


def get_active_batches(con):
    return con.execute("""
        SELECT b.*, p.name_en AS product_en, p.name_gu AS product_gu, p.sku,
          COALESCE((SELECT SUM(qty_ok) FROM stage_logs WHERE batch_id=b.id AND stage=b.current_stage),0) AS done_qty
        FROM batches b JOIN products p ON p.id=b.product_id
        WHERE b.current_stage != 'done' ORDER BY b.id DESC
    """).fetchall()


def get_recent_done_batches(con, limit=5):
    return con.execute("""
        SELECT b.*, p.name_en AS product_en, p.name_gu AS product_gu, p.sku
        FROM batches b JOIN products p ON p.id=b.product_id
        WHERE b.current_stage='done' ORDER BY b.id DESC LIMIT ?
    """, (limit,)).fetchall()


def get_open_orders(con):
    return con.execute("""
        SELECT o.*, p.name_en AS product_en, p.name_gu AS product_gu, p.sku, p.stock_qty
        FROM orders o JOIN products p ON p.id=o.product_id
        WHERE o.status != 'done' ORDER BY o.id DESC
    """).fetchall()


def get_recent_dispatches(con, limit=8):
    return con.execute("""
        SELECT d.*, o.order_no, o.customer, p.name_en AS product_en, p.name_gu AS product_gu
        FROM dispatches d JOIN orders o ON o.id=d.order_id JOIN products p ON p.id=o.product_id
        ORDER BY d.id DESC LIMIT ?
    """, (limit,)).fetchall()


def get_recent_qc_checks(con, limit=10):
    return con.execute("""
        SELECT q.*, b.batch_no, w.name AS worker_name
        FROM qc_checks q JOIN batches b ON b.id=q.batch_id
        LEFT JOIN workers w ON w.id=q.worker_id
        ORDER BY q.id DESC LIMIT ?
    """, (limit,)).fetchall()


def get_low_stock_materials(con):
    return con.execute(
        "SELECT * FROM materials WHERE current_qty <= reorder_level ORDER BY name_en"
    ).fetchall()


def get_today_stats(con):
    one = lambda sql, *a: con.execute(sql, a).fetchone()[0]
    packed = one("SELECT COALESCE(SUM(qty_ok),0) FROM stage_logs WHERE stage='packing' AND date(created_at)=date('now','localtime')")
    scrap = one("SELECT COALESCE(SUM(qty_scrap),0) FROM stage_logs WHERE date(created_at)=date('now','localtime')")
    qc = con.execute("SELECT COALESCE(SUM(sample_size),0) AS s, COALESCE(SUM(failed),0) AS f FROM qc_checks WHERE date(created_at)=date('now','localtime')").fetchone()
    stage_out = {
        s: one("SELECT COALESCE(SUM(qty_ok),0) FROM stage_logs WHERE stage=? AND date(created_at)=date('now','localtime')", s)
        for s in STAGES
    }
    return {
        "packed_today": packed,
        "scrap_today": scrap,
        "qc_fail_pct": round(qc["f"] / qc["s"] * 100, 1) if qc["s"] else 0,
        "qc_samples": qc["s"],
        "active_batches": one("SELECT COUNT(*) FROM batches WHERE current_stage!='done'"),
        "low_stock": one("SELECT COUNT(*) FROM materials WHERE current_qty <= reorder_level"),
        "pending_orders": one("SELECT COUNT(*) FROM orders WHERE status!='done'"),
        "stage_out": stage_out,
    }


# ---------- writes (each commits its own transaction) ----------

def create_batch(con, product_id: int, target_qty: int):
    from datetime import date
    if not _exists(con, "products", product_id):
        return None
    mmdd = date.today().strftime("%m%d")
    for attempt in range(20):  # numbering race: recompute and retry on collision
        n = con.execute(
            "SELECT COALESCE(MAX(CAST(substr(batch_no, -2) AS INTEGER)), 0) FROM batches "
            "WHERE date(created_at)=date('now','localtime')").fetchone()[0]
        batch_no = f"B-{mmdd}-{n + 1 + attempt:02d}"
        try:
            with con:
                con.execute("INSERT INTO batches (batch_no, product_id, target_qty) VALUES (?,?,?)",
                            (batch_no, product_id, target_qty))
            return batch_no
        except sqlite3.IntegrityError:
            continue
    return None


def log_stage_work(con, batch_id, machine_id, worker_id, shift, qty_ok, qty_scrap):
    batch = con.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
    if not batch or batch["current_stage"] == "done":
        return
    stage = batch["current_stage"]
    machine_id = _exists(con, "machines", machine_id)
    worker_id = _exists(con, "workers", worker_id)
    with con:
        con.execute(
            "INSERT INTO stage_logs (batch_id, stage, machine_id, worker_id, shift, qty_ok, qty_scrap) VALUES (?,?,?,?,?,?,?)",
            (batch_id, stage, machine_id, worker_id, shift, qty_ok, qty_scrap))
        if stage == "packing" and qty_ok > 0:
            con.execute("UPDATE products SET stock_qty = stock_qty + ? WHERE id=?",
                        (qty_ok, batch["product_id"]))


def advance_batch(con, batch_id):
    batch = con.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
    if not batch or batch["current_stage"] == "done":
        return
    idx = STAGES.index(batch["current_stage"])
    nxt = "done" if idx >= len(STAGES) - 1 else STAGES[idx + 1]
    with con:
        con.execute("UPDATE batches SET current_stage=? WHERE id=?", (nxt, batch_id))


def add_qc_check(con, batch_id, worker_id, sample_size, failed, defect_type, action, note):
    batch = con.execute("SELECT current_stage FROM batches WHERE id=?", (batch_id,)).fetchone()
    if not batch:
        return
    stage = "packing" if batch["current_stage"] == "done" else batch["current_stage"]
    worker_id = _exists(con, "workers", worker_id)
    with con:
        con.execute(
            "INSERT INTO qc_checks (batch_id, stage, worker_id, sample_size, failed, defect_type, action, note) VALUES (?,?,?,?,?,?,?,?)",
            (batch_id, stage, worker_id, sample_size, failed, defect_type, action, note))


def move_stock(con, material_id, type_, qty, note=None):
    if type_ not in ("in", "out") or not _exists(con, "materials", material_id):
        return
    delta = qty if type_ == "in" else -qty
    with con:
        con.execute("INSERT INTO stock_moves (material_id, type, qty, note) VALUES (?,?,?,?)",
                    (material_id, type_, qty, note))
        con.execute("UPDATE materials SET current_qty = MAX(0, current_qty + ?) WHERE id=?",
                    (delta, material_id))


def create_order(con, customer, product_id, qty):
    if not _exists(con, "products", product_id):
        return None
    for attempt in range(20):
        n = con.execute("SELECT COALESCE(MAX(id), 0) FROM orders").fetchone()[0]
        order_no = f"SO-{n + 1 + attempt:04d}"
        try:
            with con:
                con.execute("INSERT INTO orders (order_no, customer, product_id, qty) VALUES (?,?,?,?)",
                            (order_no, customer, product_id, qty))
            return order_no
        except sqlite3.IntegrityError:
            continue
    return None


def create_dispatch(con, order_id, qty, vehicle, lr_no):
    order = con.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order or order["status"] == "done":
        return
    send_qty = min(qty, order["qty"] - order["dispatched_qty"])
    if send_qty <= 0:
        return
    new_dispatched = order["dispatched_qty"] + send_qty
    status = "done" if new_dispatched >= order["qty"] else "partial"
    with con:
        con.execute("INSERT INTO dispatches (order_id, qty, vehicle, lr_no) VALUES (?,?,?,?)",
                    (order_id, send_qty, vehicle, lr_no))
        con.execute("UPDATE products SET stock_qty = MAX(0, stock_qty - ?) WHERE id=?",
                    (send_qty, order["product_id"]))
        con.execute("UPDATE orders SET dispatched_qty=?, status=? WHERE id=?",
                    (new_dispatched, status, order_id))


def fmt_in(n) -> str:
    """Indian digit grouping: 1234567 -> 12,34,567"""
    n = int(n)
    s, sign = str(abs(n)), "-" if n < 0 else ""
    if len(s) <= 3:
        return sign + s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return sign + ",".join(parts + [tail])
