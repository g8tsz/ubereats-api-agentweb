from datetime import datetime, timezone
import json
import sys

from scrapers.browser import create_browser_context, save_state


PROMO_KEYWORDS = [
    "order now",
    "buy one get one",
    "% off",
    "only £",
    "only $",
]


def _build_url(href):
    """Build a full URL from an href, avoiding double-domain bug."""
    if not href:
        return None
    if href.startswith("http://") or href.startswith("https://"):
        return href
    return f"https://www.ubereats.com{href}"


def _is_promotional(raw_text, href):
    """Return True if this entry is a promotional banner, not a real restaurant."""
    text_lower = raw_text.lower()
    if any(kw in text_lower for kw in PROMO_KEYWORDS):
        return True
    if href and ("utm_source=" in href or "mod=merchantUnavailable" in href):
        return True
    return False


def _extract_card_metadata(link):
    """Extract structured metadata from the card container using aria-labels and srcset."""
    return link.evaluate("""el => {
        let node = el;
        for (let i = 0; i < 8; i++) {
            if (!node.parentElement) break;
            node = node.parentElement;
            const rect = node.getBoundingClientRect();
            if (rect.height > 150 && rect.width > 200) break;
        }

        const result = {
            rating: null,
            review_count: null,
            delivery_time: null,
            delivery_fee: null,
            image_url: null,
            promo: null
        };

        // Rating and reviews from aria-label: "Rating: 4.4 stars. 500+ reviews"
        const ratingEl = node.querySelector('[aria-label^="Rating:"]');
        if (ratingEl) {
            const label = ratingEl.getAttribute('aria-label');
            const ratingMatch = label.match(/Rating:\\s*([\\d.]+)\\s*stars?/);
            if (ratingMatch) result.rating = parseFloat(ratingMatch[1]);
            const reviewMatch = label.match(/([\\d,]+\\+?)\\s*reviews?/);
            if (reviewMatch) result.review_count = reviewMatch[1];
        }

        // Delivery time from aria-label: "Estimated time of departure: 10 min"
        const timeEl = node.querySelector('[aria-label*="Estimated time"]');
        if (timeEl) {
            const label = timeEl.getAttribute('aria-label');
            const timeMatch = label.match(/:\\s*(.+)/);
            if (timeMatch) result.delivery_time = timeMatch[1].trim();
        }

        // Image from picture > source (WebP preferred, fallback to img srcset)
        const webpSource = node.querySelector('picture source[type="image/webp"]');
        if (webpSource && webpSource.srcset) {
            const firstUrl = webpSource.srcset.split(',')[0].trim().split(' ')[0];
            if (firstUrl && firstUrl.startsWith('http')) result.image_url = firstUrl;
        }
        if (!result.image_url) {
            const img = node.querySelector('picture img[srcset]');
            if (img && img.srcset) {
                const firstUrl = img.srcset.split(',')[0].trim().split(' ')[0];
                if (firstUrl && firstUrl.startsWith('http')) result.image_url = firstUrl;
            }
        }

        // Promo badge / delivery fee from span[data-baseweb="tag"]
        const promoEl = node.querySelector('[data-baseweb="tag"]');
        if (promoEl) {
            const text = promoEl.innerText.trim();
            if (text) {
                if (text.toLowerCase().includes('delivery fee')) {
                    result.delivery_fee = text;
                } else {
                    result.promo = text;
                }
            }
        }

        return result;
    }""")


def _get_card_debug_info(link):
    """Walk up the DOM from a store link to find the card container.
    Returns the container's innerText, outerHTML, image URLs, and a CSS selector fingerprint."""
    return link.evaluate("""el => {
        let node = el;
        for (let i = 0; i < 8; i++) {
            if (!node.parentElement) break;
            node = node.parentElement;
            const rect = node.getBoundingClientRect();
            if (rect.height > 150 && rect.width > 200) break;
        }

        let sel = node.tagName.toLowerCase();
        if (node.className && typeof node.className === 'string') {
            sel += '.' + node.className.trim().split(/\\s+/).join('.');
        }
        for (const attr of node.attributes) {
            if (attr.name.startsWith('data-')) {
                sel += '[' + attr.name + '="' + attr.value + '"]';
            }
        }

        const images = [...node.querySelectorAll('img[src]')].map(img => img.src);

        return {
            text: node.innerText,
            html: node.outerHTML,
            selector: sel,
            images: images,
            rect: {
                width: Math.round(node.getBoundingClientRect().width),
                height: Math.round(node.getBoundingClientRect().height)
            }
        };
    }""")


