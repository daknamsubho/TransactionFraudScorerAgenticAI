"""Unit tests for the two-page WebUI client package (src/web_client)."""

from web_client import get_static_dir


def test_web_client_separated_files_exist() -> None:
    """Verify separated index.html, queue.html, styles.css, and app.js exist in src/web_client/static."""
    static_dir = get_static_dir()
    assert static_dir.is_dir()

    index_html = static_dir / "index.html"
    queue_html = static_dir / "queue.html"
    styles_css = static_dir / "styles.css"
    app_js = static_dir / "app.js"

    assert index_html.is_file()
    assert queue_html.is_file()
    assert styles_css.is_file()
    assert app_js.is_file()


def test_submit_page_and_queue_page_structure() -> None:
    """Verify index.html has the transaction submit form and queue.html has the WebSocket queue & decision form."""
    index_html = (get_static_dir() / "index.html").read_text(encoding="utf-8")
    queue_html = (get_static_dir() / "queue.html").read_text(encoding="utf-8")

    # Page 1: Submit Transaction (index.html)
    assert '<link rel="stylesheet" href="styles.css">' in index_html
    assert '<script src="app.js" defer></script>' in index_html
    assert 'href="queue.html"' in index_html
    assert 'id="gateway-url"' in index_html
    assert 'id="transaction-form"' in index_html
    assert 'id="ws-events-table"' not in index_html

    # Page 2: Decision Queue (queue.html)
    assert '<link rel="stylesheet" href="styles.css">' in queue_html
    assert '<script src="app.js" defer></script>' in queue_html
    assert 'href="index.html"' in queue_html
    assert 'id="gateway-url"' in queue_html
    assert 'id="ws-events-table"' in queue_html
    assert 'id="decision-form"' in queue_html
    assert 'id="transaction-form"' not in queue_html


def test_styles_css_uses_user_invalid_and_container_queries() -> None:
    """Verify styles.css includes :user-invalid validation and @container responsive table queries."""
    css = (get_static_dir() / "styles.css").read_text(encoding="utf-8")

    assert ":user-invalid" in css
    assert "user-invalid-fallback" in css
    assert "container-type: inline-size" in css
    assert "@container (width < 600px)" in css


def test_app_js_handles_rest_and_websocket_endpoints() -> None:
    """Verify app.js connects to /ws/transactions/events and posts to score and decision endpoints."""
    js = (get_static_dir() / "app.js").read_text(encoding="utf-8")

    assert "/ws/transactions/events" in js
    assert "/api/v1/transactions/score" in js
    assert "/api/v1/transactions/decision" in js
    assert "new WebSocket" in js
