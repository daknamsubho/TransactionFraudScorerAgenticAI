"""WebUI client package for Transaction Fraud Scorer Agentic AI."""

from web_client.server import (
    DATASET_FILE,
    STATIC_DIR,
    WebClientRequestHandler,
    get_static_dir,
    get_test_dataset_path,
)

__all__ = [
    "DATASET_FILE",
    "STATIC_DIR",
    "WebClientRequestHandler",
    "get_static_dir",
    "get_test_dataset_path",
]
