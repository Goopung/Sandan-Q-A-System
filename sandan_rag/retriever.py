from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List

import chromadb

from .config import AppConfig, get_config
from .fts_index import SQLiteFTSIndex
from .openai_utils import embed_texts
from .object_store import create_download_url
from .utils import clean_text, compact_snippet


@dataclass
class RetrievedChunk:
    chunk_id: str
    text: str
    metadata: Dict
    score: float
    source: str


class HybridRetriever:
    def __init__(self, config: AppConfig | None = None):
        self.config = config or get_config()
        self.client = chromadb.PersistentClient(path=str(self.config.chroma_dir))
        self.collection = self.client.get_or_create_collection(
            name=self.config.collection_name,
            metadata={"hnsw:space": "cosine"},
        )
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
        where = self._build_chroma_where(menu_filter, date_from, date_to)
        try:
            query_embedding = embed_texts([query], model=self.config.embedding_model)[0]
            result = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=int(top_k),
                where=where,
                include=["documents", "metadatas", "distances"],
            )
        except Exception:
            return []

        ids = result.get("ids", [[]])[0]
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]

        output = []
        for rank, chunk_id in enumerate(ids, start=1):
            distance = distances[rank - 1] if rank - 1 < len(distances) else 1.0
            score = 1.0 / (rank + 60.0)
            score += max(0.0, 1.0 - float(distance)) * 0.02
            output.append(
                RetrievedChunk(
                    chunk_id=chunk_id,
                    text=documents[rank - 1] if rank - 1 < len(documents) else "",
                    metadata=metadatas[rank - 1] if rank - 1 < len(metadatas) else {},
                    score=score,
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
        rows = self.fts.keyword_search(
            query,
            top_k=top_k,
            menu_filter=menu_filter,
            date_from=date_from,
            date_to=date_to,
        )
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

    def _build_chroma_where(self, menu_filter: str | None, date_from: str | None, date_to: str | None) -> Dict | None:
        clauses = []
        if menu_filter and menu_filter != "전체":
            clauses.append({"menu_name": {"$eq": menu_filter}})
        if date_from:
            clauses.append({"registered_date": {"$gte": date_from}})
        if date_to:
            clauses.append({"registered_date": {"$lte": date_to}})
        if not clauses:
            return None
        if len(clauses) == 1:
            return clauses[0]
        return {"$and": clauses}

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
