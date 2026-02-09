import json
from datetime import date, datetime, timedelta
from typing import Any

from .connection import execute_query, execute_command, execute_insert_returning_id


def insert_email(
    gmail_id: str,
    thread_id: str,
    from_address: str,
    subject: str,
    received_at: datetime,
    body_html: str,
    body_text: str,
    labels: list[str]
) -> int | None:
    """
    새 이메일 삽입. 이미 존재하면 None 반환.
    """
    # 중복 체크
    existing = execute_query(
        "SELECT id FROM newsletter.raw_email WHERE gmail_id = ?",
        (gmail_id,)
    )
    if existing:
        return None

    query = """
        INSERT INTO newsletter.raw_email
        (gmail_id, thread_id, from_address, subject, received_at, body_html, body_text, labels)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    labels_json = json.dumps(labels) if labels else "[]"
    return execute_insert_returning_id(
        query,
        (gmail_id, thread_id, from_address, subject, received_at, body_html, body_text, labels_json)
    )


def get_unprocessed_emails(limit: int = 100) -> list[dict[str, Any]]:
    """처리되지 않은 이메일 조회"""
    query = """
        SELECT TOP (?)
            id, gmail_id, thread_id, from_address, subject,
            received_at, body_html, body_text, labels
        FROM newsletter.raw_email
        WHERE processed = 0
        ORDER BY received_at ASC
    """
    return execute_query(query, (limit,))


def mark_email_processed(email_id: int) -> int:
    """이메일을 처리 완료로 표시"""
    query = "UPDATE newsletter.raw_email SET processed = 1 WHERE id = ?"
    return execute_command(query, (email_id,))


def insert_chunk(
    email_id: int,
    chunk_index: int,
    content: str,
    chroma_id: str,
    metadata: dict
) -> int:
    """청크 삽입"""
    query = """
        INSERT INTO newsletter.email_chunks
        (email_id, chunk_index, content, chroma_id, metadata_json)
        VALUES (?, ?, ?, ?, ?)
    """
    metadata_json = json.dumps(metadata, ensure_ascii=False, default=str)
    return execute_insert_returning_id(
        query,
        (email_id, chunk_index, content, chroma_id, metadata_json)
    )


def get_chunks_by_chroma_ids(chroma_ids: list[str]) -> list[dict[str, Any]]:
    """Chroma ID로 청크 및 이메일 메타데이터 조회"""
    if not chroma_ids:
        return []

    placeholders = ",".join(["?"] * len(chroma_ids))
    query = f"""
        SELECT
            ec.id AS chunk_id,
            ec.chunk_index,
            ec.content,
            ec.chroma_id,
            ec.metadata_json,
            re.id AS email_id,
            re.gmail_id,
            re.subject,
            re.from_address,
            re.received_at,
            re.labels
        FROM newsletter.email_chunks ec
        INNER JOIN newsletter.raw_email re ON ec.email_id = re.id
        WHERE ec.chroma_id IN ({placeholders})
    """
    results = execute_query(query, tuple(chroma_ids))

    # chroma_ids 순서대로 정렬
    id_order = {cid: i for i, cid in enumerate(chroma_ids)}
    results.sort(key=lambda x: id_order.get(x["chroma_id"], 999))

    return results


def get_sync_state() -> dict[str, Any] | None:
    """동기화 상태 조회"""
    results = execute_query("SELECT TOP 1 * FROM newsletter.sync_state ORDER BY id DESC")
    return results[0] if results else None


def update_sync_state(history_id: str) -> int:
    """동기화 상태 업데이트"""
    # 기존 레코드가 있으면 업데이트, 없으면 삽입
    existing = get_sync_state()
    if existing:
        query = "UPDATE newsletter.sync_state SET last_history_id = ?, last_sync_at = SYSDATETIMEOFFSET() WHERE id = ?"
        return execute_command(query, (history_id, existing["id"]))
    else:
        query = "INSERT INTO newsletter.sync_state (last_history_id) VALUES (?)"
        return execute_command(query, (history_id,))


def get_newsletters(skip: int = 0, limit: int = 20) -> list[dict[str, Any]]:
    """뉴스레터 목록 조회"""
    query = """
        SELECT id, gmail_id, subject, from_address, received_at, labels, processed
        FROM newsletter.raw_email
        ORDER BY received_at DESC
        OFFSET ? ROWS FETCH NEXT ? ROWS ONLY
    """
    return execute_query(query, (skip, limit))


def get_newsletter_by_id(email_id: int) -> dict[str, Any] | None:
    """특정 뉴스레터 상세 조회"""
    results = execute_query(
        "SELECT * FROM newsletter.raw_email WHERE id = ?",
        (email_id,)
    )
    return results[0] if results else None


def get_newsletter_count() -> int:
    """뉴스레터 총 개수"""
    results = execute_query("SELECT COUNT(*) as count FROM newsletter.raw_email")
    return results[0]["count"] if results else 0


def get_email_ids_by_filters(
    date_from: date | None = None,
    date_to: date | None = None,
    sender: str | None = None,
) -> list[int]:
    """날짜/발신인 조건으로 email_id 목록 조회 (Chroma에 벡터가 있는 것만)"""
    conditions = []
    params = []

    if date_from:
        conditions.append("re.received_at >= ?")
        params.append(datetime.combine(date_from, datetime.min.time()))
    if date_to:
        conditions.append("re.received_at < ?")
        # date_to의 다음날 00:00까지 포함
        params.append(datetime.combine(date_to + timedelta(days=1), datetime.min.time()))
    if sender:
        conditions.append("re.from_address LIKE ?")
        params.append(f"%{sender}%")

    if not conditions:
        return []

    where_clause = " AND ".join(conditions)
    query = f"""
        SELECT DISTINCT re.id
        FROM newsletter.raw_email re
        INNER JOIN newsletter.email_chunks ec ON ec.email_id = re.id
        WHERE {where_clause}
    """
    results = execute_query(query, tuple(params))
    return [row["id"] for row in results]
