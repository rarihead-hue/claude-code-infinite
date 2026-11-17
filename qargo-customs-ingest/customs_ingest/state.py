"""Remembers which attachments were already uploaded, so a re-run never double-uploads."""
import sqlite3
from datetime import datetime, timezone


class State:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path)
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS uploads (
                   message_id TEXT, attachment_id TEXT, reference TEXT, order_id TEXT,
                   filename TEXT, uploaded_at TEXT,
                   PRIMARY KEY (message_id, attachment_id))"""
        )
        self.db.commit()

    def already_uploaded(self, message_id: str, attachment_id: str) -> bool:
        cur = self.db.execute(
            "SELECT 1 FROM uploads WHERE message_id=? AND attachment_id=?", (message_id, attachment_id)
        )
        return cur.fetchone() is not None

    def record(self, message_id: str, attachment_id: str, reference: str, order_id: str, filename: str) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO uploads VALUES (?,?,?,?,?,?)",
            (message_id, attachment_id, reference, order_id, filename, datetime.now(timezone.utc).isoformat()),
        )
        self.db.commit()
