from datetime import datetime, timezone
import json
import sys

from scrapers.browser import create_browser_context, save_state



def _close_modal(page):
    """Close the currently open item modal."""
    try:
        close_btn = page.locator('[data-testid="baseui-modal-close"]')
        if close_btn.count() > 0:
            close_btn.first.click()
            page.wait_for_timeout(1000)
            return
    except Exception:
        pass
    page.keyboard.press("Escape")
    page.wait_for_timeout(1000)


def _detect_required_options(page):
    """Detect if the item modal has required option groups.

    Returns True if the item needs option selections before it can be added.
    """
    return page.evaluate(
        """() => {
        const modal = document.querySelector('[role="dialog"]');
        if (!modal) return false;
        const text = modal.innerText;

        // Strategy 1: Look for "Required" label (Uber Eats marks mandatory groups)
        if (/\\bRequired\\b/.test(text)) return true;

        // Strategy 2: Look for radio/checkbox groups with selection language
        const groups = modal.querySelectorAll('[role="radiogroup"], [role="group"]');
        for (const group of groups) {
            const gt = group.innerText || '';
            if (/required|choose|select/i.test(gt)) return true;
        }

        // Strategy 3: Look for "Choose your..." / "Pick a..." section headers
        const lines = text.split('\\n');
        for (const line of lines) {
            const trimmed = line.trim();
            if (/^(choose|pick|select)\\s+(your|a|an|one)/i.test(trimmed)) return true;
        }

        // Strategy 4: If add-to-cart button is disabled, required options are unselected
        const ctaContainer = modal.querySelector('[data-test="add-to-cart-cta"]');
        if (ctaContainer) {
            const btn = ctaContainer.querySelector('button');
            if (btn && btn.disabled) return true;
        }

        return false;
    }"""
    )


def _click_add_to_order(page):
    """Click the 'Add to order' button inside the modal.

    Returns True if the button was successfully clicked.
    """
    modal = page.locator('[role="dialog"]')

    # Strategy 1: Button inside [data-test="add-to-cart-cta"]
    try:
        cta = modal.locator('[data-test="add-to-cart-cta"] button')
        if cta.count() > 0 and cta.first.is_enabled():
            cta.first.click()
            return True
    except Exception:
        pass

    # Strategy 2: Button with "Add to order" text
    try:
        btn = modal.locator('button:has-text("Add to order")')
        if btn.count() > 0 and btn.first.is_enabled():
            btn.first.click()
            return True
    except Exception:
        pass

    # Strategy 3: Any button with "Add" + price or "order"
    try:
        buttons = modal.locator("button").all()
        for b in buttons:
            text = b.inner_text().strip().lower()
            if "add" in text and ("order" in text or "£" in text or "$" in text):
                if b.is_enabled():
                    b.click()
                    return True
    except Exception:
        pass

    return False


