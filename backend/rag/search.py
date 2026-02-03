import logging
from typing import Any

from vectorstore import search_similar
from db import get_chunks_by_chroma_ids
from etl import embed_single

logger = logging.getLogger(__name__)


async def search_similar_chunks(
    query: str,
    top_k: int = 10,
    score_threshold: float = 0.3
) -> list[dict[str, Any]]:
    """
    쿼리와 유사한 청크 검색

    Args:
        query: 검색 쿼리
        top_k: 반환할 최대 결과 수
        score_threshold: 최소 유사도 점수 (0~1)

    Returns:
        검색된 청크 리스트 (메타데이터 포함)
    """
    logger.info(f"Searching for: {query[:50]}...")

    # 1. 쿼리 임베딩 생성
    query_embedding = await embed_single(query)

    # 2. Chroma에서 유사 벡터 검색
    results = search_similar(query_embedding, top_k=top_k)

    if not results or not results.get("ids") or not results["ids"][0]:
        logger.info("No similar chunks found in Chroma")
        return []

    chroma_ids = results["ids"][0]
    distances = results["distances"][0]

    logger.info(f"Found {len(chroma_ids)} similar chunks in Chroma")

    # 3. MSSQL에서 청크 메타데이터 조회
    chunks = get_chunks_by_chroma_ids(chroma_ids)

    if not chunks:
        logger.warning("Chunks not found in MSSQL for given Chroma IDs")
        return []

    # 4. 거리를 유사도 점수로 변환 (코사인 거리 → 유사도)
    # Chroma는 코사인 거리를 반환 (0 = 동일, 2 = 반대)
    # 유사도 = 1 - (거리 / 2)
    chroma_id_to_distance = dict(zip(chroma_ids, distances))

    for chunk in chunks:
        distance = chroma_id_to_distance.get(chunk["chroma_id"], 1.0)
        chunk["score"] = 1 - (distance / 2)  # 0~1 범위로 변환

    # 5. 점수 임계값으로 필터링
    filtered_chunks = [c for c in chunks if c["score"] >= score_threshold]

    # 6. 점수 기준 정렬 (높은 순)
    filtered_chunks.sort(key=lambda x: x["score"], reverse=True)

    logger.info(f"Returning {len(filtered_chunks)} chunks after filtering")
    return filtered_chunks
