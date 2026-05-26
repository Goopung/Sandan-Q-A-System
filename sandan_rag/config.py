import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .bootstrap import project_root


ROOT = project_root()
load_dotenv(ROOT / ".env")
load_dotenv()


SESSION_SETTING_KEYS = {
    "OPENAI_API_KEY": ["runtime_openai_api_key"],
    "OPENAI_CHAT_MODEL": ["runtime_chat_model"],
    "OPENAI_MODEL": ["runtime_chat_model"],
    "OPENAI_EMBEDDING_MODEL": ["runtime_embedding_model"],
    "EMBEDDING_MODEL": ["runtime_embedding_model"],
}


def get_setting(name: str, default: str = "") -> str:
    """Read runtime Streamlit settings first, then Streamlit secrets, then environment variables.

    Empty strings are treated as missing values. This prevents `.env` lines such as
    `OPENAI_CHAT_MODEL=` from overriding the real default model with an empty value.
    """
    try:
        import streamlit as st

        for session_key in SESSION_SETTING_KEYS.get(name, []):
            value: Any = st.session_state.get(session_key, "")
            if value is not None and str(value).strip():
                return str(value).strip()

        value = st.secrets.get(name, "")
        if value is not None and str(value).strip():
            return str(value).strip()
    except Exception:
        pass

    value = os.getenv(name, "")
    if value is not None and str(value).strip():
        return str(value).strip()
    return default


def _path_from_env(name: str, default: str) -> Path:
    value = get_setting(name, default)
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    return path


def _int_from_env(name: str, default: int) -> int:
    try:
        return int(get_setting(name, str(default)))
    except ValueError:
        return default


def _bool_from_env(name: str, default: bool = False) -> bool:
    value = get_setting(name, "1" if default else "0").strip().lower()
    return value in {"1", "true", "yes", "y", "on"}


def _normalize_backend(value: str) -> str:
    value = (value or "local").strip().lower().replace("-", "_")
    aliases = {
        "": "local",
        "chroma": "local",
        "chromadb": "local",
        "local_chroma": "local",
        "lance": "lancedb",
        "lance_db": "lancedb",
        "qdrant_cloud": "qdrant",
        "supabase_pgvector": "supabase",
    }
    return aliases.get(value, value)


