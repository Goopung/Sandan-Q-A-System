from __future__ import annotations

import mimetypes
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from supabase import Client, create_client

from .config import AppConfig, get_config
from .utils import clean_text


_client: Client | None = None


def reset_supabase_client() -> None:
    global _client
    _client = None


def get_supabase_client(config: AppConfig | None = None) -> Client:
    global _client
    config = config or get_config()
    if _client is None:
        if not config.supabase_url or not config.supabase_key:
            raise RuntimeError("SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY is not set.")
        _client = create_client(config.supabase_url, config.supabase_key)
    return _client


def guess_content_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def sanitize_pg_value(value: Any) -> Any:
    """Sanitize values before sending them to PostgreSQL/PostgREST.

    PostgreSQL text cannot store the NULL byte (\x00). Some extracted
    PDFs/HWPs include it in the middle of text. If it reaches Supabase,
    PostgREST raises: "\u0000 cannot be converted to text".
    """
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, list):
        return [sanitize_pg_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): sanitize_pg_value(item) for key, item in value.items()}
    return value


def sanitize_pg_row(row: Dict[str, Any]) -> Dict[str, Any]:
    cleaned = sanitize_pg_value(row)
    if not isinstance(cleaned, dict):
        return {}
    return cleaned


def safe_storage_component(value: str, default: str = "unknown", max_len: int = 80) -> str:
    """Return an ASCII-only component that is safe for Supabase Storage object keys."""
    value = str(value or "").strip()
    if not value:
        value = default

    value = value.replace("\\", "_").replace("/", "_")
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("._-")

    if not value:
        value = default

    return value[:max_len]


def safe_storage_extension(name: str, local_path: str | Path | None = None) -> str:
    candidates = []
    if local_path:
        candidates.append(Path(local_path).suffix)
    candidates.append(Path(str(name or "")).suffix)

    for suffix in candidates:
        suffix = str(suffix or "").lower().strip()
        if suffix and re.fullmatch(r"\.[a-z0-9]{1,10}", suffix):
            return suffix

    return ".bin"


def storage_path_for_record(record: Dict[str, Any]) -> str:
    """Build a Supabase Storage path without Korean/spaces/parentheses.

    Supabase Storage can reject object keys containing some Unicode or special
    characters. Keep the readable original filename in documents.attachment_name,
    but use a stable ASCII-only object key for storage.
    """
    menu_no = safe_storage_component(record.get("menu_no", "unknown"), "unknown", 40)
    board_id = safe_storage_component(record.get("board_id", "unknown"), "unknown", 40)
    attachment_key = safe_storage_component(record.get("attachment_key", "file"), "file", 80)
    attachment_name = str(record.get("attachment_name", "attachment.bin") or "attachment.bin")
    local_path = record.get("attachment_path", "")
    suffix = safe_storage_extension(attachment_name, local_path)
    return f"{menu_no}/{board_id}/{attachment_key}{suffix}"


def upload_file_to_storage(local_path: str | Path, storage_path: str, config: AppConfig | None = None) -> str:
    config = config or get_config()
    client = get_supabase_client(config)
    path = Path(local_path)
    if not path.exists() or not path.is_file():
        return ""

    data = path.read_bytes()
    content_type = guess_content_type(path)
    bucket = config.supabase_bucket

    # supabase-py has had small signature differences across versions, so try the common forms.
    try:
        client.storage.from_(bucket).upload(
            path=storage_path,
            file=data,
            file_options={"content-type": content_type, "upsert": "true"},
        )
    except TypeError:
        try:
            client.storage.from_(bucket).upload(
                storage_path,
                data,
                file_options={"content-type": content_type, "upsert": "true"},
            )
        except Exception:
            client.storage.from_(bucket).update(storage_path, data)
    except Exception:
        try:
            client.storage.from_(bucket).update(storage_path, data)
        except Exception:
            # final retry without explicit upsert option
            client.storage.from_(bucket).upload(storage_path, data)

    return storage_path


def create_signed_url(storage_path: str, expires_in: int | None = None, config: AppConfig | None = None) -> str:
    config = config or get_config()
    if not storage_path:
        return ""
    client = get_supabase_client(config)
    expires = int(expires_in or config.supabase_signed_url_seconds)
    result = client.storage.from_(config.supabase_bucket).create_signed_url(storage_path, expires)

    if isinstance(result, dict):
        data = result.get("data") if isinstance(result.get("data"), dict) else result
        return data.get("signedURL") or data.get("signedUrl") or data.get("signed_url") or ""
    try:
        return str(result.signed_url)
    except Exception:
        return ""


