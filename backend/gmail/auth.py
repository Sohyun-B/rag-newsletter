import os
import logging
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from config import settings

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def get_gmail_service():
    """
    Gmail API 서비스 객체 반환

    token.json이 존재해야 함 (로컬에서 setup_gmail_auth.py 실행 필요)
    """
    token_path = settings.GMAIL_TOKEN_PATH

    if not os.path.exists(token_path):
        raise FileNotFoundError(
            f"token.json not found at {token_path}. "
            "Run 'python scripts/setup_gmail_auth.py' locally first."
        )

    creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    # 토큰이 만료되었으면 갱신
    if creds.expired and creds.refresh_token:
        logger.info("Refreshing expired Gmail token...")
        creds.refresh(Request())
        # 갱신된 토큰 저장
        with open(token_path, "w") as token:
            token.write(creds.to_json())
        logger.info("Token refreshed successfully")

    return build("gmail", "v1", credentials=creds)


def test_gmail_connection() -> bool:
    """Gmail 연결 테스트"""
    try:
        service = get_gmail_service()
        results = service.users().labels().list(userId="me").execute()
        labels = results.get("labels", [])
        logger.info(f"Gmail connection successful. Found {len(labels)} labels.")
        return True
    except Exception as e:
        logger.error(f"Gmail connection failed: {e}")
        return False
