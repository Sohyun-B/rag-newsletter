import logging
from datetime import date
from typing import Any

from vectorstore import search_similar, search_similar_filtered
from db import get_chunks_by_chroma_ids, get_email_ids_by_filters
from etl import embed_single

logger = logging.getLogger(__name__)


async def search_similar_chunks(
    query: str,
    top_k: int = 10,
    score_threshold: float = 0.3,
    date_from: date | None = None,
    date_to: date | None = None,
    sender: str | None = None,
) -> list[dict[str, Any]]:
    """
    쿼리와 유사한 청크 검색

    Args:
        query: 검색 쿼리 (rewritten_query 권장)
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

    # 1. 필터가 있으면 MSSQL에서 email_ids 먼저 조회
    if has_filters:
        email_ids = get_email_ids_by_filters(
            date_from=date_from,
            date_to=date_to,
            sender=sender,
        )
        logger.info(f"Filter matched {len(email_ids)} emails")
        if not email_ids:
            logger.info("No emails match the filter criteria")
            return []

    # 2. 쿼리 임베딩 생성
    query_embedding = await embed_single(query)

    # 3. Chroma 검색 (필터 유무에 따라 분기)
    if has_filters:
        results = search_similar_filtered(query_embedding, email_ids, top_k=top_k)
    else:
        results = search_similar(query_embedding, top_k=top_k)

    if not results or not results.get("ids") or not results["ids"][0]:
        logger.info("No similar chunks found in Chroma")
        return []

    chroma_ids = results["ids"][0]
    distances = results["distances"][0]

    logger.info(f"Found {len(chroma_ids)} similar chunks in Chroma")

    # 4. MSSQL에서 청크 메타데이터 조회
    chunks = get_chunks_by_chroma_ids(chroma_ids)

    if not chunks:
        logger.warning("Chunks not found in MSSQL for given Chroma IDs")
        return []

    # 5. 거리를 유사도 점수로 변환 (코사인 거리 → 유사도)
    chroma_id_to_distance = dict(zip(chroma_ids, distances))

    for chunk in chunks:
        distance = chroma_id_to_distance.get(chunk["chroma_id"], 1.0)
        chunk["score"] = 1 - (distance / 2)

    # 6. 점수 임계값으로 필터링
    filtered_chunks = [c for c in chunks if c["score"] >= score_threshold]

    # 7. 점수 기준 정렬 (높은 순)
    filtered_chunks.sort(key=lambda x: x["score"], reverse=True)

    logger.info(f"Returning {len(filtered_chunks)} chunks after filtering")
    return filtered_chunks
