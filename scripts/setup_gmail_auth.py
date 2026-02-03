#!/usr/bin/env python3
"""
로컬에서 Gmail OAuth 인증을 수행하여 token.json을 생성하는 스크립트.
Docker 컨테이너 실행 전에 반드시 한 번 실행해야 함.

사용법:
  cd RAG
  pip install google-auth google-auth-oauthlib google-api-python-client
  python scripts/setup_gmail_auth.py

결과:
  backend/gmail/token.json 파일이 생성됨
"""
import os
import sys
from pathlib import Path

# 프로젝트 루트 경로 설정
BASE_DIR = Path(__file__).resolve().parent.parent
CREDENTIALS_PATH = BASE_DIR / "backend" / "gmail" / "credentials.json"
TOKEN_PATH = BASE_DIR / "backend" / "gmail" / "token.json"

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def main():
    # credentials.json 존재 확인
    if not CREDENTIALS_PATH.exists():
        print(f"Error: credentials.json not found at {CREDENTIALS_PATH}")
        print("\nPlease follow these steps:")
        print("1. Go to https://console.cloud.google.com/")
        print("2. Create a project and enable Gmail API")
        print("3. Create OAuth 2.0 Client ID (Desktop app type)")
        print("4. Download credentials.json")
        print(f"5. Place it at: {CREDENTIALS_PATH}")
        sys.exit(1)

    # 필요한 패키지 import
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        print("Error: Required packages not installed.")
        print("Run: pip install google-auth google-auth-oauthlib google-api-python-client")
        sys.exit(1)

    creds = None

    # 기존 토큰 확인
    if TOKEN_PATH.exists():
        print(f"Found existing token at {TOKEN_PATH}")
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    # 토큰이 없거나 유효하지 않으면 새로 발급
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Token expired, refreshing...")
            creds.refresh(Request())
        else:
            print("Starting OAuth flow...")
            print("A browser window will open for authentication.")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_PATH), SCOPES
            )
            creds = flow.run_local_server(port=0)

        # 토큰 저장
        TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(TOKEN_PATH, "w") as token:
            token.write(creds.to_json())
        print(f"Token saved to {TOKEN_PATH}")

    # 인증 확인: Gmail 라벨 목록 가져오기
    print("\nVerifying authentication...")
    service = build("gmail", "v1", credentials=creds)
    results = service.users().labels().list(userId="me").execute()
    labels = results.get("labels", [])

    print(f"\n✓ Authentication successful!")
    print(f"✓ Gmail labels found: {len(labels)}")
    print(f"✓ Token saved at: {TOKEN_PATH}")

    # 뉴스레터 샘플 조회
    print("\nTesting newsletter query...")
    try:
        messages = service.users().messages().list(
            userId="me",
            q="category:promotions OR label:newsletter",
            maxResults=5
        ).execute()
        msg_count = len(messages.get("messages", []))
        print(f"✓ Found {msg_count} newsletters (showing max 5)")
    except Exception as e:
        print(f"✗ Newsletter query failed: {e}")

    print("\n" + "=" * 50)
    print("Setup complete! You can now run docker-compose up")
    print("=" * 50)


if __name__ == "__main__":
    main()
