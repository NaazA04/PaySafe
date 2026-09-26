"""
Idempotency Management Service.
Prevents duplicate financial operations caused by network retries or client double-clicks.
Follows industry standards (Stripe/PayPal style idempotency guarantees).
"""

import hashlib
import json
import sqlite3
from typing import Dict, Any, Optional, Tuple
from enum import Enum
from src.core.database import DatabaseManager


class IdempotencyStatus(str, Enum):
    NEW = "NEW"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    MISMATCH = "MISMATCH"


class IdempotencyError(Exception):
    """Raised when an idempotency violation or payload mismatch occurs."""
    pass


class IdempotencyManager:
    def __init__(self, db: DatabaseManager):
        self.db = db

    @staticmethod
    def generate_request_hash(payload: Dict[str, Any]) -> str:
        """
        Create a deterministic SHA-256 hash from request payload.
        Ensures keys are sorted to avoid dictionary ordering differences.
        """
        normalized = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def acquire_or_get_lock(
        self, idempotency_key: str, request_payload: Dict[str, Any]
    ) -> Tuple[IdempotencyStatus, Optional[Dict[str, Any]]]:
        """
        Atomically inspect or acquire an idempotency lock for a key.

        Returns:
            (IdempotencyStatus, cached_response_or_None)
        """
        request_hash = self.generate_request_hash(request_payload)

        with self.db.transaction() as cursor:
            cursor.execute(
                "SELECT idempotency_key, request_hash, status, response_body, transaction_id "
                "FROM idempotency_records WHERE idempotency_key = ?",
                (idempotency_key,),
            )
            row = cursor.fetchone()

            if row is None:
                # First time seeing this key -> Register as PROCESSING
                cursor.execute(
                    """
                    INSERT INTO idempotency_records (idempotency_key, request_hash, status)
                    VALUES (?, ?, ?)
                    """,
                    (idempotency_key, request_hash, "PROCESSING"),
                )
                return IdempotencyStatus.NEW, None

            # Key already exists! Check for payload consistency
            stored_hash = row["request_hash"]
            stored_status = row["status"]
            response_body = row["response_body"]

            if stored_hash != request_hash:
                # Security/Integrity violation: Reusing key for different payload!
                raise IdempotencyError(
                    f"Idempotency key '{idempotency_key}' was previously used with a different request payload."
                )

            if stored_status == "COMPLETED" and response_body:
                cached_data = json.loads(response_body)
                cached_data["is_cached_response"] = True
                cached_data["message"] = "Idempotent response: Returning previously processed transaction result."
                return IdempotencyStatus.COMPLETED, cached_data

            if stored_status == "PROCESSING":
                return IdempotencyStatus.PROCESSING, None

            return IdempotencyStatus.NEW, None

    def mark_completed(
        self, idempotency_key: str, transaction_id: str, response_payload: Dict[str, Any]
    ):
        """Record the successful completion and store the final response."""
        with self.db.transaction() as cursor:
            cursor.execute(
                """
                UPDATE idempotency_records
                SET status = 'COMPLETED',
                    response_body = ?,
                    transaction_id = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE idempotency_key = ?
                """,
                (json.dumps(response_payload), transaction_id, idempotency_key),
            )

    def mark_failed(self, idempotency_key: str, error_message: str):
        """Mark record as failed so retry or inspection can be performed."""
        with self.db.transaction() as cursor:
            cursor.execute(
                """
                UPDATE idempotency_records
                SET status = 'FAILED',
                    response_body = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE idempotency_key = ?
                """,
                (json.dumps({"error": error_message}), idempotency_key),
            )
