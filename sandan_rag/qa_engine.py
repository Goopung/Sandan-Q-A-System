from typing import Dict, List

from .config import AppConfig, get_config
from .openai_utils import chat_complete
from .utils import clean_text, compact_snippet


def build_retriever(config: AppConfig):
    if config.use_supabase:
        from .supabase_retriever import SupabaseRetriever

        return SupabaseRetriever(config)

    if config.use_lancedb:
        from .lancedb_retriever import LanceDBRetriever

        return LanceDBRetriever(config)

    if config.use_qdrant:
        from .qdrant_retriever import QdrantRetriever

        return QdrantRetriever(config)

    from .retriever import HybridRetriever

    return HybridRetriever(config)


class SandanQAEngine:
    def __init__(self, config: AppConfig | None = None):
        self.config = config or get_config()
        self.retriever = build_retriever(self.config)

    def answer(
        self,
        question: str,
        menu_filter: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> Dict:
        chunks = self.retriever.search(
            question,
            final_top_k=self.config.final_top_k,
            menu_filter=menu_filter,
            date_from=date_from,
            date_to=date_to,
        )
        if not chunks:
            return {
                "answer": "관련 자료를 찾지 못했습니다. 검색어를 더 구체적으로 입력하거나 게시판 범위를 전체로 변경해 주세요.",
                "sources": [],
                "chunks": [],
            }

        context = self.build_context(chunks)
        messages = [
            {
                "role": "system",
                "content": (
                    "너는 경희대학교 산학협력단 연구행정 문의 Q&A 도우미다. "
                    "반드시 제공된 자료 내용에 근거해서만 답변한다. "
                    "자료에 없는 내용은 추측하지 말고 '제공된 자료만으로는 확인하기 어렵다'고 말한다. "
                    "답변은 사용자의 질문 언어에 맞추되, 행정 용어와 문서명은 원문 표현을 유지한다. "
                    "중요한 근거 문장 뒤에는 [S1], [S2] 형식으로 출처 번호를 표시한다. "
                    "실무자가 바로 사용할 수 있도록 핵심 답변, 절차, 제출서류, 주의사항을 구분해서 정리한다."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"질문:\n{question}\n\n"
                    f"검색된 근거 자료:\n{context}\n\n"
                    "위 근거만 사용해 답변해 주세요."
                ),
            },
        ]
        answer = chat_complete(self.config.chat_model, messages, max_tokens=1800)
        return {
            "answer": answer,
            "sources": self.make_sources(chunks),
            "chunks": chunks,
        }

    def query_documents(
        self,
        query: str,
        menu_filter: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        max_docs: int = 8,
    ) -> Dict:
        chunks = self.retriever.search(
            query,
            final_top_k=max(self.config.final_top_k * 3, max_docs * 5),
            menu_filter=menu_filter,
            date_from=date_from,
            date_to=date_to,
        )
        docs = self.retriever.group_by_attachment(chunks, max_docs=max_docs)
        if not docs:
            return {"summary": "관련 자료를 찾지 못했습니다.", "documents": []}

        summary_context = self.build_document_summary_context(docs)
        messages = [
            {
                "role": "system",
                "content": (
                    "너는 산학협력단 자료 검색 도우미다. "
                    "사용자가 찾는 자료와 관련성이 높은 파일들을 매우 간단히 요약한다. "
                    "5줄 이내로 작성하고, 파일 다운로드는 아래 목록에서 제공된다고 안내한다. "
                    "근거에 없는 내용은 만들지 않는다."
                ),
            },
            {
                "role": "user",
                "content": f"사용자 검색어:\n{query}\n\n검색 결과 목록:\n{summary_context}",
            },
        ]
        summary = chat_complete(self.config.chat_model, messages, max_tokens=700)
        return {"summary": summary, "documents": docs}

    def build_context(self, chunks: List) -> str:
        parts = []
        used_chars = 0
        for idx, chunk in enumerate(chunks, start=1):
            metadata = chunk.metadata
            text = clean_text(chunk.text)
            block = (
                f"[S{idx}]\n"
                f"게시판: {metadata.get('menu_name', '')}\n"
                f"게시글 제목: {metadata.get('post_title', '')}\n"
                f"등록일: {metadata.get('registered_date', '')}\n"
                f"첨부파일: {metadata.get('attachment_name', '')}\n"
                f"게시글 URL: {metadata.get('detail_url', '')}\n"
                f"본문:\n{text}\n"
            )
            if used_chars + len(block) > self.config.max_context_chars:
                break
            parts.append(block)
            used_chars += len(block)
        return "\n\n".join(parts)

    def build_document_summary_context(self, docs: List[Dict]) -> str:
        parts = []
        for idx, doc in enumerate(docs, start=1):
            snippets = "\n".join(doc.get("snippets", [])[:2])
            parts.append(
                f"[D{idx}]\n"
                f"게시판: {doc.get('menu_name', '')}\n"
                f"게시글 제목: {doc.get('post_title', '')}\n"
                f"등록일: {doc.get('registered_date', '')}\n"
                f"첨부파일: {doc.get('attachment_name', '')}\n"
                f"내용 일부:\n{snippets}"
            )
        return "\n\n".join(parts)

    def make_sources(self, chunks: List) -> List[Dict]:
        sources = []
        for idx, chunk in enumerate(chunks, start=1):
            metadata = chunk.metadata
            sources.append(
                {
                    "source_id": f"S{idx}",
                    "menu_name": metadata.get("menu_name", ""),
                    "post_title": metadata.get("post_title", ""),
                    "registered_date": metadata.get("registered_date", ""),
                    "attachment_name": metadata.get("attachment_name", ""),
                    "detail_url": metadata.get("detail_url", ""),
                    "attachment_url": metadata.get("attachment_url", ""),
                    "attachment_path": metadata.get("attachment_path", ""),
                    "storage_provider": metadata.get("storage_provider", ""),
                    "storage_bucket": metadata.get("storage_bucket", ""),
                    "storage_path": metadata.get("storage_path", ""),
                    "snippet": compact_snippet(chunk.text, 400),
                }
            )
        return sources
