import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sandan_rag.config import get_config, get_setting
from sandan_rag.fts_index import SQLiteFTSIndex


def main() -> None:
    config = get_config()
    data = {
        "python": sys.executable,
        "python_version": sys.version,
        "project_root": str(config.project_root),
        "backend": config.rag_backend,
        "backend_label": config.backend_label,
        "openai_api_key_set": bool(get_setting("OPENAI_API_KEY", "")),
        "records_jsonl": str(config.records_jsonl),
        "records_jsonl_exists": config.records_jsonl.exists(),
        "records_jsonl_size": config.records_jsonl.stat().st_size if config.records_jsonl.exists() else 0,
        "sqlite_path": str(config.sqlite_path),
        "chroma_dir": str(config.chroma_dir),
        "lancedb_path": str(config.lancedb_path),
        "lancedb_table_name": config.lancedb_table_name,
        "qdrant_url_set": bool(config.qdrant_url),
        "qdrant_api_key_set": bool(config.qdrant_api_key),
        "qdrant_collection_name": config.qdrant_collection_name,
        "r2_enabled": config.use_r2,
        "r2_endpoint_set": bool(config.r2_endpoint),
        "r2_bucket_name": config.r2_bucket_name,
        "supabase_url_set": bool(config.supabase_url),
        "supabase_key_set": bool(config.supabase_key),
        "supabase_bucket": config.supabase_bucket,
    }

    try:
        if config.use_supabase:
            from sandan_rag.supabase_store import count_chunks, count_documents

            data["indexed_documents"] = count_documents(config)
            data["indexed_chunks"] = count_chunks(config)
        elif config.use_lancedb:
            from sandan_rag.lancedb_retriever import LanceDBRetriever

            retriever = LanceDBRetriever(config)
            data["indexed_documents"] = retriever.count_documents()
            data["indexed_chunks"] = retriever.count_chunks()
        elif config.use_qdrant:
            from sandan_rag.qdrant_retriever import QdrantRetriever

            retriever = QdrantRetriever(config)
            data["indexed_documents"] = retriever.count_documents()
            data["indexed_chunks"] = retriever.count_chunks()
        else:
            fts = SQLiteFTSIndex(config.sqlite_path)
            data["indexed_documents"] = fts.count_documents()
            data["indexed_chunks"] = fts.count_chunks()
    except Exception as exc:
        data["index_error"] = str(exc)

    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
