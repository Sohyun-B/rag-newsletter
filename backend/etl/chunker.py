import logging
from typing import Any
from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)


def estimate_token_count(text: str) -> int:
    """
    토큰 수 추정 (대략적인 계산)
    영어: 약 4자당 1토큰
    한글: 약 2자당 1토큰
    """
    korean_chars = len([c for c in text if ord("가") <= ord(c) <= ord("힣")])
    total_chars = len(text)

    if total_chars == 0:
        return 0

    korean_ratio = korean_chars / total_chars
    chars_per_token = 4 * (1 - korean_ratio) + 2 * korean_ratio
    return int(total_chars / chars_per_token)


# 청킹 설정 (토큰 기준)
CHUNK_SIZE = 400    # 토큰 (한글 ~800자, 영어 ~1600자)
CHUNK_OVERLAP = 50  # 토큰

# 단락 구분 우선순위: 빈 줄 → 줄바꿈 → 문장 → 어절
# 전처리(preprocessor.py)에서 \n{3,}을 \n\n으로 정규화하므로 \n\n이 최상위
SEPARATORS = ["\n\n", "\n", ". ", "? ", "! ", " "]

splitter = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP,
    separators=SEPARATORS,
    length_function=estimate_token_count,
)


def chunk_email(text: str, metadata: dict[str, Any]) -> list[dict[str, Any]]:
    """
    이메일 텍스트를 청크로 분할

    Args:
        text: 전처리된 이메일 텍스트
        metadata: 이메일 메타데이터 (subject, from_address, received_at 등)

    Returns:
        청크 리스트 [{content, metadata, chunk_index}, ...]
    """
    if not text or len(text.strip()) < 10:
        logger.warning("Text too short to chunk")
        return []

    chunks = splitter.split_text(text)

    if not chunks:
        logger.warning("No chunks created from text")
        return []

    result = []
    for i, chunk_content in enumerate(chunks):
        chunk_data = {
            "content": chunk_content,
            "chunk_index": i,
            "metadata": {
                "subject": metadata.get("subject", ""),
                "from_address": metadata.get("from_address", ""),
                "received_at": str(metadata.get("received_at", "")),
                "email_id": metadata.get("email_id"),
                "chunk_index": i,
                "total_chunks": len(chunks),
            }
        }
        result.append(chunk_data)

    logger.info(f"Created {len(result)} chunks from email (token-based, size={CHUNK_SIZE})")
    return result