def get_document_by_attachment_key(attachment_key: str, config: AppConfig | None = None) -> Optional[Dict[str, Any]]:
    client = get_supabase_client(config)
    result = (
        client.table("documents")
        .select("*")
        .eq("attachment_key", attachment_key)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def count_chunks_by_attachment_key(attachment_key: str, config: AppConfig | None = None) -> int:
    client = get_supabase_client(config)
    result = (
        client.table("chunks")
        .select("id", count="exact")
        .eq("attachment_key", attachment_key)
        .limit(1)
        .execute()
    )
    try:
        return int(result.count or 0)
    except Exception:
        return 0


def _without_storage_provider(row: Dict[str, Any]) -> Dict[str, Any]:
    cleaned = dict(row)
    cleaned.pop("storage_provider", None)
    return cleaned


def _looks_like_missing_storage_provider_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "storage_provider" in message and ("column" in message or "schema" in message or "could not find" in message)


def upsert_document(record: Dict[str, Any], storage_path: str, config: AppConfig | None = None) -> str:
    config = config or get_config()
    client = get_supabase_client(config)

    storage_provider = str(record.get("storage_provider", "") or "")
    if not storage_provider:
        storage_provider = "r2" if config.use_r2 else "supabase"

    storage_bucket = str(record.get("storage_bucket", "") or "")
    if not storage_bucket:
        storage_bucket = config.r2_bucket_name if storage_provider == "r2" else config.supabase_bucket

    payload = {
        "attachment_key": record.get("attachment_key", ""),
        "menu_no": record.get("menu_no", ""),
        "menu_name": record.get("menu_name", ""),
        "board_id": record.get("board_id", ""),
        "post_title": record.get("post_title", ""),
        "registered_date": str(record.get("registered_date", ""))[:10],
        "author": record.get("author", ""),
        "detail_url": record.get("detail_url", ""),
        "attachment_name": record.get("attachment_name", ""),
        "attachment_url": record.get("attachment_url", ""),
        "storage_provider": storage_provider,
        "storage_bucket": storage_bucket,
        "storage_path": storage_path,
        "file_hash": record.get("attachment_file_hash", ""),
        "text_hash": record.get("attachment_text_hash", ""),
        "text_chars": int(record.get("attachment_text_chars", 0) or 0),
        "rag_text_chars": int(record.get("rag_text_chars", 0) or 0),
    }

    payload = sanitize_pg_row(payload)
    try:
        result = client.table("documents").upsert(payload, on_conflict="attachment_key").execute()
    except Exception as exc:
        if not _looks_like_missing_storage_provider_error(exc):
            raise
        result = client.table("documents").upsert(_without_storage_provider(payload), on_conflict="attachment_key").execute()

    rows = result.data or []
    if rows and rows[0].get("id"):
        return rows[0]["id"]

    existing = get_document_by_attachment_key(str(record.get("attachment_key", "")), config)
    if not existing:
        raise RuntimeError(f"document upsert failed: {record.get('attachment_key', '')}")
    return existing["id"]


def delete_old_chunks(attachment_key: str, config: AppConfig | None = None) -> None:
    if not attachment_key:
        return
    client = get_supabase_client(config)
    client.table("chunks").delete().eq("attachment_key", attachment_key).execute()


def insert_chunks(rows: List[Dict[str, Any]], config: AppConfig | None = None, batch_size: int = 100) -> None:
    if not rows:
        return

    sanitized_rows: List[Dict[str, Any]] = []
    for row in rows:
        cleaned = sanitize_pg_row(row)
        chunk_text = str(cleaned.get("chunk_text", "") or "").strip()
        if not chunk_text:
            continue
        cleaned["chunk_text"] = chunk_text
        sanitized_rows.append(cleaned)

    if not sanitized_rows:
        return

    client = get_supabase_client(config)
    for start in range(0, len(sanitized_rows), batch_size):
        batch = sanitized_rows[start:start + batch_size]
        try:
            client.table("chunks").upsert(batch, on_conflict="chunk_id").execute()
        except Exception as exc:
            if not _looks_like_missing_storage_provider_error(exc):
                raise
            fallback_batch = [_without_storage_provider(row) for row in batch]
            client.table("chunks").upsert(fallback_batch, on_conflict="chunk_id").execute()


def count_documents(config: AppConfig | None = None) -> int:
    client = get_supabase_client(config)
    result = client.table("documents").select("id", count="exact").limit(1).execute()
    return int(result.count or 0)


def count_chunks(config: AppConfig | None = None) -> int:
    client = get_supabase_client(config)
    result = client.table("chunks").select("id", count="exact").limit(1).execute()
    return int(result.count or 0)


def list_menu_names(config: AppConfig | None = None) -> List[str]:
    client = get_supabase_client(config)
    result = client.table("documents").select("menu_name").execute()
    values = sorted({row.get("menu_name", "") for row in (result.data or []) if row.get("menu_name")})
    return values


def create_update_run(status: str = "running", config: AppConfig | None = None) -> str:
    client = get_supabase_client(config)
    result = client.table("update_runs").insert({"status": status}).execute()
    rows = result.data or []
    return rows[0]["id"] if rows else ""


def finish_update_run(run_id: str, status: str, total_documents: int, total_chunks: int, error_message: str = "", config: AppConfig | None = None) -> None:
    if not run_id:
        return
    client = get_supabase_client(config)
    client.table("update_runs").update(
        {
            "status": status,
            "total_documents": int(total_documents),
            "total_chunks": int(total_chunks),
            "error_message": error_message,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", run_id).execute()
