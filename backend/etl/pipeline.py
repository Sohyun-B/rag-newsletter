import logging
from typing import Any

from db import get_unprocessed_emails, mark_email_processed, insert_chunk
from vectorstore import add_embeddings, generate_chroma_id
from .preprocessor import preprocess_email
from .chunker import chunk_email
from .embedder import embed_chunks

logger = logging.getLogger(__name__)


async def process_single_email(email: dict[str, Any]) -> dict[str, Any]:
    """
    단일 이메일 처리 (전처리 → 청킹 → 임베딩 → 저장)

    Args:
        email: raw_email 테이블의 레코드

    Returns:
        처리 결과 정보
    """
    email_id = email["id"]
    subject = email.get("subject", "")

    logger.info(f"Processing email {email_id}: {subject[:50]}")

    try:
        # 1. 전처리
        text = preprocess_email(
            html_body=email.get("body_html", ""),
            text_body=email.get("body_text", "")
        )

        if not text:
            logger.warning(f"Email {email_id} has no content after preprocessing")
            mark_email_processed(email_id)
            return {"email_id": email_id, "success": True, "chunks": 0, "skipped": True}

        # 2. 청킹
        metadata = {
            "email_id": email_id,
            "subject": subject,
            "from_address": email.get("from_address", ""),
            "received_at": email.get("received_at"),
        }
        chunks = chunk_email(text, metadata)

        if not chunks:
            logger.warning(f"Email {email_id} produced no chunks")
            mark_email_processed(email_id)
            return {"email_id": email_id, "success": True, "chunks": 0, "skipped": True}

        # 3. 임베딩 생성
        chunk_texts = [c["content"] for c in chunks]
        embeddings = await embed_chunks(chunk_texts)

        # 4. Chroma에 저장 + MSSQL에 청크 저장
        chroma_ids = []
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            chroma_id = generate_chroma_id()
            chroma_ids.append(chroma_id)

            # Chroma에 벡터 저장
            add_embeddings(
                ids=[chroma_id],
                embeddings=[embedding],
                documents=[chunk["content"]],
                metadatas=[chunk["metadata"]]
            )

            # MSSQL에 청크 메타데이터 저장
            insert_chunk(
                email_id=email_id,
                chunk_index=i,
                content=chunk["content"],
                chroma_id=chroma_id,
                metadata=chunk["metadata"]
            )

        # 5. 이메일 처리 완료 표시
        mark_email_processed(email_id)

        logger.info(f"Email {email_id} processed: {len(chunks)} chunks created")
        return {
            "email_id": email_id,
            "success": True,
            "chunks": len(chunks),
            "chroma_ids": chroma_ids
        }

    except Exception as e:
        logger.error(f"Failed to process email {email_id}: {e}")
        return {
            "email_id": email_id,
            "success": False,
            "error": str(e)
        }


async def process_unprocessed_emails(limit: int = 100) -> dict[str, Any]:
    """
    미처리 이메일 일괄 처리

    Args:
        limit: 한 번에 처리할 최대 이메일 수

    Returns:
        처리 결과 요약
    """
    logger.info(f"Starting ETL pipeline (limit: {limit})")

    # 미처리 이메일 조회
    emails = get_unprocessed_emails(limit=limit)

    if not emails:
        logger.info("No unprocessed emails found")
        return {
            "total": 0,
            "processed": 0,
            "failed": 0,
            "results": []
        }

    logger.info(f"Found {len(emails)} unprocessed emails")

    results = []
    processed_count = 0
    failed_count = 0

    for email in emails:
        result = await process_single_email(email)
        results.append(result)

        if result.get("success"):
            processed_count += 1
        else:
            failed_count += 1

    summary = {
        "total": len(emails),
        "processed": processed_count,
        "failed": failed_count,
        "results": results
    }

    logger.info(f"ETL complete: {processed_count} processed, {failed_count} failed")
    return summary
