"""
Double-Entry Ledger Service.
Implements fundamental accounting principles:
  - Every transaction has EXACTLY one DEBIT and one CREDIT entry.
  - Total Debits must ALWAYS equal Total Credits (accounting equation).
  - Money is NEVER created or destroyed - only moved between accounts.
"""

import uuid
from datetime import datetime, timezone
from typing import List, Tuple

from src.core.database import DatabaseManager
from src.core.models import EntryType, AccountType, LedgerEntryRecord


class LedgerBalanceError(Exception):
    """Raised when debit != credit or ledger is unbalanced."""
    pass


class LedgerService:
    def __init__(self, db: DatabaseManager):
        self.db = db
        # Ensure standard system accounts exist
        self._bootstrap_accounts()

    def _bootstrap_accounts(self):
        """Create default chart-of-accounts if they don't exist."""
        accounts = [
            ("GATEWAY_CLEARING", AccountType.GATEWAY_CLEARING),
            ("PLATFORM_FEE_ACC", AccountType.PLATFORM_FEE),
        ]
        with self.db.transaction() as cursor:
            for acc_id, acc_type in accounts:
                cursor.execute(
                    "INSERT OR IGNORE INTO accounts (account_id, account_type) VALUES (?, ?)",
                    (acc_id, acc_type.value),
                )

    def _ensure_account(self, account_id: str, account_type: AccountType, cursor):
        """Create an account record if it doesn't exist yet."""
        cursor.execute(
            "INSERT OR IGNORE INTO accounts (account_id, account_type) VALUES (?, ?)",
            (account_id, account_type.value),
        )

    def record_payment_entries(
        self,
        transaction_id: str,
        user_id: str,
        merchant_id: str,
        amount: float,
        currency: str = "USD",
    ) -> Tuple[str, str]:
        """
        Record double-entry ledger entries for a successful payment.

        Accounting Logic (simplified):
          DEBIT  → Customer Wallet  (money leaves customer)
          CREDIT → Merchant Account (money arrives at merchant)

        This ensures: ΣDebits = ΣCredits always.

        Returns:
            (debit_entry_id, credit_entry_id)
        """
        debit_entry_id = f"entry_{uuid.uuid4().hex[:12]}"
        credit_entry_id = f"entry_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()

        customer_account_id = f"wallet_{user_id}"
        merchant_account_id = f"merchant_{merchant_id}"

        with self.db.transaction() as cursor:
            # Create accounts if new
            self._ensure_account(customer_account_id, AccountType.CUSTOMER_WALLET, cursor)
            self._ensure_account(merchant_account_id, AccountType.MERCHANT_ACCOUNT, cursor)

            # ---- DEBIT: Money leaves Customer Wallet ----
            cursor.execute(
                """
                INSERT INTO ledger_entries
                  (entry_id, transaction_id, account_id, account_type, entry_type, amount, currency, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    debit_entry_id, transaction_id,
                    customer_account_id, AccountType.CUSTOMER_WALLET.value,
                    EntryType.DEBIT.value, amount, currency, now,
                ),
            )

            # ---- CREDIT: Money arrives at Merchant Account ----
            cursor.execute(
                """
                INSERT INTO ledger_entries
                  (entry_id, transaction_id, account_id, account_type, entry_type, amount, currency, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    credit_entry_id, transaction_id,
                    merchant_account_id, AccountType.MERCHANT_ACCOUNT.value,
                    EntryType.CREDIT.value, amount, currency, now,
                ),
            )

            # Verify balance before committing (paranoid check)
            self._verify_transaction_balance(transaction_id, cursor)

        return debit_entry_id, credit_entry_id

    def record_refund_entries(
        self,
        transaction_id: str,
        user_id: str,
        merchant_id: str,
        amount: float,
        currency: str = "USD",
    ) -> Tuple[str, str]:
        """
        Record double-entry entries for a REFUND.
        Refund reverses the original entries:
          DEBIT  → Merchant Account (money leaves merchant)
          CREDIT → Customer Wallet  (money returns to customer)
        """
        debit_entry_id = f"entry_{uuid.uuid4().hex[:12]}"
        credit_entry_id = f"entry_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()

        customer_account_id = f"wallet_{user_id}"
        merchant_account_id = f"merchant_{merchant_id}"

        with self.db.transaction() as cursor:
            self._ensure_account(customer_account_id, AccountType.CUSTOMER_WALLET, cursor)
            self._ensure_account(merchant_account_id, AccountType.MERCHANT_ACCOUNT, cursor)

            # DEBIT: Merchant account is charged
            cursor.execute(
                """
                INSERT INTO ledger_entries
                  (entry_id, transaction_id, account_id, account_type, entry_type, amount, currency, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    debit_entry_id, transaction_id,
                    merchant_account_id, AccountType.MERCHANT_ACCOUNT.value,
                    EntryType.DEBIT.value, amount, currency, now,
                ),
            )

            # CREDIT: Customer wallet is restored
            cursor.execute(
                """
                INSERT INTO ledger_entries
                  (entry_id, transaction_id, account_id, account_type, entry_type, amount, currency, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    credit_entry_id, transaction_id,
                    customer_account_id, AccountType.CUSTOMER_WALLET.value,
                    EntryType.CREDIT.value, amount, currency, now,
                ),
            )

        return debit_entry_id, credit_entry_id

    def _verify_transaction_balance(self, transaction_id: str, cursor):
        """
        CRITICAL SAFETY CHECK: Verify that for this transaction,
        total DEBIT == total CREDIT (Double-Entry Invariant).
        """
        cursor.execute(
            """
            SELECT entry_type, SUM(amount) as total
            FROM ledger_entries
            WHERE transaction_id = ?
            GROUP BY entry_type
            """,
            (transaction_id,),
        )
        rows = cursor.fetchall()
        totals = {row["entry_type"]: row["total"] for row in rows}
        total_debit = round(totals.get("DEBIT", 0.0), 6)
        total_credit = round(totals.get("CREDIT", 0.0), 6)

        if total_debit != total_credit:
            raise LedgerBalanceError(
                f"CRITICAL: Ledger imbalance for txn {transaction_id}! "
                f"Debits={total_debit}, Credits={total_credit}"
            )

    def get_account_balance(self, account_id: str) -> dict:
        """
        Compute running balance for an account.
        Balance = Total Credits - Total Debits (standard accounting).
        """
        with self.db.transaction() as cursor:
            cursor.execute(
                """
                SELECT a.account_type,
                       COALESCE(SUM(CASE WHEN l.entry_type = 'CREDIT' THEN l.amount ELSE 0 END), 0.0) AS total_credits,
                       COALESCE(SUM(CASE WHEN l.entry_type = 'DEBIT'  THEN l.amount ELSE 0 END), 0.0) AS total_debits
                FROM accounts a
                LEFT JOIN ledger_entries l ON a.account_id = l.account_id
                WHERE a.account_id = ?
                GROUP BY a.account_id
                """,
                (account_id,),
            )
            row = cursor.fetchone()
            if not row:
                return {"error": f"Account {account_id} not found"}

            total_credits = round(row["total_credits"], 2)
            total_debits = round(row["total_debits"], 2)
            balance = round(total_credits - total_debits, 2)

            return {
                "account_id": account_id,
                "account_type": row["account_type"],
                "currency": "USD",
                "balance": balance,
                "total_debits": total_debits,
                "total_credits": total_credits,
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }

    def get_transaction_entries(self, transaction_id: str) -> List[dict]:
        """Fetch all ledger entries for a given transaction."""
        with self.db.transaction() as cursor:
            cursor.execute(
                "SELECT * FROM ledger_entries WHERE transaction_id = ? ORDER BY created_at",
                (transaction_id,),
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_system_balance_check(self) -> dict:
        """
        Global ledger health check.
        In a balanced ledger, TOTAL system debits == TOTAL system credits.
        """
        with self.db.transaction() as cursor:
            cursor.execute(
                """
                SELECT entry_type, SUM(amount) as total
                FROM ledger_entries
                GROUP BY entry_type
                """
            )
            rows = cursor.fetchall()
            totals = {row["entry_type"]: round(row["total"], 2) for row in rows}
            total_debit = totals.get("DEBIT", 0.0)
            total_credit = totals.get("CREDIT", 0.0)

            return {
                "total_debit_volume": total_debit,
                "total_credit_volume": total_credit,
                "is_balanced": abs(total_debit - total_credit) < 0.01,
                "imbalance_amount": round(abs(total_debit - total_credit), 6),
            }
