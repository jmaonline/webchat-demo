# Using Google Sheets for test data

The agent's order/customer/return data can now live in a Google Sheet
instead of the local JSON files, so non-technical folks can add/edit test
orders without touching code. This uses the simplest possible wiring for a
prototype: the sheet is published to the web as CSV, and the backend fetches
it over plain HTTP — no Google API credentials, OAuth, or service account
needed.

**Trade-off to know:** "Publish to web" makes those specific sheet tabs
readable by anyone who has the link, regardless of the sheet's normal
sharing settings. Fine for mock/test data; don't put anything real or
sensitive in this sheet.

If you'd rather keep the sheet private and use the real Google Sheets API
with a service account instead, let me know and I'll wire that up — more
setup (Google Cloud project, service account, sharing the sheet with its
email) but access-controlled.

## 1. Create the sheet

1. Go to https://sheets.new (creates a blank sheet in your Google account).
2. Rename it something like "Bookly Support Agent — Mock Data" (click the
   title top-left).
3. You'll end up with three tabs, named **exactly**: `Orders`, `Customers`,
   `Returns`. Rename the default "Sheet1" tab to `Orders` first.

## 2. Import the data

I've generated CSVs matching each tab — attached to this conversation:
`orders.csv`, `customers.csv`, `returns.csv`.

For the `Orders` tab (already selected):
1. File → Import → Upload → drag in `orders.csv`.
2. Import location: **Replace current sheet**.
3. Separator type: **Comma**. Click **Import data**.

Add two more tabs (bottom-left **+**), rename them `Customers` and
`Returns`, and repeat the import for `customers.csv` and `returns.csv`
respectively into each.

**Orders columns** (one row per order; multiple items in one cell,
formatted like `Title by Author x1 @19.99; Another Title by Author x2 @9.99`):

```
order_id, customer_email, customer_name, order_date, status, shipped_date,
delivered_date, estimated_delivery, items, shipping_method, tracking_number,
carrier, total, return_window_days, cancellation_reason
```

Leave a cell blank when a field doesn't apply yet (e.g. `delivered_date` for
an order that's still `processing`).

**Customers columns:** `email, name, account_created`

**Returns columns:** `return_id, order_id, item_title, status, requested_date, resolved_date, resolution, refund_amount`

## 3. Publish each tab to the web as CSV

For **each** of the 3 tabs:

1. File → Share → **Publish to web**.
2. In the dropdown, select the specific tab (e.g. "Orders") — not "Entire
   Document".
3. Set the format dropdown to **Comma-separated values (.csv)**.
4. Check **Automatically republish when changes are made** (so edits show
   up without re-publishing every time).
5. Click **Publish**, confirm. Copy the URL it gives you — it looks like:
   ```
   https://docs.google.com/spreadsheets/d/e/2PACX-1vT.../pub?gid=0&single=true&output=csv
   ```
6. Repeat for the other two tabs (each tab has a different `gid` in its
   published URL).

## 4. Wire it up

Set these three URLs as environment variables — locally in `.env`, and in
your Render service's environment variables:

```
ORDERS_SHEET_CSV_URL=https://docs.google.com/spreadsheets/d/e/.../pub?gid=0&single=true&output=csv
CUSTOMERS_SHEET_CSV_URL=https://docs.google.com/spreadsheets/d/e/.../pub?gid=123456789&single=true&output=csv
RETURNS_SHEET_CSV_URL=https://docs.google.com/spreadsheets/d/e/.../pub?gid=987654321&single=true&output=csv
```

That's it — once all three are set, the agent reads live from the sheet
(cached 30s at a time, so edits show up within half a minute). If any of
the three env vars is unset, that data type quietly falls back to the
local `backend/mock_data/*.json` files, so partial setup (or none at all)
never breaks the app — it's just not reading from Sheets yet for that
piece.

## Notes

- Editing the sheet directly is now the fastest way to add/change test
  orders — no redeploy needed, just edit a cell and wait up to 30s.
- Malformed rows (e.g. a typo in the `items` format) are skipped rather
  than crashing the agent — double check a new order shows up correctly
  after adding it.
- Keep `order_id` values unique and typo-free; that's the lookup key.
