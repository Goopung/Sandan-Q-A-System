from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List

from .config import AppConfig, get_config
from .fts_index import SQLiteFTSIndex
from .object_store import create_download_url
from .openai_utils import embed_texts
from .utils import clean_text, compact_snippet


@dataclass
class RetrievedChunk:
    chunk_id: str
    text: str
    metadata: Dict
    score: float
    source: str


class QdrantRetriever:
    def __init__(self, config: AppConfig | None = None):
        from qdrant_client import QdrantClient

        self.config = config or get_config()
        if not self.config.qdrant_url:
            raise RuntimeError("QDRANT_URL is not set.")
        self.client = QdrantClient(
            url=self.config.qdrant_url,
            api_key=self.config.qdrant_api_key or None,
            prefer_grpc=self.config.qdrant_prefer_grpc,
            timeout=self.config.qdrant_timeout,
        )
        self.collection_name = self.config.qdrant_collection_name
        self.fts = SQLiteFTSIndex(self.config.sqlite_path)

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

        vector_results = self.vector_search(query, self.config.vector_top_k, menu_filter, date_from, date_to)
        keyword_results = self.keyword_search(query, self.config.keyword_top_k, menu_filter, date_from, date_to)
        fused = self.fuse_results(vector_results, keyword_results)
        filtered = [
            item for item in fused
            if self._date_ok(item.metadata.get("registered_date", ""), date_from, date_to)
        ]
        return filtered[:final_top_k]

    def vector_search(
        self,
        query: str,
        top_k: int,
        menu_filter: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> List[RetrievedChunk]:
        try:
            query_embedding = embed_texts([query], model=self.config.embedding_model)[0]
            query_filter = self._build_qdrant_filter(menu_filter)
            try:
                result = self.client.query_points(
                    collection_name=self.collection_name,
                    query=query_embedding,
                    query_filter=query_filter,
                    limit=int(top_k),
                    with_payload=True,
                    with_vectors=False,
                )
                points = result.points
            except AttributeError:
                points = self.client.search(
                    collection_name=self.collection_name,
                    query_vector=query_embedding,
                    query_filter=query_filter,
                    limit=int(top_k),
                    with_payload=True,
                    with_vectors=False,
                )
        except Exception:
            return []

        output = []
        for rank, point in enumerate(points, start=1):
            payload = point.payload or {}
            score = float(getattr(point, "score", 0.0) or 0.0)
            output.append(
                RetrievedChunk(
                    chunk_id=str(payload.get("chunk_id", "")),
                    text=str(payload.get("text", "")),
                    metadata={key: value for key, value in payload.items() if key != "text"},
                    score=score * 0.30 + 1.0 / (rank + 60.0),
                    source="vector",
                )
            )
        return output

    def keyword_search(
        self,
        query: str,
        top_k: int,
        menu_filter: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> List[RetrievedChunk]:
        try:
            if self.fts.count_chunks() <= 0:
                return []
        except Exception:
            return []
        rows = self.fts.keyword_search(query, top_k=top_k, menu_filter=menu_filter, date_from=date_from, date_to=date_to)
        output = []
        for row in rows:
            metadata = dict(row)
            chunk_id = metadata.get("chunk_id", "")
            text = self.fts.get_chunk_text(chunk_id)
            output.append(
                RetrievedChunk(
                    chunk_id=chunk_id,
                    text=text,
                    metadata=metadata,
                    score=1.0 / (float(metadata.get("rank", 1)) + 60.0),
                    source="keyword",
                )
            )
        return output

    def fuse_results(self, vector_results: List[RetrievedChunk], keyword_results: List[RetrievedChunk]) -> List[RetrievedChunk]:
        by_id: Dict[str, RetrievedChunk] = {}
        for rank, item in enumerate(vector_results, start=1):
            item.score = item.score + 1.0 / (rank + 60.0) + self.recency_boost(item.metadata.get("registered_date", ""))
            by_id[item.chunk_id] = item
        for rank, item in enumerate(keyword_results, start=1):
            boost = 1.0 / (rank + 60.0)
            if item.chunk_id in by_id:
                by_id[item.chunk_id].score += boost + 0.025
                by_id[item.chunk_id].source = "hybrid"
            else:
                item.score = item.score + boost + self.recency_boost(item.metadata.get("registered_date", ""))
                by_id[item.chunk_id] = item
        return sorted(by_id.values(), key=lambda item: item.score, reverse=True)

    def _build_qdrant_filter(self, menu_filter: str | None):
        if not menu_filter or menu_filter == "전체":
            return None
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        return Filter(must=[FieldCondition(key="menu_name", match=MatchValue(value=menu_filter))])

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

    def _date_ok(self, registered_date: str, date_from: str | None, date_to: str | None) -> bool:
        if not registered_date:
            return True
        date_value = str(registered_date)[:10]
        if date_from and date_value < date_from:
            return False
        if date_to and date_value > date_to:
            return False
        return True

    def group_by_attachment(self, chunks: List[RetrievedChunk], max_docs: int = 8) -> List[Dict]:
        grouped: Dict[str, Dict] = {}
        for chunk in chunks:
            metadata = chunk.metadata
            key = metadata.get("attachment_key", "") or metadata.get("attachment_path", "") or chunk.chunk_id
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
                    "attachment_path": metadata.get("attachment_path", ""),
                    "storage_provider": metadata.get("storage_provider", ""),
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

    def count_chunks(self) -> int:
        try:
            result = self.client.count(collection_name=self.collection_name, exact=True)
            return int(result.count)
        except Exception:
            return 0

    def count_documents(self) -> int:
        seen = set()
        offset = None
        while True:
            try:
                points, offset = self.client.scroll(
                    collection_name=self.collection_name,
                    limit=512,
                    offset=offset,
                    with_vectors=False,
                    with_payload=["attachment_key"],
                )
            except Exception:
                break
            for point in points:
                payload = point.payload or {}
                key = payload.get("attachment_key")
                if key:
                    seen.add(str(key))
            if offset is None:
                break
        return len(seen)
