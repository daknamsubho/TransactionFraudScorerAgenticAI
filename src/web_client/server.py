"""Lightweight local HTTP server for serving the Transaction Fraud Scorer WebUI."""

import argparse
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

STATIC_DIR = Path(__file__).resolve().parent / "static"
console = Console()


def get_static_dir() -> Path:
    """Return the absolute path to the static WebUI assets directory."""
    return STATIC_DIR


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

    handler_cls = functools.partial(SimpleHTTPRequestHandler, directory=str(STATIC_DIR))
    server = ThreadingHTTPServer((args.host, args.port), handler_cls)

    url = f"http://{args.host}:{args.port}"
    console.print(
        Panel(
            f"[bold green]Transaction Fraud Scorer WebUI Running![/]\n"
            f"Open in Browser: [bold cyan]{url}[/]\n"
            f"Static Assets  : [dim]{STATIC_DIR}[/]\n\n"
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
