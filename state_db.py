import sqlite3
import json
from datetime import datetime

class SyncStateDB:
    def __init__(self, db_path="sync_state.db"):
        self.conn = sqlite3.connect(db_path)
        self._create_tables()

    def _create_tables(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_state (
                confluence_page_id TEXT PRIMARY KEY,
                dify_document_id TEXT,
                confluence_version INT,
                last_synced_at TEXT,
                extra_meta TEXT
            )
        """)
        self.conn.commit()

    def get_state(self, page_id):
        row = self.conn.execute(
            "SELECT * FROM sync_state WHERE confluence_page_id=?", (page_id,)
        ).fetchone()
        if row:
            return {
                "page_id": row[0],
                "dify_doc_id": row[1],
                "version": row[2],
                "synced_at": row[3],
                "extra": json.loads(row[4]) if row[4] else {}
            }
        return None

    def upsert_state(self, page_id, dify_doc_id, version, extra_meta=None):
        now = datetime.utcnow().isoformat()
        self.conn.execute("""
            INSERT OR REPLACE INTO sync_state
            VALUES (?, ?, ?, ?, ?)
        """, (page_id, dify_doc_id, version, now, json.dumps(extra_meta or {})))
        self.conn.commit()