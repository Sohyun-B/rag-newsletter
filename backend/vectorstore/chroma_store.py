import chromadb
from chromadb.config import Settings
import uuid
import logging

from config import settings

logger = logging.getLogger(__name__)

# 로컬 파일 기반 Chroma 클라이언트
chroma_client = chromadb.PersistentClient(
    path=settings.CHROMA_PATH,
    settings=Settings(anonymized_telemetry=False)
)

# 컬렉션 생성/로드
collection = chroma_client.get_or_create_collection(
    name="newsletter_chunks",
    metadata={"hnsw:space": "cosine"}
)


def add_embeddings(
    ids: list[str],
    embeddings: list[list[float]],
    documents: list[str],
    metadatas: list[dict] = None
) -> None:
    """벡터 임베딩 추가"""
    try:
        collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas or [{}] * len(ids)
        )
        logger.info(f"Added {len(ids)} embeddings to Chroma")
    except Exception as e:
        logger.error(f"Failed to add embeddings: {e}")
        raise


def search_similar(
    query_embedding: list[float],
    top_k: int = 10
) -> dict:
    """유사 벡터 검색"""
    try:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"]
        )
        return results
    except Exception as e:
        logger.error(f"Failed to search: {e}")
        raise


def search_similar_filtered(
    query_embedding: list[float],
    email_ids: list[int],
    top_k: int = 10,
) -> dict:
    """email_id 필터를 적용한 유사 벡터 검색"""
    try:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where={"email_id": {"$in": email_ids}},
            include=["documents", "metadatas", "distances"],
        )
        return results
    except Exception as e:
        logger.error(f"Failed to filtered search: {e}")
        raise


def generate_chroma_id() -> str:
    """고유 Chroma ID 생성"""
    return str(uuid.uuid4())


def delete_by_ids(ids: list[str]) -> None:
    """ID로 벡터 삭제"""
    try:
        collection.delete(ids=ids)
        logger.info(f"Deleted {len(ids)} embeddings from Chroma")
    except Exception as e:
        logger.error(f"Failed to delete embeddings: {e}")
        raise


def get_collection_count() -> int:
    """컬렉션 내 벡터 수"""
    return collection.count()
