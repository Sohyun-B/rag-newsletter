
Newsletter RAG System - 상세 구현 계획

기술 스택 요약
┌────────────┬────────────────────────────────┬──────────────────────────────────────┐
│    항목    │              선택              │                 비고                 │
├────────────┼────────────────────────────────┼──────────────────────────────────────┤
│ 이메일     │ Gmail API (자동 수집)          │ OAuth2, gmail.readonly 스코프        │
├────────────┼────────────────────────────────┼──────────────────────────────────────┤
│ 인프라     │ Docker Compose (로컬)          │ Backend + Frontend 컨테이너          │
├────────────┼────────────────────────────────┼──────────────────────────────────────┤
│ LLM        │ Claude (Anthropic API)         │ Citations API 활용하여 출처 표시     │
├────────────┼────────────────────────────────┼──────────────────────────────────────┤
│ 임베딩     │ OpenAI text-embedding-3-small  │ 1536차원, $0.02/1M tokens            │
├────────────┼────────────────────────────────┼──────────────────────────────────────┤
│ 메타DB     │ MSSQL (원격 서버)              │ 이메일/청크 메타데이터 저장          │
├────────────┼────────────────────────────────┼──────────────────────────────────────┤
│ 벡터DB     │ Chroma (로컬 파일)             │ Backend 내장, 벡터 임베딩 저장       │
├────────────┼────────────────────────────────┼──────────────────────────────────────┤
│ 백엔드     │ Python FastAPI                 │ pyodbc/aioodbc로 MSSQL 연결          │
├────────────┼────────────────────────────────┼──────────────────────────────────────┤
│ 프론트엔드 │ Streamlit 채팅 UI              │ st.chat_message 컴포넌트             │
├────────────┼────────────────────────────────┼──────────────────────────────────────┤
│ 청킹       │ RecursiveCharacterTextSplitter │ 512토큰, 50토큰 오버랩               │
└────────────┴────────────────────────────────┴──────────────────────────────────────┘

---
주요 설계 결정 사항

┌──────────────────┬─────────────────────────────────────────────────────────────┐
│       항목       │                            결정                             │
├──────────────────┼─────────────────────────────────────────────────────────────┤
│ 뉴스레터 필터    │ category:promotions OR label:newsletter                     │
├──────────────────┼─────────────────────────────────────────────────────────────┤
│ OAuth 인증 방식  │ 로컬에서 먼저 인증 후 token.json을 Docker 볼륨에 마운트     │
├──────────────────┼─────────────────────────────────────────────────────────────┤
│ 재시도 정책      │ 지수 백오프 (최대 3회, 1초→2초→4초)                         │
├──────────────────┼─────────────────────────────────────────────────────────────┤
│ Citations 렌더링 │ 인용 번호 표시 + 확장 패널로 출처 상세 표시                 │
├──────────────────┼─────────────────────────────────────────────────────────────┤
│ DB 아키텍처      │ MSSQL(직접 연결, 메타데이터) + Chroma(로컬 파일, 벡터)      │
├──────────────────┼─────────────────────────────────────────────────────────────┤
│ DB 스키마        │ newsletter (newsletter.raw_email, newsletter.email_chunks)  │
└──────────────────┴─────────────────────────────────────────────────────────────┘

---
시스템 아키텍처

┌─────────────────────────────────────────────────────────────────────────────┐
│                              Docker Host (로컬)                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                         docker-compose                               │   │
│  │   ┌─────────────────┐       ┌─────────────────┐                     │   │
│  │   │    Backend      │       │    Frontend     │                     │   │
│  │   │   (FastAPI)     │◄─────►│   (Streamlit)   │                     │   │
│  │   │   Port 8000     │       │   Port 8501     │                     │   │
│  │   └────────┬────────┘       └─────────────────┘                     │   │
│  │            │                                                         │   │
│  │            ▼                                                         │   │
│  │   ┌─────────────────┐                                               │   │
│  │   │  Chroma (파일)  │  ← 벡터 임베딩 저장                           │   │
│  │   │  ./chroma_data  │                                               │   │
│  │   └─────────────────┘                                               │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │      원격 MSSQL Server        │
                    │   (이메일/청크 메타데이터)    │
                    └───────────────────────────────┘

