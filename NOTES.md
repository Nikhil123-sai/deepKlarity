# NOTES
# NOTES

## 1. Report

> Finance says that on some days the revenue in the daily report is higher than what the payment provider paid out, and a few orders show more money received than their total.

**Status:** fixed

**What I saw:** Retried `payment.succeeded` webhook events with the same `id` were inserted again into `payments`, inflating `paid_cents()` and `daily_sales()`.

**Root cause:** `Payments.handle_event()` in `tillpoint/payments.py` did not check whether `event["id"]` had already been recorded before inserting into `payments`.

**Fix and why:** Added an idempotency check in `Payments.handle_event()` for existing `event["id"]` so retries return the current order status without double-counting payments.

**How I verified it:** Added `test_duplicate_webhook_event_is_idempotent` in `tests/test_fixes.py` and ran `python -m pytest -v`.

**Commits:** `2d666a8`, `5055f12`

## 2. Report

> Products show as sold out, or nearly, while the shelf is full. Staff say it gets worse on days when many customers abandon checkout.

**Status:** fixed

**What I saw:** Creating an order reserved inventory while the order was `pending`, but cancelling a `pending` order did not release those units back to stock.

**Root cause:** `Orders.cancel()` in `tillpoint/orders.py` only called `self.catalog.release()` when `order["status"] == "paid"`.

**Fix and why:** Updated `Orders.cancel()` to release stock for both `pending` and `paid` orders prior to cancellation.

**How I verified it:** Added `test_cancel_pending_order_restocks` in `tests/test_fixes.py` and ran `python -m pytest -v`.

**Commits:** `28b78e3`, `5055f12`

## 3. Report

> Customers in taxed regions who used a coupon say the tax on their receipt is too high. Receipts without a coupon are right.

**Status:** fixed

**What I saw:** Orders with a coupon and a taxed region charged sales tax on the full pre-discount subtotal rather than the discounted amount.

**Root cause:** `price_order()` in `tillpoint/pricing.py` computed `tax = tax_for(sub, region)` before subtracting `discount_for(coupon, sub)`.

**Fix and why:** Subtracted the coupon discount first (`taxable = max(0, sub - discount)`) and passed `taxable` to `tax_for()` so tax applies to the discounted amount.

**How I verified it:** Added `test_coupon_reduces_taxable_amount` in `tests/test_fixes.py` and ran `python -m pytest -v`.

**Commits:** `2eb71ba`, `5055f12`

## 4. Report

> Our shop in India (UTC+5:30) says sales taken in the morning do not appear in that day's report and turn up under the day before.

**Status:** fixed

**What I saw:** Morning sales in `UTC+5:30` (`+330` minutes) fell outside the queried daily window or shifted onto the adjacent day.

**Root cause:** `day_bounds_utc()` in `tillpoint/reports.py` added `timedelta(minutes=utc_offset_minutes)` to local midnight instead of subtracting the offset to convert local time to UTC.

**Fix and why:** Changed `day_bounds_utc()` to `local_midnight - timedelta(minutes=utc_offset_minutes)` so `00:00` local time maps to the exact UTC instant.

**How I verified it:** Added `test_india_morning_sale_stays_on_same_local_day` in `tests/test_fixes.py` and ran `python -m pytest -v`.

**Commits:** `357b1dc`, `5055f12`

## 5. Report

> Ever since we started running two server workers, we have sold more units of an item than we had, and its stock went negative.

**Status:** fixed

**What I saw:** Concurrent stock reservations could over-deduct stock or read stale cached inventory across workers/connections.

**Root cause:** `Catalog.reserve()` in `tillpoint/catalog.py` executed `UPDATE products SET stock = stock - ? WHERE sku = ?` without a `stock >= ?` guard and read from a per-instance cache without invalidating/re-reading first.

**Fix and why:** Invalidated cache before reading, checked available stock, and used a conditional atomic update `WHERE sku = ? AND stock >= ?`, raising `OutOfStock` when insufficient units remain.

**How I verified it:** Added `test_concurrent_reservations_do_not_overdraw_stock` in `tests/test_fixes.py` and ran `python -m pytest -v`.

**Commits:** `e79898d`, `5055f12`

## 6. Open question

> Open question from support, no single right answer: sometimes a customer really does pay twice for one order (two separate payments, not a retry of the same one). Today the system records both and says nothing. Decide what should happen, build the smallest version of your decision, and explain what it costs in `NOTES.md`.

**My decision:** Reject any new payment event with a distinct `event_id` once an order is already `paid` or `shipped` (or already has `paid_cents >= total_cents`) by raising `PaymentError`.

**Why:** Silent acceptance of a second payment inflates recorded payments above the order total and creates accounting ambiguity; raising `PaymentError` makes overpayment explicit so support/refund handling can deal with it deliberately.

**What it costs:** If a customer genuinely pays twice and the system rejects the second webhook event, the extra payment is not recorded automatically and must be handled out-of-band (such as manual review or provider refund), and callers must handle the `409` / `PaymentError` response.

**What I built:** Added a check in `Payments.handle_event()` in `tillpoint/payments.py` rejecting new `event_id` deliveries when the order is already settled (`paid`/`shipped` or `paid_cents >= total_cents`).

**How I verified it:** Added `test_second_payment_on_paid_order_is_rejected` in `tests/test_fixes.py` and ran `python -m pytest -v`.

**Commits:** `2d666a8`, `917c000`, `5055f12`

## Other things I noticed

`Catalog` uses an in-memory `_cache` dictionary per `Catalog` instance; if external SQL writes occur outside that instance, cached rows can become stale unless invalidated.

## Session logs

- AI assistant session export saved in `session_logs/` (with any secrets or personal data removed).
