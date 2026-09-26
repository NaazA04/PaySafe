"""
Database layer for Payment System.
Provides thread-safe, transactional SQLite storage ensuring ACID compliance.
"""

import sqlite3
import threading
from contextlib import contextmanager
from typing import Generator, Optional
import os


class DatabaseManager:
    _instance: Optional["DatabaseManager"] = None
    _lock = threading.Lock()

    def __init__(self, db_path: str = "payment_system.db"):
        self.db_path = db_path
        self._local = threading.local()
        self._init_db()

    @classmethod
    def get_instance(cls, db_path: str = "payment_system.db") -> "DatabaseManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(db_path)
            return cls._instance

    def _get_connection(self) -> sqlite3.Connection:
        if not hasattr(self._local, "connection") or self._local.connection is None:
            conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            # Enable Foreign Keys & Write-Ahead Logging (WAL) for concurrency & durability
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("PRAGMA journal_mode = WAL;")
            self._local.connection = conn
        return self._local.connection

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Cursor, None, None]:
        """
        Atomic transaction context manager.
        Commits on success; rolls back on any exception.
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()

    def _init_db(self):
        """Initialize all schema tables and indexes."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 1. Accounts Table (Chart of Accounts)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                account_id TEXT PRIMARY KEY,
                account_type TEXT NOT NULL,
                currency TEXT NOT NULL DEFAULT 'USD',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 2. Transactions Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                transaction_id TEXT PRIMARY KEY,
                idempotency_key TEXT UNIQUE NOT NULL,
                user_id TEXT NOT NULL,
                merchant_id TEXT NOT NULL,
                amount REAL NOT NULL CHECK(amount > 0),
                currency TEXT NOT NULL DEFAULT 'USD',
                payment_method TEXT NOT NULL,
                status TEXT NOT NULL,
                failure_reason TEXT,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 3. Double-Entry Ledger Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ledger_entries (
                entry_id TEXT PRIMARY KEY,
                transaction_id TEXT NOT NULL,
                account_id TEXT NOT NULL,
                account_type TEXT NOT NULL,
                entry_type TEXT NOT NULL CHECK(entry_type IN ('DEBIT', 'CREDIT')),
                amount REAL NOT NULL CHECK(amount > 0),
                currency TEXT NOT NULL DEFAULT 'USD',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (transaction_id) REFERENCES transactions(transaction_id),
                FOREIGN KEY (account_id) REFERENCES accounts(account_id)
            );
        """)

        # 4. Idempotency Keys Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS idempotency_records (
                idempotency_key TEXT PRIMARY KEY,
                request_hash TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('PROCESSING', 'COMPLETED', 'FAILED')),
                response_body TEXT,
                transaction_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 5. Audit Log Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                details TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Indexes for fast lookup
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_txn_user ON transactions(user_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ledger_txn ON ledger_entries(transaction_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ledger_acc ON ledger_entries(account_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_idemp_key ON idempotency_records(idempotency_key);")

        conn.commit()
        conn.close()

    def reset_db(self):
        """Utility method to clean database for tests."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DROP TABLE IF EXISTS audit_logs;")
        cursor.execute("DROP TABLE IF EXISTS ledger_entries;")
        cursor.execute("DROP TABLE IF EXISTS transactions;")
        cursor.execute("DROP TABLE IF EXISTS idempotency_records;")
        cursor.execute("DROP TABLE IF EXISTS accounts;")
        conn.commit()
        conn.close()
        self._init_db()
