-- CAESAR POS structured order schema (SQLite)
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS orders (id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, status TEXT, voided INTEGER NOT NULL DEFAULT 0, total REAL NOT NULL DEFAULT 0, subtotal REAL, discount_amount REAL, payment TEXT, cash_amount REAL, card_amount REAL, customer TEXT, table_no TEXT, order_type TEXT, cashier_name TEXT, note TEXT, payload TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_orders_timestamp ON orders(timestamp);
CREATE INDEX IF NOT EXISTS idx_orders_status_ts ON orders(status, timestamp);
CREATE TABLE IF NOT EXISTS order_items (order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE, item_index INTEGER NOT NULL, name TEXT, qty REAL NOT NULL DEFAULT 0, price REAL NOT NULL DEFAULT 0, modifiers TEXT, payload TEXT, PRIMARY KEY(order_id, item_index));
CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
CREATE TABLE IF NOT EXISTS migration_state (name TEXT PRIMARY KEY, version INTEGER NOT NULL, completed_at TEXT NOT NULL, source_count INTEGER NOT NULL);
