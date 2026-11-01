"""Lightweight local HTTP server for serving the Transaction Fraud Scorer WebUI."""

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from rich.console import Console
from rich.panel import Panel

STATIC_DIR = Path(__file__).resolve().parent / "static"
DATASET_FILE = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "dataset"
    / "test_transactions_dataset.json"
)
console = Console()


def get_static_dir() -> Path:
    """Return the absolute path to the static WebUI assets directory."""
    return STATIC_DIR


def get_test_dataset_path() -> Path:
    """Return the absolute path to the test_transactions_dataset.json file."""
    return DATASET_FILE


class WebClientRequestHandler(SimpleHTTPRequestHandler):
    """HTTP request handler serving static WebUI files and the local test dataset."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("directory", str(STATIC_DIR))
        super().__init__(*args, **kwargs)

    def translate_path(self, path: str) -> str:
        """Route /dataset/test_transactions_dataset.json directly to docs/dataset/test_transactions_dataset.json."""
        parsed_path = urlparse(path).path
        if parsed_path in (
            "/dataset/test_transactions_dataset.json",
            "/test_transactions_dataset.json",
        ):
            return str(DATASET_FILE)
        return super().translate_path(path)


def main() -> None:
    """CLI entrypoint (`fraud-web-client`) to serve the WebUI locally."""
    parser = argparse.ArgumentParser(
        description="Serve the Transaction Fraud Scorer WebUI locally.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host address to bind (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=3000,
        help="Port to serve the WebUI on (default: 3000)",
    )
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), WebClientRequestHandler)

    url = f"http://{args.host}:{args.port}"
    console.print(
        Panel(
            f"[bold green]Transaction Fraud Scorer WebUI Running![/]\n"
            f"Open in Browser: [bold cyan]{url}[/]\n"
            f"Static Assets  : [dim]{STATIC_DIR}[/]\n"
            f"Test Dataset   : [dim]{DATASET_FILE}[/]\n\n"
            f"[italic]Tip: Paste your Cloudflare Tunnel URL (or http://localhost:8000) "
            f"into the API Gateway URL box in the UI.[/]",
            title="Web Client Server",
            expand=False,
        )
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        console.print("\n[yellow]Shutting down WebUI server...[/]")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
