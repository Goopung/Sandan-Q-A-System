from typing import List

from openai import OpenAI

from .config import get_setting
from .utils import clean_text


_client: OpenAI | None = None


def reset_openai_client() -> None:
    global _client
    _client = None


def get_openai_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = get_setting("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set. Set it in .env or Streamlit Secrets.")
        _client = OpenAI(api_key=api_key)
    return _client


def _resolve_model(model: str, primary_key: str, fallback_key: str, default: str) -> str:
    value = (model or "").strip()
    if value:
        return value
    value = get_setting(primary_key, get_setting(fallback_key, default)).strip()
    if value:
        return value
    return default


def embed_texts(texts: List[str], model: str) -> List[List[float]]:
    cleaned = [clean_text(text or "") for text in texts if text is not None]
    if not cleaned:
        return []

    model = _resolve_model(
        model,
        primary_key="OPENAI_EMBEDDING_MODEL",
        fallback_key="EMBEDDING_MODEL",
        default="text-embedding-3-small",
    )
    client = get_openai_client()
    response = client.embeddings.create(model=model, input=cleaned)
    return [item.embedding for item in response.data]


def chat_complete(model: str, messages: List[dict], max_tokens: int = 1400) -> str:
    model = _resolve_model(
        model,
        primary_key="OPENAI_CHAT_MODEL",
        fallback_key="OPENAI_MODEL",
        default="gpt-4.1-mini",
    )
    client = get_openai_client()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
        )
    except Exception as exc:
        message = str(exc).lower()
        if "max_tokens" in message and "max_completion_tokens" in message:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_completion_tokens=max_tokens,
            )
        else:
            raise
    return response.choices[0].message.content or ""
