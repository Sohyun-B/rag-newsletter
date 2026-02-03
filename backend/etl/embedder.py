import logging
from openai import AsyncOpenAI
import httpx

from config import settings
from utils import with_retry

logger = logging.getLogger(__name__)

# OpenAI 클라이언트
client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

# 임베딩 모델 설정
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536
MAX_BATCH_SIZE = 100  # OpenAI 배치 제한


@with_retry(max_retries=3, base_delay=1.0, exceptions=(httpx.HTTPError, Exception))
async def embed_chunks(texts: list[str]) -> list[list[float]]:
    """
    텍스트 리스트를 임베딩 벡터로 변환

    Args:
        texts: 임베딩할 텍스트 리스트

    Returns:
        임베딩 벡터 리스트 (1536차원)
    """
    if not texts:
        return []

    embeddings = []

    # 배치 처리
    for i in range(0, len(texts), MAX_BATCH_SIZE):
        batch = texts[i:i + MAX_BATCH_SIZE]

        response = await client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=batch
        )

        batch_embeddings = [item.embedding for item in response.data]
        embeddings.extend(batch_embeddings)

        logger.debug(f"Embedded batch {i // MAX_BATCH_SIZE + 1}, total: {len(embeddings)}")

    logger.info(f"Created {len(embeddings)} embeddings")
    return embeddings


@with_retry(max_retries=3, base_delay=1.0, exceptions=(httpx.HTTPError, Exception))
async def embed_single(text: str) -> list[float]:
    """
    단일 텍스트를 임베딩 벡터로 변환

    Args:
        text: 임베딩할 텍스트

    Returns:
        임베딩 벡터 (1536차원)
    """
    response = await client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=[text]
    )

    return response.data[0].embedding
