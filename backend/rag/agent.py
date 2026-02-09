import logging
from typing import Any
from openai import OpenAI

from config import settings
from utils import with_retry

logger = logging.getLogger(__name__)

# OpenAI 클라이언트
client = OpenAI(api_key=settings.OPENAI_API_KEY)

# 모델 설정
MODEL = "gpt-4o-mini"
MAX_TOKENS = 2048

SYSTEM_PROMPT = """당신은 뉴스레터 지식 검색 어시스턴트입니다.
제공된 뉴스레터 문서를 기반으로 질문에 답변하세요.
답변 시 반드시 출처 번호를 [1], [2] 형식으로 인용하여 답변하세요.
문서에 없는 내용은 '관련 뉴스레터를 찾지 못했습니다'라고 답하세요.
한국어로 답변하세요."""


def format_date(date_value: Any) -> str:
    """날짜를 읽기 쉬운 형식으로 변환"""
    if not date_value:
        return ""
    date_str = str(date_value)
    # YYYY-MM-DD만 추출
    return date_str[:10] if len(date_str) >= 10 else date_str


def _build_context(chunks: list[dict[str, Any]]) -> str:
    """검색된 청크를 컨텍스트 문자열로 조합"""
    context_parts = []
    for i, chunk in enumerate(chunks, 1):
        subject = chunk.get("subject", "Unknown")
        from_addr = chunk.get("from_address", "")
        date = format_date(chunk.get("received_at"))

        header = f"[문서 {i}] {subject}"
        if from_addr:
            header += f" ({from_addr}"
            if date:
                header += f", {date}"
            header += ")"
        elif date:
            header += f" ({date})"

        context_parts.append(f"{header}\n{chunk['content']}")

    return "\n\n---\n\n".join(context_parts)


@with_retry(max_retries=3, base_delay=1.0, exceptions=(Exception,))
def generate_answer(query: str, chunks: list[dict[str, Any]]) -> dict[str, Any]:
    """
    OpenAI Chat Completions API를 사용하여 답변 생성

    Args:
        query: 사용자 질문
        chunks: 검색된 청크 리스트

    Returns:
        {content: 응답 텍스트, sources: 사용된 소스 리스트}
    """
    if not chunks:
        return {
            "content": "관련 뉴스레터를 찾지 못했습니다.",
            "sources": []
        }

    context = _build_context(chunks)

    logger.info(f"Calling OpenAI with {len(chunks)} documents")

    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"다음은 검색된 뉴스레터 문서입니다:\n\n{context}\n\n질문: {query}"}
        ]
    )

    answer_text = response.choices[0].message.content

    return {
        "content": answer_text,
        "sources": chunks
    }


def parse_citations_response(
    content: str,
    sources: list[dict[str, Any]]
) -> dict[str, Any]:
    """
    OpenAI 응답을 프론트엔드 표시용으로 파싱

    Args:
        content: OpenAI 응답 텍스트
        sources: 원본 소스 청크 리스트

    Returns:
        {text: 전체 답변 텍스트, citations: 인용 정보 리스트}
    """
    citations = []
    for i, source in enumerate(sources, 1):
        citations.append({
            "index": i,
            "cited_text": "",
            "document_index": i - 1,
            "source": {
                "subject": source.get("subject", "Unknown"),
                "from_address": source.get("from_address", ""),
                "received_at": format_date(source.get("received_at")),
            }
        })

    return {
        "text": content,
        "citations": citations
    }
