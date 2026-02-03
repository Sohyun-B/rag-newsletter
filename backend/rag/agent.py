import logging
from typing import Any
import anthropic

from config import settings
from utils import with_retry

logger = logging.getLogger(__name__)

# Anthropic 클라이언트
client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

# Claude 모델 설정
MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 2048

SYSTEM_PROMPT = """당신은 뉴스레터 지식 검색 어시스턴트입니다.
제공된 뉴스레터 문서를 기반으로 질문에 답변하세요.
반드시 출처를 인용하여 답변하세요.
문서에 없는 내용은 '관련 뉴스레터를 찾지 못했습니다'라고 답하세요.
한국어로 답변하세요."""


def format_date(date_value: Any) -> str:
    """날짜를 읽기 쉬운 형식으로 변환"""
    if not date_value:
        return ""
    date_str = str(date_value)
    # YYYY-MM-DD만 추출
    return date_str[:10] if len(date_str) >= 10 else date_str


@with_retry(max_retries=3, base_delay=1.0, exceptions=(anthropic.APIError, Exception))
def generate_answer(query: str, chunks: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Claude Citations API를 사용하여 답변 생성

    Args:
        query: 사용자 질문
        chunks: 검색된 청크 리스트

    Returns:
        {content: API 응답 content, sources: 사용된 소스 리스트}
    """
    if not chunks:
        # 검색 결과가 없는 경우
        return {
            "content": [{"type": "text", "text": "관련 뉴스레터를 찾지 못했습니다."}],
            "sources": []
        }

    # 검색된 청크를 Claude document 형태로 변환
    content = []

    for i, chunk in enumerate(chunks):
        # 문서 제목 생성
        subject = chunk.get("subject", "Unknown")
        from_addr = chunk.get("from_address", "")
        date = format_date(chunk.get("received_at"))

        title = f"{subject}"
        if from_addr:
            title += f" ({from_addr}"
            if date:
                title += f", {date}"
            title += ")"
        elif date:
            title += f" ({date})"

        content.append({
            "type": "document",
            "source": {
                "type": "text",
                "media_type": "text/plain",
                "data": chunk["content"],
            },
            "title": title,
            "citations": {"enabled": True}
        })

    # 사용자 질문 추가
    content.append({
        "type": "text",
        "text": query
    })

    logger.info(f"Calling Claude with {len(chunks)} documents")

    # Claude API 호출
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": content
        }]
    )

    return {
        "content": response.content,
        "sources": chunks
    }


def parse_citations_response(
    content_blocks: list,
    sources: list[dict[str, Any]]
) -> dict[str, Any]:
    """
    Claude Citations API 응답을 프론트엔드 표시용으로 파싱

    Args:
        content_blocks: Claude API 응답의 content 필드
        sources: 원본 소스 청크 리스트

    Returns:
        {text: 전체 답변 텍스트, citations: 인용 정보 리스트}
    """
    full_text = ""
    citations = []
    citation_counter = 0

    for block in content_blocks:
        # text 블록인 경우
        if hasattr(block, "type") and block.type == "text":
            text = block.text

            # citations 속성이 있는 경우
            if hasattr(block, "citations") and block.citations:
                citation_indices = []

                for citation in block.citations:
                    citation_counter += 1
                    doc_idx = citation.document_index

                    # 소스 정보 가져오기
                    source = sources[doc_idx] if doc_idx < len(sources) else None

                    citations.append({
                        "index": citation_counter,
                        "cited_text": citation.cited_text,
                        "document_index": doc_idx,
                        "source": {
                            "subject": source.get("subject", "Unknown") if source else "Unknown",
                            "from_address": source.get("from_address", "") if source else "",
                            "received_at": format_date(source.get("received_at")) if source else "",
                        } if source else None
                    })

                    citation_indices.append(str(citation_counter))

                # 인용 번호 추가
                if citation_indices:
                    text += f" [{','.join(citation_indices)}]"

            full_text += text

    return {
        "text": full_text,
        "citations": citations
    }
