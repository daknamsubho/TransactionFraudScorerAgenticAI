"""CLI entrypoint for launching the FastAPI Gateway and optional Cloudflare Tunnel."""

import argparse
import logging

import uvicorn
from rich.console import Console
from rich.panel import Panel

from api_gateway.tunnel import start_cloudflare_tunnel
from fraud_scorer.config import settings

console = Console()


def main() -> None:
    """Start the FastAPI Gateway server and optional Cloudflare Quick Tunnel."""
    parser = argparse.ArgumentParser(
        description="Transaction Fraud Scorer FastAPI Gateway",
    )
    parser.add_argument(
        "--host",
        default=settings.api_gateway_host,
        help=f"Host interface to bind (default: {settings.api_gateway_host})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=settings.api_gateway_port,
        help=f"Port to listen on (default: {settings.api_gateway_port})",
    )
    parser.add_argument(
        "--tunnel",
        action="store_true",
        default=settings.enable_cloudflare_tunnel,
        help="Expose the FastAPI server externally via Cloudflare Quick Tunnel (cloudflared).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))

    tunnel_process = None
    if args.tunnel:
        tunnel_process, public_url = start_cloudflare_tunnel(port=args.port)
        ws_url = public_url.replace("https://", "wss://") + "/ws/transactions/events"
        console.print(
            Panel(
                f"[bold green]Cloudflare Tunnel Active![/]\n"
                f"Public Base URL: [bold cyan]{public_url}[/]\n"
                f"Swagger UI Docs: [bold cyan]{public_url}/docs[/]\n"
                f"Score Endpoint:  [bold]{public_url}/api/v1/transactions/score[/]\n"
                f"Decision API:    [bold]{public_url}/api/v1/transactions/decision[/]\n"
                f"WebSocket URL:   [bold magenta]{ws_url}[/]",
                title="Transaction Fraud Scorer API Gateway",
                expand=False,
            )
        )

    try:
        uvicorn.run("api_gateway.app:app", host=args.host, port=args.port, reload=False)
    finally:
        if tunnel_process is not None:
            tunnel_process.terminate()


if __name__ == "__main__":
    main()
