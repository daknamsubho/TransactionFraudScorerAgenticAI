"""FastAPI application implementing the OpenAPI v3 Transaction Fraud Scorer Gateway."""

import importlib.util
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
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
    VectorDocumentsListResponse,
    VectorDocumentUploadRequest,
    VectorDocumentUploadResponse,
    VectorQueryRequest,
    VectorQueryResponse,
    VectorQueryResultItem,
    VectorStatsResponse,
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

_CHROMADB_MODULE_DIR = Path(__file__).resolve().parents[1] / "chromadb"


def _load_chroma_submodule(module_name: str, filename: str) -> Any:
    """Load a module from src/chromadb/ without colliding with the PyPI chromadb package."""
    if str(_CHROMADB_MODULE_DIR) not in sys.path:
        sys.path.insert(0, str(_CHROMADB_MODULE_DIR))
    spec = importlib.util.spec_from_file_location(module_name, str(_CHROMADB_MODULE_DIR / filename))
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load {filename} from {_CHROMADB_MODULE_DIR}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_chroma_client_mod = _load_chroma_submodule("_fraud_chroma_client", "client.py")
_chroma_ingest_mod = _load_chroma_submodule("_fraud_chroma_ingest", "ingest_policies.py")
_chroma_query_mod = _load_chroma_submodule("_fraud_chroma_query", "query_policies.py")