def scrape_ubereats_restaurants(location="Shoreditch, London", headless=True, debug=False):
    pw, browser, context = create_browser_context(headless=headless)
    page = context.new_page()

    try:
        print("[Scraper] Opening Uber Eats...", flush=True)
        page.goto("https://www.ubereats.com/gb", wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        # Handle cookies
        try:
            accept_button = page.locator('button:has-text("Accept")')
            if accept_button.is_visible(timeout=3000):
                accept_button.click()
                print("[Scraper] Cookies accepted", flush=True)
        except:
            pass

        # Enter delivery address
        print(f"[Scraper] Entering location: {location}", flush=True)
        address_input = page.locator('input[placeholder*="delivery address"]')
        address_input.fill(location)
        page.wait_for_timeout(1500)
        address_input.press("Enter")

        # Wait for restaurants to load
        print("[Scraper] Waiting for restaurants to load...", flush=True)
        try:
            page.wait_for_selector('a[href*="/store/"]', timeout=15000)
            page.wait_for_timeout(2000)
        except:
            print("[Scraper] Warning: Timed out waiting for restaurant feed, continuing anyway...", flush=True)
            page.wait_for_timeout(3000)

        # Scroll to load more restaurants
        for _ in range(3):
            page.evaluate("window.scrollBy(0, 800)")
            page.wait_for_timeout(1500)

        # Extract restaurant data
        print("[Scraper] Extracting restaurant data...", flush=True)
        restaurant_cards = page.locator('a[href*="/store/"]').all()
        print(f"[Scraper] Found {len(restaurant_cards)} restaurant links", flush=True)

        restaurants = []
        debug_cards = []
        seen_urls = set()

        for i, card in enumerate(restaurant_cards):
            try:
                text_content = card.inner_text()
                href = card.get_attribute("href")
                url = _build_url(href)

                # Deduplicate
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                # Filter promotional banners
                if _is_promotional(text_content, href):
                    print(f"  Skipped promo: {text_content[:50]}...")
                    continue

                # Restaurant name from heading element
                name_elem = card.locator('h3, h2, [role="heading"]').first
                name = name_elem.inner_text() if name_elem.count() > 0 else text_content.split("\n")[0]

                # Extract structured metadata from the card container
                metadata = _extract_card_metadata(card)

                restaurant_data = {
                    "name": name,
                    "url": url,
                    "rating": metadata.get("rating"),
                    "review_count": metadata.get("review_count"),
                    "delivery_time": metadata.get("delivery_time"),
                    "delivery_fee": metadata.get("delivery_fee"),
                    "promo": metadata.get("promo"),
                    "image_url": metadata.get("image_url"),
                }

                restaurants.append(restaurant_data)
                rating_str = f" ({metadata.get('rating')})" if metadata.get("rating") else ""
                print(f"  {len(restaurants)}. {name}{rating_str}")

                # Capture debug info
                if debug:
                    try:
                        card_info = _get_card_debug_info(card)
                        debug_cards.append({
                            "restaurant_name": name,
                            "link_href": href,
                            "link_text": text_content,
                            "card_container": card_info,
                        })
                    except Exception as e:
                        print(f"    Debug capture failed: {e}")

            except Exception as e:
                print(f"  Error extracting restaurant {i+1}: {e}")
                continue

        result = {
            "location": location,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "restaurant_count": len(restaurants),
            "restaurants": restaurants,
        }

        print(f"\nScraped {len(restaurants)} restaurants")

        # Save debug info to file when running in debug mode
        if debug and debug_cards:
            with open("debug_cards.json", "w", encoding="utf-8") as f:
                json.dump(debug_cards, f, indent=2, ensure_ascii=False)
            print(f"Saved {len(debug_cards)} card debug snapshots to debug_cards.json")

        save_state(context)
        return result
    finally:
        context.close()
        browser.close()
        pw.stop()


if __name__ == "__main__":
    debug_mode = "--debug" in sys.argv
    output = scrape_ubereats_restaurants(
        "Shoreditch, London", headless=False, debug=debug_mode
    )

    with open("restaurants.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"Saved to restaurants.json")
