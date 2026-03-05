import re


def extract_store_id(url):
    """Extract the store ID from a Uber Eats URL.
    e.g. '.../store/kfc-bishopsgate/rzYSYjkoTmufdl-RSdMI8Q' -> 'rzYSYjkoTmufdl-RSdMI8Q'
    """
    if not url:
        return None
    parts = url.rstrip("/").split("/")
    return parts[-1] if parts else None


def parse_reviews(review_count):
    """Parse review count string into an integer.
    e.g. '2,000+' -> 2000, '500+' -> 500
    """
    if not review_count:
        return None
    cleaned = review_count.replace(",", "").replace("+", "")
    try:
        return int(cleaned)
    except ValueError:
        return None


def parse_eta_minutes(delivery_time):
    """Parse delivery time string into minutes (integer, lower bound).
    e.g. '10 min' -> 10, '10-20 min' -> 10
    """
    if not delivery_time:
        return None
    match = re.search(r"(\d+)", delivery_time)
    return int(match.group(1)) if match else None


def transform_restaurant(raw):
    """Transform a raw scraper restaurant dict into an agent-friendly format."""
    return {
        "id": extract_store_id(raw.get("url")),
        "name": raw.get("name"),
        "rating": raw.get("rating"),
        "reviews": parse_reviews(raw.get("review_count")),
        "eta_minutes": parse_eta_minutes(raw.get("delivery_time")),
        "delivery_fee": raw.get("delivery_fee"),
        "promo": raw.get("promo"),
        "image": raw.get("image_url"),
        "url": raw.get("url"),
    }


def parse_price(price_str):
    """Parse a price string into a float.
    e.g. '£8.99' -> 8.99, '£12.50' -> 12.50
    """
    if not price_str:
        return None
    match = re.search(r"[\d.]+", price_str)
    if match:
        try:
            return float(match.group())
        except ValueError:
            return None
    return None


def parse_calories(cal_str):
    """Parse calories string into an integer.
    e.g. '390 kcal' -> 390
    """
    if not cal_str:
        return None
    match = re.search(r"(\d+)", cal_str)
    return int(match.group(1)) if match else None


def transform_menu_item(raw):
    """Transform a raw menu item into an agent-friendly format."""
    return {
        "id": raw.get("id"),
        "name": raw.get("name"),
        "price": parse_price(raw.get("price")),
        "price_formatted": raw.get("price"),
        "calories": parse_calories(raw.get("calories")),
        "description": raw.get("description"),
        "image": raw.get("image_url"),
    }


def transform_menu(raw_result):
    """Transform the full menu scraper output into agent-friendly format."""
    categories = []
    for cat in raw_result.get("categories", []):
        items = [transform_menu_item(item) for item in cat.get("items", [])]
        if items:
            categories.append({
                "name": cat["name"],
                "items": items,
            })

    return {
        "restaurant_name": raw_result.get("restaurant_name"),
        "cuisine": raw_result.get("cuisine", []),
        "store_url": raw_result.get("store_url"),
        "scraped_at": raw_result.get("scraped_at"),
        "category_count": len(categories),
        "item_count": sum(len(c["items"]) for c in categories),
        "categories": categories,
    }


def transform_cart_item(raw):
    """Transform a raw cart item result into agent-friendly format."""
    return {
        "item_id": raw.get("item_id"),
        "name": raw.get("item_name"),
        "price": parse_price(raw.get("item_price")),
        "price_formatted": raw.get("item_price"),
        "quantity": raw.get("quantity"),
        "status": raw.get("status"),
        "reason": raw.get("reason"),
    }


def transform_cart(raw_result):
    """Transform the full cart scraper output into agent-friendly format."""
    added = [transform_cart_item(i) for i in raw_result.get("added_items", [])]
    skipped = [transform_cart_item(i) for i in raw_result.get("skipped_items", [])]
    failed = [transform_cart_item(i) for i in raw_result.get("failed_items", [])]

    summary = raw_result.get("cart_summary")
    cart_totals = None
    if summary and not raw_result.get("error"):
        cart_totals = {
            "subtotal": parse_price(summary.get("subtotal")),
            "subtotal_formatted": summary.get("subtotal"),
            "delivery_fee": parse_price(summary.get("delivery_fee")),
            "delivery_fee_formatted": summary.get("delivery_fee"),
            "fees": parse_price(summary.get("fees")),
            "fees_formatted": summary.get("fees"),
            "total": parse_price(summary.get("total")),
            "total_formatted": summary.get("total"),
            "cart_items": summary.get("items", []),
        }

    return {
        "store_url": raw_result.get("store_url"),
        "address": raw_result.get("address"),
        "scraped_at": raw_result.get("scraped_at"),
        "error": raw_result.get("error"),
        "added_count": len(added),
        "skipped_count": len(skipped),
        "failed_count": len(failed),
        "added_items": added,
        "skipped_items": skipped,
        "failed_items": failed,
        "cart_totals": cart_totals,
    }
