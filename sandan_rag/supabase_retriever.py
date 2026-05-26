from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List

from .config import AppConfig, get_config
from .openai_utils import embed_texts
from .object_store import create_download_url
from .supabase_store import get_supabase_client
from .utils import clean_text, compact_snippet


@dataclass
class RetrievedChunk:
    chunk_id: str
    text: str
    metadata: Dict
    score: float
    source: str


class SupabaseRetriever:
    def __init__(self, config: AppConfig | None = None):
        self.config = config or get_config()
        self.client = get_supabase_client(self.config)

    def search(
        self,
        query: str,
        final_top_k: int | None = None,
        menu_filter: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> List[RetrievedChunk]:
        query = clean_text(query)
        if not query:
            return []
        if final_top_k is None:
            final_top_k = self.config.final_top_k

        vector_rows = self.vector_search(query, self.config.vector_top_k, menu_filter, date_from, date_to)
        keyword_rows = self.keyword_search(query, self.config.keyword_top_k, menu_filter, date_from, date_to)
        fused = self.fuse_rows(vector_rows, keyword_rows)
        return fused[:final_top_k]

    def vector_search(self, query: str, top_k: int, menu_filter: str | None, date_from: str | None, date_to: str | None) -> List[Dict]:
        try:
            embedding = embed_texts([query], model=self.config.embedding_model)[0]
            result = self.client.rpc(
                "match_sandan_chunks",
                {
                    "query_embedding": embedding,
                    "match_count": int(top_k),
                    "menu_filter": None if not menu_filter or menu_filter == "전체" else menu_filter,
                    "date_from": date_from,
                    "date_to": date_to,
                },
            ).execute()
            rows = result.data or []
            for idx, row in enumerate(rows, start=1):
                row["_source"] = "vector"
                row["_rank"] = idx
            return rows
        except Exception:
            return []

    def keyword_search(self, query: str, top_k: int, menu_filter: str | None, date_from: str | None, date_to: str | None) -> List[Dict]:
        try:
            result = self.client.rpc(
                "keyword_sandan_chunks",
                {
                    "query_text": query,
                    "match_count": int(top_k),
                    "menu_filter": None if not menu_filter or menu_filter == "전체" else menu_filter,
                    "date_from": date_from,
                    "date_to": date_to,
                },
            ).execute()
            rows = result.data or []
            for idx, row in enumerate(rows, start=1):
                row["_source"] = "keyword"
                row["_rank"] = idx
            return rows
        except Exception:
            return []

    def fuse_rows(self, vector_rows: List[Dict], keyword_rows: List[Dict]) -> List[RetrievedChunk]:
        by_id: Dict[str, Dict] = {}

        for row in vector_rows:
            chunk_id = row.get("chunk_id", "")
            if not chunk_id:
                continue
            rank = int(row.get("_rank", 1) or 1)
            sim = float(row.get("similarity", 0.0) or 0.0)
            row["_score"] = sim * 0.30 + 1.0 / (rank + 60.0) + self.recency_boost(row.get("registered_date", ""))
            row["_fused_source"] = "vector"
            by_id[chunk_id] = row

        for row in keyword_rows:
            chunk_id = row.get("chunk_id", "")
            if not chunk_id:
                continue
            rank = int(row.get("_rank", 1) or 1)
            sim = float(row.get("similarity", 0.0) or 0.0)
            score = sim * 0.15 + 1.0 / (rank + 60.0) + self.recency_boost(row.get("registered_date", ""))
            if chunk_id in by_id:
                by_id[chunk_id]["_score"] += score + 0.03
                by_id[chunk_id]["_fused_source"] = "hybrid"
            else:
                row["_score"] = score
                row["_fused_source"] = "keyword"
                by_id[chunk_id] = row

        chunks = []
        for row in sorted(by_id.values(), key=lambda item: item.get("_score", 0.0), reverse=True):
            metadata = {
                "attachment_key": row.get("attachment_key", ""),
                "menu_no": row.get("menu_no", ""),
                "menu_name": row.get("menu_name", ""),
                "board_id": row.get("board_id", ""),
                "post_title": row.get("post_title", ""),
                "registered_date": row.get("registered_date", ""),
                "attachment_name": row.get("attachment_name", ""),
                "detail_url": row.get("detail_url", ""),
                "storage_provider": row.get("storage_provider", "") or ("r2" if self.config.use_r2 else "supabase"),
                "storage_bucket": row.get("storage_bucket", ""),
                "storage_path": row.get("storage_path", ""),
                "attachment_url": row.get("detail_url", ""),
            }
            chunks.append(
                RetrievedChunk(
                    chunk_id=row.get("chunk_id", ""),
                    text=row.get("chunk_text", ""),
                    metadata=metadata,
                    score=float(row.get("_score", 0.0) or 0.0),
                    source=row.get("_fused_source", row.get("_source", "supabase")),
                )
            )
        return chunks

    def recency_boost(self, registered_date: str) -> float:
        try:
            year = int(str(registered_date)[:4])
            current_year = datetime.now().year
            if year >= current_year - 1:
                return 0.015
            if year >= current_year - 3:
                return 0.008
        except Exception:
            pass
        return 0.0

    def group_by_attachment(self, chunks: List[RetrievedChunk], max_docs: int = 8) -> List[Dict]:
        grouped: Dict[str, Dict] = {}
        for chunk in chunks:
            metadata = chunk.metadata
            key = metadata.get("attachment_key", "") or chunk.chunk_id
            if key not in grouped:
                grouped[key] = {
                    "attachment_key": key,
                    "score": 0.0,
                    "post_title": metadata.get("post_title", ""),
                    "registered_date": metadata.get("registered_date", ""),
                    "menu_name": metadata.get("menu_name", ""),
                    "detail_url": metadata.get("detail_url", ""),
                    "attachment_name": metadata.get("attachment_name", ""),
                    "attachment_url": metadata.get("attachment_url", ""),
                    "attachment_path": "",
                    "storage_provider": metadata.get("storage_provider", "") or ("r2" if self.config.use_r2 else "supabase"),
                    "storage_bucket": metadata.get("storage_bucket", ""),
                    "storage_path": metadata.get("storage_path", ""),
                    "download_url": "",
                    "snippets": [],
                    "chunks": [],
                }
            grouped[key]["score"] += chunk.score
            grouped[key]["chunks"].append(chunk)
            grouped[key]["snippets"].append(compact_snippet(chunk.text, 500))

        docs = sorted(grouped.values(), key=lambda item: item["score"], reverse=True)[:max_docs]
        for doc in docs:
            if doc.get("storage_path"):
                doc["download_url"] = create_download_url(
                    doc.get("storage_provider", ""),
                    doc.get("storage_path", ""),
                    config=self.config,
                )
        return docs