---
프로젝트 구조

RAG/
├── docker-compose.yml
├── .env                          # API 키, DB 접속 정보
├── .env.example
├── .gitignore
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py                   # FastAPI 앱 진입점 + 스케줄러 시작
│   ├── config.py                 # pydantic-settings 기반 환경변수
│   ├── db/
│   │   ├── schema.sql            # MSSQL 스키마 (DBA 전달용)
│   │   ├── connection.py         # MSSQL 연결 (pyodbc)
│   │   └── queries.py            # SQL 쿼리 함수들
│   ├── gmail/
│   │   ├── auth.py               # Gmail OAuth2 인증/토큰 갱신
│   │   ├── fetcher.py            # 뉴스레터 가져오기
│   │   ├── credentials.json      # Google OAuth 클라이언트 (.gitignore)
│   │   └── token.json            # OAuth 토큰 (.gitignore, Docker 볼륨 마운트)
│   ├── etl/
│   │   ├── preprocessor.py       # HTML→텍스트, 정리
│   │   ├── chunker.py            # 텍스트 청킹
│   │   └── embedder.py           # OpenAI 임베딩 생성
│   ├── vectorstore/
│   │   └── chroma_store.py       # Chroma 벡터 저장소 관리
│   ├── rag/
│   │   ├── search.py             # Chroma 유사도 검색 + MSSQL 메타데이터 조회
│   │   └── agent.py              # Claude Citations API 답변 생성
│   ├── utils/
│   │   └── retry.py              # 지수 백오프 재시도 유틸리티
│   └── scheduler.py              # APScheduler 주기적 Gmail 폴링
├── frontend/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app.py                    # Streamlit 채팅 UI
├── chroma_data/                  # Chroma 벡터 데이터 (Docker 볼륨)
└── scripts/
    ├── init_db.sh                # DB 초기화 안내 스크립트
    └── setup_gmail_auth.py       # 로컬 Gmail OAuth 인증 스크립트

---
Step 1: 인프라 (Docker Compose + DB)

1-1. Docker Compose 구성

2개 서비스 (DB는 원격 MSSQL 사용):
- backend: FastAPI (Python 3.12) - 포트 8000
- frontend: Streamlit - 포트 8501

# docker-compose.yml
services:
  backend:
    build: ./backend
    env_file: .env
    ports:
      - "8000:8000"
    volumes:
      - ./backend:/app
      - ./backend/gmail/token.json:/app/gmail/token.json:ro
      - ./chroma_data:/app/chroma_data    # Chroma 벡터 데이터 영속화

  frontend:
    build: ./frontend
    env_file: .env
    ports:
      - "8501:8501"
    depends_on:
      - backend

1-2. MSSQL 스키마 (DBA 전달용)

파일 위치: backend/db/schema.sql
스키마 이름: newsletter

-- 스키마 생성
IF NOT EXISTS (SELECT * FROM sys.schemas WHERE name = 'newsletter')
BEGIN
    EXEC('CREATE SCHEMA newsletter');
END
GO

-- 원본 이메일
CREATE TABLE newsletter.raw_email (
    id              BIGINT IDENTITY(1,1) PRIMARY KEY,
    gmail_id        NVARCHAR(255) NOT NULL,
    thread_id       NVARCHAR(255),
    from_address    NVARCHAR(500),
    subject         NVARCHAR(1000),
    received_at     DATETIMEOFFSET NOT NULL,
    body_html       NVARCHAR(MAX),
    body_text       NVARCHAR(MAX),
    labels          NVARCHAR(MAX),                  -- JSON 배열
    processed       BIT DEFAULT 0,
    created_at      DATETIMEOFFSET DEFAULT SYSDATETIMEOFFSET(),
    CONSTRAINT UQ_raw_email_gmail_id UNIQUE (gmail_id)
);

