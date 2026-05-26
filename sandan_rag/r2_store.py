from __future__ import annotations

import mimetypes
import re
from pathlib import Path
from typing import Any, Dict
from urllib.parse import quote

from .config import AppConfig, get_config


_client = None


def reset_r2_client() -> None:
    global _client
    _client = None


def safe_storage_component(value: str, default: str = "unknown", max_len: int = 80) -> str:
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
    menu_no = safe_storage_component(record.get("menu_no", "unknown"), "unknown", 40)
    board_id = safe_storage_component(record.get("board_id", "unknown"), "unknown", 40)
    attachment_key = safe_storage_component(record.get("attachment_key", "file"), "file", 90)
    attachment_name = str(record.get("attachment_name", "attachment.bin") or "attachment.bin")
    local_path = record.get("attachment_path", "")
    suffix = safe_storage_extension(attachment_name, local_path)
    return f"{menu_no}/{board_id}/{attachment_key}{suffix}"


def guess_content_type(path: Path) -> str:
    custom = {
        ".hwp": "application/x-hwp",
        ".hwpx": "application/vnd.hancom.hwpx",
        ".ppt": "application/vnd.ms-powerpoint",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".zip": "application/zip",
        ".pdf": "application/pdf",
    }
    suffix = path.suffix.lower()
    if suffix in custom:
        return custom[suffix]
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def get_r2_client(config: AppConfig | None = None):
    global _client
    config = config or get_config()
    if _client is not None:
        return _client

    if not config.r2_bucket_name:
        raise RuntimeError("R2_BUCKET_NAME is not set.")
    if not config.r2_endpoint:
        raise RuntimeError("R2_ENDPOINT_URL or R2_ACCOUNT_ID is not set.")
    if not config.r2_access_key_id or not config.r2_secret_access_key:
        raise RuntimeError("R2_ACCESS_KEY_ID or R2_SECRET_ACCESS_KEY is not set.")

    import boto3
    from botocore.config import Config

    _client = boto3.client(
        "s3",
        endpoint_url=config.r2_endpoint,
        aws_access_key_id=config.r2_access_key_id,
        aws_secret_access_key=config.r2_secret_access_key,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )
    return _client


def upload_file_to_r2(local_path: str | Path, storage_path: str, config: AppConfig | None = None) -> str:
    config = config or get_config()
    path = Path(local_path)
    if not path.exists() or not path.is_file():
        return ""

    client = get_r2_client(config)
    content_type = guess_content_type(path)
    with path.open("rb") as file_obj:
        client.upload_fileobj(
            file_obj,
            config.r2_bucket_name,
            storage_path,
            ExtraArgs={"ContentType": content_type},
        )
    return storage_path


def create_presigned_url(storage_path: str, expires_in: int | None = None, config: AppConfig | None = None) -> str:
    config = config or get_config()
    storage_path = str(storage_path or "").strip()
    if not storage_path:
        return ""

    if config.r2_public_base_url:
        return f"{config.r2_public_base_url.rstrip('/')}/{quote(storage_path, safe='/')}"

    client = get_r2_client(config)
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": config.r2_bucket_name, "Key": storage_path},
        ExpiresIn=int(expires_in or config.r2_signed_url_seconds),
    )
