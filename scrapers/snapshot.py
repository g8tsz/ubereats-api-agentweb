from playwright.sync_api import sync_playwright


def take_snapshot():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            channel="chrome",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
            slow_mo=500,
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="en-GB",
            timezone_id="Europe/London",
            extra_http_headers={
                "Accept-Language": "en-GB,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Sec-CH-UA-Platform": '"macOS"',
            },
        )
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-GB', 'en']});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'maxTouchPoints', {get: () => 0});
        """)
        page = context.new_page()

        print("Opening KFC store page...", flush=True)
        page.goto(
            "https://www.ubereats.com/gb/store/kfc-bishopsgate/rzYSYjkoTmufdl-RSdMI8Q",
            wait_until="domcontentloaded",
        )
        page.wait_for_timeout(3000)

        # Accept cookies if prompted
        try:
            accept_button = page.locator('button:has-text("Accept")')
            if accept_button.is_visible(timeout=3000):
                accept_button.click()
                print("Cookies accepted", flush=True)
                page.wait_for_timeout(1000)
        except:
            pass

        # Wait for menu content
        try:
            page.wait_for_selector('span:has-text("£")', timeout=15000)
        except:
            print("Warning: menu items not found", flush=True)

        # --- Enter delivery address ---
        print("Entering delivery address...", flush=True)
        address_input = page.locator("#store-address-search-input")
        if address_input.is_visible(timeout=3000):
            print("Address input already visible", flush=True)
        else:
            try:
                addr_button = page.locator('button:has-text("Enter delivery address")').first
                addr_button.click(timeout=5000)
                print("Clicked address button", flush=True)
                page.wait_for_timeout(2000)
            except Exception as e:
                print(f"Could not click address button: {e}", flush=True)

        address_input = page.locator("#store-address-search-input")
        if address_input.is_visible(timeout=3000):
            address_input.click()
            address_input.fill("Shoreditch, London")
            page.wait_for_timeout(2000)

            # Wait for autocomplete and click first suggestion
            try:
                page.wait_for_function(
                    """() => {
                        const el = document.querySelector(
                            '[data-testid="store-ephemeral-address-input-wrapper"]'
                        );
                        return el && el.getAttribute('aria-expanded') === 'true';
                    }""",
                    timeout=8000,
                )
                suggestion = page.locator(
                    '[data-testid="store-ephemeral-address-search-result-0"]'
                )
                suggestion.click(timeout=5000)
                print("Selected address suggestion", flush=True)
                page.wait_for_timeout(3000)
            except Exception as e:
                print(f"Address autocomplete failed: {e}", flush=True)
        else:
            print("Address input not found", flush=True)

        # --- Scroll to load all items, then scroll back ---
        for _ in range(10):
            page.evaluate("window.scrollBy(0, 1500)")
            page.wait_for_timeout(800)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(1000)

        # --- Click Pepsi MAX Can to open its modal ---
        pepsi_id = "d19351b2-e5ed-5643-b6a7-37c30e0d8841"
        item_el = page.locator(f'li[data-testid="store-item-{pepsi_id}"]')
        if item_el.count() > 0:
            item_el.first.scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            item_el.first.click()
            print("Clicked Pepsi MAX Can", flush=True)
            page.wait_for_timeout(2000)

            # Screenshot the item modal
            page.screenshot(path="snapshot_item_modal.png", full_page=False)
            print("Screenshot saved: snapshot_item_modal.png", flush=True)

            # Click "Add to order" button
            modal = page.locator('[role="dialog"]')
            added = False
            try:
                cta = modal.locator('[data-test="add-to-cart-cta"] button')
                if cta.count() > 0 and cta.first.is_enabled():
                    cta.first.click()
                    added = True
            except:
                pass
            if not added:
                try:
                    btn = modal.locator('button:has-text("Add to order")')
                    if btn.count() > 0 and btn.first.is_enabled():
                        btn.first.click()
                        added = True
                except:
                    pass
            if not added:
                try:
                    buttons = modal.locator("button").all()
                    for b in buttons:
                        text = b.inner_text().strip().lower()
                        if "add" in text and ("order" in text or "£" in text):
                            if b.is_enabled():
                                b.click()
                                added = True
                                break
                except:
                    pass

            if added:
                print("Clicked Add to order!", flush=True)
            else:
                print("Could not find Add to order button", flush=True)

            page.wait_for_timeout(3000)

            # --- Capture the cart modal/sidebar that appeared ---
            page.screenshot(path="snapshot_cart_modal.png", full_page=False)
            print("Screenshot saved: snapshot_cart_modal.png", flush=True)

            content = page.content()
            with open("snapshot_cart_modal.html", "w", encoding="utf-8") as f:
                f.write(content)
            print("HTML saved: snapshot_cart_modal.html", flush=True)
        else:
            print(f"Pepsi MAX Can item not found (id: {pepsi_id})", flush=True)

        input("Press Enter to close browser...")
        browser.close()


if __name__ == "__main__":
    take_snapshot()