-- 청크 (Chroma ID로 벡터 연결)
CREATE TABLE newsletter.email_chunks (
    id              BIGINT IDENTITY(1,1) PRIMARY KEY,
    email_id        BIGINT NOT NULL,
    chunk_index     INT NOT NULL,
    content         NVARCHAR(MAX) NOT NULL,
    chroma_id       NVARCHAR(255),                  -- Chroma 벡터 ID
    metadata_json   NVARCHAR(MAX),
    created_at      DATETIMEOFFSET DEFAULT SYSDATETIMEOFFSET(),
    CONSTRAINT FK_email_chunks_raw_email
        FOREIGN KEY (email_id) REFERENCES newsletter.raw_email(id) ON DELETE CASCADE
);

-- Gmail 동기화 상태
CREATE TABLE newsletter.sync_state (
    id                  INT IDENTITY(1,1) PRIMARY KEY,
    last_history_id     NVARCHAR(255),
    last_sync_at        DATETIMEOFFSET DEFAULT SYSDATETIMEOFFSET()
);

-- 초기 레코드 삽입
INSERT INTO newsletter.sync_state (last_history_id) VALUES (NULL);

-- 인덱스
CREATE INDEX IX_raw_email_processed ON newsletter.raw_email(processed) WHERE processed = 0;
CREATE INDEX IX_raw_email_received_at ON newsletter.raw_email(received_at DESC);
CREATE INDEX IX_email_chunks_email_id ON newsletter.email_chunks(email_id);
CREATE INDEX IX_email_chunks_chroma_id ON newsletter.email_chunks(chroma_id);

-- 뷰: 청크와 이메일 정보 조인
GO
CREATE VIEW newsletter.vw_chunks_with_email AS
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
INNER JOIN newsletter.raw_email re ON ec.email_id = re.id;
GO

1-3. 파이썬 의존성

# backend/requirements.txt
fastapi==0.115.*
uvicorn[standard]==0.34.*
pyodbc==5.*                        # MSSQL 연결
pydantic-settings==2.*
anthropic==0.45.*
openai==1.60.*
chromadb==0.5.*                    # 벡터 저장소
google-auth==2.*
google-auth-oauthlib==1.*
google-api-python-client==2.*
beautifulsoup4==4.*
langchain-text-splitters==0.3.*
apscheduler==3.*
httpx==0.28.*

# frontend/requirements.txt
streamlit==1.42.*
httpx==0.28.*

1-4. Backend Dockerfile (ODBC 드라이버 포함)

FROM python:3.12-slim

# MSSQL ODBC 드라이버 설치
RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    unixodbc-dev \
    && curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add - \
    && curl https://packages.microsoft.com/config/debian/11/prod.list > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y msodbcsql18 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

---
Step 2: 데이터베이스 연결

2-1. db/connection.py - MSSQL 연결

import pyodbc
from contextlib import contextmanager
from config import settings

def get_connection_string():
    """MSSQL 연결 문자열 생성"""
    return (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={settings.MSSQL_SERVER};"
        f"DATABASE={settings.MSSQL_DATABASE};"
        f"UID={settings.MSSQL_USER};"
        f"PWD={settings.MSSQL_PASSWORD};"
        f"TrustServerCertificate=yes;"
    )

@contextmanager
def get_db_connection():
    """DB 연결 컨텍스트 매니저"""
    conn = pyodbc.connect(get_connection_string())
    try:
        yield conn
    finally:
        conn.close()

def execute_query(query: str, params: tuple = None):
    """SELECT 쿼리 실행"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params or ())
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

def execute_command(query: str, params: tuple = None) -> int:
    """INSERT/UPDATE/DELETE 실행, 영향받은 행 수 반환"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params or ())
        conn.commit()
        return cursor.rowcount

