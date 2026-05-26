from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from .config import AppConfig, get_config


def storage_path_for_record(record: Dict[str, Any], config: AppConfig | None = None) -> str:
    config = config or get_config()
    if config.use_r2:
        from .r2_store import storage_path_for_record as r2_storage_path_for_record

        return r2_storage_path_for_record(record)
    if config.use_supabase:
        from .supabase_store import storage_path_for_record as supabase_storage_path_for_record

        return supabase_storage_path_for_record(record)
    return ""


def upload_file_to_object_storage(local_path: str | Path, storage_path: str, config: AppConfig | None = None) -> str:
    config = config or get_config()
    if not storage_path:
        return ""
    if config.use_r2:
        from .r2_store import upload_file_to_r2

        return upload_file_to_r2(local_path, storage_path, config)
    if config.use_supabase:
        from .supabase_store import upload_file_to_storage

        return upload_file_to_storage(local_path, storage_path, config)
    return ""


def enrich_record_with_object_storage(record: Dict[str, Any], config: AppConfig | None = None, upload_files: bool = True) -> Dict[str, Any]:
    config = config or get_config()
    enriched = dict(record)

    if config.use_r2:
        storage_path = str(enriched.get("storage_path", "") or "")
        local_path = str(enriched.get("attachment_path", "") or "")
        if not storage_path:
            storage_path = storage_path_for_record(enriched, config)
        if upload_files and local_path and Path(local_path).exists():
            upload_file_to_object_storage(local_path, storage_path, config)
        enriched["storage_provider"] = "r2"
        enriched["storage_bucket"] = config.r2_bucket_name
        enriched["storage_path"] = storage_path
    elif config.use_supabase:
        enriched.setdefault("storage_provider", "supabase")
        enriched.setdefault("storage_bucket", config.supabase_bucket)
    else:
        enriched.setdefault("storage_provider", "local")
        enriched.setdefault("storage_bucket", "")
        enriched.setdefault("storage_path", "")

    return enriched


def create_download_url(storage_provider: str, storage_path: str, config: AppConfig | None = None) -> str:
    config = config or get_config()
    provider = (storage_provider or "").strip().lower()
    if not provider and config.use_r2:
        provider = "r2"
    if not storage_path:
        return ""
    if provider == "r2":
        from .r2_store import create_presigned_url

        return create_presigned_url(storage_path, config=config)
    if provider == "supabase":
        from .supabase_store import create_signed_url

        return create_signed_url(storage_path, config=config)
    return ""
