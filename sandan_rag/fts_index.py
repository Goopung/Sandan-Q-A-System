import re
import sqlite3
from pathlib import Path
from typing import Dict, List

from .utils import clean_text, safe_metadata_value


class SQLiteFTSIndex:
    def __init__(self, sqlite_path: Path):
        self.sqlite_path = Path(sqlite_path)
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.sqlite_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.init_schema()

    def init_schema(self) -> None:
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                chunk_id UNINDEXED,
                text,
                post_title,
                attachment_name,
                menu_name,
                tokenize = 'unicode61'
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chunks_meta (
                chunk_id TEXT PRIMARY KEY,
                attachment_key TEXT,
                chunk_index INTEGER,
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
                storage_provider TEXT,
                storage_bucket TEXT,
                storage_path TEXT,
                attachment_file_hash TEXT,
                attachment_text_hash TEXT,
                chunk_hash TEXT,
                chunk_tokens INTEGER
            )
            """
        )
        self._ensure_column("chunks_meta", "storage_provider", "TEXT")
        self._ensure_column("chunks_meta", "storage_bucket", "TEXT")
        self._ensure_column("chunks_meta", "storage_path", "TEXT")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_meta_attachment_key ON chunks_meta(attachment_key)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_meta_registered_date ON chunks_meta(registered_date)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_meta_menu_name ON chunks_meta(menu_name)")
        self.conn.commit()

    def _ensure_column(self, table_name: str, column_name: str, column_type: str) -> None:
        rows = self.conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        columns = {row["name"] for row in rows}
        if column_name not in columns:
            self.conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

    def delete_by_attachment_key(self, attachment_key: str) -> None:
        rows = self.conn.execute(
            "SELECT chunk_id FROM chunks_meta WHERE attachment_key = ?",
            (attachment_key,),
        ).fetchall()
        chunk_ids = [row["chunk_id"] for row in rows]
        for chunk_id in chunk_ids:
            self.conn.execute("DELETE FROM chunks_fts WHERE chunk_id = ?", (chunk_id,))
        self.conn.execute("DELETE FROM chunks_meta WHERE attachment_key = ?", (attachment_key,))
        self.conn.commit()

    def upsert_chunks(self, chunks: List[Dict]) -> None:
        for item in chunks:
            chunk_id = item["chunk_id"]
            text = clean_text(item["text"])
            metadata = item["metadata"]

            self.conn.execute("DELETE FROM chunks_fts WHERE chunk_id = ?", (chunk_id,))
            self.conn.execute("DELETE FROM chunks_meta WHERE chunk_id = ?", (chunk_id,))
            self.conn.execute(
                """
                INSERT INTO chunks_fts(chunk_id, text, post_title, attachment_name, menu_name)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    chunk_id,
                    text,
                    metadata.get("post_title", ""),
                    metadata.get("attachment_name", ""),
                    metadata.get("menu_name", ""),
                ),
            )
            self.conn.execute(
                """
                INSERT INTO chunks_meta(
                    chunk_id, attachment_key, chunk_index, menu_no, menu_name, post_uid,
                    board_id, post_title, registered_date, author, detail_url,
                    attachment_name, attachment_url, attachment_path, attachment_text_path,
                    storage_provider, storage_bucket, storage_path,
                    attachment_file_hash, attachment_text_hash, chunk_hash, chunk_tokens
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chunk_id,
                    safe_metadata_value(metadata.get("attachment_key", "")),
                    int(metadata.get("chunk_index", 0) or 0),
                    safe_metadata_value(metadata.get("menu_no", "")),
                    safe_metadata_value(metadata.get("menu_name", "")),
                    safe_metadata_value(metadata.get("post_uid", "")),
                    safe_metadata_value(metadata.get("board_id", "")),
                    safe_metadata_value(metadata.get("post_title", "")),
                    safe_metadata_value(str(metadata.get("registered_date", ""))[:10]),
                    safe_metadata_value(metadata.get("author", "")),
                    safe_metadata_value(metadata.get("detail_url", "")),
                    safe_metadata_value(metadata.get("attachment_name", "")),
                    safe_metadata_value(metadata.get("attachment_url", "")),
                    safe_metadata_value(metadata.get("attachment_path", "")),
                    safe_metadata_value(metadata.get("attachment_text_path", "")),
                    safe_metadata_value(metadata.get("storage_provider", "")),
                    safe_metadata_value(metadata.get("storage_bucket", "")),
                    safe_metadata_value(metadata.get("storage_path", "")),
                    safe_metadata_value(metadata.get("attachment_file_hash", "")),
                    safe_metadata_value(metadata.get("attachment_text_hash", "")),
                    safe_metadata_value(metadata.get("chunk_hash", "")),
                    int(metadata.get("chunk_tokens", 0) or 0),
                ),
            )
        self.conn.commit()

    def keyword_search(
        self,
        query: str,
        top_k: int = 20,
        menu_filter: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> List[Dict]:
        fts_query = self.make_fts_query(query)
        if not fts_query:
            return []

        where_parts = ["chunks_fts MATCH ?"]
        params: list = [fts_query]
        if menu_filter and menu_filter != "전체":
            where_parts.append("m.menu_name = ?")
            params.append(menu_filter)
        if date_from:
            where_parts.append("m.registered_date >= ?")
            params.append(date_from)
        if date_to:
            where_parts.append("m.registered_date <= ?")
            params.append(date_to)

        params.append(int(top_k))
        sql = f"""
            SELECT
                f.chunk_id,
                snippet(chunks_fts, 1, '<b>', '</b>', '...', 24) AS snippet,
                bm25(chunks_fts) AS bm25_score,
                m.*
            FROM chunks_fts f
            JOIN chunks_meta m ON f.chunk_id = m.chunk_id
            WHERE {' AND '.join(where_parts)}
            ORDER BY bm25(chunks_fts)
            LIMIT ?
        """
        try:
            rows = self.conn.execute(sql, tuple(params)).fetchall()
        except sqlite3.OperationalError:
            return []

        results = []
        for rank, row in enumerate(rows, start=1):
            item = dict(row)
            item["rank"] = rank
            item["score"] = 1.0 / (rank + 1)
            results.append(item)
        return results

    def get_chunk_text(self, chunk_id: str) -> str:
        row = self.conn.execute(
            "SELECT text FROM chunks_fts WHERE chunk_id = ? LIMIT 1",
            (chunk_id,),
        ).fetchone()
        return clean_text(row["text"]) if row else ""

    def make_fts_query(self, query: str) -> str:
        query = clean_text(query)
        tokens = re.findall(r"[가-힣A-Za-z0-9_]{2,}", query)
        tokens = [token.strip() for token in tokens if len(token.strip()) >= 2]
        if not tokens:
            return ""
        safe_tokens = []
        seen = set()
        for token in tokens[:16]:
            token = token.replace('"', "")
            if not token or token in seen:
                continue
            seen.add(token)
            safe_tokens.append(f'"{token}"')
        return " OR ".join(safe_tokens)

    def count_chunks(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS n FROM chunks_meta").fetchone()
        return int(row["n"] if row else 0)

    def count_documents(self) -> int:
        row = self.conn.execute("SELECT COUNT(DISTINCT attachment_key) AS n FROM chunks_meta").fetchone()
        return int(row["n"] if row else 0)

    def recent_documents(self, limit: int = 5) -> List[Dict]:
        rows = self.conn.execute(
            """
            SELECT attachment_key, menu_name, post_title, registered_date, attachment_name, detail_url
            FROM chunks_meta
            GROUP BY attachment_key
            ORDER BY registered_date DESC, attachment_name ASC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        return [dict(row) for row in rows]
