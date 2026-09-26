"""
PaySafe API — FastAPI Application Entry Point.
Exposes all Payment System REST endpoints.
"""

import uuid
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from src.core.database import DatabaseManager
from src.core.models import (
    PaymentRequest, RefundRequest, PaymentResponse,
    AccountBalanceResponse, SystemHealthResponse
)
from src.services.payment import PaymentService
from src.services.audit import AuditLogger
from src.services.idempotency import IdempotencyError

# ── Application Startup ────────────────────────────────────────────────
app = FastAPI(
    title="PaySafe — Payment System",
    description=(
        "A reliable FinTech payment system featuring:\n"
        "- **Double-Entry Ledger** (DEBIT = CREDIT, always)\n"
        "- **Idempotency** (safe retries, no duplicate charges)\n"
        "- **Transaction Lifecycle** (PENDING → SUCCESS/FAILED/REFUNDED)\n"
        "- **Audit Logs** for compliance\n\n"
        "Built for System Design Course — Student Project."
    ),
    version="1.0.0",
    contact={"name": "Naaz Fatema Ahmedi"},
)

# Singleton DB + Service layer
db = DatabaseManager.get_instance("paysafe.db")
payment_service = PaymentService(db)
audit_logger = AuditLogger(db)


# ── Global Exception Handler ───────────────────────────────────────────
@app.exception_handler(IdempotencyError)
async def idempotency_error_handler(request: Request, exc: IdempotencyError):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"detail": f"Internal server error: {str(exc)}"})


# ── Health & Root ──────────────────────────────────────────────────────
@app.get("/", tags=["System"])
def root():
    return {
        "service": "PaySafe Payment System",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health", tags=["System"])
def health_check():
    """Returns system-wide stats and ledger balance verification."""
    return payment_service.get_system_stats()


# ── Payment Endpoints ──────────────────────────────────────────────────
@app.post("/payments", tags=["Payments"], status_code=201)
def create_payment(
    request: PaymentRequest,
    idempotency_key: Optional[str] = Header(
        default=None,
        alias="Idempotency-Key",
        description="Unique key to prevent duplicate payments. Auto-generated if not provided.",
    ),
):
    """
    **Initiate a new payment.**

    - Provide an `Idempotency-Key` header to safely retry on network failures.
    - The same key + same payload always returns the same result.
    - The same key + **different** payload returns HTTP 409 (Conflict).
    """
    if not idempotency_key:
        idempotency_key = f"auto_{uuid.uuid4().hex}"

    result = payment_service.initiate_payment(request, idempotency_key)

    # Return 200 for cached idempotent responses, 201 for new transactions
    status_code = 200 if result.get("is_cached_response") else 201
    return JSONResponse(content=result, status_code=status_code)


@app.get("/payments/{transaction_id}", tags=["Payments"])
def get_payment(transaction_id: str):
    """
    **Get full payment details including ledger entries.**

    Shows the debit & credit entries proving money moved correctly.
    """
    result = payment_service.get_payment(transaction_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Transaction '{transaction_id}' not found.")
    return result


@app.post("/refunds", tags=["Payments"])
def create_refund(
    request: RefundRequest,
    idempotency_key: Optional[str] = Header(
        default=None,
        alias="Idempotency-Key",
    ),
):
    """
    **Initiate a refund for a completed payment.**

    - Supports full and partial refunds.
    - Generates reverse ledger entries (DEBIT merchant, CREDIT customer).
    - Idempotent: same refund key will not create a duplicate refund.
    """
    if not idempotency_key:
        idempotency_key = f"ref_auto_{uuid.uuid4().hex}"

    result = payment_service.initiate_refund(request, idempotency_key)

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


# ── Ledger & Account Endpoints ─────────────────────────────────────────
@app.get("/accounts/{account_id}/balance", tags=["Ledger"])
def get_account_balance(account_id: str):
    """
    **Get balance for an account.**

    Account IDs follow these conventions:
    - Customer wallet: `wallet_<user_id>`
    - Merchant account: `merchant_<merchant_id>`
    """
    result = payment_service.ledger.get_account_balance(account_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get("/ledger/{transaction_id}", tags=["Ledger"])
def get_ledger_entries(transaction_id: str):
    """
    **Get all double-entry ledger records for a transaction.**

    Demonstrates that DEBIT = CREDIT for every transaction.
    """
    entries = payment_service.ledger.get_transaction_entries(transaction_id)
    if not entries:
        raise HTTPException(status_code=404, detail="No ledger entries found for this transaction.")
    return {"transaction_id": transaction_id, "entries": entries, "count": len(entries)}


# ── Audit Log Endpoints ────────────────────────────────────────────────
@app.get("/audit-logs", tags=["Audit"])
def get_audit_logs(entity_id: Optional[str] = None, limit: int = 50):
    """
    **Retrieve audit logs for compliance & debugging.**

    Filter by entity_id (transaction ID or idempotency key).
    """
    logs = audit_logger.get_logs(entity_id=entity_id, limit=limit)
    return {"logs": logs, "count": len(logs)}