def execute_insert_returning_id(query: str, params: tuple = None) -> int:
    """INSERT 후 생성된 ID 반환"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params or ())
        cursor.execute("SELECT SCOPE_IDENTITY()")
        new_id = cursor.fetchone()[0]
        conn.commit()
        return int(new_id)

2-2. vectorstore/chroma_store.py - Chroma 벡터 저장소

import chromadb
from chromadb.config import Settings
import uuid

# 로컬 파일 기반 Chroma 클라이언트
chroma_client = chromadb.PersistentClient(
    path="./chroma_data",
    settings=Settings(anonymized_telemetry=False)
)

# 컬렉션 생성/로드
collection = chroma_client.get_or_create_collection(
    name="newsletter_chunks",
    metadata={"hnsw:space": "cosine"}  # 코사인 유사도 사용
)

def add_embeddings(
    ids: list[str],
    embeddings: list[list[float]],
    documents: list[str],
    metadatas: list[dict]
) -> None:
    """벡터 임베딩 추가"""
    collection.add(
        ids=ids,
        embeddings=embeddings,
        documents=documents,
        metadatas=metadatas
    )

def search_similar(
    query_embedding: list[float],
    top_k: int = 10
) -> dict:
    """유사 벡터 검색"""
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        include=["documents", "metadatas", "distances"]
    )
    return results

def generate_chroma_id() -> str:
    """고유 Chroma ID 생성"""
    return str(uuid.uuid4())

def delete_by_ids(ids: list[str]) -> None:
    """ID로 벡터 삭제"""
    collection.delete(ids=ids)

---
Step 3: Gmail 연동

3-1. 사전 준비 (수동)

1. https://console.cloud.google.com/에서 프로젝트 생성
2. Gmail API 활성화
3. OAuth 2.0 클라이언트 ID 생성 (데스크톱 앱 유형)
4. credentials.json 다운로드 → backend/gmail/credentials.json에 배치

3-2. 로컬 OAuth 인증 (Docker 실행 전 필수)

# scripts/setup_gmail_auth.py
"""
로컬에서 Gmail OAuth 인증을 수행하여 token.json을 생성하는 스크립트.
Docker 컨테이너 실행 전에 반드시 한 번 실행해야 함.

사용법:
  cd RAG
  python scripts/setup_gmail_auth.py

결과:
  backend/gmail/token.json 파일이 생성됨
"""
import os
from pathlib import Path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
BASE_DIR = Path(__file__).resolve().parent.parent
CREDENTIALS_PATH = BASE_DIR / "backend" / "gmail" / "credentials.json"
TOKEN_PATH = BASE_DIR / "backend" / "gmail" / "token.json"

def main():
    creds = None

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_PATH), SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open(TOKEN_PATH, "w") as token:
            token.write(creds.to_json())

    # 인증 확인
    service = build("gmail", "v1", credentials=creds)
    results = service.users().labels().list(userId="me").execute()
    labels = results.get("labels", [])
    print(f"인증 성공! Gmail 라벨 수: {len(labels)}")
    print(f"토큰 저장 위치: {TOKEN_PATH}")

if __name__ == "__main__":
    main()

3-3. gmail/auth.py

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
TOKEN_PATH = "/app/gmail/token.json"

def get_gmail_service():
    """Gmail API 서비스 객체 반환"""
    if not os.path.exists(TOKEN_PATH):
        raise FileNotFoundError(
            "token.json not found. Run 'python scripts/setup_gmail_auth.py' locally first."
        )

    creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

    return build("gmail", "v1", credentials=creds)

3-4. gmail/fetcher.py

NEWSLETTER_QUERY = "category:promotions OR label:newsletter"

def fetch_new_newsletters(service, after_history_id=None):
    """
    1. history_id가 있으면 → Gmail History API로 증분 조회
    2. history_id가 없으면 → messages.list로 최근 N개 조회
    3. 쿼리 필터: 'category:promotions OR label:newsletter'
    4. 각 메시지의 subject, from, body(html/text), date 추출
    5. raw_email 테이블에 INSERT (gmail_id UNIQUE로 중복 방지)
    6. sync_state 업데이트
    """

3-5. scheduler.py

# APScheduler로 5분마다 실행
scheduler = BackgroundScheduler()
scheduler.add_job(sync_gmail, 'interval', minutes=5)

---
Step 4: ETL 파이프라인

4-1. utils/retry.py - 지수 백오프 재시도 유틸리티

import asyncio
import logging
from functools import wraps
from typing import Type

logger = logging.getLogger(__name__)

def with_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    exceptions: tuple[Type[Exception], ...] = (Exception,)
):
    """지수 백오프 재시도 데코레이터 (1초 → 2초 → 4초)"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        logger.warning(
                            f"{func.__name__} failed (attempt {attempt + 1}/{max_retries}), "
                            f"retrying in {delay}s: {e}"
                        )
                        await asyncio.sleep(delay)
            raise last_exception
        return wrapper
    return decorator

