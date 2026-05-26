from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Set


class SQLiteCollectionState:
    """Persistent collection state for attachment crawling.

    The collector previously relied only on sandan_attachment_records.jsonl.
    If the app restarted and that file was missing or incomplete, the crawler
    could not know which attachments had already been processed.

    This small SQLite table stores the full record JSON for every processed
    attachment and is used as the source of truth for de-duplication.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.init_schema()

    def init_schema(self) -> None:
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS attachment_collection_records (
                attachment_key TEXT PRIMARY KEY,
                menu_no TEXT,
                menu_name TEXT,
                post_uid TEXT,
                board_id TEXT,
                post_title TEXT,
                registered_date TEXT,
                author TEXT,
                detail_url TEXT,
                attachment_name TEXT,
                attachment_url TEXT,
                attachment_path TEXT,
                attachment_text_path TEXT,
                attachment_file_hash TEXT,
                attachment_text_hash TEXT,
                rag_text_chars INTEGER,
                record_json TEXT NOT NULL,
                collected_at TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_attachment_collection_registered_date "
            "ON attachment_collection_records(registered_date)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_attachment_collection_board "
            "ON attachment_collection_records(menu_no, board_id)"
        )
        self.conn.commit()

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

    def clear(self) -> None:
        self.conn.execute("DELETE FROM attachment_collection_records")
        self.conn.commit()

    def upsert_record(self, record: Dict) -> None:
        attachment_key = str(record.get("attachment_key", "")).strip()
        if not attachment_key:
            return

        now = datetime.now().isoformat(timespec="seconds")
        record_json = json.dumps(record, ensure_ascii=False)
        self.conn.execute(
            """
            INSERT INTO attachment_collection_records(
                attachment_key, menu_no, menu_name, post_uid, board_id,
                post_title, registered_date, author, detail_url,
                attachment_name, attachment_url, attachment_path,
                attachment_text_path, attachment_file_hash, attachment_text_hash,
                rag_text_chars, record_json, collected_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(attachment_key) DO UPDATE SET
                menu_no = excluded.menu_no,
                menu_name = excluded.menu_name,
                post_uid = excluded.post_uid,
                board_id = excluded.board_id,
                post_title = excluded.post_title,
                registered_date = excluded.registered_date,
                author = excluded.author,
                detail_url = excluded.detail_url,
                attachment_name = excluded.attachment_name,
                attachment_url = excluded.attachment_url,
                attachment_path = excluded.attachment_path,
                attachment_text_path = excluded.attachment_text_path,
                attachment_file_hash = excluded.attachment_file_hash,
                attachment_text_hash = excluded.attachment_text_hash,
                rag_text_chars = excluded.rag_text_chars,
                record_json = excluded.record_json,
                collected_at = COALESCE(attachment_collection_records.collected_at, excluded.collected_at),
                updated_at = excluded.updated_at
            """,
            (
                attachment_key,
                str(record.get("menu_no", "")),
                str(record.get("menu_name", "")),
                str(record.get("post_uid", "")),
                str(record.get("board_id", "")),
                str(record.get("post_title", "")),
                str(record.get("registered_date", ""))[:10],
                str(record.get("author", "")),
                str(record.get("detail_url", "")),
                str(record.get("attachment_name", "")),
                str(record.get("attachment_url", "")),
                str(record.get("attachment_path", "")),
                str(record.get("attachment_text_path", "")),
                str(record.get("attachment_file_hash", "")),
                str(record.get("attachment_text_hash", "")),
                int(record.get("rag_text_chars", 0) or 0),
                record_json,
                str(record.get("collected_at", "")) or now,
                now,
            ),
        )
        self.conn.commit()

    def upsert_records(self, records: Iterable[Dict]) -> None:
        for record in records:
            self.upsert_record(record)

    def keys(self) -> Set[str]:
        rows = self.conn.execute("SELECT attachment_key FROM attachment_collection_records").fetchall()
        return {str(row["attachment_key"]) for row in rows if row["attachment_key"]}

    def load_records(self) -> List[Dict]:
        rows = self.conn.execute(
            """
            SELECT record_json
            FROM attachment_collection_records
            ORDER BY registered_date DESC, menu_no ASC, board_id DESC, attachment_name ASC
            """
        ).fetchall()

        records: List[Dict] = []
        for row in rows:
            try:
                item = json.loads(row["record_json"])
                if isinstance(item, dict) and item.get("attachment_key"):
                    records.append(item)
            except Exception:
                continue
        return records

    def count_records(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS n FROM attachment_collection_records").fetchone()
        return int(row["n"] if row else 0)
