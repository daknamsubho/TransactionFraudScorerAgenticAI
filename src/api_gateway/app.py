"""FastAPI application implementing the OpenAPI v3 Transaction Fraud Scorer Gateway."""

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api_gateway.schemas import (
    DeleteRecordResponse,
    PaginatedTransactionScoresResponse,
    PaginatedTransactionsResponse,
    PaginatedUserProfilesResponse,
    ScoreDetails,
    TransactionCreateRequest,
    TransactionDecisionRequest,
    TransactionDecisionResponse,
    TransactionIngestRequest,
    TransactionRecord,
    TransactionScoreCreateRequest,
    TransactionScoreRecord,
    TransactionScoreResponse,
    TransactionScoreUpdateRequest,
    TransactionUpdateRequest,
    UserProfileCreateRequest,
    UserProfileRecord,
    UserProfileUpdateRequest,
    WebSocketTransactionEvent,
    to_domain_transaction,
)
from api_gateway.store import TransactionStore
from api_gateway.websocket_manager import ConnectionManager
from fraud_scorer.agents.orchestrator_agent import FraudScorerOrchestrator, is_ollama_available
from fraud_scorer.models.transaction import FraudAssessment
from sqllite import (
    DEFAULT_DB_PATH,
    delete_transaction,
    delete_transaction_score,
    delete_user_profile,
    init_db,
    insert_transaction,
    insert_transaction_score,
    insert_user_profile,
    select_transaction,
    select_transaction_score,
    select_transaction_scores_paginated,
    select_transactions_paginated,
    select_user_profile,
    select_user_profiles_paginated,
    update_transaction_decision,
    update_transaction_record,
    update_transaction_score,
    update_user_profile,
)

logger = logging.getLogger(__name__)


