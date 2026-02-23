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

DIRECT_ANSWER_PROMPT = """당신은 뉴스레터 검색 어시스턴트입니다.
현재 질문은 뉴스레터 검색이 필요하지 않습니다.
친절하고 자연스럽게 한국어로 답변하세요.
뉴스레터에 대한 질문이 있으면 언제든 물어봐달라고 안내하세요."""

STRUCTURED_SYSTEM_PROMPT = """당신은 뉴스레터 지식 검색 어시스턴트입니다.
제공된 뉴스레터 문서는 주제/관점별로 구분되어 있습니다.
각 섹션의 문서를 활용하여 질문에 답변하세요.
답변 시 반드시 출처 번호를 [1], [2] 형식으로 인용하여 답변하세요.
문서에 없는 내용은 '관련 뉴스레터를 찾지 못했습니다'라고 답하세요.
한국어로 답변하세요.
{aggregation_instruction}"""


def format_date(date_value: Any) -> str:
    """날짜를 읽기 쉬운 형식으로 변환"""
    if not date_value:
        return ""
    date_str = str(date_value)
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


def _build_structured_context(
    per_subquery_chunks: dict[str, list[dict[str, Any]]],
) -> tuple[str, list[dict[str, Any]]]:
    """
    서브쿼리별로 섹션을 나눈 컨텍스트 + 전체 소스 리스트 생성

    Returns:
        (context_str, all_chunks_ordered)
    """
    context_parts = []
    all_chunks: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    doc_index = 1

    for purpose, chunks in per_subquery_chunks.items():
        if not chunks:
            continue

        section_parts = [f"\n=== {purpose} ==="]
        for chunk in chunks:
            # chroma_id 기준 중복 청크 skip
            cid = chunk.get("chroma_id")
            if cid and cid in seen_ids:
                continue
            if cid:
                seen_ids.add(cid)

            subject = chunk.get("subject", "Unknown")
            from_addr = chunk.get("from_address", "")
            date = format_date(chunk.get("received_at"))

            header = f"[문서 {doc_index}] {subject}"
            if from_addr:
                header += f" ({from_addr}"
                if date:
                    header += f", {date}"
                header += ")"
            elif date:
                header += f" ({date})"

            section_parts.append(f"{header}\n{chunk['content']}")
            all_chunks.append(chunk)
            doc_index += 1

        if len(section_parts) > 1:  # 헤더 외 내용이 있을 때만 섹션 추가
            context_parts.append("\n\n".join(section_parts))

    return "\n\n---\n\n".join(context_parts), all_chunks


def _format_history_for_answer(
    history: list[dict] | None,
    max_assistant_chars: int = 300,
) -> list[dict[str, str]]:
    """대화 히스토리를 OpenAI messages 형식으로 변환"""
    if not history:
        return []

    messages = []
    for msg in history:
        content = msg["content"]
        if msg["role"] == "assistant" and len(content) > max_assistant_chars:
            content = content[:max_assistant_chars] + "..."
        messages.append({"role": msg["role"], "content": content})
    return messages


@with_retry(max_retries=3, base_delay=1.0, exceptions=(Exception,))
def generate_answer(
    query: str,
    chunks: list[dict[str, Any]],
    conversation_history: list[dict] | None = None,
) -> dict[str, Any]:
    """
    OpenAI Chat Completions API를 사용하여 답변 생성

    Args:
        query: 사용자 질문
        chunks: 검색된 청크 리스트
        conversation_history: 이전 대화 히스토리

    Returns:
        {content: 응답 텍스트, sources: 사용된 소스 리스트}
    """
    if not chunks:
        return {
            "content": "관련 뉴스레터를 찾지 못했습니다.",
            "sources": []
        }

    context = _build_context(chunks)
    history_messages = _format_history_for_answer(conversation_history)

    logger.info(f"Calling OpenAI with {len(chunks)} documents, {len(history_messages)} history messages")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *history_messages,
        {"role": "user", "content": f"다음은 검색된 뉴스레터 문서입니다:\n\n{context}\n\n질문: {query}"},
    ]

    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=messages,
    )

    answer_text = response.choices[0].message.content

    return {
        "content": answer_text,
        "sources": chunks
    }


@with_retry(max_retries=3, base_delay=1.0, exceptions=(Exception,))
def generate_structured_answer(
    query: str,
    per_subquery_chunks: dict[str, list[dict[str, Any]]],
    aggregation_instruction: str | None = None,
    conversation_history: list[dict] | None = None,
) -> dict[str, Any]:
    """
    서브쿼리별 구조화된 컨텍스트로 답변 생성 (복합 질문용)

    Args:
        query: 사용자 질문
        per_subquery_chunks: 서브쿼리 purpose별 청크 리스트
        aggregation_instruction: 결과 종합 방법 지시
        conversation_history: 이전 대화 히스토리

    Returns:
        {content: 응답 텍스트, sources: 전체 소스 리스트}
    """
    context, all_chunks = _build_structured_context(per_subquery_chunks)

    if not all_chunks:
        return {
            "content": "관련 뉴스레터를 찾지 못했습니다.",
            "sources": []
        }

    agg_text = ""
    if aggregation_instruction:
        agg_text = f"\n\n종합 지시: {aggregation_instruction}"

    system_prompt = STRUCTURED_SYSTEM_PROMPT.format(
        aggregation_instruction=agg_text,
    )

    history_messages = _format_history_for_answer(conversation_history)

    logger.info(
        f"Calling OpenAI (structured) with {len(all_chunks)} documents, "
        f"{len(per_subquery_chunks)} sections"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        *history_messages,
        {"role": "user", "content": f"다음은 주제별로 구분된 뉴스레터 문서입니다:\n\n{context}\n\n질문: {query}"},
    ]

    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=messages,
    )

    answer_text = response.choices[0].message.content

    return {
        "content": answer_text,
        "sources": all_chunks,
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


@with_retry(max_retries=3, base_delay=1.0, exceptions=(Exception,))
def generate_direct_answer(
    query: str,
    conversation_history: list[dict] | None = None,
) -> dict[str, Any]:
    """
    검색 없이 직접 답변 (인사말, 시스템 질문 등)

    Args:
        query: 사용자 질문
        conversation_history: 이전 대화 히스토리

    Returns:
        {content: 응답 텍스트, sources: []}
    """
    logger.info(f"Generating direct answer for: {query[:50]}...")

    history_messages = _format_history_for_answer(conversation_history)

    messages = [
        {"role": "system", "content": DIRECT_ANSWER_PROMPT},
        *history_messages,
        {"role": "user", "content": query},
    ]

    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=512,
        messages=messages,
    )

    return {
        "content": response.choices[0].message.content,
        "sources": []
    }
