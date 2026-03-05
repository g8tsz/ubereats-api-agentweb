from pathlib import Path
from playwright.sync_api import sync_playwright, BrowserContext


STATE_DIR = Path(__file__).parent.parent / ".session"
STATE_FILE = STATE_DIR / "ubereats_state.json"

# Centralized config — previously duplicated across every scraper
LAUNCH_ARGS = {
    "channel": "chrome",
    "args": [
        "--disable-blink-features=AutomationControlled",
        "--disable-features=IsolateOrigins,site-per-process",
    ],
}

CONTEXT_OPTIONS = {
    "viewport": {"width": 1440, "height": 900},
    "locale": "en-GB",
    "timezone_id": "Europe/London",
    "extra_http_headers": {
        "Accept-Language": "en-GB,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-CH-UA-Platform": '"macOS"',
    },
}

ANTI_DETECT_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    Object.defineProperty(navigator, 'languages', {get: () => ['en-GB', 'en']});
    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
    window.chrome = { runtime: {} };
    Object.defineProperty(navigator, 'maxTouchPoints', {get: () => 0});
"""


def has_saved_state() -> bool:
    return STATE_FILE.exists() and STATE_FILE.stat().st_size > 10


def save_state(context: BrowserContext):
    """Persist cookies and localStorage to disk."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    context.storage_state(path=str(STATE_FILE))


def clear_state():
    """Delete saved session state."""
    if STATE_FILE.exists():
        STATE_FILE.unlink()


def create_browser_context(headless=True):
    """Create a fresh Playwright instance, browser, and context.

    Returns (playwright, browser, context) — caller must close all three.
    Each call creates everything fresh on the calling thread,
    which avoids Playwright's thread-safety issues.
    """
    pw = sync_playwright().start()

    launch_args = dict(LAUNCH_ARGS)
    launch_args["headless"] = headless
    if not headless:
        launch_args["slow_mo"] = 500
    browser = pw.chromium.launch(**launch_args)

    opts = dict(CONTEXT_OPTIONS)
    if has_saved_state():
        opts["storage_state"] = str(STATE_FILE)
    context = browser.new_context(**opts)
    context.add_init_script(ANTI_DETECT_SCRIPT)

    return pw, browser, context
