"""
Core domain models and schema definitions for the Payment System.
Includes Enums, Pydantic Request/Response models, and Data Transfer Objects.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


class TransactionStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


class EntryType(str, Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class AccountType(str, Enum):
    CUSTOMER_WALLET = "CUSTOMER_WALLET"
    MERCHANT_ACCOUNT = "MERCHANT_ACCOUNT"
    GATEWAY_CLEARING = "GATEWAY_CLEARING"
    PLATFORM_FEE = "PLATFORM_FEE"


# ==========================================
# API Request & Response Schemas
# ==========================================

class PaymentRequest(BaseModel):
    user_id: str = Field(..., description="Unique customer identifier",
                         json_schema_extra={"example": "user_101"})
    merchant_id: str = Field(..., description="Unique merchant identifier",
                              json_schema_extra={"example": "merchant_909"})
    amount: float = Field(..., gt=0, description="Payment amount (must be positive)",
                          json_schema_extra={"example": 250.00})
    currency: str = Field(default="USD", description="ISO currency code",
                          json_schema_extra={"example": "USD"})
    payment_method: str = Field(default="CARD", description="Payment method: CARD, UPI, WALLET",
                                json_schema_extra={"example": "CARD"})
    description: Optional[str] = Field(default="Payment for Order #456", description="Optional note")


class RefundRequest(BaseModel):
    transaction_id: str = Field(..., description="Original transaction ID to refund",
                                json_schema_extra={"example": "txn_abc123"})
    amount: Optional[float] = Field(None, gt=0, description="Partial or full refund amount. If empty, full refund.")
    reason: Optional[str] = Field(default="Customer requested refund", description="Reason for refund")


class PaymentResponse(BaseModel):
    transaction_id: str
    idempotency_key: str
    user_id: str
    merchant_id: str
    amount: float
    currency: str
    status: TransactionStatus
    failure_reason: Optional[str] = None
    created_at: str
    updated_at: str
    is_cached_response: bool = False
    message: str


class LedgerEntryRecord(BaseModel):
    entry_id: str
    transaction_id: str
    account_id: str
    account_type: AccountType
    entry_type: EntryType
    amount: float
    currency: str
    created_at: str


class AccountBalanceResponse(BaseModel):
    account_id: str
    account_type: AccountType
    currency: str
    balance: float
    total_debits: float
    total_credits: float
    last_updated: str


class SystemHealthResponse(BaseModel):
    status: str
    timestamp: str
    total_transactions: int
    successful_transactions: int
    failed_transactions: int
    ledger_balanced: bool
    total_debit_volume: float
    total_credit_volume: float
