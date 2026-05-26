import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sandan_rag.bootstrap import configure_utf8
from sandan_rag.config import get_config
from sandan_rag.indexer import SandanIndexer


configure_utf8()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build or update the configured RAG index.")
    parser.add_argument("--force", action="store_true", help="Re-index all current records.")
    parser.add_argument("--hard-reset", action="store_true", help="Delete vector DB, SQLite index and manifest before indexing.")
    parser.add_argument("--no-upload-files", action="store_true", help="Do not upload original files to R2/Supabase object storage.")
    args = parser.parse_args()

    config = get_config()
    print(f"[INFO] backend: {config.rag_backend}")
    print(f"[INFO] vector store: {config.vector_store_label}")
    print(f"[INFO] file storage: {config.storage_label}")

    indexer = SandanIndexer(config)
    if args.hard_reset:
        indexer.hard_reset_all()
        indexer = SandanIndexer(config)

    stats = indexer.build_or_update(
        force=args.force or args.hard_reset,
        upload_files=not args.no_upload_files,
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    if stats.get("records_total", 0) == 0:
        print("[WARN] No records were indexed. Run scripts/collect_data.py first.")


if __name__ == "__main__":
    main()
