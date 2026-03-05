# Uber Eats API for AgentWeb

First prototype of an Uber Eats API for AgentWeb. This service exposes HTTP endpoints that use browser automation (Playwright) to search restaurants, fetch menus, add items to cart, and optionally complete checkout on Uber Eats. It is intended for use by agents or automation that need programmatic access to Uber Eats flows.

**Base URL:** All endpoints are under `/api/ubereats`. The server runs on port `5001` by default.

---

## Setup

```bash
# Create virtual environment (recommended)
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
# source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers (required for scraping)
playwright install chromium
```

**Chrome:** The scrapers use Playwright’s `channel: "chrome"`, so Chrome must be installed on the machine.

---

## Running the server

```bash
python run.py
```

The API is available at `http://localhost:5001`.

---

## API endpoints

### 1. Health check

**`GET /api/ubereats/health`**

Check that the service is up.

**Example:**

```bash
curl http://localhost:5001/api/ubereats/health
```

**Response:** `200 OK`

```json
{ "status": "ok" }
```

---

### 2. Search restaurants

**`POST /api/ubereats/search`**

Search for restaurants that deliver to a given location. Uses Uber Eats in the browser, enters the address, and returns a list of restaurants with ratings, delivery time, fees, and store URLs.

**Request body (JSON):**

| Field                 | Type   | Required | Description                                      |
|-----------------------|--------|----------|--------------------------------------------------|
| `location`            | string | Yes      | Delivery address (e.g. `"Shoreditch, London"`)  |
| `min_rating`          | number | No       | Only return restaurants with rating ≥ this      |
| `max_delivery_minutes`| number | No       | Only return restaurants with ETA ≤ this         |

**Example:**

```bash
curl -X POST http://localhost:5001/api/ubereats/search \
  -H "Content-Type: application/json" \
  -d '{"location": "Shoreditch, London"}'
```

With filters:

```bash
curl -X POST http://localhost:5001/api/ubereats/search \
  -H "Content-Type: application/json" \
  -d '{"location": "Shoreditch, London", "min_rating": 4.0, "max_delivery_minutes": 45}'
```

**Response:** `200 OK`

```json
{
  "location": "Shoreditch, London",
  "scraped_at": "2025-03-04T12:00:00.000000+00:00",
  "count": 25,
  "restaurants": [
    {
      "id": "rzYSYjkoTmufdl-RSdMI8Q",
      "name": "KFC Bishopsgate",
      "rating": 4.4,
      "reviews": 500,
      "eta_minutes": 25,
      "delivery_fee": "£2.99",
      "promo": null,
      "image": "https://...",
      "url": "https://www.ubereats.com/gb/store/kfc-bishopsgate/rzYSYjkoTmufdl-RSdMI8Q"
    }
  ]
}
```

Use `restaurants[].url` as `store_url` for the **Menu** and **Cart** endpoints.

---

### 3. Get menu

**`POST /api/ubereats/menu`**

Fetch the menu (categories and items) for a restaurant. Use a `store_url` from the search response.

**Request body (JSON):**

| Field       | Type   | Required | Description                                              |
|------------|--------|----------|----------------------------------------------------------|
| `store_url`| string | Yes      | Full store URL (e.g. from search `restaurants[].url`)     |

**Example:**

```bash
curl -X POST http://localhost:5001/api/ubereats/menu \
  -H "Content-Type: application/json" \
  -d '{"store_url": "https://www.ubereats.com/gb/store/kfc-bishopsgate/rzYSYjkoTmufdl-RSdMI8Q"}'
```

**Response:** `200 OK`

```json
{
  "restaurant_name": "KFC Bishopsgate",
  "cuisine": ["American"],
  "store_url": "https://www.ubereats.com/gb/store/...",
  "scraped_at": "2025-03-04T12:05:00.000000+00:00",
  "category_count": 5,
  "item_count": 42,
  "categories": [
    {
      "name": "Burgers",
      "items": [
        {
          "id": "d497d440-fea8-5a55-9688-d2477f2d3008",
          "name": "Coleslaw",
          "price": 1.49,
          "price_formatted": "£1.49",
          "calories": 95,
          "description": "...",
          "image": "https://..."
        }
      ]
    }
  ]
}
```

