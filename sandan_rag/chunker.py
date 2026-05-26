import re
from dataclasses import dataclass
from typing import Dict, List

from .utils import clean_text, sha256_short

try:
    import tiktoken
except ImportError:
    tiktoken = None


@dataclass
class TextChunk:
    chunk_id: str
    text: str
    metadata: Dict[str, str | int | float | bool]


class TokenTextSplitter:
    def __init__(self, chunk_tokens: int = 900, chunk_overlap: int = 160):
        self.chunk_tokens = max(200, int(chunk_tokens or 900))
        self.chunk_overlap = max(0, min(int(chunk_overlap or 0), self.chunk_tokens // 2))
        self.encoding = None
        if tiktoken is not None:
            try:
                self.encoding = tiktoken.get_encoding("cl100k_base")
            except Exception:
                self.encoding = None

    def count_tokens(self, text: str) -> int:
        text = text or ""
        if not text:
            return 0
        if self.encoding is None:
            return max(1, len(text) // 3)
        return len(self.encoding.encode(text))

    def split_by_tokens(self, text: str) -> List[str]:
        text = clean_text(text)
        if not text:
            return []
        if self.encoding is None:
            return self._split_by_chars(text)

        token_ids = self.encoding.encode(text)
        if len(token_ids) <= self.chunk_tokens:
            return [text]

        chunks = []
        step = max(1, self.chunk_tokens - self.chunk_overlap)
        for start in range(0, len(token_ids), step):
            end = start + self.chunk_tokens
            chunk_ids = token_ids[start:end]
            chunk_text = clean_text(self.encoding.decode(chunk_ids))
            if chunk_text:
                chunks.append(chunk_text)
            if end >= len(token_ids):
                break
        return chunks

    def _split_by_chars(self, text: str) -> List[str]:
        approx_chunk_chars = self.chunk_tokens * 3
        approx_overlap_chars = self.chunk_overlap * 3
        step = max(1, approx_chunk_chars - approx_overlap_chars)
        chunks = []
        for start in range(0, len(text), step):
            end = start + approx_chunk_chars
            chunk = clean_text(text[start:end])
            if chunk:
                chunks.append(chunk)
            if end >= len(text):
                break
        return chunks

    def split_record(self, record: Dict, chunk_prefix: str = "chunk") -> List[TextChunk]:
        text = clean_text(record.get("rag_text", ""))
        if not text:
            return []

        sections = self._split_by_soft_sections(text)
        raw_chunks: List[str] = []
        for section in sections:
            if self.count_tokens(section) <= self.chunk_tokens:
                raw_chunks.append(section)
            else:
                raw_chunks.extend(self.split_by_tokens(section))

        merged_chunks = self._merge_small_chunks(raw_chunks)
        chunks: List[TextChunk] = []
        attachment_key = str(record.get("attachment_key", ""))
        for idx, chunk_text in enumerate(merged_chunks):
            chunk_hash = sha256_short(f"{attachment_key}|{idx}|{chunk_text}", 24)
            chunk_id = f"{chunk_prefix}_{attachment_key}_{idx:05d}_{chunk_hash}"
            metadata = {
                "attachment_key": attachment_key,
                "chunk_index": idx,
                "menu_no": record.get("menu_no", ""),
                "menu_name": record.get("menu_name", ""),
                "post_uid": record.get("post_uid", ""),
                "board_id": record.get("board_id", ""),
                "post_title": record.get("post_title", ""),
                "registered_date": str(record.get("registered_date", ""))[:10],
                "author": record.get("author", ""),
                "detail_url": record.get("detail_url", ""),
                "attachment_name": record.get("attachment_name", ""),
                "attachment_url": record.get("attachment_url", ""),
                "attachment_path": record.get("attachment_path", ""),
                "attachment_text_path": record.get("attachment_text_path", ""),
                "storage_provider": record.get("storage_provider", ""),
                "storage_bucket": record.get("storage_bucket", ""),
                "storage_path": record.get("storage_path", ""),
                "attachment_file_hash": record.get("attachment_file_hash", ""),
                "attachment_text_hash": record.get("attachment_text_hash", ""),
                "chunk_hash": sha256_short(chunk_text, 24),
                "chunk_tokens": self.count_tokens(chunk_text),
            }
            chunks.append(TextChunk(chunk_id=chunk_id, text=chunk_text, metadata=metadata))
        return chunks

    def _split_by_soft_sections(self, text: str) -> List[str]:
        parts = re.split(r"\n(?=\[[^\n\]]+\]\n)", text)
        cleaned = [clean_text(part) for part in parts if clean_text(part)]
        return cleaned or [text]

    def _merge_small_chunks(self, chunks: List[str]) -> List[str]:
        merged = []
        buffer = ""
        for chunk in chunks:
            candidate = clean_text(buffer + "\n\n" + chunk) if buffer else clean_text(chunk)
            if self.count_tokens(candidate) <= self.chunk_tokens:
                buffer = candidate
            else:
                if buffer:
                    merged.append(buffer)
                buffer = clean_text(chunk)
        if buffer:
            merged.append(buffer)
        return merged