def _add_item_to_cart(page, item_id, quantity, close_sidebar=True):
    """Open an item modal, set quantity, and add to cart.

    Returns a dict with status ("added", "skipped", or "error"),
    item details, and a reason if not added.
    """
    result = {
        "item_id": item_id,
        "item_name": None,
        "item_price": None,
        "quantity": quantity,
        "status": "error",
        "reason": None,
    }

    # Scroll down to find the item (Uber Eats virtualizes the list,
    # so off-screen items may not exist in the DOM yet)
    item_selector = f'li[data-testid="store-item-{item_id}"]'
    item_el = page.locator(item_selector)
    if item_el.count() == 0:
        # Scroll incrementally until the item appears
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(500)
        for _ in range(20):
            page.evaluate("window.scrollBy(0, 800)")
            page.wait_for_timeout(600)
            if item_el.count() > 0:
                break
        if item_el.count() == 0:
            result["reason"] = f"Item {item_id} not found on page"
            return result

    # Click the item to open its modal
    try:
        item_el.first.scroll_into_view_if_needed()
        page.wait_for_timeout(500)
        item_el.first.click()
        page.wait_for_timeout(2000)
    except Exception as e:
        result["reason"] = f"Failed to click item: {e}"
        return result

    # Wait for the modal to appear
    try:
        page.locator('[role="dialog"]').wait_for(state="visible", timeout=5000)
    except Exception as e:
        result["reason"] = f"Modal did not appear: {e}"
        return result

    modal = page.locator('[role="dialog"]')

    # Extract item name and price from modal
    try:
        title_el = modal.locator('[data-testid="menu-item-title"]')
        if title_el.count() > 0:
            result["item_name"] = title_el.first.inner_text().strip()
    except Exception:
        pass

    try:
        price_el = modal.locator('[data-testid="menu-item-price"]')
        if price_el.count() > 0:
            result["item_price"] = price_el.first.inner_text().strip()
    except Exception:
        pass

    # Detect required options
    if _detect_required_options(page):
        result["status"] = "skipped"
        result["reason"] = "Item has required options that must be selected"
        _close_modal(page)
        return result

    # Set quantity (values are quantity * 100000 based on DOM observation)
    if quantity > 1:
        try:
            qty_select = modal.locator('[data-testid="quantity-selector"] select')
            if qty_select.count() > 0:
                target_value = str(quantity * 100000)
                qty_select.first.select_option(value=target_value)
                page.wait_for_timeout(500)
        except Exception as e:
            print(f"  Warning: Could not set quantity: {e}", flush=True)

    # Click "Add to order"
    if _click_add_to_order(page):
        result["status"] = "added"
        page.wait_for_timeout(2000)
        # Close the cart sidebar so the next item can be clicked,
        # unless this is the last item (keep sidebar open for scraping)
        if close_sidebar:
            _close_cart_sidebar(page)
    else:
        result["status"] = "error"
        result["reason"] = "Could not click the Add to order button"
        _close_modal(page)

    return result


def _close_cart_sidebar(page):
    """Close the cart sidebar that opens after adding an item."""
    try:
        close_btn = page.locator('[data-testid="close-button"]')
        if close_btn.count() > 0 and close_btn.first.is_visible(timeout=2000):
            close_btn.first.click()
            page.wait_for_timeout(1000)
            return
    except Exception:
        pass
    # Fallback: click outside the sidebar
    page.mouse.click(100, 400)
    page.wait_for_timeout(1000)


def _scrape_cart_summary(page):
    """Extract the cart summary (items, totals) from the page.

    Expects the cart sidebar to already be open (kept open after last item add).
    If not visible, attempts to reopen it.
    """
    # If the cart list isn't visible, try to open it
    if page.locator('[data-testid="cart-items-list"]').count() == 0:
        # Try clicking elements that might open the cart
        for selector in [
            '[data-testid="cart-button"]',
            'button:has-text("View cart")',
            'button:has-text("Your order")',
        ]:
            try:
                el = page.locator(selector).first
                if el.is_visible(timeout=1000):
                    el.click()
                    page.wait_for_timeout(2000)
                    if page.locator('[data-testid="cart-items-list"]').count() > 0:
                        break
            except Exception:
                continue

    return page.evaluate(
        """() => {
        const cart = {
            items: [],
            subtotal: null,
            delivery_fee: null,
            fees: null,
            total: null,
            raw_text: null,
        };

        // Cart items from [data-testid="cart-items-list"]
        const itemsList = document.querySelector('[data-testid="cart-items-list"]');
        if (itemsList) {
            const itemEls = itemsList.querySelectorAll('[data-test^="cart-item-"]');
            for (const el of itemEls) {
                const divs = el.querySelectorAll('div');
                let name = null;
                let price = null;
                for (const div of divs) {
                    const text = div.innerText.trim();
                    if (!text || text === 'Remove') continue;
                    if (text.match(/^[£$€][\\d.]+$/) && !price) {
                        price = text;
                    } else if (!name && text.length > 1 && !text.match(/^\\d+$/)) {
                        name = text;
                    }
                }
                // Get quantity from the select element
                const select = el.querySelector('[data-testid="quantity-selector"] select');
                const qty = select ? parseInt(select.value) / 100000 : 1;
                if (name) {
                    cart.items.push({ name, price, quantity: qty });
                }
            }
        }

        // Fee breakdown from [data-testid="subtotal-breakdown"]
        const getText = (sel) => {
            const el = document.querySelector(sel);
            return el ? el.innerText.trim() : null;
        };

        cart.subtotal = getText('[data-testid="fare-breakdown-charge-badge-subtotal"]');
        cart.delivery_fee = getText('[data-testid="fare-breakdown-charge-badge-delivery-fee"]');
        cart.fees = getText('[data-testid="fare-breakdown-charge-badge-fees"]');
        cart.total = getText('[data-testid="fare-breakdown-charge-badge-total"]');

        // Raw text fallback
        const breakdown = document.querySelector('[data-testid="subtotal-breakdown"]');
        if (breakdown) {
            cart.raw_text = breakdown.innerText.substring(0, 1000);
        }

        return cart;
    }"""
    )