4-2. etl/preprocessor.py - HTML → 텍스트 변환

def preprocess_email(html_body: str, text_body: str) -> str:
    """
    1. HTML 우선 사용, 없으면 text_body 사용
    2. BeautifulSoup으로 파싱
    3. 불필요 요소 제거: script, style, footer, 구독취소 링크
    4. 연속 공백/빈줄 정리
    """

4-3. etl/chunker.py - 텍스트 청킹

from langchain_text_splitters import RecursiveCharacterTextSplitter

splitter = RecursiveCharacterTextSplitter(
    chunk_size=512,
    chunk_overlap=50,
    separators=["\n\n", "\n", ". ", " "],
)

def chunk_email(text: str, metadata: dict) -> list[dict]:
    """텍스트를 청크로 분할"""

4-4. etl/embedder.py - 임베딩 생성

from openai import AsyncOpenAI
from utils.retry import with_retry

client = AsyncOpenAI()

@with_retry(max_retries=3, base_delay=1.0)
async def embed_chunks(chunks: list[str]) -> list[list[float]]:
    """OpenAI 임베딩 생성"""
    response = await client.embeddings.create(
        model="text-embedding-3-small",
        input=chunks
    )
    return [item.embedding for item in response.data]

4-5. ETL 전체 흐름

async def process_unprocessed_emails():
    """
    1. MSSQL에서 processed=0인 이메일 조회
    2. 각 이메일에 대해:
       a. preprocess_email() → 정제된 텍스트
       b. chunk_email() → 청크 리스트
       c. embed_chunks() → 임베딩 리스트
       d. Chroma에 벡터 저장 → chroma_id 획득
       e. MSSQL email_chunks에 INSERT (chroma_id 포함)
       f. raw_email.processed = 1로 업데이트
    """

---
Step 5: RAG 검색 + Claude 답변

5-1. rag/search.py - 벡터 유사도 검색

from vectorstore.chroma_store import search_similar
from db.queries import get_chunks_by_chroma_ids
from etl.embedder import embed_chunks

async def search_similar_chunks(query: str, top_k: int = 10) -> list[dict]:
    """
    1. query를 임베딩으로 변환
    2. Chroma에서 유사 벡터 검색 → chroma_id 목록
    3. MSSQL에서 chroma_id로 메타데이터 조회
    4. 결과 병합하여 반환
    """
    # 쿼리 임베딩
    query_embedding = (await embed_chunks([query]))[0]

    # Chroma 검색
    results = search_similar(query_embedding, top_k)

    if not results['ids'][0]:
        return []

    # MSSQL에서 메타데이터 조회
    chroma_ids = results['ids'][0]
    distances = results['distances'][0]

    chunks = get_chunks_by_chroma_ids(chroma_ids)

    # 거리 정보 추가 (코사인 거리 → 유사도)
    for chunk, distance in zip(chunks, distances):
        chunk['score'] = 1 - distance

    return chunks

5-2. rag/agent.py - Claude Citations API 답변 생성

import anthropic
from utils.retry import with_retry

client = anthropic.Anthropic()

