import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sandan_rag.bootstrap import configure_utf8
from sandan_rag.chunker import TokenTextSplitter
from sandan_rag.config import get_config
from sandan_rag.object_store import enrich_record_with_object_storage, storage_path_for_record
from sandan_rag.openai_utils import embed_texts
from sandan_rag.supabase_store import (
    count_chunks,
    count_chunks_by_attachment_key,
    count_documents,
    delete_old_chunks,
    get_document_by_attachment_key,
    insert_chunks,
    upsert_document,
)
from sandan_rag.utils import batch_iter, read_jsonl, safe_metadata_value


configure_utf8()


def build_chunk_rows(record: Dict, document_id: str, storage_path: str, splitter: TokenTextSplitter) -> List[Dict]:
    chunks = splitter.split_record(record, chunk_prefix="sb")
    storage_provider = str(record.get("storage_provider", "") or "")
    storage_bucket = str(record.get("storage_bucket", "") or "")

    rows = []
    for chunk in chunks:
        metadata = {key: safe_metadata_value(value) for key, value in chunk.metadata.items()}
        rows.append(
            {
                "document_id": document_id,
                "attachment_key": record.get("attachment_key", ""),
                "chunk_id": chunk.chunk_id,
                "chunk_index": int(metadata.get("chunk_index", 0) or 0),
                "chunk_text": chunk.text,
                "embedding": None,
                "menu_no": metadata.get("menu_no", ""),
                "menu_name": metadata.get("menu_name", ""),
                "board_id": metadata.get("board_id", ""),
                "post_title": metadata.get("post_title", ""),
                "registered_date": str(metadata.get("registered_date", ""))[:10],
                "attachment_name": metadata.get("attachment_name", ""),
                "detail_url": metadata.get("detail_url", ""),
                "storage_provider": storage_provider,
                "storage_bucket": storage_bucket,
                "storage_path": storage_path,
                "text_hash": metadata.get("attachment_text_hash", ""),
            }
        )
    return rows


def migrate_records(force: bool = False, upload_files: bool = True) -> Dict[str, int | str]:
    config = get_config()
    records = read_jsonl(config.records_jsonl)
    if not records:
        raise FileNotFoundError(f"Records file not found or empty: {config.records_jsonl}. Run scripts/collect_data.py first.")

    splitter = TokenTextSplitter(config.chunk_tokens, config.chunk_overlap)
    total_docs = 0
    skipped_docs = 0
    updated_docs = 0
    total_chunks = 0

    print(f"[INFO] records: {len(records)}")
    print("[INFO] vector backend: Supabase pgvector")
    print(f"[INFO] file storage: {config.storage_label}")

    seen_keys = set()
    for idx, record in enumerate(records, start=1):
        attachment_key = str(record.get("attachment_key", "") or "")
        if not attachment_key or attachment_key in seen_keys:
            continue
        seen_keys.add(attachment_key)
        total_docs += 1

        text_hash = str(record.get("attachment_text_hash", "") or "")
        existing = get_document_by_attachment_key(attachment_key, config)
        existing_chunks = count_chunks_by_attachment_key(attachment_key, config) if existing else 0

        existing_provider = str((existing or {}).get("storage_provider", "") or "")
        existing_bucket = str((existing or {}).get("storage_bucket", "") or "")
        expected_provider = "r2" if config.use_r2 else ("supabase" if config.use_supabase else "local")
        expected_bucket = config.r2_bucket_name if expected_provider == "r2" else config.supabase_bucket
        storage_provider_changed = bool(
            existing
            and expected_provider
            and (existing_provider != expected_provider or existing_bucket != expected_bucket)
        )

        if not force and not storage_provider_changed and existing and existing.get("text_hash") == text_hash and existing_chunks > 0:
            skipped_docs += 1
            print(f"[SKIP] {idx}/{len(records)} unchanged: {record.get('attachment_name', '')}")
            continue

        enriched_record = dict(record)
        existing_storage_path = str((existing or {}).get("storage_path", "") or "")
        if existing_storage_path:
            enriched_record["storage_path"] = existing_storage_path
        else:
            enriched_record["storage_path"] = storage_path_for_record(enriched_record, config)

        enriched_record = enrich_record_with_object_storage(
            enriched_record,
            config,
            upload_files=upload_files,
        )
        storage_path = str(enriched_record.get("storage_path", "") or "")

        document_id = upsert_document(enriched_record, storage_path, config)
        delete_old_chunks(attachment_key, config)

        rows = build_chunk_rows(enriched_record, document_id, storage_path, splitter)
        if not rows:
            print(f"[WARN] no chunks: {record.get('attachment_name', '')}")
            continue

        for batch in batch_iter(rows, config.embedding_batch_size):
            texts = [row["chunk_text"] for row in batch]
            embeddings = embed_texts(texts, config.embedding_model)
            for row, embedding in zip(batch, embeddings):
                row["embedding"] = embedding
            insert_chunks(batch, config)

        updated_docs += 1
        total_chunks += len(rows)
        print(
            f"[DONE] {idx}/{len(records)} chunks={len(rows)} "
            f"storage={enriched_record.get('storage_provider', '')} "
            f"file={record.get('attachment_name', '')}"
        )

    stats = {
        "records_total": len(records),
        "documents_total_input": total_docs,
        "documents_updated": updated_docs,
        "documents_skipped": skipped_docs,
        "chunks_updated": total_chunks,
        "supabase_documents_total": count_documents(config),
        "supabase_chunks_total": count_chunks(config),
        "vector_backend": "supabase",
        "file_storage": config.storage_label,
    }
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return stats


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Recreate chunks even if text hash is unchanged.")
    parser.add_argument("--no-upload-files", action="store_true", help="Skip uploading original files to the configured object storage.")
    args = parser.parse_args()
    migrate_records(force=args.force, upload_files=not args.no_upload_files)


if __name__ == "__main__":
    main()
