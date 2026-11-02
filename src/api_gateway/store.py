"""In-memory transaction and decision state store for the FastAPI Gateway."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from api_gateway.schemas import TransactionStatus
from fraud_scorer.models.transaction import FraudAssessment, Transaction


@dataclass
class StoredTransactionRecord:
    """Represents a scored transaction and its current disposition state."""

    transaction: Transaction
    assessment: FraudAssessment
    status: TransactionStatus
    decision_reason: str | None = None
    updated_at: datetime | None = None


class TransactionStore:
    """Thread-safe / async-compatible in-memory store of scored transactions."""

    def __init__(self) -> None:
        self._records: dict[str, StoredTransactionRecord] = {}

    def save(self, transaction: Transaction, assessment: FraudAssessment) -> StoredTransactionRecord:
        """Save a newly scored transaction and its assessment."""
        record = StoredTransactionRecord(
            transaction=transaction,
            assessment=assessment,
            status=assessment.decision,
            updated_at=assessment.evaluated_at,
        )
        self._records[transaction.transaction_id] = record
        return record

    def get(self, transaction_id: str) -> StoredTransactionRecord | None:
        """Retrieve a stored transaction record by ID."""
        return self._records.get(transaction_id)

    def apply_decision(
        self,
        transaction_id: str,
        accept: bool,
        reason: str,
    ) -> tuple[StoredTransactionRecord | None, Literal["ACCEPTED", "REJECTED"] | None]:
        """Apply an explicit Accept or Reject decision to an existing transaction."""
        record = self._records.get(transaction_id)
        if record is None:
            return None, None

        applied: Literal["ACCEPTED", "REJECTED"] = "ACCEPTED" if accept else "REJECTED"
        record.status = applied
        record.decision_reason = reason
        record.updated_at = datetime.now(UTC)
        return record, applied

    def clear(self) -> None:
        """Clear all stored records (useful for testing)."""
        self._records.clear()
