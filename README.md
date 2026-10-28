# Tulip Ops

Factory operations for Tulip Enterprise / Zecta: production tracking, QC, raw-material stock, finished goods, and dispatch. Gujarati-first UI with an English toggle. Runs entirely on the factory LAN — no internet needed after install.

## Run it (factory laptop)

```bash
pip install -r requirements.txt
python seed.py       # loads demo data; skips if data already exists
python app.py        # serves on 0.0.0.0:3000
```

No build step. Find the laptop's LAN IP (`ipconfig` / `ifconfig`), connect workers' phones to the factory WiFi, and open `http://<laptop-ip>:3000` in Chrome. Add to Home Screen for an app-like feel.

Reset data: delete `data/factory.db*` and re-run `python seed.py`.

## How it maps to the floor

- **Production** — batches flow Molding → Tufting → Trimming → Packing. Each work session logs good qty + scrap against a machine, worker, and shift. Logging good qty at Packing automatically adds to finished-goods stock. "Move to next stage" is an explicit supervisor action.
- **QC** — sample checks against any active batch at its current stage, with toothbrush-specific defect types (short shot, loose bristles, sharp ends…) and a three-way decision: Pass / Rework / Reject.
- **Stock** — raw materials with reorder levels (low-stock flags surface on the dashboard) and live finished-goods counts. Material consumption is logged manually.
- **Dispatch** — orders → partial or full dispatches with vehicle/LR number. Dispatching decrements finished stock and updates order status. Every dispatch generates a WhatsApp-shareable note; the dashboard generates a daily production report the same way (wa.me links — no API, no cost).

## Stack

Flask 3 + Jinja templates, SQLite from Python's standard library (single file in `data/`, WAL mode, transactional writes), plain CSS — no framework, no bundler. Waitress serves it in production mode. System fonts only — Android renders Gujarati natively, so the app stays fully offline.

Layout: `app.py` (routes), `db.py` (all queries and transactional writes), `i18n.py` (the Gujarati/English dictionary), `schema.sql`, `seed.py`, `templates/`, `static/style.css`.
