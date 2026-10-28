"""Seed demo data. Skips if the database already has products."""
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
(BASE / "data").mkdir(exist_ok=True)
con = sqlite3.connect(BASE / "data" / "factory.db")
con.execute("PRAGMA journal_mode = WAL")
con.executescript((BASE / "schema.sql").read_text(encoding="utf-8"))

if con.execute("SELECT COUNT(*) FROM products").fetchone()[0] > 0:
    print("Database already has data — skipping seed. Delete data/factory.db to reseed.")
    raise SystemExit(0)

ago = lambda h: (datetime.now() - timedelta(hours=h)).strftime("%Y-%m-%d %H:%M:%S")

with con:
    con.executemany("INSERT INTO products (sku, name_en, name_gu, stock_qty) VALUES (?,?,?,?)", [
        ("ZEC-PRO-S", "Zecta Pro Soft", "\u0a9d\u0ac7\u0a95\u0acd\u0a9f\u0abe \u0aaa\u0acd\u0ab0\u0acb \u0ab8\u0acb\u0aab\u0acd\u0a9f", 4200),
        ("ZEC-KID", "Zecta Kids", "\u0a9d\u0ac7\u0a95\u0acd\u0a9f\u0abe \u0a95\u0abf\u0aa1\u0acd\u0ab8", 1800),
        ("TUL-CLA-M", "Tulip Classic Medium", "\u0aa4\u0ac1\u0ab2\u0abf\u0aaa \u0a95\u0acd\u0ab2\u0abe\u0ab8\u0abf\u0a95 \u0aae\u0ac0\u0aa1\u0abf\u0aaf\u0aae", 9500),
    ])
    con.executemany("INSERT INTO machines (code, stage) VALUES (?,?)", [
        ("IM-01", "molding"), ("IM-02", "molding"),
        ("TF-01", "tufting"), ("TF-02", "tufting"),
        ("TR-01", "trimming"), ("PK-01", "packing"),
    ])
    con.executemany("INSERT INTO workers (name) VALUES (?)", [
        ("\u0ab0\u0aae\u0ac7\u0ab6\u0aad\u0abe\u0a88",), ("\u0ab8\u0ac1\u0ab0\u0ac7\u0ab6\u0aad\u0abe\u0a88",),
        ("\u0a95\u0abf\u0ab0\u0aa3\u0aac\u0ac7\u0aa8",), ("\u0a9c\u0aaf\u0ac7\u0ab6\u0aad\u0abe\u0a88",),
        ("\u0aa6\u0ac0\u0aaa\u0abf\u0a95\u0abe\u0aac\u0ac7\u0aa8",), ("\u0ab5\u0abf\u0aaa\u0ac1\u0ab2\u0aad\u0abe\u0a88",),
        ("\u0aa8\u0abe\u0ab0\u0aa3\u0aad\u0abe\u0a88",), ("\u0aae\u0ab9\u0ac7\u0ab6\u0aad\u0abe\u0a88",),
    ])
    con.executemany("INSERT INTO materials (name_en, name_gu, unit, current_qty, reorder_level) VALUES (?,?,?,?,?)", [
        ("PP Granules", "PP \u0aa6\u0abe\u0aa3\u0abe (\u0a95\u0abe\u0a9a\u0ac1\u0a82 \u0aaa\u0acd\u0ab2\u0abe\u0ab8\u0acd\u0a9f\u0abf\u0a95)", "kg", 480, 150),
        ("Nylon Filament", "\u0aa8\u0abe\u0aaf\u0ab2\u0acb\u0aa8 \u0aab\u0abf\u0ab2\u0abe\u0aae\u0ac7\u0aa8\u0acd\u0a9f (\u0aac\u0acd\u0ab0\u0abf\u0ab8\u0ab2)", "kg", 26, 30),
        ("Anchor Wire", "\u0a8f\u0aa8\u0acd\u0a95\u0ab0 \u0ab5\u0abe\u0aaf\u0ab0", "kg", 42, 10),
        ("Blister Film", "\u0aac\u0acd\u0ab2\u0abf\u0ab8\u0acd\u0a9f\u0ab0 \u0aab\u0abf\u0ab2\u0acd\u0aae", "roll", 14, 5),
        ("Inner Cartons", "\u0aa8\u0abe\u0aa8\u0abe \u0a96\u0acb\u0a96\u0abe", "pcs", 320, 400),
        ("Master Cartons", "\u0aae\u0acb\u0a9f\u0abe \u0a96\u0acb\u0a96\u0abe", "pcs", 210, 80),
    ])
    con.executemany("INSERT INTO batches (batch_no, product_id, target_qty, current_stage, created_at) VALUES (?,?,?,?,?)", [
        ("B-0708-01", 3, 10000, "tufting", ago(50)),
        ("B-0706-02", 1, 5000, "packing", ago(96)),
        ("B-0710-01", 2, 4000, "molding", ago(5)),
        ("B-0702-01", 3, 8000, "done", ago(190)),
    ])
    con.executemany("INSERT INTO stage_logs (batch_id, stage, machine_id, worker_id, shift, qty_ok, qty_scrap, created_at) VALUES (?,?,?,?,?,?,?,?)", [
        (1, "molding", 1, 1, "day", 5200, 80, ago(48)),
        (1, "molding", 2, 2, "night", 4800, 110, ago(38)),
        (1, "tufting", 3, 3, "day", 3600, 45, ago(26)),
        (1, "tufting", 4, 4, "day", 2400, 30, ago(4)),
        (2, "molding", 1, 5, "day", 5100, 60, ago(90)),
        (2, "tufting", 3, 6, "day", 5000, 70, ago(70)),
        (2, "trimming", 5, 7, "day", 4930, 55, ago(50)),
        (2, "packing", 6, 8, "day", 2200, 15, ago(6)),
        (2, "packing", 6, 3, "day", 950, 5, ago(2)),
        (3, "molding", 2, 1, "day", 1400, 25, ago(3)),
    ])
    con.executemany("INSERT INTO qc_checks (batch_id, stage, worker_id, sample_size, failed, defect_type, action, created_at) VALUES (?,?,?,?,?,?,?,?)", [
        (1, "tufting", 3, 100, 2, "looseBristle", "pass", ago(25)),
        (2, "trimming", 7, 80, 6, "sharpEnds", "rework", ago(49)),
        (2, "packing", 8, 120, 1, None, "pass", ago(5)),
        (3, "molding", 1, 60, 3, "flash", "pass", ago(2)),
    ])
    con.executemany("INSERT INTO orders (order_no, customer, product_id, qty, dispatched_qty, status, created_at) VALUES (?,?,?,?,?,?,?)", [
        ("SO-0001", "Sharma Traders, Surat", 3, 12000, 8000, "partial", ago(160)),
        ("SO-0002", "MediPlus Pharmacy, Vadodara", 1, 3000, 0, "pending", ago(20)),
    ])
    con.execute("INSERT INTO dispatches (order_id, qty, vehicle, lr_no, created_at) VALUES (?,?,?,?,?)",
                (1, 8000, "GJ-06-XT-4521", "LR-88213", ago(30)))

print("Seeded: 3 products, 6 machines, 8 workers, 6 materials, 4 batches, 4 QC checks, 2 orders, 1 dispatch.")
