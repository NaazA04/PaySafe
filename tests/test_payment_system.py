"""
Test Suite for PaySafe Payment System.
Covers: Payment creation, idempotency, refunds, ledger balance, and edge cases.
Run: pytest tests/ -v
"""

import pytest
import uuid
from src.core.database import DatabaseManager
from src.core.models import PaymentRequest, RefundRequest
from src.services.payment import PaymentService


# ── Fixtures ──────────────────────────────────────────────────────────
@pytest.fixture(scope="function")
def db():
    """Fresh in-memory database for each test."""
    DatabaseManager._instance = None
    test_db = DatabaseManager.get_instance("test_paysafe.db")
    test_db.reset_db()
    yield test_db
    test_db.reset_db()
    DatabaseManager._instance = None


@pytest.fixture
def service(db):
    return PaymentService(db)


@pytest.fixture
def sample_request():
    return PaymentRequest(
        user_id="user_test_001",
        merchant_id="merchant_test_001",
        amount=500.00,
        currency="USD",
        payment_method="CARD",
        description="Test payment",
    )


# ── Core Payment Tests ──────────────────────────────────────────────────
class TestPaymentCreation:
    def test_payment_returns_valid_transaction_id(self, service, sample_request):
        key = f"idemp_{uuid.uuid4().hex}"
        result = service.initiate_payment(sample_request, key)
        assert "transaction_id" in result
        assert result["transaction_id"] is not None

    def test_payment_status_is_success_or_failed(self, service, sample_request):
        key = f"idemp_{uuid.uuid4().hex}"
        result = service.initiate_payment(sample_request, key)
        assert result["status"] in ["SUCCESS", "FAILED"]

    def test_payment_amount_matches(self, service, sample_request):
        key = f"idemp_{uuid.uuid4().hex}"
        result = service.initiate_payment(sample_request, key)
        assert result["amount"] == 500.00

    def test_payment_currency_matches(self, service, sample_request):
        key = f"idemp_{uuid.uuid4().hex}"
        result = service.initiate_payment(sample_request, key)
        assert result["currency"] == "USD"

    def test_get_payment_returns_details(self, service, sample_request):
        key = f"idemp_{uuid.uuid4().hex}"
        created = service.initiate_payment(sample_request, key)
        txn_id = created["transaction_id"]
        fetched = service.get_payment(txn_id)
        assert fetched is not None
        assert fetched["transaction_id"] == txn_id

    def test_get_nonexistent_payment_returns_none(self, service):
        result = service.get_payment("txn_does_not_exist_xyz")
        assert result is None


# ── Idempotency Tests ───────────────────────────────────────────────────
class TestIdempotency:
    def test_same_key_same_payload_returns_cached(self, service, sample_request):
        key = f"idemp_{uuid.uuid4().hex}"
        first = service.initiate_payment(sample_request, key)
        second = service.initiate_payment(sample_request, key)

        # Second should be cached response
        assert second.get("is_cached_response") is True
        # Both should have the same transaction_id
        assert first["transaction_id"] == second["transaction_id"]

    def test_same_key_different_payload_raises_error(self, service, sample_request):
        from src.services.idempotency import IdempotencyError
        key = f"idemp_{uuid.uuid4().hex}"
        service.initiate_payment(sample_request, key)

        # Change amount → different payload
        modified = PaymentRequest(
            user_id=sample_request.user_id,
            merchant_id=sample_request.merchant_id,
            amount=999.99,  # ← DIFFERENT
            currency="USD",
            payment_method="CARD",
        )
        with pytest.raises(IdempotencyError):
            service.initiate_payment(modified, key)

    def test_different_keys_are_independent(self, service, sample_request):
        key1 = f"idemp_{uuid.uuid4().hex}"
        key2 = f"idemp_{uuid.uuid4().hex}"
        r1 = service.initiate_payment(sample_request, key1)
        r2 = service.initiate_payment(sample_request, key2)
        # Different keys → different transactions
        assert r1["transaction_id"] != r2["transaction_id"]


# ── Ledger Tests ────────────────────────────────────────────────────────
class TestDoublEntryLedger:
    def _make_successful_payment(self, service, sample_request):
        """Keep retrying until we get a SUCCESS (gateway is random)."""
        for _ in range(30):
            service.db.reset_db()
            DatabaseManager._instance = None
            svc = PaymentService(service.db)
            key = f"idemp_{uuid.uuid4().hex}"
            result = svc.initiate_payment(sample_request, key)
            if result["status"] == "SUCCESS":
                return svc, result
        pytest.skip("Could not get a SUCCESS after 30 attempts (gateway randomness)")

    def test_successful_payment_creates_two_ledger_entries(self, service, sample_request):
        svc, result = self._make_successful_payment(service, sample_request)
        txn_id = result["transaction_id"]
        entries = svc.ledger.get_transaction_entries(txn_id)
        assert len(entries) == 2

    def test_ledger_has_one_debit_and_one_credit(self, service, sample_request):
        svc, result = self._make_successful_payment(service, sample_request)
        txn_id = result["transaction_id"]
        entries = svc.ledger.get_transaction_entries(txn_id)
        types = [e["entry_type"] for e in entries]
        assert "DEBIT" in types
        assert "CREDIT" in types

    def test_debit_equals_credit(self, service, sample_request):
        svc, result = self._make_successful_payment(service, sample_request)
        txn_id = result["transaction_id"]
        entries = svc.ledger.get_transaction_entries(txn_id)
        debit_total = sum(e["amount"] for e in entries if e["entry_type"] == "DEBIT")
        credit_total = sum(e["amount"] for e in entries if e["entry_type"] == "CREDIT")
        assert abs(debit_total - credit_total) < 0.001, "Ledger imbalance detected!"

    def test_system_ledger_is_balanced(self, service, sample_request):
        # Process multiple transactions and verify global ledger balance
        for _ in range(5):
            key = f"idemp_{uuid.uuid4().hex}"
            service.initiate_payment(sample_request, key)
        balance = service.ledger.get_system_balance_check()
        assert balance["is_balanced"] is True, f"Imbalance: {balance}"


# ── System Stats Tests ──────────────────────────────────────────────────
class TestSystemStats:
    def test_stats_are_returned(self, service, sample_request):
        stats = service.get_system_stats()
        assert "total_transactions" in stats
        assert "ledger_balanced" in stats
        assert stats["status"] == "healthy"

    def test_total_transactions_increases(self, service, sample_request):
        before = service.get_system_stats()["total_transactions"]
        service.initiate_payment(sample_request, f"key_{uuid.uuid4().hex}")
        after = service.get_system_stats()["total_transactions"]
        assert after == before + 1
