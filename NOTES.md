# NOTES

## 1. Report

> Finance says that on some days the revenue in the daily report is higher than what the payment provider paid out, and a few orders show more money received than their total.

**Status:** fixed

**What I saw:** Retried `payment.succeeded` webhook deliveries with the same `event["id"]` were inserted again into the `payments` table, inflating both order `paid_cents` and `daily_sales()` revenue totals.

**Root cause:** `Payments.handle_event()` in `tillpoint/payments.py` did not check whether `event["id"]` had already been recorded before inserting a new payment row.

**Fix and why:** Added an idempotency check in `Payments.handle_event()` for existing `event["id"]` values so retried webhook deliveries return the current order status without inserting duplicate payment rows.

**How I verified it:** Added `test_duplicate_webhook_event_is_idempotent` in `tests/test_fixes.py` and ran `python -m pytest -v`.

**Commits:** `2d666a8`, `5055f12`

## 2. Report

> Products show as sold out, or nearly, while the shelf is full. Staff say it gets worse on days when many customers abandon checkout.

**Status:** fixed

**What I saw:** Creating an order reserved product stock while the order was `pending`, but cancelling a `pending` order left those units deducted from stock.

**Root cause:** `Orders.cancel()` in `tillpoint/orders.py` only called `self.catalog.release()` when `order["status"] == "paid"`.

**Fix and why:** Updated `Orders.cancel()` to release reserved stock for both `pending` and `paid` orders before marking them `cancelled`, returning abandoned/unpaid reservations back to available stock.

**How I verified it:** Added `test_cancel_pending_order_restocks` in `tests/test_fixes.py` and ran `python -m pytest -v`.

**Commits:** `28b78e3`, `5055f12`

## 3. Report

> Customers in taxed regions who used a coupon say the tax on their receipt is too high. Receipts without a coupon are right.

**Status:** fixed

**What I saw:** Orders in taxed regions that applied a coupon calculated sales tax on the full pre-discount subtotal rather than the discounted amount.

**Root cause:** `price_order()` in `tillpoint/pricing.py` called `tax_for(sub, region)` before subtracting `discount_for(coupon, sub)`.

**Fix and why:** Calculated the coupon discount first, set `taxable = max(0, sub - discount)`, and passed `taxable` to `tax_for()` so tax is applied after coupon discounts.

**How I verified it:** Added `test_coupon_reduces_taxable_amount` in `tests/test_fixes.py` and ran `python -m pytest -v`.

**Commits:** `2eb71ba`, `5055f12`

## 4. Report

> Our shop in India (UTC+5:30) says sales taken in the morning do not appear in that day's report and turn up under the day before.

**Status:** fixed

**What I saw:** Morning sales in `UTC+5:30` (`utc_offset_minutes=330`) fell outside the expected local day bounds or shifted onto an adjacent day.

**Root cause:** `day_bounds_utc()` in `tillpoint/reports.py` added `timedelta(minutes=utc_offset_minutes)` instead of subtracting the offset when converting local midnight (`00:00` local time) to UTC.

**Fix and why:** Changed `day_bounds_utc()` to `local_midnight - timedelta(minutes=utc_offset_minutes)` so local day boundaries map accurately to UTC instants.

**How I verified it:** Added `test_india_morning_sale_stays_on_same_local_day` in `tests/test_fixes.py` and ran `python -m pytest -v`.

**Commits:** `357b1dc`, `5055f12`

## 5. Report

> Ever since we started running two server workers, we have sold more units of an item than we had, and its stock went negative.

**Status:** fixed

**What I saw:** Concurrent stock reservations could over-deduct inventory or read stale cached stock values across workers/connections.

**Root cause:** `Catalog.reserve()` in `tillpoint/catalog.py` updated `stock = stock - ?` without checking `stock >= ?` atomically in SQL and relied on a per-instance cache without invalidating/re-reading first.

**Fix and why:** Invalidated the SKU cache before reading, checked available stock, and executed `UPDATE products SET stock = stock - ? WHERE sku = ? AND stock >= ?`, raising `OutOfStock` when fewer units are available.

**How I verified it:** Added `test_concurrent_reservations_do_not_overdraw_stock` in `tests/test_fixes.py` and ran `python -m pytest -v`.

**Commits:** `e79898d`, `5055f12`

## 6. Open question

> Open question from support, no single right answer: sometimes a customer really does pay twice for one order (two separate payments, not a retry of the same one). Today the system records both and says nothing. Decide what should happen, build the smallest version of your decision, and explain what it costs in `NOTES.md`.

**My decision:** Reject any new payment event with a distinct `event_id` once an order is already `paid` or `shipped` (or already has `paid_cents >= total_cents`) by raising `PaymentError`.

**Why:** Silently recording a second payment causes orders to show more money received than their total and inflates payment totals; rejecting extra payments explicitly surfaces the conflict (`409` / `PaymentError`) instead of hiding overpayment.

**What it costs:** If a customer genuinely pays twice and the second webhook arrives with a new `event_id`, the second payment is not recorded automatically and must be reviewed or refunded manually by support/operations rather than auto-accepted into `payments`.

**What I built:** Added a guard in `Payments.handle_event()` in `tillpoint/payments.py` that raises `PaymentError` when a new `event_id` arrives for an order that is already `paid`/`shipped` or already has `paid_cents >= total_cents`.

**How I verified it:** Added `test_second_payment_on_paid_order_is_rejected` in `tests/test_fixes.py` and ran `python -m pytest -v`.

**Commits:** `2d666a8`, `917c000`, `5055f12`

## Other things I noticed

`Catalog` maintains an in-memory `_cache` dictionary per instance, so external writes made outside that `Catalog` instance can leave cached product rows stale unless invalidated.

## Session logs

- AI assistant session export saved in `session_logs/gemini_session.md` (with secrets, API keys, and personal data removed).