@with_retry(max_retries=3, base_delay=1.0)
async def generate_answer(query: str, chunks: list[dict]) -> dict:
    """Claude Citations API로 답변 생성"""
    content = []
    for chunk in chunks:
        content.append({
            "type": "document",
            "source": {
                "type": "text",
                "media_type": "text/plain",
                "data": chunk["content"],
            },
            "title": f"{chunk['subject']} ({chunk['from_address']}, {chunk['received_at'][:10]})",
            "citations": {"enabled": True}
        })

    content.append({"type": "text", "text": query})

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        messages=[{"role": "user", "content": content}],
        system="당신은 뉴스레터 지식 검색 어시스턴트입니다. "
               "제공된 뉴스레터 문서를 기반으로 질문에 답변하세요. "
               "반드시 출처를 인용하여 답변하세요. "
               "문서에 없는 내용은 '관련 뉴스레터를 찾지 못했습니다'라고 답하세요."
    )

    return {
        "content": response.content,
        "sources": chunks
    }

5-3. Citations API 응답 파싱

def parse_citations_response(content_blocks: list, sources: list[dict]) -> dict:
    """Claude Citations 응답을 프론트엔드 표시용으로 파싱"""
    full_text = ""
    citations = []
    citation_counter = 0

    for block in content_blocks:
        if block.type == "text":
            text = block.text
            if hasattr(block, 'citations') and block.citations:
                citation_indices = []
                for citation in block.citations:
                    citation_counter += 1
                    doc_idx = citation.document_index
                    citations.append({
                        "index": citation_counter,
                        "cited_text": citation.cited_text,
                        "source": sources[doc_idx] if doc_idx < len(sources) else None
                    })
                    citation_indices.append(str(citation_counter))
                text += f" [{','.join(citation_indices)}]"
            full_text += text

    return {"text": full_text, "citations": citations}

---
Step 6: FastAPI 엔드포인트

from pydantic import BaseModel
from rag.search import search_similar_chunks
from rag.agent import generate_answer, parse_citations_response

class ChatRequest(BaseModel):
    query: str

class ChatResponse(BaseModel):
    text: str
    citations: list[dict]
    sources: list[dict]

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """RAG 채팅 엔드포인트"""
    chunks = await search_similar_chunks(request.query)
    result = await generate_answer(request.query, chunks)
    parsed = parse_citations_response(result["content"], result["sources"])
    return ChatResponse(
        text=parsed["text"],
        citations=parsed["citations"],
        sources=result["sources"]
    )

@app.post("/sync")
async def manual_sync():
    """수동 Gmail 동기화 + ETL 실행"""

@app.get("/newsletters")
async def list_newsletters(skip: int = 0, limit: int = 20):
    """수집된 뉴스레터 목록"""

@app.get("/health")
async def health():
    """헬스체크 (MSSQL + Chroma 연결 확인)"""

---
Step 7: Streamlit 채팅 UI

# frontend/app.py
import streamlit as st
import httpx

BACKEND_URL = "http://backend:8000"

st.title("Newsletter RAG Assistant")

# 사이드바
with st.sidebar:
    st.header("뉴스레터 관리")
    if st.button("지금 동기화"):
        with st.spinner("동기화 중..."):
            httpx.post(f"{BACKEND_URL}/sync", timeout=60)
        st.success("동기화 완료!")

# 채팅 인터페이스
if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("citations"):
            with st.expander("출처 보기"):
                for cite in msg["citations"]:
                    src = cite.get("source", {})
                    st.caption(f"[{cite['index']}] {src.get('subject', 'Unknown')}")

if prompt := st.chat_input("뉴스레터에 대해 질문하세요"):
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.spinner("답변 생성 중..."):
        response = httpx.post(f"{BACKEND_URL}/chat", json={"query": prompt}, timeout=30)
        answer = response.json()

    st.session_state.messages.append({
        "role": "assistant",
        "content": answer["text"],
        "citations": answer.get("citations", [])
    })
    st.rerun()

---
필요한 설정 (.env)

