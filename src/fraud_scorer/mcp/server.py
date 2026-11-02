"""FastMCP server for Transaction Fraud Scoring."""

import argparse
import sys
from typing import Any

from mcp.server.mcpserver import MCPServer as FastMCP

from fraud_scorer.config import settings
from fraud_scorer.mcp.tools.check_geo_anomaly import (
    check_geo_anomaly as _check_geo_anomaly,
)
from fraud_scorer.mcp.tools.check_merchant_risk import (
    check_merchant_risk as _check_merchant_risk,
)
from fraud_scorer.mcp.tools.check_velocity import (
    check_velocity as _check_velocity,
)
from fraud_scorer.mcp.tools.lookup_account_history import (
    lookup_account_history as _lookup_account_history,
)

# Initialize FastMCP Server
mcp_server = FastMCP(
    name="TransactionFraudScorerMCP",
    instructions="FastMCP server providing financial transaction risk analysis and fraud detection tools.",
)


@mcp_server.tool()
def check_velocity(account_id: str, window_minutes: int = 60) -> dict[str, Any]:
    """Analyze transaction velocity, swipe frequency, and burst spend for an account.

    Args:
        account_id: Customer account identifier.
        window_minutes: Time window in minutes to evaluate (default 60).
    """
    return _check_velocity(account_id=account_id, window_minutes=window_minutes)


@mcp_server.tool()
def check_geo_anomaly(
    account_id: str,
    current_lat: float,
    current_lon: float,
    current_timestamp_iso: str | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Detect impossible travel, extreme distances, and rapid geographic hops between transactions.

    Args:
        account_id: Customer account identifier.
        current_lat: Current transaction latitude (-90.0 to 90.0).
        current_lon: Current transaction longitude (-180.0 to 180.0).
        current_timestamp_iso: ISO-8601 timestamp string of the current transaction.
        timestamp: Optional alias for current_timestamp_iso.
    """
    return _check_geo_anomaly(
        account_id=account_id,
        current_lat=current_lat,
        current_lon=current_lon,
        current_timestamp_iso=current_timestamp_iso,
        timestamp=timestamp,
    )


@mcp_server.tool()
def check_merchant_risk(merchant_id: str, mcc: str) -> dict[str, Any]:
    """Evaluate Merchant Category Code (MCC) risk and commercial reputation.

    Args:
        merchant_id: Merchant identifier.
        mcc: 4-digit Merchant Category Code (e.g. '7995', '6051', '5411').
    """
    return _check_merchant_risk(merchant_id=merchant_id, mcc=mcc)


@mcp_server.tool()
def lookup_account_history(account_id: str) -> dict[str, Any]:
    """Retrieve historical account age, chargeback history, and trust profile.

    Args:
        account_id: Customer account identifier.
    """
    return _lookup_account_history(account_id=account_id)


def create_server() -> FastMCP:
    """Return the configured FastMCP server instance."""
    return mcp_server


def main() -> None:
    """CLI entrypoint for running the FastMCP server."""
    parser = argparse.ArgumentParser(
        description="Transaction Fraud Scorer FastMCP Server",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default=settings.mcp_server_transport,
        help="Transport protocol (stdio or sse). Default: stdio",
    )
    parser.add_argument(
        "--host",
        default=settings.mcp_server_host,
        help="Host for SSE transport (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=settings.mcp_server_port,
        help="Port for SSE transport (default: 8000)",
    )

    args = parser.parse_args()

    if args.transport == "sse":
        print(f"Starting Fraud Scorer FastMCP Server over SSE at http://{args.host}:{args.port}...", file=sys.stderr)
        mcp_server.run(transport="sse", host=args.host, port=args.port)
    else:
        print("Starting Fraud Scorer FastMCP Server over stdio...", file=sys.stderr)
        mcp_server.run(transport="stdio")


if __name__ == "__main__":
    main()