def create_app(
    orchestrator: FraudScorerOrchestrator | None = None,
    store: TransactionStore | None = None,
    ws_manager: ConnectionManager | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
    chroma_dir: str | Path | None = None,
) -> FastAPI:
    """Create and configure the FastAPI Gateway application."""
    application = FastAPI(
        title="Transaction Fraud Scorer Agentic AI API",
        version="1.0.0",
        description=(
            "OpenAPI v3 gateway for the Transaction Fraud Scorer Agentic AI. "
            "Ingests user & ACH/Card transactions, streams real-time WebSocket score events, "
            "records Accept/Reject analyst decisions, and exposes RDBMS CRUD and ChromaDB Vector endpoints."
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

    resolved_db_path = init_db(db_path)
    fraud_orchestrator = orchestrator or FraudScorerOrchestrator(db_path=resolved_db_path)
    tx_store = store or TransactionStore()
    connection_manager = ws_manager or ConnectionManager()
    resolved_chroma_dir = Path(chroma_dir) if chroma_dir else _chroma_client_mod.DEFAULT_CHROMA_DIR

    # Attach state for programmatic access and testing
    application.state.orchestrator = fraud_orchestrator
    application.state.store = tx_store
    application.state.ws_manager = connection_manager
    application.state.db_path = resolved_db_path
    application.state.chroma_dir = resolved_chroma_dir

    def _get_vector_collection() -> Any:
        """Return the ChromaDB fraud_policies collection, auto-seeding if empty."""
        c_client = _chroma_client_mod.get_chroma_client(resolved_chroma_dir)
        collection = _chroma_client_mod.get_or_create_policy_collection(c_client)
        if collection.count() == 0 and _chroma_ingest_mod.DEFAULT_POLICY_DIR.exists():
            _chroma_ingest_mod.ingest_policy_documents(
                policy_dir=_chroma_ingest_mod.DEFAULT_POLICY_DIR,
                collection=collection,
            )
        return collection

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
        assessment: FraudAssessment = await fraud_orchestrator.evaluate_transaction(
            domain_tx,
            db_path=resolved_db_path,
        )
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
            assessment_id=assessment.assessment_id,
            score=assessment.overall_risk_score,
            status=assessment.decision,
            reasoning_summary=assessment.reasoning_summary,
            risk_factors=assessment.risk_factors,
            tools_invoked=assessment.tools_invoked,
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

    # =========================================================================
    # ChromaDB Vector Database Endpoints (PRD-016)
    # =========================================================================

    @application.post(
        "/api/v1/vector/query",
        response_model=VectorQueryResponse,
        tags=["VectorDB"],
        summary="Query ChromaDB vector database for relevant fraud policy clauses",
        operation_id="queryVectorDatabase",
    )
    async def query_vector_database_endpoint(
        payload: VectorQueryRequest,
    ) -> VectorQueryResponse:
        """Perform semantic similarity search against the ChromaDB fraud_policies collection."""
        collection = _get_vector_collection()
        clean_year = payload.policy_year.strip() if payload.policy_year and payload.policy_year.strip() else None
        clean_cat = payload.category.strip() if payload.category and payload.category.strip() else None

        raw_results = _chroma_query_mod.query_fraud_policies(
            query_text=payload.query,
            policy_year=clean_year,
            n_results=payload.top_k,
            category=clean_cat,
            collection=collection,
        )

        items = [VectorQueryResultItem.model_validate(r) for r in raw_results]
        return VectorQueryResponse(
            query=payload.query,
            top_k=payload.top_k,
            policy_year=clean_year,
            category=clean_cat,
            total_results=len(items),
            results=items,
        )

    @application.get(
        "/api/v1/vector/documents",
        response_model=VectorDocumentsListResponse,
        tags=["VectorDB"],
        summary="List ingested policy document chunks in ChromaDB",
        operation_id="listVectorDocuments",
    )
    async def list_vector_documents_endpoint(
        limit: int = Query(default=50, ge=1, le=200),
        policy_year: str | None = Query(default=None),
    ) -> VectorDocumentsListResponse:
        """List ingested policy document chunks in ChromaDB."""
        collection = _get_vector_collection()
        clean_year = policy_year.strip() if policy_year and policy_year.strip() else None

        get_kwargs: dict[str, Any] = {"limit": limit}
        if clean_year:
            get_kwargs["where"] = {"policy_year": clean_year}

        raw = collection.get(**get_kwargs)
        ids = raw.get("ids") or []
        docs = raw.get("documents") or []
        metas = raw.get("metadatas") or []

        items: list[VectorQueryResultItem] = []
        for doc_id, text, meta in zip(ids, docs, metas, strict=False):
            meta_dict = meta or {}
            items.append(
                VectorQueryResultItem(
                    id=str(doc_id),
                    clause_id=str(meta_dict.get("clause_id", "N/A")),
                    policy_year=str(meta_dict.get("policy_year", "N/A")),
                    category=str(meta_dict.get("category", "N/A")),
                    title=str(meta_dict.get("title", "N/A")),
                    text=str(text or ""),
                    distance=0.0,
                    similarity_score=1.0,
                    metadata=dict(meta_dict),
                )
            )

        return VectorDocumentsListResponse(
            collection_name=collection.name,
            total_returned=len(items),
            items=items,
        )

    @application.post(
        "/api/v1/vector/documents",
        response_model=VectorDocumentUploadResponse,
        status_code=201,
        tags=["VectorDB"],
        summary="Upload and ingest new policy document(s) into ChromaDB",
        operation_id="uploadVectorDocument",
    )
    async def upload_vector_document_endpoint(
        payload: VectorDocumentUploadRequest,
    ) -> VectorDocumentUploadResponse:
        """Chunk and ingest a new policy document or custom rule into ChromaDB."""
        collection = _get_vector_collection()
        res = _chroma_ingest_mod.ingest_custom_document(
            content=payload.content,
            filename=payload.filename or "uploaded-policy.md",
            policy_year=payload.policy_year or "2026",
            title=payload.title,
            clause_id=payload.clause_id,
            category=payload.category or "CUSTOM",
            collection=collection,
        )
        return VectorDocumentUploadResponse(
            status="SUCCESS",
            message=f"Successfully ingested {res['chunks_ingested']} policy chunk(s) into ChromaDB.",
            chunks_ingested=res["chunks_ingested"],
            collection_count=res["collection_count"],
            ingested_ids=res["ingested_ids"],
        )

    @application.get(
        "/api/v1/vector/stats",
        response_model=VectorStatsResponse,
        tags=["VectorDB"],
        summary="Get ChromaDB collection statistics and document counts",
        operation_id="getVectorStats",
    )
    async def get_vector_stats_endpoint() -> VectorStatsResponse:
        """Return ChromaDB collection statistics including counts per year and category."""
        collection = _get_vector_collection()
        all_items = collection.get()
        metas = all_items.get("metadatas") or []

        chunks_per_year: dict[str, int] = {}
        categories_set: set[str] = set()

        for m in metas:
            if not m:
                continue
            yr = str(m.get("policy_year", "unknown"))
            chunks_per_year[yr] = chunks_per_year.get(yr, 0) + 1
            cat = str(m.get("category", "")).strip()
            if cat:
                categories_set.add(cat)

        return VectorStatsResponse(
            collection_name=collection.name,
            total_documents=collection.count(),
            chunks_per_year=chunks_per_year,
            categories=sorted(categories_set),
        )

    return application


app = create_app()