# MSSQL (직접 연결)
MSSQL_SERVER=192.168.1.100,1433      # IP,포트 또는 hostname,포트
MSSQL_DATABASE=project_pm
MSSQL_USER=sa
MSSQL_PASSWORD=YourStrongPassword123!

# OpenAI (임베딩용)
OPENAI_API_KEY=sk-proj-...

# Anthropic (Claude LLM)
ANTHROPIC_API_KEY=sk-ant-api03-...

# 선택 설정 (기본값 있음)
# CHROMA_PATH=./chroma_data
# GMAIL_TOKEN_PATH=./gmail/token.json
# GMAIL_CREDENTIALS_PATH=./gmail/credentials.json
# SYNC_INTERVAL_MINUTES=5

---
.gitignore

# API Keys & Secrets
.env
backend/gmail/credentials.json
backend/gmail/token.json

# Chroma Data (선택적으로 포함 가능)
chroma_data/

# Python
__pycache__/
*.py[cod]
.venv/
venv/

# IDE
.idea/
.vscode/

---
사전 준비 체크리스트

- [ ] Google Cloud Console 프로젝트 생성 + Gmail API 활성화
- [ ] OAuth 2.0 클라이언트 ID 생성 → credentials.json 다운로드
- [ ] credentials.json을 backend/gmail/에 배치
- [ ] OpenAI API 키 발급
- [ ] Anthropic API 키 발급
- [ ] Docker Desktop 설치 및 실행 확인
- [ ] 원격 MSSQL 서버 접속 정보 확인
- [ ] DBA에게 backend/db/schema.sql 전달하여 테이블 생성 요청
- [ ] python scripts/setup_gmail_auth.py 실행하여 token.json 생성

---
구현 순서 및 검증
┌──────┬────────────────────────────┬───────────────────────────────────────────────────────────┐
│ 단계 │         구현 내용          │                         검증 방법                         │
├──────┼────────────────────────────┼───────────────────────────────────────────────────────────┤
│ 1    │ MSSQL 스키마 생성          │ DBA에게 schema.sql 전달 → 테이블 생성 확인                │
├──────┼────────────────────────────┼───────────────────────────────────────────────────────────┤
│ 2    │ MSSQL 연결 테스트          │ pyodbc로 원격 서버 연결 및 쿼리 테스트                    │
├──────┼────────────────────────────┼───────────────────────────────────────────────────────────┤
│ 3    │ Gmail 로컬 인증            │ python scripts/setup_gmail_auth.py → token.json 생성     │
├──────┼────────────────────────────┼───────────────────────────────────────────────────────────┤
│ 4    │ Gmail 연동                 │ 컨테이너에서 이메일 목록 조회 성공                        │
├──────┼────────────────────────────┼───────────────────────────────────────────────────────────┤
│ 5    │ ETL + Chroma               │ 이메일 1개 처리 → MSSQL + Chroma에 저장 확인             │
├──────┼────────────────────────────┼───────────────────────────────────────────────────────────┤
│ 6    │ RAG 검색 + Claude          │ curl로 /chat 호출 → 답변 + 출처 확인                     │
├──────┼────────────────────────────┼───────────────────────────────────────────────────────────┤
│ 7    │ Streamlit UI               │ docker-compose up → 브라우저에서 채팅 테스트             │
├──────┼────────────────────────────┼───────────────────────────────────────────────────────────┤
│ 8    │ 전체 통합                  │ 새 뉴스레터 수신 → 자동 수집 → 질문 답변 E2E 확인        │
└──────┴────────────────────────────┴───────────────────────────────────────────────────────────┘

---
참고 자료

- https://developers.google.com/workspace/gmail/api/quickstart/python
- https://learn.microsoft.com/en-us/sql/connect/python/pyodbc/python-sql-driver-pyodbc
- https://docs.trychroma.com/
- https://docs.anthropic.com/en/docs/build-with-claude/citations
- https://www.firecrawl.dev/blog/best-chunking-strategies-rag-2025
