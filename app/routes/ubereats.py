import logging
import sys
from flask import Blueprint, request, jsonify
from scrapers.restaurants import scrape_ubereats_restaurants
from scrapers.menu import scrape_menu
from scrapers.cart import scrape_cart
from scrapers.auth import start_login_session, complete_login, check_session
from scrapers.checkout import scrape_checkout
from app.services.transform import transform_restaurant, transform_menu, transform_cart

logging.basicConfig(stream=sys.stdout, level=logging.INFO)
logger = logging.getLogger(__name__)

ubereats_bp = Blueprint("ubereats", __name__, url_prefix="/api/ubereats")


@ubereats_bp.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@ubereats_bp.route("/search", methods=["POST"])
def search():
    data = request.get_json(silent=True) or {}

    location = data.get("location")
    if not location:
        return jsonify({"error": "location is required"}), 400

    min_rating = data.get("min_rating")
    max_delivery_minutes = data.get("max_delivery_minutes")

    # Scrape
    print(f"[API] Scraping restaurants for: {location}", flush=True)
    try:
        raw_result = scrape_ubereats_restaurants(location, headless=True)
    except Exception as e:
        logger.exception("Scraping failed")
        return jsonify({"error": f"Scraping failed: {e}"}), 500

    print(f"[API] Scraped {raw_result['restaurant_count']} restaurants, transforming...", flush=True)

    # Transform
    restaurants = [transform_restaurant(r) for r in raw_result["restaurants"]]

    # Filter
    if min_rating is not None:
        restaurants = [
            r for r in restaurants if r["rating"] is not None and r["rating"] >= min_rating
        ]
    if max_delivery_minutes is not None:
        restaurants = [
            r
            for r in restaurants
            if r["eta_minutes"] is not None and r["eta_minutes"] <= max_delivery_minutes
        ]

    print(f"[API] Returning {len(restaurants)} restaurants after filtering", flush=True)

    return jsonify(
        {
            "location": raw_result["location"],
            "scraped_at": raw_result["scraped_at"],
            "count": len(restaurants),
            "restaurants": restaurants,
        }
    )


@ubereats_bp.route("/menu", methods=["POST"])
def menu():
    data = request.get_json(silent=True) or {}

    store_url = data.get("store_url")
    if not store_url:
        return jsonify({"error": "store_url is required"}), 400

    # Scrape menu
    print(f"[API] Scraping menu for: {store_url}", flush=True)
    try:
        raw_result = scrape_menu(store_url, headless=True)
    except Exception as e:
        logger.exception("Menu scraping failed")
        return jsonify({"error": f"Menu scraping failed: {e}"}), 500

    # Transform
    result = transform_menu(raw_result)

    print(f"[API] Returning {result['item_count']} menu items in {result['category_count']} categories", flush=True)

    return jsonify(result)


@ubereats_bp.route("/cart", methods=["POST"])
def cart():
    data = request.get_json(silent=True) or {}

    store_url = data.get("store_url")
    if not store_url:
        return jsonify({"error": "store_url is required"}), 400

    address = data.get("address")
    if not address:
        return jsonify({"error": "address is required"}), 400

    items = data.get("items")
    if not items or not isinstance(items, list):
        return jsonify({"error": "items is required and must be a list"}), 400

    for i, item in enumerate(items):
        if not isinstance(item, dict) or not item.get("item_id"):
            return jsonify({"error": f"items[{i}] must have an item_id"}), 400
        if "quantity" not in item:
            item["quantity"] = 1

    print(f"[API] Adding {len(items)} items to cart at: {store_url}", flush=True)
    try:
        raw_result = scrape_cart(store_url, address, items, headless=True)
    except Exception as e:
        logger.exception("Cart scraping failed")
        return jsonify({"error": f"Cart scraping failed: {e}"}), 500

    result = transform_cart(raw_result)

    print(
        f"[API] Cart result: {result['added_count']} added, "
        f"{result['skipped_count']} skipped, {result['failed_count']} failed",
        flush=True,
    )

    return jsonify(result)


@ubereats_bp.route("/login", methods=["POST"])
def login():
    try:
        result = start_login_session()
        return jsonify(result)
    except Exception as e:
        logger.exception("Login failed")
        return jsonify({"error": f"Login failed: {e}"}), 500


@ubereats_bp.route("/login/complete", methods=["POST"])
def login_complete():
    try:
        result = complete_login()
        status = 200 if result.get("success") else 400
        return jsonify(result), status
    except Exception as e:
        logger.exception("Login completion failed")
        return jsonify({"error": f"Login completion failed: {e}"}), 500


@ubereats_bp.route("/session", methods=["GET"])
def session_status():
    try:
        result = check_session()
        return jsonify(result)
    except Exception as e:
        logger.exception("Session check failed")
        return jsonify({"error": str(e)}), 500


@ubereats_bp.route("/checkout", methods=["POST"])
def checkout():
    data = request.get_json(silent=True) or {}
    debug = data.get("debug", False)
    dry_run = data.get("dry_run", True)

    try:
        result = scrape_checkout(headless=True, debug=debug, dry_run=dry_run)
        if result.get("success"):
            return jsonify(result)
        elif result.get("error") in ("SESSION_EXPIRED", "NOT_AUTHENTICATED"):
            return jsonify(result), 401
        else:
            return jsonify(result), 400
    except Exception as e:
        logger.exception("Checkout failed")
        return jsonify({"error": f"Checkout failed: {e}"}), 500
