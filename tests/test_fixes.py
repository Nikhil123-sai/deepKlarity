import sqlite3
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tillpoint import db, reports
from tillpoint.api import App
from tillpoint.catalog import Catalog, OutOfStock
from tillpoint.payments import PaymentError


class FixesTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect()
        self.app = App(self.conn)
        self.app.catalog.add_product("MUG", "Mug", 1200, stock=10)
        self.app.catalog.add_product("TEE", "T-shirt", 2500, stock=3)
        self.conn.execute(
            "INSERT INTO coupons (code, kind, value, min_subtotal_cents) VALUES ('TEN', 'percent', 10, 0)"
        )

    def test_duplicate_webhook_event_is_idempotent(self):
        order = self.app.orders.create("ana", [("MUG", 1)])
        evt = {"id": "evt_dup", "type": "payment.succeeded", "order_id": order["id"], "amount_cents": 1200}
        self.assertEqual(self.app.payments.handle_event(evt), "paid")
        self.assertEqual(self.app.payments.handle_event(evt), "paid")
        self.assertEqual(self.app.payments.paid_cents(order["id"]), 1200)

    def test_cancel_pending_order_restocks(self):
        order = self.app.orders.create("ana", [("TEE", 2)])
        self.assertEqual(self.app.catalog.get_product("TEE").stock, 1)
        self.app.orders.cancel(order["id"])
        self.assertEqual(self.app.catalog.get_product("TEE").stock, 3)

    def test_coupon_reduces_taxable_amount(self):
        order = self.app.orders.create("ana", [("MUG", 1)], region="CA", coupon_code="TEN")
        self.assertEqual(order["subtotal_cents"], 1200)
        self.assertEqual(order["discount_cents"], 120)
        self.assertEqual(order["tax_cents"], 78)
        self.assertEqual(order["total_cents"], 1158)

    def test_india_morning_sale_stays_on_same_local_day(self):
        order = self.app.orders.create("ana", [("MUG", 1)])
        morning_utc = datetime(2025, 3, 10, 2, 0, tzinfo=timezone.utc)
        self.app.payments.handle_event(
            {"id": "evt_ist", "type": "payment.succeeded", "order_id": order["id"], "amount_cents": 1200},
            now=morning_utc,
        )
        rep = reports.daily_sales(self.conn, "2025-03-10", utc_offset_minutes=330)
        self.assertEqual(rep, {"day": "2025-03-10", "revenue_cents": 1200, "orders": 1})

    def test_concurrent_reservations_do_not_overdraw_stock(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "shop.sqlite")
            setup_conn = db.connect(db_path)
            setup_conn.execute(
                "INSERT INTO products (sku, name, price_cents, stock) VALUES ('CAP', 'Cap', 1000, 1)"
            )
            setup_conn.close()

            successes = []
            failures = []
            lock = threading.Lock()

            def worker():
                conn = sqlite3.connect(db_path, isolation_level=None, timeout=10.0)
                conn.row_factory = sqlite3.Row
                cat = Catalog(conn)
                time.sleep(0.01)
                try:
                    cat.reserve("CAP", 1)
                    with lock:
                        successes.append(1)
                except OutOfStock:
                    with lock:
                        failures.append(1)
                finally:
                    conn.close()

            t1 = threading.Thread(target=worker)
            t2 = threading.Thread(target=worker)
            t1.start()
            t2.start()
            t1.join()
            t2.join()

            self.assertEqual(len(successes), 1)
            self.assertEqual(len(failures), 1)
            check_conn = db.connect(db_path)
            stock = check_conn.execute("SELECT stock FROM products WHERE sku = 'CAP'").fetchone()["stock"]
            check_conn.close()
            self.assertEqual(stock, 0)

    def test_second_payment_on_paid_order_is_rejected(self):
        order = self.app.orders.create("ana", [("MUG", 1)])
        self.app.payments.handle_event(
            {"id": "evt_first", "type": "payment.succeeded", "order_id": order["id"], "amount_cents": 1200}
        )
        with self.assertRaises(PaymentError):
            self.app.payments.handle_event(
                {"id": "evt_second", "type": "payment.succeeded", "order_id": order["id"], "amount_cents": 1200}
            )
        self.assertEqual(self.app.payments.paid_cents(order["id"]), 1200)


if __name__ == "__main__":
    unittest.main()