def scrape_cart(store_url, address, items, headless=True):
    """Open a store, enter address, add items to cart, and return cart state.

    Args:
        store_url: Full Uber Eats store URL
        address: Delivery address (e.g. "Shoreditch, London")
        items: List of dicts with "item_id" (str) and optional "quantity" (int)
        headless: Run browser in headless mode
    """
    pw, browser, context = create_browser_context(headless=headless)
    page = context.new_page()

    try:
        print(f"[Cart] Opening {store_url}", flush=True)
        page.goto(store_url, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        # Handle cookies
        try:
            accept_button = page.locator('button:has-text("Accept")')
            if accept_button.is_visible(timeout=3000):
                accept_button.click()
                print("[Cart] Cookies accepted", flush=True)
        except Exception:
            pass

        # Wait for menu to load
        print("[Cart] Waiting for menu to load...", flush=True)
        try:
            page.wait_for_selector('span:has-text("£")', timeout=15000)
            page.wait_for_timeout(2000)
        except Exception:
            print("[Cart] Warning: Timed out waiting for menu", flush=True)
            page.wait_for_timeout(3000)

        # Process each item (scrolling happens on-demand per item)
        added_items = []
        skipped_items = []
        failed_items = []

        for idx, item_req in enumerate(items):
            item_id = item_req["item_id"]
            quantity = item_req.get("quantity", 1)
            is_last = idx == len(items) - 1
            print(f"[Cart] Processing item {item_id} (qty={quantity})...", flush=True)

            item_result = _add_item_to_cart(
                page, item_id, quantity, close_sidebar=not is_last
            )

            if item_result["status"] == "added":
                added_items.append(item_result)
                print(f"  Added: {item_result['item_name']}", flush=True)
            elif item_result["status"] == "skipped":
                skipped_items.append(item_result)
                print(
                    f"  Skipped: {item_result['item_name']} — {item_result['reason']}",
                    flush=True,
                )
            else:
                failed_items.append(item_result)
                print(
                    f"  Failed: {item_result.get('item_name', item_id)} — {item_result['reason']}",
                    flush=True,
                )

        # Scrape the cart summary
        # The cart sidebar should still be open from the last added item.
        # If the last item was skipped/failed, the sidebar may be closed —
        # _scrape_cart_summary will try to reopen it.
        cart_summary = None
        if added_items:
            print("[Cart] Scraping cart summary...", flush=True)
            page.wait_for_timeout(1000)
            cart_summary = _scrape_cart_summary(page)

        save_state(context)

        return {
            "store_url": store_url,
            "address": address,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "added_items": added_items,
            "skipped_items": skipped_items,
            "failed_items": failed_items,
            "cart_summary": cart_summary,
        }
    finally:
        context.close()
        browser.close()
        pw.stop()


if __name__ == "__main__":
    store_url = (
        "https://www.ubereats.com/gb/store/kfc-bishopsgate/rzYSYjkoTmufdl-RSdMI8Q"
    )
    address = "Shoreditch, London"

    # Simple items for testing (no required options expected)
    test_items = [
        {
            "item_id": "d497d440-fea8-5a55-9688-d2477f2d3008",
            "quantity": 1,
        },  # slaw
        {
            "item_id": "f35db3e8-f168-5169-ba89-56bfc70bc110",
            "quantity": 1,
        },  # cheese sauce
    ]

    for arg in sys.argv[1:]:
        if arg.startswith("http"):
            store_url = arg
        elif not arg.startswith("--"):
            address = arg

    result = scrape_cart(store_url, address, test_items, headless=False)

    with open("cart_result.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"[Cart] Saved result to cart_result.json")
