from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Dict, List

from tqdm import tqdm

from .chunker import TokenTextSplitter
from .collection_state import SQLiteCollectionState
from .config import AppConfig, get_config
from .fts_index import SQLiteFTSIndex
from .object_store import enrich_record_with_object_storage
from .openai_utils import embed_texts
from .utils import batch_iter, read_json, read_jsonl, safe_metadata_value, sha256_short, write_json


METADATA_KEYS = [
    "attachment_key",
    "chunk_index",
    "menu_no",
    "menu_name",
    "post_uid",
    "board_id",
    "post_title",
    "registered_date",
    "author",
    "detail_url",
    "attachment_name",
    "attachment_url",
    "attachment_path",
    "attachment_text_path",
    "storage_provider",
    "storage_bucket",
    "storage_path",
    "attachment_file_hash",
    "attachment_text_hash",
    "chunk_hash",
    "chunk_tokens",
]


class SandanIndexer:
    """Build or update the configured RAG index.

    Supported vector backends:
    - local: ChromaDB + SQLite FTS
    - lancedb: LanceDB + SQLite FTS
    - qdrant: Qdrant + optional SQLite FTS
    - supabase: handled by scripts/migrate_local_to_supabase.py for legacy deployments
    """

    def __init__(self, config: AppConfig | None = None):
        self.config = config or get_config()
        self.config.ensure_dirs()
        if self.config.use_supabase:
            raise RuntimeError("Use scripts/migrate_local_to_supabase.py for SANDAN_RAG_BACKEND=supabase.")

        self.fts = SQLiteFTSIndex(self.config.sqlite_path)
        self.splitter = TokenTextSplitter(
            chunk_tokens=self.config.chunk_tokens,
            chunk_overlap=self.config.chunk_overlap,
        )
        self.manifest = read_json(self.config.manifest_path, default={"documents": {}})
        self.manifest.setdefault("documents", {})

        self.backend = self._init_vector_backend()

    def _init_vector_backend(self):
        if self.config.use_lancedb:
            return LanceDBBackend(self.config)
        if self.config.use_qdrant:
            return QdrantBackend(self.config)
        return ChromaBackend(self.config)

    def load_collection_records(self) -> List[Dict]:
        records = read_jsonl(self.config.records_jsonl)
        if records:
            return records

        try:
            state = SQLiteCollectionState(self.config.collection_state_path)
            records = state.load_records()
            state.close()
        except Exception:
            records = []

        if records:
            # Recreate the jsonl file so older code paths and manual inspection still work.
            self.config.records_jsonl.parent.mkdir(parents=True, exist_ok=True)
            with self.config.records_jsonl.open("w", encoding="utf-8") as f:
                for record in records:
                    import json

                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return records

    def build_or_update(self, force: bool = False, upload_files: bool = True) -> Dict[str, int | str]:
        records = self.load_collection_records()
        if not records:
            return {
                "records_total": 0,
                "documents_indexed": 0,
                "documents_skipped": 0,
                "chunks_indexed": 0,
                "chunks_total": self.fts.count_chunks(),
                "documents_total": self.fts.count_documents(),
                "backend": self.config.rag_backend,
                "storage": self.config.storage_label,
                "message": (
                    f"Records file not found or empty: {self.config.records_jsonl}. "
                    f"Collection state DB checked: {self.config.collection_state_path}. "
                    "Run scripts/collect_data.py first."
                ),
            }

        if force:
            self.reset_index()

        changed_records = []
        skipped = 0
        seen_keys = set()

        for record in records:
            attachment_key = str(record.get("attachment_key", ""))
            if not attachment_key or attachment_key in seen_keys:
                continue
            seen_keys.add(attachment_key)

            current_signature = self.make_record_signature(record)
            previous_signature = self.manifest["documents"].get(attachment_key, {}).get("signature", "")
            if force or current_signature != previous_signature:
                changed_records.append((record, current_signature))
            else:
                skipped += 1

        indexed_chunks = 0
        indexed_docs = 0

        for record, signature in tqdm(changed_records, desc=f"Indexing documents [{self.config.rag_backend}]"):
            attachment_key = str(record.get("attachment_key", ""))
            enriched_record = enrich_record_with_object_storage(record, self.config, upload_files=upload_files)
            chunks = self.splitter.split_record(enriched_record)
            self.delete_document(attachment_key)
            if not chunks:
                continue

            payloads = [
                {
                    "chunk_id": chunk.chunk_id,
                    "text": chunk.text,
                    "metadata": {key: safe_metadata_value(value) for key, value in chunk.metadata.items()},
                }
                for chunk in chunks
            ]
            self.add_chunks(payloads)
            self.manifest["documents"][attachment_key] = {
                "signature": signature,
                "chunk_count": len(payloads),
                "post_title": enriched_record.get("post_title", ""),
                "attachment_name": enriched_record.get("attachment_name", ""),
                "registered_date": str(enriched_record.get("registered_date", ""))[:10],
                "storage_provider": enriched_record.get("storage_provider", ""),
                "storage_bucket": enriched_record.get("storage_bucket", ""),
                "storage_path": enriched_record.get("storage_path", ""),
            }
            indexed_chunks += len(payloads)
            indexed_docs += 1

        write_json(self.config.manifest_path, self.manifest)
        return {
            "records_total": len(records),
            "documents_indexed": indexed_docs,
            "documents_skipped": skipped,
            "chunks_indexed": indexed_chunks,
            "chunks_total": self.count_chunks(),
            "documents_total": self.count_documents(),
            "backend": self.config.rag_backend,
            "storage": self.config.storage_label,
            "message": "ok",
        }

    def make_record_signature(self, record: Dict) -> str:
        parts = [
            record.get("attachment_key", ""),
            record.get("attachment_file_hash", ""),
            record.get("attachment_text_hash", ""),
            str(record.get("rag_text_chars", "")),
            sha256_short(record.get("rag_text", ""), 24),
        ]
        return sha256_short("|".join(parts), 24)

    def delete_document(self, attachment_key: str) -> None:
        if not attachment_key:
            return
        self.backend.delete_document(attachment_key)
        self.fts.delete_by_attachment_key(attachment_key)

    def add_chunks(self, chunks: List[Dict]) -> None:
        self.backend.add_chunks(chunks)
        self.fts.upsert_chunks(chunks)

    def count_chunks(self) -> int:
        try:
            return self.backend.count_chunks()
        except Exception:
            return self.fts.count_chunks()

    def count_documents(self) -> int:
        try:
            return self.backend.count_documents()
        except Exception:
            return self.fts.count_documents()

    def reset_index(self) -> None:
        self.backend.reset_index()
        self._reset_fts_and_manifest()

    def hard_reset_all(self) -> None:
        self.backend.hard_reset_all()
        self._reset_fts_and_manifest(remove_manifest=True)

    def _reset_fts_and_manifest(self, remove_manifest: bool = False) -> None:
        try:
            self.fts.close()
        except Exception:
            pass
        for suffix in ["", "-wal", "-shm"]:
            path = self.config.sqlite_path.with_name(self.config.sqlite_path.name + suffix)
            if path.exists():
                path.unlink()
        self.fts = SQLiteFTSIndex(self.config.sqlite_path)
        self.manifest = {"documents": {}}
        if remove_manifest:
            if self.config.manifest_path.exists():
                self.config.manifest_path.unlink()
        else:
            write_json(self.config.manifest_path, self.manifest)