Use `categories[].items[].id` as `item_id` when calling the **Cart** endpoint.

---

### 4. Add to cart

**`POST /api/ubereats/cart`**

Open the store, set the delivery address, and add the given items to the cart. Items that require options (e.g. “choose size”) are skipped and reported in `skipped_items`.

**Request body (JSON):**

| Field       | Type   | Required | Description                                                                 |
|------------|--------|----------|-----------------------------------------------------------------------------|
| `store_url`| string | Yes      | Full store URL (same as menu)                                              |
| `address`  | string | Yes      | Delivery address (e.g. `"Shoreditch, London"`)                              |
| `items`    | array  | Yes      | List of `{ "item_id": "<id>", "quantity": 1 }`. `quantity` defaults to 1.  |

**Example:**

```bash
curl -X POST http://localhost:5001/api/ubereats/cart \
  -H "Content-Type: application/json" \
  -d '{
    "store_url": "https://www.ubereats.com/gb/store/kfc-bishopsgate/rzYSYjkoTmufdl-RSdMI8Q",
    "address": "Shoreditch, London",
    "items": [
      { "item_id": "d497d440-fea8-5a55-9688-d2477f2d3008", "quantity": 1 },
      { "item_id": "f35db3e8-f168-5169-ba89-56bfc70bc110", "quantity": 2 }
    ]
  }'
```

**Response:** `200 OK`

```json
{
  "store_url": "https://...",
  "address": "Shoreditch, London",
  "scraped_at": "2025-03-04T12:10:00.000000+00:00",
  "error": null,
  "added_count": 2,
  "skipped_count": 0,
  "failed_count": 0,
  "added_items": [...],
  "skipped_items": [],
  "failed_items": [],
  "cart_totals": {
    "subtotal": 15.97,
    "subtotal_formatted": "£15.97",
    "delivery_fee": 2.99,
    "delivery_fee_formatted": "£2.99",
    "fees": 0.5,
    "fees_formatted": "£0.50",
    "total": 19.46,
    "total_formatted": "£19.46",
    "cart_items": [...]
  }
}
```

Session state (cookies) is saved so that **Checkout** can run in the same “browser” session. Call **Login** first if you need an authenticated session for checkout.

---

### 5. Login (start session)

**`POST /api/ubereats/login`**

Opens a **visible** browser window at Uber Eats. The user must log in manually (Apple, Google, email, etc.). After logging in, call **Login complete** to save the session.

**Request body:** None (or empty JSON).

**Example:**

```bash
curl -X POST http://localhost:5001/api/ubereats/login
```

**Response:** `200 OK`

```json
{
  "status": "LOGIN_STARTED",
  "message": "Browser window opened at ubereats.com. Log in using any method, then call /login/complete."
}
```

---

### 6. Login complete

**`POST /api/ubereats/login/complete`**

Saves the current browser session (cookies) after the user has logged in. Call this only after **Login** and after the user has finished signing in.

**Request body:** None (or empty JSON).

**Example:**

```bash
curl -X POST http://localhost:5001/api/ubereats/login/complete
```

**Response (success):** `200 OK`

```json
{ "success": true, "message": "Session saved." }
```

**Response (no active login):** `400`

```json
{
  "success": false,
  "error": "NO_LOGIN_SESSION",
  "message": "No login session active. Call /login first."
}
```

---

### 7. Session status

**`GET /api/ubereats/session`**

Check whether a saved session exists and has auth cookies.

**Example:**

```bash
curl http://localhost:5001/api/ubereats/session
```

**Response:** `200 OK`

```json
{
  "authenticated": true,
  "cookies_count": 12,
  "auth_cookies": ["jwt-session", "sid"]
}
```

If no session is saved, `authenticated` is `false` and `reason` explains (e.g. `"No saved session"`).

---

### 8. Checkout

**`POST /api/ubereats/checkout`**