@dataclass
class AppConfig:
    project_root: Path = ROOT

    # local data and index paths
    base_dir: Path = field(default_factory=lambda: _path_from_env("SANDAN_BASE_DIR", "data/sandan_attachment_kb"))
    chroma_dir: Path = field(default_factory=lambda: _path_from_env("SANDAN_CHROMA_DIR", "data/sandan_chroma"))
    sqlite_path: Path = field(default_factory=lambda: _path_from_env("SANDAN_SQLITE_PATH", "data/sandan_chunks.sqlite3"))
    collection_state_path: Path = field(default_factory=lambda: _path_from_env("SANDAN_STATE_DB_PATH", "data/sandan_collection_state.sqlite3"))
    manifest_path: Path = field(default_factory=lambda: _path_from_env("SANDAN_INDEX_MANIFEST", "data/sandan_index_manifest.json"))
    collection_name: str = field(default_factory=lambda: get_setting("SANDAN_COLLECTION_NAME", "sandan_attachments"))

    # backend: local, lancedb, qdrant, supabase
    rag_backend: str = field(default_factory=lambda: _normalize_backend(get_setting("SANDAN_RAG_BACKEND", "local")))

    # OpenAI
    embedding_model: str = field(
        default_factory=lambda: get_setting(
            "OPENAI_EMBEDDING_MODEL",
            get_setting("EMBEDDING_MODEL", "text-embedding-3-small"),
        )
    )
    chat_model: str = field(
        default_factory=lambda: get_setting(
            "OPENAI_CHAT_MODEL",
            get_setting("OPENAI_MODEL", "gpt-4.1-mini"),
        )
    )

    # LanceDB backend
    lancedb_path: Path = field(default_factory=lambda: _path_from_env("LANCEDB_PATH", "data/lancedb"))
    lancedb_table_name: str = field(default_factory=lambda: get_setting("LANCEDB_TABLE_NAME", get_setting("SANDAN_COLLECTION_NAME", "sandan_attachments")))

    # Qdrant backend
    qdrant_url: str = field(default_factory=lambda: get_setting("QDRANT_URL", ""))
    qdrant_api_key: str = field(default_factory=lambda: get_setting("QDRANT_API_KEY", ""))
    qdrant_collection_name: str = field(default_factory=lambda: get_setting("QDRANT_COLLECTION_NAME", get_setting("SANDAN_COLLECTION_NAME", "sandan_attachments")))
    qdrant_prefer_grpc: bool = field(default_factory=lambda: _bool_from_env("QDRANT_PREFER_GRPC", False))
    qdrant_timeout: int = field(default_factory=lambda: _int_from_env("QDRANT_TIMEOUT", 60))

    # Cloudflare R2 object storage. R2 is used for original files only.
    r2_account_id: str = field(default_factory=lambda: get_setting("R2_ACCOUNT_ID", ""))
    r2_access_key_id: str = field(default_factory=lambda: get_setting("R2_ACCESS_KEY_ID", ""))
    r2_secret_access_key: str = field(default_factory=lambda: get_setting("R2_SECRET_ACCESS_KEY", ""))
    r2_bucket_name: str = field(default_factory=lambda: get_setting("R2_BUCKET_NAME", get_setting("R2_BUCKET", "")))
    r2_endpoint_url: str = field(default_factory=lambda: get_setting("R2_ENDPOINT_URL", ""))
    r2_public_base_url: str = field(default_factory=lambda: get_setting("R2_PUBLIC_BASE_URL", ""))
    r2_signed_url_seconds: int = field(default_factory=lambda: _int_from_env("R2_SIGNED_URL_SECONDS", 3600))
    object_storage: str = field(default_factory=lambda: get_setting("SANDAN_OBJECT_STORAGE", "r2").strip().lower())

    # Supabase legacy backend
    supabase_url: str = field(default_factory=lambda: get_setting("SUPABASE_URL", ""))
    supabase_key: str = field(default_factory=lambda: get_setting("SUPABASE_SERVICE_ROLE_KEY", get_setting("SUPABASE_KEY", get_setting("SUPABASE_ANON_KEY", ""))))
    supabase_bucket: str = field(default_factory=lambda: get_setting("SUPABASE_BUCKET", "sandan-files"))
    supabase_signed_url_seconds: int = field(default_factory=lambda: _int_from_env("SUPABASE_SIGNED_URL_SECONDS", 3600))

    # RAG controls
    chunk_tokens: int = field(default_factory=lambda: _int_from_env("SANDAN_CHUNK_TOKENS", 900))
    chunk_overlap: int = field(default_factory=lambda: _int_from_env("SANDAN_CHUNK_OVERLAP", 160))
    embedding_batch_size: int = field(default_factory=lambda: _int_from_env("SANDAN_EMBEDDING_BATCH_SIZE", 64))
    vector_top_k: int = field(default_factory=lambda: _int_from_env("SANDAN_VECTOR_TOP_K", 40))
    keyword_top_k: int = field(default_factory=lambda: _int_from_env("SANDAN_KEYWORD_TOP_K", 40))
    final_top_k: int = field(default_factory=lambda: _int_from_env("SANDAN_FINAL_TOP_K", 10))
    max_context_chars: int = field(default_factory=lambda: _int_from_env("SANDAN_MAX_CONTEXT_CHARS", 24000))

    # deployment controls
    enable_update_dialog: bool = field(default_factory=lambda: _bool_from_env("SANDAN_ENABLE_UPDATE_DIALOG", True))

    @property
    def records_jsonl(self) -> Path:
        return self.base_dir / "sandan_attachment_records.jsonl"

    @property
    def records_csv(self) -> Path:
        return self.base_dir / "sandan_attachment_records.csv"

    @property
    def data_dir(self) -> Path:
        return self.project_root / "data"

    @property
    def use_supabase(self) -> bool:
        return self.rag_backend == "supabase"

    @property
    def use_lancedb(self) -> bool:
        return self.rag_backend == "lancedb"

    @property
    def use_qdrant(self) -> bool:
        return self.rag_backend == "qdrant"

    @property
    def use_local_chroma(self) -> bool:
        return self.rag_backend == "local"

    @property
    def use_r2(self) -> bool:
        if self.object_storage not in {"r2", "cloudflare_r2", "cloudflare"}:
            return False
        return bool(self.r2_bucket_name and self.r2_access_key_id and self.r2_secret_access_key and self.r2_endpoint)

    @property
    def r2_endpoint(self) -> str:
        if self.r2_endpoint_url:
            return self.r2_endpoint_url.rstrip("/")
        if self.r2_account_id:
            return f"https://{self.r2_account_id}.r2.cloudflarestorage.com"
        return ""

    @property
    def vector_store_label(self) -> str:
        labels = {
            "local": "Chroma + SQLite FTS",
            "lancedb": "LanceDB + SQLite FTS",
            "qdrant": "Qdrant + optional SQLite FTS",
            "supabase": "Supabase pgvector",
        }
        return labels.get(self.rag_backend, self.rag_backend)

    @property
    def storage_label(self) -> str:
        if self.use_r2:
            return "Cloudflare R2"
        if self.use_supabase:
            return "Supabase Storage"
        return "Local files"

    @property
    def backend_label(self) -> str:
        return f"{self.vector_store_label} / {self.storage_label}"

    def ensure_dirs(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.chroma_dir.mkdir(parents=True, exist_ok=True)
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self.collection_state_path.parent.mkdir(parents=True, exist_ok=True)
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.lancedb_path.mkdir(parents=True, exist_ok=True)


def get_config() -> AppConfig:
    config = AppConfig()
    config.ensure_dirs()
    return config
