"""FastAPI application implementing the OpenAPI v3 Transaction Fraud Scorer Gateway."""

import logging
from datetime import UTC, datetime

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api_gateway.schemas import (
    ScoreDetails,
    TransactionDecisionRequest,
    TransactionDecisionResponse,
    TransactionIngestRequest,
    TransactionScoreResponse,
    WebSocketTransactionEvent,
    to_domain_transaction,
)
from api_gateway.store import TransactionStore
from api_gateway.websocket_manager import ConnectionManager
from fraud_scorer.agent.orchestrator import FraudScorerOrchestrator, is_ollama_available
from fraud_scorer.models.transaction import FraudAssessment

logger = logging.getLogger(__name__)


def create_app(
    orchestrator: FraudScorerOrchestrator | None = None,
    store: TransactionStore | None = None,
    ws_manager: ConnectionManager | None = None,
) -> FastAPI:
    """Create and configure the FastAPI Gateway application."""
    application = FastAPI(
        title="Transaction Fraud Scorer Agentic AI API",
        version="1.0.0",
        description=(
            "OpenAPI v3 gateway for the Transaction Fraud Scorer Agentic AI. "
            "Ingests user & ACH/Card transactions, streams real-time WebSocket score events, "
            "and records Accept/Reject analyst decisions."
        ),
    )

    # Enable CORS for external web consumption (e.g., local website calling Cloudflare tunnel)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    fraud_orchestrator = orchestrator or FraudScorerOrchestrator()
    tx_store = store or TransactionStore()
    connection_manager = ws_manager or ConnectionManager()

    # Attach state for programmatic access and testing
    application.state.orchestrator = fraud_orchestrator
    application.state.store = tx_store
    application.state.ws_manager = connection_manager

    @application.get("/health", tags=["Health"])
    async def health_check() -> dict[str, object]:
        """Return API Gateway and Ollama backend connectivity status."""
        return {
            "status": "ok",
            "ollama_connected": is_ollama_available(fraud_orchestrator.ollama_base_url),
            "model": fraud_orchestrator.model_name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    @application.post(
        "/api/v1/transactions/score",
        response_model=TransactionScoreResponse,
        tags=["Transactions"],
        summary="Ingest user & ACH/Card transaction data for fraud scoring",
        operation_id="ingestAndScoreTransaction",
    )
    async def ingest_and_score_transaction(
        payload: TransactionIngestRequest,
    ) -> TransactionScoreResponse:
        """Ingest user context and ACH/Card transaction details, return score=100 & APPROVE, and push WS event."""
        domain_tx = to_domain_transaction(payload)
        evaluated_at = datetime.now(UTC)

        # Per PRD-002: Return request in WebSocket response format with Score=100.0 and all transactions successful
        assessment = FraudAssessment(
            transaction_id=domain_tx.transaction_id,
            account_id=payload.username,
            overall_risk_score=100.0,
            decision="APPROVE",
            risk_factors=[],
            reasoning_summary=(
                f"Request received for user '{payload.username}' "
                f"({payload.transaction_details.transaction_type} ${domain_tx.amount:,.2f} {domain_tx.currency}). "
                "All transactions are successful (Score=100.0)."
            ),
            tools_invoked=[],
            evaluated_at=evaluated_at,
        )

        tx_store.save(domain_tx, assessment)

        ws_event = WebSocketTransactionEvent(
            event_type="TRANSACTION_SCORED",
            transaction_id=assessment.transaction_id,
            username=payload.username,
            amount=domain_tx.amount,
            currency=domain_tx.currency,
            score=assessment.overall_risk_score,
            score_details=ScoreDetails(
                assessment_id=assessment.assessment_id,
                status=assessment.decision,
                reasoning_summary=assessment.reasoning_summary,
                risk_factors=assessment.risk_factors,
                tools_invoked=assessment.tools_invoked,
                request_payload=payload.model_dump(mode="json"),
                evaluated_at=assessment.evaluated_at,
            ),
        )
        await connection_manager.broadcast_event(ws_event)

        return TransactionScoreResponse(
            transaction_id=assessment.transaction_id,
            score=assessment.overall_risk_score,
            status=assessment.decision,
            evaluated_at=assessment.evaluated_at,
        )

    @application.websocket("/ws/transactions/events")
    async def stream_transaction_score_events(
        websocket: WebSocket,
        username: str | None = Query(default=None),
    ) -> None:
        """WebSocket endpoint streaming real-time transaction score events to Web clients."""
        await connection_manager.connect(websocket, username=username)
        try:
            while True:
                # Keep connection open; ignore or handle client ping messages
                await websocket.receive_text()
        except WebSocketDisconnect:
            connection_manager.disconnect(websocket)
        except Exception:
            connection_manager.disconnect(websocket)

    @application.post(
        "/api/v1/transactions/decision",
        response_model=TransactionDecisionResponse,
        tags=["Transactions"],
        summary="Accept or Reject a transaction with a reason",
        operation_id="submitTransactionDecision",
    )
    async def submit_transaction_decision(
        payload: TransactionDecisionRequest,
    ) -> TransactionDecisionResponse | JSONResponse:
        """Accept or reject a previously scored transaction with an audit reason."""
        record, applied = tx_store.apply_decision(
            transaction_id=payload.transaction_id,
            accept=payload.accept,
            reason=payload.reason,
        )

        if record is None or applied is None:
            not_found_resp = TransactionDecisionResponse(
                status="FAILURE",
                success=False,
                transaction_id=payload.transaction_id,
                decision_applied=None,
                message=f"Transaction ID {payload.transaction_id} does not exist.",
                processed_at=datetime.now(UTC),
            )
            return JSONResponse(
                status_code=404,
                content=not_found_resp.model_dump(mode="json"),
            )

        return TransactionDecisionResponse(
            status="SUCCESS",
            success=True,
            transaction_id=payload.transaction_id,
            decision_applied=applied,
            message=f"Transaction {payload.transaction_id} marked as {applied}.",
            processed_at=record.updated_at or datetime.now(UTC),
        )

    return application


app = create_app()
