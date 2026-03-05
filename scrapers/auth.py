import threading
from scrapers.browser import create_browser_context, save_state, STATE_FILE

# Login runs on a dedicated thread so all Playwright calls stay on the same thread.
# Flask dispatches /login and /login/complete from different threads, but Playwright's
# sync API can't be accessed across threads — so we coordinate via threading.Event.
_login_thread = None
_login_result = None
_complete_event = threading.Event()
_done_event = threading.Event()


def _accept_cookies(page):
    try:
        btn = page.locator('button:has-text("Accept")')
        if btn.is_visible(timeout=3000):
            btn.click()
    except Exception:
        pass


def _login_thread_fn():
    """Runs on a dedicated thread: opens browser, waits for signal, saves state."""
    global _login_result

    pw, browser, context = create_browser_context(headless=False)
    page = context.new_page()

    try:
        page.goto("https://www.ubereats.com", wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        _accept_cookies(page)

        # Wait for /login/complete to be called (or timeout after 5 minutes)
        signalled = _complete_event.wait(timeout=300)

        if not signalled:
            _login_result = {
                "success": False,
                "error": "TIMEOUT",
                "message": "Login timed out after 5 minutes. Call /login to try again.",
            }
            return

        # Save the session state — trust the user that they logged in
        save_state(context)
        _login_result = {"success": True, "message": "Session saved."}
    except Exception as e:
        _login_result = {"success": False, "error": str(e)}
    finally:
        context.close()
        browser.close()
        pw.stop()
        _done_event.set()


def start_login_session():
    """Open a visible browser window to ubereats.com for manual login.

    The user logs in using any method (Apple, Google, email, passkey, etc.).
    Once done, call complete_login() to save the session.

    Returns:
        dict with status and message.
    """
    global _login_thread, _login_result

    # If a login thread is already running, clean up
    if _login_thread is not None and _login_thread.is_alive():
        _complete_event.set()
        _login_thread.join(timeout=5)

    # Reset state
    _complete_event.clear()
    _done_event.clear()
    _login_result = None

    _login_thread = threading.Thread(target=_login_thread_fn, daemon=True)
    _login_thread.start()

    # Give the browser a moment to open
    import time
    time.sleep(3)

    return {
        "status": "LOGIN_STARTED",
        "message": "Browser window opened at ubereats.com. Log in using any method, then call /login/complete.",
    }


def complete_login():
    """Save the session after the user has logged in manually.

    Returns:
        dict with success status and message.
    """
    if _login_thread is None or not _login_thread.is_alive():
        return {
            "success": False,
            "error": "NO_LOGIN_SESSION",
            "message": "No login session active. Call /login first.",
        }

    # Signal the login thread to save state
    _complete_event.set()

    # Wait for it to finish (up to 10 seconds)
    _done_event.wait(timeout=10)

    if _login_result is not None:
        return _login_result
    else:
        return {"success": False, "error": "Login thread did not respond in time."}


def check_session():
    """Check if a saved session exists with auth cookies."""
    import json

    if not STATE_FILE.exists():
        return {"authenticated": False, "reason": "No saved session"}

    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
        cookies = state.get("cookies", [])
        auth_cookies = [
            c for c in cookies
            if c.get("name") in ("jwt-session", "sid")
            or "session" in c.get("name", "").lower()
        ]
        return {
            "authenticated": len(auth_cookies) > 0,
            "cookies_count": len(cookies),
            "auth_cookies": [c["name"] for c in auth_cookies],
        }
    except Exception as e:
        return {"authenticated": False, "reason": str(e)}


if __name__ == "__main__":
    # CLI utility: open browser for manual login, save on Enter
    print("Opening browser for manual login...")
    pw, browser, context = create_browser_context(headless=False)
    page = context.new_page()
    page.goto("https://www.ubereats.com", wait_until="domcontentloaded")
    page.wait_for_timeout(2000)
    _accept_cookies(page)

    input("\nLog in using any method, then press Enter to save session...")

    save_state(context)
    print("Session saved.")

    context.close()
    browser.close()
    pw.stop()
