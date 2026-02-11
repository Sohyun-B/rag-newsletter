import logging
from datetime import date
from typing import Any

from vectorstore import search_similar, search_similar_filtered
from db import get_chunks_by_chroma_ids, get_email_ids_by_filters
from etl import embed_chunks

logger = logging.getLogger(__name__)


async def search_similar_chunks(
    query: str,
    hypothetical_doc: str | None = None,
    multi_queries: list[str] | None = None,
    top_k: int = 10,
    score_threshold: float = 0.3,
    date_from: date | None = None,
    date_to: date | None = None,
    sender: str | None = None,
) -> list[dict[str, Any]]:
    """
    쿼리와 유사한 청크 검색 (HyDE + Multi-Query 지원)

    Args:
        query: 검색 쿼리 (rewritten_query 권장)
        hypothetical_doc: HyDE 가상 답변 문서 (있으면 임베딩하여 검색에 사용)
        multi_queries: 다중 검색 쿼리 변형 리스트
        top_k: 반환할 최대 결과 수
        score_threshold: 최소 유사도 점수 (0~1)
        date_from: 시작 날짜 필터
        date_to: 종료 날짜 필터
        sender: 발신인 필터

    Returns:
        검색된 청크 리스트 (메타데이터 포함)
    """
    logger.info(f"Searching for: {query[:50]}...")

    has_filters = date_from or date_to or sender
    email_ids = None

    # 1. 필터가 있으면 MSSQL에서 email_ids 먼저 조회
    if has_filters:
        email_ids = get_email_ids_by_filters(
            date_from=date_from,
            date_to=date_to,
            sender=sender,
        )
        logger.info(f"Filter matched {len(email_ids)} emails")
        if not email_ids:
            logger.info("No emails match filter, falling back to unfiltered search")
            has_filters = False
            email_ids = None

    # 2. 검색할 텍스트 수집
    texts_to_embed = []
    if hypothetical_doc:
        texts_to_embed.append(hypothetical_doc)
    if multi_queries:
        texts_to_embed.extend(multi_queries)
    # 항상 원본 쿼리도 포함 (fallback 겸 보완)
    texts_to_embed.append(query)

    # 3. 배치 임베딩 (1회 API 호출)
    embeddings = await embed_chunks(texts_to_embed)
    logger.info(f"Created {len(embeddings)} embeddings for search")

    # 4. 각 임베딩으로 Chroma 검색 + 결과 병합
    merged: dict[str, dict[str, Any]] = {}  # chroma_id -> {distance}

    for embedding in embeddings:
        if has_filters and email_ids:
            results = search_similar_filtered(embedding, email_ids, top_k=top_k)
        else:
            results = search_similar(embedding, top_k=top_k)

        if not results or not results.get("ids") or not results["ids"][0]:
            continue

        for chroma_id, distance in zip(results["ids"][0], results["distances"][0]):
            if chroma_id not in merged or distance < merged[chroma_id]["distance"]:
                merged[chroma_id] = {"distance": distance}

    if not merged:
        logger.info("No similar chunks found in Chroma")
        return []

    chroma_ids = list(merged.keys())
    logger.info(f"Found {len(chroma_ids)} unique chunks after merging {len(embeddings)} queries")

    # 5. MSSQL에서 청크 메타데이터 조회
    chunks = get_chunks_by_chroma_ids(chroma_ids)

    if not chunks:
        logger.warning("Chunks not found in MSSQL for given Chroma IDs")
        return []

    # 6. 거리를 유사도 점수로 변환 (코사인 거리 → 유사도)
    for chunk in chunks:
        entry = merged.get(chunk["chroma_id"])
        distance = entry["distance"] if entry else 1.0
        chunk["score"] = 1 - (distance / 2)

    # 7. 점수 임계값으로 필터링
    filtered_chunks = [c for c in chunks if c["score"] >= score_threshold]

    # 8. 점수 기준 정렬 (높은 순) + top_k 제한
    filtered_chunks.sort(key=lambda x: x["score"], reverse=True)
    filtered_chunks = filtered_chunks[:top_k]

    logger.info(f"Returning {len(filtered_chunks)} chunks after filtering")
    return filtered_chunks
