CREATE TABLE IF NOT EXISTS products (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sku TEXT NOT NULL UNIQUE,
  name_en TEXT NOT NULL,
  name_gu TEXT NOT NULL,
  stock_qty INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS machines (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL UNIQUE,
  stage TEXT NOT NULL CHECK (stage IN ('molding','tufting','trimming','packing'))
);
CREATE TABLE IF NOT EXISTS workers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS materials (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name_en TEXT NOT NULL,
  name_gu TEXT NOT NULL,
  unit TEXT NOT NULL,
  current_qty REAL NOT NULL DEFAULT 0,
  reorder_level REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS stock_moves (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  material_id INTEGER NOT NULL REFERENCES materials(id),
  type TEXT NOT NULL CHECK (type IN ('in','out')),
  qty REAL NOT NULL,
  note TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS batches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_no TEXT NOT NULL UNIQUE,
  product_id INTEGER NOT NULL REFERENCES products(id),
  target_qty INTEGER NOT NULL,
  current_stage TEXT NOT NULL DEFAULT 'molding'
    CHECK (current_stage IN ('molding','tufting','trimming','packing','done')),
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS stage_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id INTEGER NOT NULL REFERENCES batches(id),
  stage TEXT NOT NULL,
  machine_id INTEGER REFERENCES machines(id),
  worker_id INTEGER REFERENCES workers(id),
  shift TEXT NOT NULL,
  qty_ok INTEGER NOT NULL DEFAULT 0,
  qty_scrap INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS qc_checks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id INTEGER NOT NULL REFERENCES batches(id),
  stage TEXT NOT NULL,
  worker_id INTEGER REFERENCES workers(id),
  sample_size INTEGER NOT NULL,
  failed INTEGER NOT NULL DEFAULT 0,
  defect_type TEXT,
  action TEXT NOT NULL CHECK (action IN ('pass','rework','reject')),
  note TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_no TEXT NOT NULL UNIQUE,
  customer TEXT NOT NULL,
  product_id INTEGER NOT NULL REFERENCES products(id),
  qty INTEGER NOT NULL,
  dispatched_qty INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','partial','done')),
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS dispatches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id INTEGER NOT NULL REFERENCES orders(id),
  qty INTEGER NOT NULL,
  vehicle TEXT,
  lr_no TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  pin_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('worker','supervisor')),
  worker_id INTEGER REFERENCES workers(id),
  active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS bom (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id INTEGER NOT NULL REFERENCES products(id),
  material_id INTEGER NOT NULL REFERENCES materials(id),
  qty_per_1000 REAL NOT NULL,
  UNIQUE (product_id, material_id)
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS invoices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_no TEXT NOT NULL UNIQUE,
  dispatch_id INTEGER NOT NULL UNIQUE REFERENCES dispatches(id),
  taxable REAL NOT NULL,
  cgst REAL NOT NULL,
  sgst REAL NOT NULL,
  igst REAL NOT NULL,
  total REAL NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