def create_app(
    orchestrator: FraudScorerOrchestrator | None = None,
    store: TransactionStore | None = None,
    ws_manager: ConnectionManager | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> FastAPI:
    """Create and configure the FastAPI Gateway application."""
    application = FastAPI(
        title="Transaction Fraud Scorer Agentic AI API",
        version="1.0.0",
        description=(
            "OpenAPI v3 gateway for the Transaction Fraud Scorer Agentic AI. "
            "Ingests user & ACH/Card transactions, streams real-time WebSocket score events, "
            "records Accept/Reject analyst decisions, and exposes RDBMS CRUD endpoints."
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
    resolved_db_path = init_db(db_path)

    # Attach state for programmatic access and testing
    application.state.orchestrator = fraud_orchestrator
    application.state.store = tx_store
    application.state.ws_manager = connection_manager
    application.state.db_path = resolved_db_path

    @application.get("/health", tags=["Health"])
    async def health_check() -> dict[str, object]:
        """Return API Gateway, Ollama backend connectivity, and configured Agent flags."""
        return {
            "status": "ok",
            "ollama_connected": is_ollama_available(fraud_orchestrator.ollama_base_url),
            "model": fraud_orchestrator.model_name,
            "agent_flags": fraud_orchestrator.agent_flags.model_dump(),
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
        """Ingest transaction details, coordinate evaluation via Orchestrator -> Decision Agent, and push WS event."""
        domain_tx = to_domain_transaction(payload)
        assessment: FraudAssessment = await fraud_orchestrator.evaluate_transaction(domain_tx)
        evaluated_at = assessment.evaluated_at

        tx_store.save(domain_tx, assessment)

        # Also persist to SQLite RDBMS (PRD-005 & PRD-006)
        details = payload.transaction_details
        rail_details = (
            details.card_details.model_dump(mode="json")
            if details.transaction_type == "CARD" and details.card_details
            else (details.ach_details.model_dump(mode="json") if details.ach_details else {})
        )
        insert_transaction(
            transaction_id=domain_tx.transaction_id,
            username=payload.username,
            transaction_type=details.transaction_type,
            amount=domain_tx.amount,
            currency=domain_tx.currency,
            timestamp=payload.datetime.isoformat(),
            ip_address=payload.ip,
            device_id=payload.device_id,
            latitude=payload.location.latitude,
            longitude=payload.location.longitude,
            city=payload.location.city,
            state=payload.location.state,
            country=payload.location.country,
            postal_code=payload.location.postal_code,
            merchant_id=domain_tx.merchant.merchant_id,
            merchant_name=domain_tx.merchant.name,
            mcc=domain_tx.merchant.mcc,
            merchant_country=domain_tx.merchant.country,
            payment_method_type=domain_tx.payment_method.payment_type,
            card_or_account_last_four=domain_tx.payment_method.card_last_four,
            is_card_present=domain_tx.payment_method.is_card_present,
            payment_details=rail_details,
            status=assessment.decision,
            db_path=resolved_db_path,
        )
        insert_transaction_score(
            transaction_id=domain_tx.transaction_id,
            assessment_id=assessment.assessment_id,
            score=assessment.overall_risk_score,
            approval_status=assessment.decision,
            reasoning_summary=assessment.reasoning_summary,
            risk_factors=[rf.model_dump(mode="json") for rf in assessment.risk_factors],
            tools_invoked=assessment.tools_invoked,
            evaluated_at=evaluated_at.isoformat(),
            db_path=resolved_db_path,
        )

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

        db_tx = select_transaction(payload.transaction_id, db_path=resolved_db_path)
        if db_tx is not None:
            update_transaction_decision(
                transaction_id=payload.transaction_id,
                accepted=payload.accept,
                reason=payload.reason,
                db_path=resolved_db_path,
            )

        if (record is None or applied is None) and db_tx is None:
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

        final_applied: Literal["ACCEPTED", "REJECTED"] = (
            applied if applied is not None else ("ACCEPTED" if payload.accept else "REJECTED")
        )
        return TransactionDecisionResponse(
            status="SUCCESS",
            success=True,
            transaction_id=payload.transaction_id,
            decision_applied=final_applied,
            message=f"Transaction {payload.transaction_id} marked as {final_applied}.",
            processed_at=(record.updated_at if record and record.updated_at else datetime.now(UTC)),
        )

    # =========================================================================
    # RDBMS Database CRUD & Paginated Endpoints (PRD-006)
    # 1. User Profiles (user_profiles)
    # =========================================================================

    @application.get(
        "/api/v1/db/user-profiles",
        response_model=PaginatedUserProfilesResponse,
        tags=["Database"],
        summary="List user profiles (paginated)",
        operation_id="listUserProfiles",
    )
    async def list_user_profiles(
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=10, ge=1, le=100),
    ) -> PaginatedUserProfilesResponse:
        """Return paginated records from the user_profiles RDBMS table."""
        data = select_user_profiles_paginated(page=page, page_size=page_size, db_path=resolved_db_path)
        return PaginatedUserProfilesResponse.model_validate(data)

    @application.post(
        "/api/v1/db/user-profiles",
        response_model=UserProfileRecord,
        tags=["Database"],
        summary="Create or upsert a user profile",
        operation_id="createUserProfile",
    )
    async def create_user_profile_endpoint(
        payload: UserProfileCreateRequest,
    ) -> UserProfileRecord:
        """Insert or upsert a UserProfile record in user_profiles."""
        row = insert_user_profile(
            username=payload.username,
            created_date=payload.created_date,
            address=payload.address,
            city=payload.city,
            state=payload.state,
            country=payload.country,
            postal_code=payload.postal_code,
            db_path=resolved_db_path,
        )
        return UserProfileRecord.model_validate(row)

    @application.get(
        "/api/v1/db/user-profiles/{username}",
        response_model=UserProfileRecord,
        tags=["Database"],
        summary="Get a user profile by username",
        operation_id="getUserProfile",
    )
    async def get_user_profile_endpoint(username: str) -> UserProfileRecord:
        """Fetch a single UserProfile record by username."""
        row = select_user_profile(username, db_path=resolved_db_path)
        if row is None:
            raise HTTPException(status_code=404, detail=f"UserProfile '{username}' not found.")
        return UserProfileRecord.model_validate(row)

    @application.put(
        "/api/v1/db/user-profiles/{username}",
        response_model=UserProfileRecord,
        tags=["Database"],
        summary="Update a user profile by username",
        operation_id="updateUserProfile",
    )
    async def update_user_profile_endpoint(
        username: str,
        payload: UserProfileUpdateRequest,
    ) -> UserProfileRecord:
        """Update address fields on an existing UserProfile record."""
        existing = select_user_profile(username, db_path=resolved_db_path)
        if existing is None:
            raise HTTPException(status_code=404, detail=f"UserProfile '{username}' not found.")
        row = update_user_profile(
            username=username,
            address=payload.address,
            city=payload.city,
            state=payload.state,
            country=payload.country,
            postal_code=payload.postal_code,
            db_path=resolved_db_path,
        )
        if row is None:
            raise HTTPException(status_code=404, detail=f"UserProfile '{username}' not found.")
        return UserProfileRecord.model_validate(row)

    @application.delete(
        "/api/v1/db/user-profiles/{username}",
        response_model=DeleteRecordResponse,
        tags=["Database"],
        summary="Delete a user profile by username",
        operation_id="deleteUserProfile",
    )
    async def delete_user_profile_endpoint(username: str) -> DeleteRecordResponse:
        """Delete a UserProfile record by username."""
        deleted = delete_user_profile(username, db_path=resolved_db_path)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"UserProfile '{username}' not found.")
        return DeleteRecordResponse(
            deleted=True,
            id=username,
            message=f"UserProfile '{username}' deleted.",
        )

    # =========================================================================
    # 2. Transactions (transactions)
    # =========================================================================

    @application.get(
        "/api/v1/db/transactions",
        response_model=PaginatedTransactionsResponse,
        tags=["Database"],
        summary="List transactions (paginated)",
        operation_id="listTransactions",
    )
    async def list_transactions_endpoint(
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=10, ge=1, le=100),
        username: str | None = Query(default=None),
        status: str | None = Query(default=None),
    ) -> PaginatedTransactionsResponse:
        """Return paginated records from the transactions RDBMS table."""
        data = select_transactions_paginated(
            page=page,
            page_size=page_size,
            username=username,
            status=status,
            db_path=resolved_db_path,
        )
        return PaginatedTransactionsResponse.model_validate(data)

    @application.post(
        "/api/v1/db/transactions",
        response_model=TransactionRecord,
        tags=["Database"],
        summary="Create a transaction record in RDBMS",
        operation_id="createTransactionRecord",
    )
    async def create_transaction_endpoint(
        payload: TransactionCreateRequest,
    ) -> TransactionRecord:
        """Insert a new Transaction record into transactions."""
        tx_id = payload.transaction_id or f"tx_{uuid4().hex[:12]}"
        row = insert_transaction(
            transaction_id=tx_id,
            username=payload.username,
            transaction_type=payload.transaction_type,
            amount=payload.amount,
            currency=payload.currency,
            timestamp=payload.timestamp,
            ip_address=payload.ip_address,
            device_id=payload.device_id,
            latitude=payload.latitude,
            longitude=payload.longitude,
            city=payload.city,
            state=payload.state,
            country=payload.country,
            postal_code=payload.postal_code,
            merchant_id=payload.merchant_id,
            merchant_name=payload.merchant_name,
            mcc=payload.mcc,
            merchant_country=payload.merchant_country,
            payment_method_type=payload.payment_method_type,
            card_or_account_last_four=payload.card_or_account_last_four,
            is_card_present=payload.is_card_present,
            payment_details=payload.payment_details,
            status=payload.status,
            db_path=resolved_db_path,
        )
        return TransactionRecord.model_validate(row)

    @application.get(
        "/api/v1/db/transactions/{transaction_id}",
        response_model=TransactionRecord,
        tags=["Database"],
        summary="Get a transaction record by transaction_id",
        operation_id="getTransactionRecord",
    )
    async def get_transaction_endpoint(transaction_id: str) -> TransactionRecord:
        """Fetch a single Transaction record by transaction_id."""
        row = select_transaction(transaction_id, db_path=resolved_db_path)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Transaction '{transaction_id}' not found.")
        return TransactionRecord.model_validate(row)

    @application.put(
        "/api/v1/db/transactions/{transaction_id}",
        response_model=TransactionRecord,
        tags=["Database"],
        summary="Update a transaction record by transaction_id",
        operation_id="updateTransactionRecord",
    )
    async def update_transaction_endpoint(
        transaction_id: str,
        payload: TransactionUpdateRequest,
    ) -> TransactionRecord:
        """Update mutable fields on an existing Transaction record."""
        row = update_transaction_record(
            transaction_id=transaction_id,
            amount=payload.amount,
            city=payload.city,
            state=payload.state,
            country=payload.country,
            merchant_name=payload.merchant_name,
            mcc=payload.mcc,
            status=payload.status,
            db_path=resolved_db_path,
        )
        if row is None:
            raise HTTPException(status_code=404, detail=f"Transaction '{transaction_id}' not found.")
        return TransactionRecord.model_validate(row)

    @application.delete(
        "/api/v1/db/transactions/{transaction_id}",
        response_model=DeleteRecordResponse,
        tags=["Database"],
        summary="Delete a transaction record by transaction_id",
        operation_id="deleteTransactionRecord",
    )
    async def delete_transaction_endpoint(transaction_id: str) -> DeleteRecordResponse:
        """Delete a Transaction record by transaction_id."""
        deleted = delete_transaction(transaction_id, db_path=resolved_db_path)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Transaction '{transaction_id}' not found.")
        return DeleteRecordResponse(
            deleted=True,
            id=transaction_id,
            message=f"Transaction '{transaction_id}' deleted.",
        )

    # =========================================================================
    # 3. Transaction Scores (transaction_scores)
    # =========================================================================

    @application.get(
        "/api/v1/db/transaction-scores",
        response_model=PaginatedTransactionScoresResponse,
        tags=["Database"],
        summary="List transaction scores (paginated)",
        operation_id="listTransactionScores",
    )
    async def list_transaction_scores_endpoint(
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=10, ge=1, le=100),
    ) -> PaginatedTransactionScoresResponse:
        """Return paginated records from the transaction_scores RDBMS table."""
        data = select_transaction_scores_paginated(page=page, page_size=page_size, db_path=resolved_db_path)
        return PaginatedTransactionScoresResponse.model_validate(data)

    @application.post(
        "/api/v1/db/transaction-scores",
        response_model=TransactionScoreRecord,
        tags=["Database"],
        summary="Create a transaction score record in RDBMS",
        operation_id="createTransactionScoreRecord",
    )
    async def create_transaction_score_endpoint(
        payload: TransactionScoreCreateRequest,
    ) -> TransactionScoreRecord:
        """Insert a new TransactionScore record into transaction_scores."""
        if select_transaction(payload.transaction_id, db_path=resolved_db_path) is None:
            raise HTTPException(
                status_code=404,
                detail=f"Parent transaction '{payload.transaction_id}' not found in transactions table.",
            )
        row = insert_transaction_score(
            transaction_id=payload.transaction_id,
            assessment_id=payload.assessment_id,
            score=payload.score,
            approval_status=payload.approval_status,
            decision_accepted=payload.decision_accepted,
            decision_reason=payload.decision_reason,
            reasoning_summary=payload.reasoning_summary,
            risk_factors=payload.risk_factors,
            tools_invoked=payload.tools_invoked,
            db_path=resolved_db_path,
        )
        return TransactionScoreRecord.model_validate(row)

    @application.get(
        "/api/v1/db/transaction-scores/{transaction_id}",
        response_model=TransactionScoreRecord,
        tags=["Database"],
        summary="Get a transaction score record by transaction_id",
        operation_id="getTransactionScoreRecord",
    )
    async def get_transaction_score_endpoint(transaction_id: str) -> TransactionScoreRecord:
        """Fetch a single TransactionScore record by transaction_id."""
        row = select_transaction_score(transaction_id, db_path=resolved_db_path)
        if row is None:
            raise HTTPException(status_code=404, detail=f"TransactionScore for '{transaction_id}' not found.")
        return TransactionScoreRecord.model_validate(row)

    @application.put(
        "/api/v1/db/transaction-scores/{transaction_id}",
        response_model=TransactionScoreRecord,
        tags=["Database"],
        summary="Update a transaction score record by transaction_id",
        operation_id="updateTransactionScoreRecord",
    )
    async def update_transaction_score_endpoint(
        transaction_id: str,
        payload: TransactionScoreUpdateRequest,
    ) -> TransactionScoreRecord:
        """Update an existing TransactionScore record by transaction_id."""
        existing = select_transaction_score(transaction_id, db_path=resolved_db_path)
        if existing is None:
            raise HTTPException(status_code=404, detail=f"TransactionScore for '{transaction_id}' not found.")
        decided_at = (
            datetime.now(UTC).isoformat()
            if payload.decision_accepted is not None
            else existing.get("decided_at")
        )
        row = update_transaction_score(
            transaction_id=transaction_id,
            score=payload.score,
            approval_status=payload.approval_status,
            decision_accepted=payload.decision_accepted,
            decision_reason=payload.decision_reason,
            reasoning_summary=payload.reasoning_summary,
            risk_factors=payload.risk_factors,
            tools_invoked=payload.tools_invoked,
            decided_at=decided_at,
            db_path=resolved_db_path,
        )
        if row is None:
            raise HTTPException(status_code=404, detail=f"TransactionScore for '{transaction_id}' not found.")
        return TransactionScoreRecord.model_validate(row)

    @application.delete(
        "/api/v1/db/transaction-scores/{transaction_id}",
        response_model=DeleteRecordResponse,
        tags=["Database"],
        summary="Delete a transaction score record by transaction_id",
        operation_id="deleteTransactionScoreRecord",
    )
    async def delete_transaction_score_endpoint(transaction_id: str) -> DeleteRecordResponse:
        """Delete a TransactionScore record by transaction_id."""
        deleted = delete_transaction_score(transaction_id, db_path=resolved_db_path)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"TransactionScore for '{transaction_id}' not found.")
        return DeleteRecordResponse(
            deleted=True,
            id=transaction_id,
            message=f"TransactionScore for '{transaction_id}' deleted.",
        )

    return application


app = create_app()
