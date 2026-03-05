from datetime import datetime, timezone
import json
import sys

from scrapers.browser import create_browser_context, save_state


def _extract_menu_data(page):
    """Extract menu categories and items from a restaurant page.

    Uses data-testid selectors discovered from the Uber Eats DOM:
    - Sections: div[data-testid="store-catalog-section-vertical-grid"]
    - Section titles: div[data-testid="catalog-section-title"] > h3
    - Items: li[data-testid^="store-item-"]
    - Item fields: span[data-testid="rich-text"] for name/price/calories
    - Images: picture > source[type="image/webp"] srcset
    """
    return page.evaluate("""() => {
        const results = {
            restaurant_name: null,
            cuisine: [],
            categories: []
        };

        // Restaurant name from h1
        const nameEl = document.querySelector('h1');
        if (nameEl) results.restaurant_name = nameEl.innerText.trim();

        // Try to extract cuisine from JSON-LD structured data
        const ldScript = document.querySelector('script[type="application/ld+json"]');
        if (ldScript) {
            try {
                const ld = JSON.parse(ldScript.textContent);
                if (ld.servesCuisine) results.cuisine = ld.servesCuisine;
            } catch(e) {}
        }

        // Find all menu sections by data-testid
        const sections = document.querySelectorAll('[data-testid="store-catalog-section-vertical-grid"]');

        for (const section of sections) {
            // Get category name from the section title h3
            const titleEl = section.querySelector('[data-testid="catalog-section-title"] h3');
            if (!titleEl) continue;
            const categoryName = titleEl.innerText.trim();
            if (!categoryName) continue;

            const category = {
                name: categoryName,
                items: []
            };

            // Find all menu items in this section: li[data-testid^="store-item-"]
            const itemEls = section.querySelectorAll('li[data-testid^="store-item-"]');

            for (const itemEl of itemEls) {
                // Extract rich-text spans — they contain name, price, calories in order
                const richTexts = itemEl.querySelectorAll('span[data-testid="rich-text"]');
                if (richTexts.length === 0) continue;

                let name = null;
                let price = null;
                let calories = null;

                for (const rt of richTexts) {
                    const text = rt.innerText.trim();
                    if (!text || text === '•') continue;

                    if (text.match(/^[£$€]/)) {
                        price = text;
                    } else if (text.match(/kcal$/i)) {
                        calories = text;
                    } else if (!name) {
                        name = text;
                    }
                }

                if (!name) continue;

                // Description — look for the truncated description div
                let description = null;
                const descEl = itemEl.querySelector('span._la, div._la');
                if (descEl) {
                    description = descEl.innerText.trim();
                }

                // Image — from picture > source (WebP preferred)
                let imageUrl = null;
                const webpSource = itemEl.querySelector('picture source[type="image/webp"]');
                if (webpSource && webpSource.srcset) {
                    const firstUrl = webpSource.srcset.split(',')[0].trim().split(' ')[0];
                    if (firstUrl.startsWith('http')) imageUrl = firstUrl;
                }
                if (!imageUrl) {
                    const img = itemEl.querySelector('picture img[srcset]');
                    if (img && img.srcset) {
                        const firstUrl = img.srcset.split(',')[0].trim().split(' ')[0];
                        if (firstUrl.startsWith('http')) imageUrl = firstUrl;
                    }
                }

                // Item UUID from data-testid="store-item-{uuid}"
                const testId = itemEl.getAttribute('data-testid') || '';
                const itemId = testId.replace('store-item-', '') || null;

                category.items.push({
                    id: itemId,
                    name: name,
                    price: price,
                    calories: calories,
                    description: description,
                    image_url: imageUrl
                });
            }

            if (category.items.length > 0) {
                results.categories.push(category);
            }
        }

        return results;
    }""")


