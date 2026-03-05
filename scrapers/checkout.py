from datetime import datetime, timezone
from scrapers.browser import create_browser_context, save_state, has_saved_state


def _accept_cookies(page):
    try:
        btn = page.locator('button:has-text("Accept")')
        if btn.is_visible(timeout=3000):
            btn.click()
    except Exception:
        pass


def _scrape_checkout_page(page):
    """Extract checkout page details before placing order."""
    return page.evaluate("""() => {
        const result = {
            delivery_address: null,
            payment_method: null,
            restaurant: null,
            cart_summary: null,
            order_total: null
        };

        // Delivery address from checkout-delivery-address-section
        const addrSection = document.querySelector('[data-testid="checkout-delivery-address-section"]');
        if (addrSection) result.delivery_address = addrSection.innerText.trim();

        // Payment method — look near edit-payment-button
        const payBtn = document.querySelector('[data-testid="edit-payment-button"]');
        if (payBtn) {
            // Walk up to the payment section and get its text
            let section = payBtn.parentElement;
            for (let i = 0; i < 5; i++) {
                if (!section.parentElement) break;
                section = section.parentElement;
            }
            const sectionText = section.innerText.trim();
            // Check if it says "Add payment method" (no payment set)
            if (sectionText.includes('Add payment method')) {
                result.payment_method = null;
            } else {
                // Extract payment text excluding "Edit" and "Payment" labels
                const lines = sectionText.split('\\n').filter(l =>
                    l.trim() && l.trim() !== 'Edit' && l.trim() !== 'Payment'
                );
                result.payment_method = lines.join(' ').trim() || null;
            }
        }

        // Heuristic fallback for payment — match card patterns in page text
        if (!result.payment_method) {
            const allText = document.body.innerText;
            const cardMatch = allText.match(/(?:Visa|Mastercard|Amex|Apple Pay|Google Pay|PayPal|\\*{4}\\s*\\d{4})/i);
            if (cardMatch) result.payment_method = cardMatch[0];
        }

        // Restaurant name
        const storeLink = document.querySelector('a[href*="/store/"]');
        if (storeLink) result.restaurant = storeLink.innerText.trim();

        // Cart summary from cart-summary-panel
        const cartPanel = document.querySelector('[data-testid="cart-summary-panel"]');
        if (cartPanel) result.cart_summary = cartPanel.innerText.trim();

        // Order total — look for "Order total" text nearby
        const allText = document.body.innerText;
        const totalMatch = allText.match(/Order total[\\s\\S]*?([£$€][\\d.,]+)/i);
        if (totalMatch) result.order_total = totalMatch[1];

        return result;
    }""")


def _scrape_order_confirmation(page):
    """Extract order confirmation details after placing order."""
    return page.evaluate("""() => {
        const result = {
            order_id: null,
            estimated_delivery: null,
            status: null,
            confirmation_text: null
        };

        const pageText = document.body.innerText;

        // Order ID pattern
        const orderMatch = pageText.match(/order\\s*#?\\s*([A-Z0-9-]+)/i);
        if (orderMatch) result.order_id = orderMatch[1];

        // ETA
        const etaMatch = pageText.match(/(?:estimated|arriving|delivery).*?(\\d{1,2}:\\d{2}|\\d+ min)/i);
        if (etaMatch) result.estimated_delivery = etaMatch[1];

        // Status heading
        const h1 = document.querySelector('h1');
        if (h1) result.status = h1.innerText.trim();

        // Chunk of confirmation text for debugging
        result.confirmation_text = pageText.substring(0, 1000);

        return result;
    }""")


def scrape_checkout(headless=True, debug=False, dry_run=True):
    """Navigate to checkout and optionally place the order.

    Assumes items are already in the cart (from a prior /cart call with
    session persistence). Uses the authenticated session.

    Args:
        headless: Run browser in headless mode.
        debug: If True, capture checkout page HTML for selector refinement.
        dry_run: If True (default), scrape checkout details but do NOT click
                 "Place order". Set to False to actually place the order.

    Returns:
        dict with order details or error info.
    """
    if not has_saved_state():
        return {
            "success": False,
            "error": "NOT_AUTHENTICATED",
            "message": "No saved session. Call /login first.",
        }

    pw, browser, context = create_browser_context(headless=headless)
    page = context.new_page()

    try:
        print("[Checkout] Navigating to checkout page...", flush=True)
        page.goto("https://www.ubereats.com/checkout", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        _accept_cookies(page)

        # Debug: capture page DOM for selector discovery
        if debug:
            html = page.content()
            with open("debug_checkout.html", "w", encoding="utf-8") as f:
                f.write(html)
            page.screenshot(path="debug_checkout.png")
            print("[Checkout] Debug: saved debug_checkout.html and debug_checkout.png", flush=True)

        # Check if cart is empty
        empty_indicators = page.locator('text="Your cart is empty", text="Add items to get started", text="Your bag is empty"')
        if empty_indicators.count() > 0:
            return {
                "success": False,
                "error": "CART_EMPTY",
                "message": "No items in cart. Use /cart endpoint first.",
            }

        # Scrape pre-checkout summary
        print("[Checkout] Scraping checkout page details...", flush=True)
        pre_checkout = _scrape_checkout_page(page)

        # Verify delivery address
        if not pre_checkout.get("delivery_address"):
            print("[Checkout] Warning: Could not detect delivery address", flush=True)

        # Verify payment method
        if not pre_checkout.get("payment_method"):
            return {
                "success": False,
                "error": "NO_PAYMENT",
                "message": "No payment method found. Add one in the UberEats app first.",
                "pre_checkout": pre_checkout,
            }

        if dry_run:
            print("[Checkout] Dry run — skipping Place order click", flush=True)
            save_state(context)
            return {
                "success": True,
                "dry_run": True,
                "scraped_at": datetime.now(timezone.utc).isoformat(),
                "pre_checkout": pre_checkout,
            }

        # Click "Place order"
        print("[Checkout] Placing order...", flush=True)
        place_order_btn = page.locator(
            '[data-testid="place-order-btn"], '
            'button:has-text("Place order")'
        ).first

        if not place_order_btn.is_visible(timeout=5000):
            return {
                "success": False,
                "error": "NO_PLACE_ORDER_BUTTON",
                "message": "Place order button not found or not visible.",
                "pre_checkout": pre_checkout,
            }

        place_order_btn.click()
        page.wait_for_timeout(5000)

        # Scrape order confirmation
        print("[Checkout] Scraping order confirmation...", flush=True)
        confirmation = _scrape_order_confirmation(page)

        # Save updated session state
        save_state(context)

        return {
            "success": True,
            "dry_run": False,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "pre_checkout": pre_checkout,
            "confirmation": confirmation,
        }

    except Exception as e:
        print(f"[Checkout] Error: {e}", flush=True)
        return {"success": False, "error": str(e)}
    finally:
        context.close()
        browser.close()
        pw.stop()
