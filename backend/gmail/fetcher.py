import base64
import logging
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any

from .auth import get_gmail_service
from db import insert_email, get_sync_state, update_sync_state

logger = logging.getLogger(__name__)

NEWSLETTER_QUERY = "category:promotions OR label:newsletter"
MAX_RESULTS = 50


def decode_base64(data: str) -> str:
    """Base64 URL-safe 디코딩"""
    if not data:
        return ""
    try:
        decoded = base64.urlsafe_b64decode(data.encode("UTF-8"))
        return decoded.decode("UTF-8", errors="replace")
    except Exception as e:
        logger.warning(f"Failed to decode base64: {e}")
        return ""


def extract_header(headers: list[dict], name: str) -> str:
    """헤더에서 특정 값 추출"""
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


def extract_body(payload: dict) -> tuple[str, str]:
    """
    이메일 본문 추출 (HTML, Plain Text)

    Returns:
        (body_html, body_text)
    """
    body_html = ""
    body_text = ""

    def process_part(part: dict):
        nonlocal body_html, body_text

        mime_type = part.get("mimeType", "")
        body = part.get("body", {})
        data = body.get("data", "")

        if mime_type == "text/html" and data:
            body_html = decode_base64(data)
        elif mime_type == "text/plain" and data:
            body_text = decode_base64(data)

        # 멀티파트인 경우 재귀 처리
        for sub_part in part.get("parts", []):
            process_part(sub_part)

    process_part(payload)
    return body_html, body_text


def extract_labels(label_ids: list[str]) -> list[str]:
    """라벨 ID를 읽기 쉬운 형태로 변환"""
    # Gmail 내부 라벨 제외하고 반환
    excluded = {"UNREAD", "INBOX", "SPAM", "TRASH", "SENT", "DRAFT", "STARRED", "IMPORTANT"}
    return [label for label in label_ids if label not in excluded]


def parse_date(date_str: str) -> datetime:
    """이메일 날짜 파싱"""
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        return datetime.now()


def fetch_message_detail(service, message_id: str) -> dict[str, Any] | None:
    """단일 메시지 상세 정보 가져오기"""
    try:
        message = service.users().messages().get(
            userId="me",
            id=message_id,
            format="full"
        ).execute()
        return message
    except Exception as e:
        logger.error(f"Failed to fetch message {message_id}: {e}")
        return None


def process_message(message: dict) -> dict[str, Any] | None:
    """메시지를 DB 저장 형태로 변환"""
    try:
        gmail_id = message.get("id")
        thread_id = message.get("threadId")
        label_ids = message.get("labelIds", [])

        payload = message.get("payload", {})
        headers = payload.get("headers", [])

        from_address = extract_header(headers, "From")
        subject = extract_header(headers, "Subject")
        date_str = extract_header(headers, "Date")

        received_at = parse_date(date_str)
        body_html, body_text = extract_body(payload)
        labels = extract_labels(label_ids)

        return {
            "gmail_id": gmail_id,
            "thread_id": thread_id,
            "from_address": from_address,
            "subject": subject,
            "received_at": received_at,
            "body_html": body_html,
            "body_text": body_text,
            "labels": labels
        }
    except Exception as e:
        logger.error(f"Failed to process message: {e}")
        return None


def fetch_new_newsletters(max_results: int = MAX_RESULTS) -> list[dict]:
    """
    새 뉴스레터 가져오기

    Returns:
        삽입된 이메일 정보 리스트
    """
    service = get_gmail_service()
    inserted = []

    try:
        # 메시지 목록 조회
        results = service.users().messages().list(
            userId="me",
            q=NEWSLETTER_QUERY,
            maxResults=max_results
        ).execute()

        messages = results.get("messages", [])
        logger.info(f"Found {len(messages)} newsletters matching query")

        for msg_ref in messages:
            message_id = msg_ref["id"]

            # 상세 정보 가져오기
            message = fetch_message_detail(service, message_id)
            if not message:
                continue

            # 메시지 파싱
            email_data = process_message(message)
            if not email_data:
                continue

            # DB에 삽입 (중복이면 None 반환)
            new_id = insert_email(**email_data)
            if new_id:
                email_data["id"] = new_id
                inserted.append(email_data)
                logger.info(f"Inserted email: {email_data['subject'][:50]}")

        logger.info(f"Inserted {len(inserted)} new emails")
        return inserted

    except Exception as e:
        logger.error(f"Failed to fetch newsletters: {e}")
        raise


def sync_gmail() -> dict[str, Any]:
    """
    Gmail 동기화 실행

    Returns:
        동기화 결과 정보
    """
    logger.info("Starting Gmail sync...")

    try:
        # 새 뉴스레터 가져오기
        inserted = fetch_new_newsletters()

        # 동기화 상태 업데이트
        if inserted:
            # 마지막 history ID 업데이트 (간단히 현재 시간 기록)
            update_sync_state(str(datetime.now().timestamp()))

        result = {
            "success": True,
            "inserted_count": len(inserted),
            "inserted_emails": [
                {"id": e["id"], "subject": e["subject"]}
                for e in inserted
            ]
        }
        logger.info(f"Gmail sync completed: {len(inserted)} new emails")
        return result

    except Exception as e:
        logger.error(f"Gmail sync failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "inserted_count": 0
        }