def _capture_debug_snapshot(page):
    """Capture the menu page DOM for debugging and selector refinement."""
    return page.evaluate("""() => {
        const snapshot = {
            title: document.title,
            url: window.location.href,
            headings: [],
            menu_sections: [],
            all_buttons_sample: []
        };

        // Capture all headings for structure analysis
        document.querySelectorAll('h1, h2, h3, h4').forEach(h => {
            snapshot.headings.push({
                tag: h.tagName,
                text: h.innerText.trim().substring(0, 100),
                classes: h.className,
                parent_classes: h.parentElement ? h.parentElement.className : null
            });
        });

        // Capture elements that look like menu item containers
        // Look for list-like structures with prices
        const priceElements = document.querySelectorAll('*');
        const menuContainers = new Set();

        for (const el of priceElements) {
            const text = el.innerText || '';
            if (text.match(/[£$€]\\s*\\d+\\.\\d{2}/) && el.children.length > 0) {
                // This element contains a price, might be a menu item
                let container = el;
                for (let i = 0; i < 5; i++) {
                    if (!container.parentElement) break;
                    container = container.parentElement;
                    const rect = container.getBoundingClientRect();
                    if (rect.height > 80 && rect.width > 200) {
                        if (!menuContainers.has(container)) {
                            menuContainers.add(container);
                            if (snapshot.menu_sections.length < 10) {
                                snapshot.menu_sections.push({
                                    tag: container.tagName,
                                    classes: container.className,
                                    text: container.innerText.substring(0, 500),
                                    html: container.outerHTML.substring(0, 2000),
                                    rect: {
                                        width: Math.round(rect.width),
                                        height: Math.round(rect.height)
                                    },
                                    data_attrs: Object.fromEntries(
                                        [...container.attributes]
                                            .filter(a => a.name.startsWith('data-'))
                                            .map(a => [a.name, a.value])
                                    )
                                });
                            }
                        }
                        break;
                    }
                }
            }
        }

        // Sample of clickable elements that might be menu items
        document.querySelectorAll('button, [role="button"]').forEach((btn, i) => {
            if (i < 15 && btn.innerText.trim().length > 5) {
                const img = btn.querySelector('img[src], img[srcset]');
                snapshot.all_buttons_sample.push({
                    text: btn.innerText.trim().substring(0, 200),
                    classes: btn.className,
                    has_image: !!img,
                    image_src: img ? (img.src || img.srcset?.split(',')[0]?.trim()?.split(' ')[0]) : null,
                    aria_label: btn.getAttribute('aria-label'),
                    data_testid: btn.getAttribute('data-testid'),
                    rect: {
                        width: Math.round(btn.getBoundingClientRect().width),
                        height: Math.round(btn.getBoundingClientRect().height)
                    }
                });
            }
        });

        return snapshot;
    }""")


def scrape_menu(store_url, headless=True, debug=False):
    """Scrape menu items from a specific Uber Eats restaurant page.

    Args:
        store_url: Full URL like https://www.ubereats.com/gb/store/kfc-bishopsgate/rzYSYjkoTmufdl-RSdMI8Q
        headless: Run browser in headless mode
        debug: Capture DOM snapshots for debugging
    """
    pw, browser, context = create_browser_context(headless=headless)
    page = context.new_page()

    try:
        print(f"[Menu Scraper] Opening {store_url}", flush=True)
        page.goto(store_url, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        # Handle cookies
        try:
            accept_button = page.locator('button:has-text("Accept")')
            if accept_button.is_visible(timeout=3000):
                accept_button.click()
                print("[Menu Scraper] Cookies accepted", flush=True)
        except:
            pass

        # Wait for menu content to load
        print("[Menu Scraper] Waiting for menu to load...", flush=True)
        try:
            # Menu items typically have prices
            page.wait_for_selector('span:has-text("£")', timeout=15000)
            page.wait_for_timeout(2000)
        except:
            print("[Menu Scraper] Warning: Timed out waiting for menu items", flush=True)
            page.wait_for_timeout(3000)

        # Scroll to bottom to load all menu items (lazy loading)
        for _ in range(10):
            page.evaluate("window.scrollBy(0, 1500)")
            page.wait_for_timeout(800)

        # Extract menu data
        print("[Menu Scraper] Extracting menu data...", flush=True)
        menu_data = _extract_menu_data(page)

        total_items = sum(len(c["items"]) for c in menu_data["categories"])
        print(f"[Menu Scraper] Found {len(menu_data['categories'])} categories, {total_items} items", flush=True)

        result = {
            "store_url": store_url,
            "restaurant_name": menu_data["restaurant_name"],
            "cuisine": menu_data.get("cuisine", []),
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "category_count": len(menu_data["categories"]),
            "categories": menu_data["categories"],
        }

        # Debug snapshot
        if debug:
            print("[Menu Scraper] Capturing debug snapshot...", flush=True)
            debug_snapshot = _capture_debug_snapshot(page)
            with open("debug_menu.json", "w", encoding="utf-8") as f:
                json.dump(debug_snapshot, f, indent=2, ensure_ascii=False)
            print("[Menu Scraper] Saved debug snapshot to debug_menu.json", flush=True)

        save_state(context)
        return result
    finally:
        context.close()
        browser.close()
        pw.stop()


if __name__ == "__main__":
    debug_mode = "--debug" in sys.argv

    # Default test URL — KFC Bishopsgate
    test_url = "https://www.ubereats.com/gb/store/kfc-bishopsgate/rzYSYjkoTmufdl-RSdMI8Q"

    # Allow passing a custom URL as argument
    for arg in sys.argv[1:]:
        if arg.startswith("http"):
            test_url = arg
            break

    output = scrape_menu(test_url, headless=False, debug=debug_mode)

    with open("menu.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"Saved to menu.json")
