"""
Audit Logger — tracks all critical events for compliance and debugging.
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from src.core.database import DatabaseManager


class AuditLogger:
    def __init__(self, db: DatabaseManager):
        self.db = db

    def log(self, event_type: str, entity_id: str, details: Optional[Dict[str, Any]] = None):
        try:
            with self.db.transaction() as cursor:
                cursor.execute(
                    """
                    INSERT INTO audit_logs (event_type, entity_id, details, timestamp)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        event_type,
                        entity_id,
                        json.dumps(details or {}),
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
        except Exception:
            # Audit failures must never break the main payment flow
            pass

    def get_logs(self, entity_id: str = None, limit: int = 100) -> list:
        with self.db.transaction() as cursor:
            if entity_id:
                cursor.execute(
                    "SELECT * FROM audit_logs WHERE entity_id = ? ORDER BY timestamp DESC LIMIT ?",
                    (entity_id, limit),
                )
            else:
                cursor.execute(
                    "SELECT * FROM audit_logs ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                )
            return [dict(row) for row in cursor.fetchall()]