Go to the Uber Eats checkout page and optionally place the order. Requires an authenticated session (use **Login** then **Login complete** first). The cart should already be filled (e.g. via **Cart**). By default this is a **dry run**: it scrapes checkout details but does **not** click “Place order”.

**Request body (JSON):**

| Field     | Type    | Required | Description                                                                 |
|----------|---------|----------|-----------------------------------------------------------------------------|
| `dry_run`| boolean | No       | If `true` (default), do not place the order; only return checkout details. |
| `debug`  | boolean | No       | If `true`, save debug HTML/screenshot to disk.                             |

**Example (dry run, default):**

```bash
curl -X POST http://localhost:5001/api/ubereats/checkout \
  -H "Content-Type: application/json" \
  -d '{}'
```

Or explicitly:

```bash
curl -X POST http://localhost:5001/api/ubereats/checkout \
  -H "Content-Type: application/json" \
  -d '{"dry_run": true}'
```

**Response (dry run):** `200 OK`

```json
{
  "success": true,
  "dry_run": true,
  "scraped_at": "2025-03-04T12:15:00.000000+00:00",
  "pre_checkout": {
    "delivery_address": "Shoreditch, London...",
    "payment_method": "Visa **** 4242",
    "restaurant": "KFC Bishopsgate",
    "cart_summary": "...",
    "order_total": "£19.46"
  }
}
```

**Example (place order):**

```bash
curl -X POST http://localhost:5001/api/ubereats/checkout \
  -H "Content-Type: application/json" \
  -d '{"dry_run": false}'
```

**Response (order placed):** `200 OK`

```json
{
  "success": true,
  "dry_run": false,
  "scraped_at": "2025-03-04T12:16:00.000000+00:00",
  "pre_checkout": { ... },
  "confirmation": {
    "order_id": "ABC123",
    "estimated_delivery": "12:45",
    "status": "Order confirmed",
    "confirmation_text": "..."
  }
}
```

**Errors:**

- `401`: No saved session or session expired. Body includes `"error": "NOT_AUTHENTICATED"` or `"SESSION_EXPIRED"`. Log in again with **Login** and **Login complete**.
- `400`: e.g. cart empty (`CART_EMPTY`), no payment method (`NO_PAYMENT`), or place-order button not found (`NO_PLACE_ORDER_BUTTON`).

---

## Typical flow for an agent

1. **Search** — `POST /api/ubereats/search` with `location` to get restaurants and their `url`.
2. **Menu** — `POST /api/ubereats/menu` with a restaurant’s `store_url` to get categories and items and their `id`.
3. **Cart** — `POST /api/ubereats/cart` with `store_url`, `address`, and `items` (each with `item_id` and optional `quantity`).
4. **Checkout (dry run)** — `POST /api/ubereats/checkout` with `dry_run: true` to verify delivery address, payment, and total.
5. **Checkout (place order)** — If the user confirms, call again with `dry_run: false` to place the order.

For checkout to work, the same server process must have an authenticated session:

1. **Login** — `POST /api/ubereats/login` (browser opens).
2. User logs in in the browser.
3. **Login complete** — `POST /api/ubereats/login/complete` to save the session.
4. **Session** — `GET /api/ubereats/session` to confirm `authenticated: true`.

Session state is stored under `.session/` in the project directory. Do not commit this folder; it contains auth cookies.

---

## Errors

- **400** — Missing or invalid body (e.g. missing `location`, `store_url`, `address`, or `items`). Response body includes an `error` message.
- **401** — Checkout called without a valid session (`NOT_AUTHENTICATED` or `SESSION_EXPIRED`).
- **500** — Scraping or server error. Response body may include `error` with details (e.g. timeout, element not found). Check server logs for stack traces.

---

## Notes

- The API uses Playwright with Chrome. Scraping can be slow (tens of seconds per request) and may be sensitive to Uber Eats UI changes.
- Items that require choices (e.g. “Choose your side”) are skipped when adding to cart and listed in `skipped_items` with a reason.
- This is a prototype. Use at your own risk; ensure compliance with Uber Eats’ terms of service and applicable laws.
