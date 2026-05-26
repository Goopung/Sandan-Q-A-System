import hashlib
import json
import mimetypes
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List


def clean_text(text: str) -> str:
    text = text or ""
    text = str(text)
    # PostgreSQL text fields cannot contain the NULL byte (\x00).
    # Some PDF/HWP extractors can leak it into extracted text, which later
    # causes: unsupported Unicode escape sequence: \u0000 cannot be converted to text.
    text = text.replace("\x00", " ")
    text = text.replace("\xa0", " ")
    text = text.replace("\ufeff", " ")
    # Remove non-printable control characters except newline and tab.
    text = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", text)
    # Remove invalid Unicode surrogate code points if any slipped in.
    text = re.sub(r"[\ud800-\udfff]", "", text)
    text = re.sub(r"\r\n|\r", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def sha256_short(data: bytes | str, length: int = 16) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8", errors="ignore")
    return hashlib.sha256(data).hexdigest()[:length]


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return []

    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}, line {line_no}: {exc}") from exc
    return rows


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path, default: Dict[str, Any] | None = None) -> Dict[str, Any]:
    if default is None:
        default = {}
    if not path.exists() or path.stat().st_size == 0:
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def batch_iter(items: List[Any], batch_size: int) -> Iterable[List[Any]]:
    batch_size = max(1, int(batch_size or 1))
    for start in range(0, len(items), batch_size):
        yield items[start:start + batch_size]


def safe_metadata_value(value: Any) -> str | int | float | bool:
    if value is None:
        return ""
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, (int, float, bool)):
        return value
    return clean_text(str(value))


def compact_snippet(text: str, max_chars: int = 600) -> str:
    text = clean_text(text)
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


def guess_mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
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
    if suffix in custom:
        return custom[suffix]
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def resolve_existing_path(path_text: str, project_root: Path) -> Path | None:
    if not path_text:
        return None
    raw = Path(path_text)
    candidates = [raw]
    if not raw.is_absolute():
        candidates.append(project_root / raw)
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None