def flatten_row(chunk: Dict, embedding: List[float]) -> Dict:
    metadata = chunk.get("metadata", {}) or {}
    row = {
        "vector": embedding,
        "chunk_id": chunk.get("chunk_id", ""),
        "text": chunk.get("text", ""),
    }
    for key in METADATA_KEYS:
        value = metadata.get(key, "")
        row[key] = safe_metadata_value(value)
    return row


def point_id_from_chunk_id(chunk_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, str(chunk_id)))


def sql_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


class ChromaBackend:
    def __init__(self, config: AppConfig):
        import chromadb

        self.config = config
        self.client = chromadb.PersistentClient(path=str(self.config.chroma_dir))
        self.collection = self.client.get_or_create_collection(
            name=self.config.collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def add_chunks(self, chunks: List[Dict]) -> None:
        for batch in batch_iter(chunks, self.config.embedding_batch_size):
            texts = [item["text"] for item in batch]
            embeddings = embed_texts(texts, model=self.config.embedding_model)
            ids = [item["chunk_id"] for item in batch]
            metadatas = [item["metadata"] for item in batch]
            self.collection.add(ids=ids, documents=texts, metadatas=metadatas, embeddings=embeddings)

    def delete_document(self, attachment_key: str) -> None:
        try:
            self.collection.delete(where={"attachment_key": attachment_key})
        except Exception:
            pass

    def reset_index(self) -> None:
        try:
            self.client.delete_collection(self.config.collection_name)
        except Exception:
            pass
        self.collection = self.client.get_or_create_collection(
            name=self.config.collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def hard_reset_all(self) -> None:
        if self.config.chroma_dir.exists():
            shutil.rmtree(self.config.chroma_dir)

    def count_chunks(self) -> int:
        return int(self.collection.count())

    def count_documents(self) -> int:
        # Chroma does not support distinct count efficiently; SQLite FTS is used as fallback by SandanIndexer.
        raise RuntimeError("distinct document count is provided by SQLite FTS")


class LanceDBBackend:
    def __init__(self, config: AppConfig):
        import lancedb

        self.config = config
        self.db = lancedb.connect(str(self.config.lancedb_path))
        self.table_name = self.config.lancedb_table_name
        self.table = self._open_table()

    def _open_table(self):
        try:
            if self.table_name in self.db.table_names():
                return self.db.open_table(self.table_name)
        except Exception:
            pass
        return None

    def add_chunks(self, chunks: List[Dict]) -> None:
        for batch in batch_iter(chunks, self.config.embedding_batch_size):
            texts = [item["text"] for item in batch]
            embeddings = embed_texts(texts, model=self.config.embedding_model)
            rows = [flatten_row(item, embedding) for item, embedding in zip(batch, embeddings)]
            if not rows:
                continue
            if self.table is None:
                self.table = self.db.create_table(self.table_name, data=rows, mode="overwrite")
            else:
                self.table.add(rows)

    def delete_document(self, attachment_key: str) -> None:
        if self.table is None:
            return
        try:
            self.table.delete(f"attachment_key = {sql_literal(attachment_key)}")
        except Exception:
            pass

    def reset_index(self) -> None:
        try:
            if self.table_name in self.db.table_names():
                self.db.drop_table(self.table_name)
        except Exception:
            pass
        self.table = None

    def hard_reset_all(self) -> None:
        try:
            self.reset_index()
        finally:
            if self.config.lancedb_path.exists():
                shutil.rmtree(self.config.lancedb_path)

    def count_chunks(self) -> int:
        if self.table is None:
            return 0
        return int(self.table.count_rows())

    def count_documents(self) -> int:
        if self.table is None:
            return 0
        try:
            rows = self.table.to_pandas()["attachment_key"].dropna().unique()
            return int(len(rows))
        except Exception:
            return 0


class QdrantBackend:
    def __init__(self, config: AppConfig):
        from qdrant_client import QdrantClient

        self.config = config
        if not self.config.qdrant_url:
            raise RuntimeError("QDRANT_URL is not set.")
        self.client = QdrantClient(
            url=self.config.qdrant_url,
            api_key=self.config.qdrant_api_key or None,
            prefer_grpc=self.config.qdrant_prefer_grpc,
            timeout=self.config.qdrant_timeout,
        )
        self.collection_name = self.config.qdrant_collection_name

    def ensure_collection(self, vector_size: int) -> None:
        from qdrant_client.models import Distance, VectorParams

        try:
            self.client.get_collection(self.collection_name)
            return
        except Exception:
            pass
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(size=int(vector_size), distance=Distance.COSINE),
        )

    def add_chunks(self, chunks: List[Dict]) -> None:
        from qdrant_client.models import PointStruct

        for batch in batch_iter(chunks, self.config.embedding_batch_size):
            texts = [item["text"] for item in batch]
            embeddings = embed_texts(texts, model=self.config.embedding_model)
            if embeddings:
                self.ensure_collection(len(embeddings[0]))
            points = []
            for item, embedding in zip(batch, embeddings):
                metadata = item.get("metadata", {}) or {}
                payload = {key: safe_metadata_value(metadata.get(key, "")) for key in METADATA_KEYS}
                payload["chunk_id"] = item.get("chunk_id", "")
                payload["text"] = item.get("text", "")
                points.append(
                    PointStruct(
                        id=point_id_from_chunk_id(item.get("chunk_id", "")),
                        vector=embedding,
                        payload=payload,
                    )
                )
            if points:
                self.client.upsert(collection_name=self.collection_name, points=points, wait=True)

    def delete_document(self, attachment_key: str) -> None:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        try:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=Filter(
                    must=[FieldCondition(key="attachment_key", match=MatchValue(value=attachment_key))]
                ),
                wait=True,
            )
        except Exception:
            pass

    def reset_index(self) -> None:
        try:
            self.client.delete_collection(self.collection_name)
        except Exception:
            pass

    def hard_reset_all(self) -> None:
        self.reset_index()

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
            if len(seen) > 200000:
                break
        return len(seen)
