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
    assert 'id="decision-form"' not in index_html

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
    assert "/api/v1/db/user-profiles" in js
    assert "/api/v1/db/transactions" in js
    assert "/api/v1/db/transaction-scores" in js
    assert "new WebSocket" in js


def test_rdbms_paginated_table_pages_exist_and_have_pagination() -> None:
    """Verify users.html, transactions.html, and scores.html exist and provide paginated table views."""
    static_dir = get_static_dir()
    users_html = (static_dir / "users.html").read_text(encoding="utf-8")
    tx_html = (static_dir / "transactions.html").read_text(encoding="utf-8")
    scores_html = (static_dir / "scores.html").read_text(encoding="utf-8")

    # Verify navigation links across all 5 pages
    for page_html in (users_html, tx_html, scores_html):
        assert 'href="index.html"' in page_html
        assert 'href="queue.html"' in page_html
        assert 'href="users.html"' in page_html
        assert 'href="transactions.html"' in page_html
        assert 'href="scores.html"' in page_html
        assert 'class="pagination-bar"' in page_html
        assert 'class="table-wrapper"' in page_html

    assert 'id="users-rdbms-table"' in users_html
    assert 'id="users-prev-btn"' in users_html
    assert 'id="users-next-btn"' in users_html

    assert 'id="transactions-rdbms-table"' in tx_html
    assert 'id="tx-prev-btn"' in tx_html
    assert 'id="tx-next-btn"' in tx_html

    assert 'id="scores-rdbms-table"' in scores_html
    assert 'id="scores-prev-btn"' in scores_html
    assert 'id="scores-next-btn"' in scores_html


def test_index_html_has_manual_test_buttons_and_details_section() -> None:
    """PRD-012: index.html exposes 3 test loader buttons and a Test Transaction Details section."""
    index_html = (get_static_dir() / "index.html").read_text(encoding="utf-8")

    assert '<button type="button" id="btn-import-random-test"' in index_html
    assert "Import Random transaction from test_transaction_dataset" in index_html
    assert '<button type="button" id="btn-generate-good-tx"' in index_html
    assert "Generate Good Transaction" in index_html
    assert '<button type="button" id="btn-generate-fraud-tx"' in index_html
    assert "Generate Fraud Transaction" in index_html

    for element_id in (
        "test-transaction-details-section",
        "test-detail-scenario-id",
        "test-detail-source",
        "test-detail-persona",
        "test-detail-username",
        "test-detail-profile",
        "test-detail-description",
        "test-detail-json",
    ):
        assert f'id="{element_id}"' in index_html

    # index.html must remain free of decisioning UI (that lives on queue.html)
    assert 'id="decision-form"' not in index_html


def test_app_js_loads_test_dataset_from_web_client_only() -> None:
    """PRD-012: app.js loads the dataset from the WebClient itself; the API Gateway stays headless."""
    js = (get_static_dir() / "app.js").read_text(encoding="utf-8")

    assert 'const TEST_DATASET_URL = "dataset/test_transactions_dataset.json"' in js
    assert "function importRandomTestTransaction" in js
    assert "function generateGoodTransaction" in js
    assert "function generateFraudTransaction" in js
    assert "function populateFormFromTransaction" in js
    assert "function renderTestDetails" in js
    assert 'addEventListener("click", importRandomTestTransaction)' in js
    assert 'addEventListener("click", generateGoodTransaction)' in js
    assert 'addEventListener("click", generateFraudTransaction)' in js
    # No gateway endpoint for test data
    assert "/api/v1/transactions/test-dataset" not in js


def test_web_client_server_serves_local_test_dataset() -> None:
    """PRD-012: WebClientRequestHandler maps /dataset/test_transactions_dataset.json to docs/dataset."""
    import json

    from web_client import WebClientRequestHandler, get_test_dataset_path

    dataset_path = get_test_dataset_path()
    assert dataset_path.is_file()
    items = json.loads(dataset_path.read_text(encoding="utf-8"))
    assert len(items) == 25
    assert {item["transaction_profile"] for item in items} == {"good", "bad"}

    handler = WebClientRequestHandler.__new__(WebClientRequestHandler)
    handler.directory = str(get_static_dir())
    assert handler.translate_path("/dataset/test_transactions_dataset.json") == str(dataset_path)
    assert handler.translate_path("/dataset/test_transactions_dataset.json?x=1") == str(dataset_path)
    assert handler.translate_path("/index.html") == str(get_static_dir() / "index.html")


def test_api_gateway_has_no_test_dataset_route() -> None:
    """PRD-012: The headless API Gateway must not expose any test dataset endpoint."""
    from api_gateway.app import app

    paths = {getattr(route, "path", "") for route in app.routes}
    assert not any("test-dataset" in path for path in paths)


def test_vectordb_html_page_and_navigation_exist() -> None:
    """PRD-016: Verify vectordb.html exists with query, Top K, filters, and upload form, and is linked across pages."""
    static_dir = get_static_dir()
    vectordb_path = static_dir / "vectordb.html"
    assert vectordb_path.is_file()

    vectordb_html = vectordb_path.read_text(encoding="utf-8")
    assert 'id="vector-query-form"' in vectordb_html
    assert 'id="vector-query-input"' in vectordb_html
    assert 'id="vector-top-k"' in vectordb_html
    assert 'name="policy_year"' in vectordb_html
    assert 'id="vector-category-filter"' in vectordb_html
    assert 'id="vector-results-container"' in vectordb_html
    assert 'id="vector-upload-form"' in vectordb_html
    assert 'id="vector-upload-file"' in vectordb_html
    assert 'id="vector-upload-content"' in vectordb_html

    # Verify navigation link to vectordb.html exists on all 6 pages
    for page_name in ("index.html", "queue.html", "users.html", "transactions.html", "scores.html", "vectordb.html"):
        page_text = (static_dir / page_name).read_text(encoding="utf-8")
        assert 'href="vectordb.html"' in page_text

    # Verify app.js references the ChromaDB endpoints
    app_js = (static_dir / "app.js").read_text(encoding="utf-8")
    assert "/api/v1/vector/query" in app_js
    assert "/api/v1/vector/stats" in app_js
    assert "/api/v1/vector/documents" in app_js

