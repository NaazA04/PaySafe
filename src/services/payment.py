"""
Core Payment Service — Orchestrates the full payment lifecycle.

Flow:
  1. Validate request
  2. Check idempotency (is this a duplicate request?)
  3. Create transaction record (PENDING)
  4. Call External Payment Gateway
  5. If SUCCESS → write double-entry ledger entries
  6. Update transaction status (SUCCESS / FAILED)
  7. Mark idempotency key COMPLETED
  8. Return result
"""

import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from src.core.database import DatabaseManager
from src.core.models import TransactionStatus, PaymentRequest, RefundRequest
from src.services.idempotency import IdempotencyManager, IdempotencyStatus, IdempotencyError
from src.services.ledger import LedgerService
from src.services.gateway import ExternalPaymentGateway
from src.services.audit import AuditLogger


class PaymentService:
    def __init__(self, db: DatabaseManager):
        self.db = db
        self.idempotency = IdempotencyManager(db)
        self.ledger = LedgerService(db)
        self.gateway = ExternalPaymentGateway()
        self.audit = AuditLogger(db)

    # ------------------------------------------------------------------
    # PAYMENT INITIATION
    # ------------------------------------------------------------------
    def initiate_payment(
        self, request: PaymentRequest, idempotency_key: str
    ) -> Dict[str, Any]:
        """
        Initiates a payment with full idempotency and double-entry accounting.
        """
        # Build the canonical payload for hashing (exclude non-semantic fields)
        request_payload = {
            "user_id": request.user_id,
            "merchant_id": request.merchant_id,
            "amount": request.amount,
            "currency": request.currency,
            "payment_method": request.payment_method,
        }

        # ── Step 1: Idempotency Check ─────────────────────────────────
        idemp_status, cached_response = self.idempotency.acquire_or_get_lock(
            idempotency_key, request_payload
        )

        if idemp_status == IdempotencyStatus.COMPLETED and cached_response:
            self.audit.log("IDEMPOTENT_HIT", idempotency_key, {"status": "returned_cached"})
            return cached_response

        if idemp_status == IdempotencyStatus.PROCESSING:
            return {
                "transaction_id": None,
                "status": TransactionStatus.PENDING,
                "message": "Payment is currently being processed. Please retry in a moment.",
                "is_cached_response": True,
            }

        # ── Step 2: Create PENDING Transaction Record ─────────────────
        transaction_id = f"txn_{uuid.uuid4().hex[:16]}"
        now_iso = datetime.now(timezone.utc).isoformat()

        with self.db.transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO transactions
                  (transaction_id, idempotency_key, user_id, merchant_id, amount,
                   currency, payment_method, status, description, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    transaction_id, idempotency_key, request.user_id, request.merchant_id,
                    request.amount, request.currency, request.payment_method,
                    TransactionStatus.PROCESSING.value, request.description, now_iso, now_iso,
                ),
            )

        self.audit.log("PAYMENT_INITIATED", transaction_id, request_payload)

        # ── Step 3: Call External Gateway ────────────────────────────
        gateway_resp = self.gateway.process_payment(
            amount=request.amount,
            currency=request.currency,
            payment_method=request.payment_method,
            user_id=request.user_id,
        )

        # ── Step 4: Handle Gateway Response ───────────────────────────
        if gateway_resp.success:
            # Record double-entry ledger
            self.ledger.record_payment_entries(
                transaction_id=transaction_id,
                user_id=request.user_id,
                merchant_id=request.merchant_id,
                amount=request.amount,
                currency=request.currency,
            )
            final_status = TransactionStatus.SUCCESS
            failure_reason = None
            self.audit.log("PAYMENT_SUCCESS", transaction_id, {"gateway_txn": gateway_resp.gateway_txn_id})
        else:
            final_status = TransactionStatus.FAILED
            failure_reason = gateway_resp.message
            self.audit.log("PAYMENT_FAILED", transaction_id, {"reason": failure_reason})

        # ── Step 5: Update Transaction Status ─────────────────────────
        updated_at = datetime.now(timezone.utc).isoformat()
        with self.db.transaction() as cursor:
            cursor.execute(
                """
                UPDATE transactions
                SET status = ?, failure_reason = ?, updated_at = ?
                WHERE transaction_id = ?
                """,
                (final_status.value, failure_reason, updated_at, transaction_id),
            )

        # ── Step 6: Finalize Idempotency Record ───────────────────────
        response = self._build_response(
            transaction_id=transaction_id,
            idempotency_key=idempotency_key,
            request=request,
            status=final_status,
            failure_reason=failure_reason,
            created_at=now_iso,
            updated_at=updated_at,
        )

        if gateway_resp.success:
            self.idempotency.mark_completed(idempotency_key, transaction_id, response)
        else:
            self.idempotency.mark_failed(idempotency_key, failure_reason)

        return response

    # ------------------------------------------------------------------
    # GET PAYMENT STATUS
    # ------------------------------------------------------------------
    def get_payment(self, transaction_id: str) -> Optional[Dict[str, Any]]:
        with self.db.transaction() as cursor:
            cursor.execute(
                "SELECT * FROM transactions WHERE transaction_id = ?",
                (transaction_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            entries = self.ledger.get_transaction_entries(transaction_id)
            result = dict(row)
            result["ledger_entries"] = entries
            return result

    # ------------------------------------------------------------------
    # REFUND
    # ------------------------------------------------------------------
    def initiate_refund(self, request: RefundRequest, idempotency_key: str) -> Dict[str, Any]:
        # Fetch original transaction
        original = self.get_payment(request.transaction_id)
        if not original:
            return {"error": f"Transaction {request.transaction_id} not found."}

        if original["status"] != TransactionStatus.SUCCESS.value:
            return {"error": f"Cannot refund transaction in state: {original['status']}"}

        refund_amount = request.amount if request.amount else original["amount"]
        if refund_amount > original["amount"]:
            return {"error": "Refund amount exceeds original payment amount."}

        # Check idempotency for refund
        refund_payload = {"transaction_id": request.transaction_id, "refund_amount": refund_amount}
        idemp_status, cached = self.idempotency.acquire_or_get_lock(idempotency_key, refund_payload)
        if idemp_status == IdempotencyStatus.COMPLETED and cached:
            return cached

        # Create refund transaction record
        refund_txn_id = f"ref_{uuid.uuid4().hex[:14]}"
        now_iso = datetime.now(timezone.utc).isoformat()

        with self.db.transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO transactions
                  (transaction_id, idempotency_key, user_id, merchant_id, amount,
                   currency, payment_method, status, description, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    refund_txn_id, idempotency_key,
                    original["user_id"], original["merchant_id"],
                    refund_amount, original["currency"], original["payment_method"],
                    TransactionStatus.PROCESSING.value,
                    f"Refund for {request.transaction_id}: {request.reason}",
                    now_iso, now_iso,
                ),
            )

        # Call gateway refund
        gw_resp = self.gateway.process_refund("", refund_amount, original["currency"])
        updated_at = datetime.now(timezone.utc).isoformat()

        if gw_resp.success:
            self.ledger.record_refund_entries(
                transaction_id=refund_txn_id,
                user_id=original["user_id"],
                merchant_id=original["merchant_id"],
                amount=refund_amount,
                currency=original["currency"],
            )
            final_status = TransactionStatus.REFUNDED
            failure_reason = None
            # Mark original transaction as refunded
            with self.db.transaction() as cursor:
                cursor.execute(
                    "UPDATE transactions SET status = ?, updated_at = ? WHERE transaction_id = ?",
                    (TransactionStatus.REFUNDED.value, updated_at, request.transaction_id),
                )
        else:
            final_status = TransactionStatus.FAILED
            failure_reason = gw_resp.message

        with self.db.transaction() as cursor:
            cursor.execute(
                "UPDATE transactions SET status = ?, failure_reason = ?, updated_at = ? WHERE transaction_id = ?",
                (final_status.value, failure_reason, updated_at, refund_txn_id),
            )

        response = {
            "transaction_id": refund_txn_id,
            "original_transaction_id": request.transaction_id,
            "idempotency_key": idempotency_key,
            "refund_amount": refund_amount,
            "currency": original["currency"],
            "status": final_status.value,
            "failure_reason": failure_reason,
            "created_at": now_iso,
            "updated_at": updated_at,
            "message": "Refund processed successfully." if gw_resp.success else "Refund failed.",
            "is_cached_response": False,
        }

        if gw_resp.success:
            self.idempotency.mark_completed(idempotency_key, refund_txn_id, response)
        return response

    # ------------------------------------------------------------------
    # SYSTEM HEALTH & STATS
    # ------------------------------------------------------------------
    def get_system_stats(self) -> Dict[str, Any]:
        with self.db.transaction() as cursor:
            cursor.execute("SELECT COUNT(*) as total FROM transactions")
            total = cursor.fetchone()["total"]

            cursor.execute(
                "SELECT status, COUNT(*) as cnt FROM transactions GROUP BY status"
            )
            status_counts = {row["status"]: row["cnt"] for row in cursor.fetchall()}

        balance_check = self.ledger.get_system_balance_check()

        return {
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_transactions": total,
            "successful_transactions": status_counts.get("SUCCESS", 0),
            "failed_transactions": status_counts.get("FAILED", 0),
            "pending_transactions": status_counts.get("PENDING", 0) + status_counts.get("PROCESSING", 0),
            "refunded_transactions": status_counts.get("REFUNDED", 0),
            "ledger_balanced": balance_check["is_balanced"],
            "total_debit_volume": balance_check["total_debit_volume"],
            "total_credit_volume": balance_check["total_credit_volume"],
        }

    # ------------------------------------------------------------------
    # INTERNAL HELPER
    # ------------------------------------------------------------------
    def _build_response(
        self, transaction_id, idempotency_key, request,
        status, failure_reason, created_at, updated_at
    ) -> Dict[str, Any]:
        return {
            "transaction_id": transaction_id,
            "idempotency_key": idempotency_key,
            "user_id": request.user_id,
            "merchant_id": request.merchant_id,
            "amount": request.amount,
            "currency": request.currency,
            "status": status.value,
            "failure_reason": failure_reason,
            "created_at": created_at,
            "updated_at": updated_at,
            "is_cached_response": False,
            "message": "Payment processed successfully." if status == TransactionStatus.SUCCESS else f"Payment failed: {failure_reason}",
        }
