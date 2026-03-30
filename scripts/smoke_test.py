"""Smoke test: start server and hit every route to verify non-error responses.

Usage: python scripts/smoke_test.py
Requires: pip install httpx
"""

import sys
import time
import threading
import httpx
import uvicorn

BASE = "http://127.0.0.1:8765"

# All routes to test: (method, path, expected_status_or_range)
# Pages should return 200. APIs may return 200 or 404 (no data loaded).
# We just verify nothing returns 500.
ROUTES = [
    # Pages
    ("GET", "/"),
    ("GET", "/dwarves"),
    ("GET", "/dwarves/relationships"),
    ("GET", "/dwarves/religion"),
    ("GET", "/events"),
    ("GET", "/dashboard"),
    ("GET", "/lore"),
    ("GET", "/lore/map"),
    ("GET", "/gazette"),
    ("GET", "/quests"),
    ("GET", "/settings"),
    # JSON APIs
    ("GET", "/api/relationships"),
    ("GET", "/api/religion"),
    ("GET", "/api/highlights"),
    ("GET", "/api/notes"),
    ("GET", "/api/quests"),
    ("GET", "/api/worlds"),
    ("GET", "/api/lore/search?q=test"),
    ("GET", "/api/lore/pins"),
    # These may 404 with no data, that's fine
    ("GET", "/dwarves/1"),
    ("GET", "/api/lore/stats/world"),
]


def run_server():
    """Start the server in a thread."""
    from df_storyteller.web.app import app
    config = uvicorn.Config(app, host="127.0.0.1", port=8765, log_level="warning")
    server = uvicorn.Server(config)
    server.run()


def wait_for_server(timeout: float = 30) -> bool:
    """Wait for server to be ready."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = httpx.get(f"{BASE}/settings", timeout=2)
            if r.status_code < 500:
                return True
        except (httpx.ConnectError, httpx.ReadTimeout):
            pass
        time.sleep(0.5)
    return False


def main():
    # Start server in background thread
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    print("Waiting for server to start...")
    if not wait_for_server():
        print("FAIL: Server did not start within 30 seconds")
        sys.exit(1)
    print("Server is ready.\n")

    passed = 0
    failed = 0
    errors = []

    with httpx.Client(base_url=BASE, timeout=15, follow_redirects=True) as client:
        for method, path in ROUTES:
            try:
                if method == "GET":
                    r = client.get(path)
                elif method == "POST":
                    r = client.post(path)
                else:
                    continue

                if r.status_code >= 500:
                    print(f"  FAIL  {method} {path} -> {r.status_code}")
                    errors.append((method, path, r.status_code))
                    failed += 1
                else:
                    print(f"  OK    {method} {path} -> {r.status_code}")
                    passed += 1
            except Exception as e:
                print(f"  ERROR {method} {path} -> {e}")
                errors.append((method, path, str(e)))
                failed += 1

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")

    if errors:
        print("\nFailures:")
        for method, path, detail in errors:
            print(f"  {method} {path}: {detail}")
        sys.exit(1)
    else:
        print("All routes OK!")
        sys.exit(0)


if __name__ == "__main__":
    main()
