
Newsletter RAG System - 구현 명세

기술 스택 요약
┌────────────┬────────────────────────────────┬──────────────────────────────────────┐
│    항목    │              선택              │                 비고                 │
├────────────┼────────────────────────────────┼──────────────────────────────────────┤
│ 이메일     │ Gmail API (자동 수집)          │ OAuth2, gmail.readonly 스코프        │
├────────────┼────────────────────────────────┼──────────────────────────────────────┤
│ 인프라     │ Docker Compose (로컬)          │ Backend + Frontend 컨테이너          │
├────────────┼────────────────────────────────┼──────────────────────────────────────┤
│ LLM        │ OpenAI gpt-4o-mini             │ 쿼리 분석 + 답변 생성 모두 사용      │
├────────────┼────────────────────────────────┼──────────────────────────────────────┤
│ 임베딩     │ OpenAI text-embedding-3-small  │ 1536차원, $0.02/1M tokens            │
├────────────┼────────────────────────────────┼──────────────────────────────────────┤
│ 메타DB     │ MSSQL (원격 서버)              │ 이메일/청크 메타데이터 저장          │
├────────────┼────────────────────────────────┼──────────────────────────────────────┤
│ 벡터DB     │ Chroma (로컬 파일)             │ Backend 내장, 벡터 임베딩 저장       │
├────────────┼────────────────────────────────┼──────────────────────────────────────┤
│ 백엔드     │ Python FastAPI                 │ pyodbc로 MSSQL 연결                  │
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
│ 이메일 수집      │ 발신인 기반 수집 (SYNC_SENDERS 목록)                        │
│                  │ + category:promotions OR label:newsletter 쿼리 수집         │
├──────────────────┼─────────────────────────────────────────────────────────────┤
│ OAuth 인증 방식  │ 로컬에서 먼저 인증 후 token.json을 Docker 볼륨에 마운트     │
├──────────────────┼─────────────────────────────────────────────────────────────┤
│ 재시도 정책      │ 지수 백오프 (최대 3회, 1초→2초→4초), sync/async 자동 감지   │
├──────────────────┼─────────────────────────────────────────────────────────────┤
│ Citations 렌더링 │ 인용 번호 표시 + 확장 패널로 출처 상세 표시                 │
├──────────────────┼─────────────────────────────────────────────────────────────┤
│ DB 아키텍처      │ MSSQL(직접 연결, 메타데이터) + Chroma(로컬 파일, 벡터)      │
├──────────────────┼─────────────────────────────────────────────────────────────┤
│ DB 스키마        │ newsletter (newsletter.raw_email, newsletter.email_chunks)  │
├──────────────────┼─────────────────────────────────────────────────────────────┤
│ 쿼리 분석       │ gpt-4o-mini JSON mode로 질문 → 검색 계획 생성               │
│                  │ Simple Routing + HyDE + Multi-Query 적용                    │
│                  │ LLM이 직접 날짜(YYYY-MM-DD) 계산, 서술형 쿼리 변환         │
├──────────────────┼─────────────────────────────────────────────────────────────┤
│ 메타데이터 필터  │ MSSQL pre-filter → Chroma where 필터 ($in email_id)        │
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
RAG 검색 파이프라인

```
질문 → gpt-4o-mini 쿼리 분석 → 조건부 검색 → gpt-4o-mini 답변
              │                      │
              ├ needs_retrieval       │  (false → 직접 답변, true → 아래 실행)
              ├ rewritten_query      ├ 필터 있으면: MSSQL pre-filter → Chroma where 검색
              ├ hypothetical_document├ 필터 없으면: Chroma 전체 검색
              ├ alternative_queries  └ HyDE + Multi-Query + 원본 쿼리 → 배치 임베딩 → 각각 검색 → 결과 병합
              ├ date_from (YYYY-MM-DD)
              ├ date_to (YYYY-MM-DD)
              ├ sender_filter
              └ keywords
```

---
프로젝트 구조

RAG/
├── docker-compose.yml
├── .env                          # API 키, DB 접속 정보
├── .env.example
├── .gitignore
├── CLAUDE.md
├── CHANGELOG.md
├── README.md
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py                   # FastAPI 앱 진입점 + 스케줄러 시작
│   ├── config.py                 # pydantic-settings 기반 환경변수 (SYNC_SENDERS 포함)
│   ├── scheduler.py              # APScheduler 발신인 기반 주기적 Gmail 폴링
│   ├── db/
│   │   ├── __init__.py
│   │   ├── schema.sql            # MSSQL 스키마 (DBA 전달용)
│   │   ├── create_view.sql       # 뷰 생성 SQL
│   │   ├── verify_schema.sql     # 스키마 검증 SQL
│   │   ├── connection.py         # MSSQL 연결 (pyodbc, DATETIMEOFFSET 핸들링)
│   │   └── queries.py            # SQL 쿼리 함수들
│   ├── gmail/
│   │   ├── __init__.py
│   │   ├── auth.py               # Gmail OAuth2 인증/토큰 갱신
│   │   ├── fetcher.py            # 뉴스레터 가져오기 (쿼리 기반 + 발신인 기반)
│   │   ├── credentials.json      # Google OAuth 클라이언트 (.gitignore)
│   │   └── token.json            # OAuth 토큰 (.gitignore, Docker 볼륨 마운트)
│   ├── etl/
│   │   ├── __init__.py
│   │   ├── preprocessor.py       # HTML→텍스트, 풋터 자동 감지/제거, 패턴 정리
│   │   ├── chunker.py            # 텍스트 청킹
│   │   ├── embedder.py           # OpenAI 임베딩 생성 (배치 처리)
│   │   └── pipeline.py           # ETL 전체 파이프라인 오케스트레이션
│   ├── vectorstore/
│   │   ├── __init__.py
│   │   └── chroma_store.py       # Chroma 벡터 저장소 관리
│   ├── rag/
│   │   ├── __init__.py
│   │   ├── query_analyzer.py     # gpt-4o-mini 쿼리 분석 (Routing + HyDE + Multi-Query)
│   │   ├── search.py             # 다중 임베딩 벡터 검색 + MSSQL 메타데이터 조회 (필터 지원)
│   │   └── agent.py              # OpenAI Chat Completions 답변 생성 + 직접 답변
│   └── utils/
│       ├── __init__.py
│       └── retry.py              # 지수 백오프 재시도 유틸리티 (sync/async 자동 감지)
├── frontend/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app.py                    # Streamlit 채팅 UI (파이프라인 시각화 포함)
├── chroma_data/                  # Chroma 벡터 데이터 (Docker 볼륨)
├── docs/                         # 리서치 문서
└── scripts/
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
      - ./backend/gmail/token.json:/app/gmail/token.json
      - ./chroma_data:/app/chroma_data    # Chroma 벡터 데이터 영속화
    restart: unless-stopped

  frontend:
    build: ./frontend
    env_file: .env
    ports:
      - "8501:8501"
    depends_on:
      - backend
    restart: unless-stopped

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

# MSSQL ODBC 드라이버 설치 (Debian 12 bookworm)
RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    unixodbc-dev \
    && curl https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && curl https://packages.microsoft.com/config/debian/12/prod.list > /etc/apt/sources.list.d/mssql-release.list \
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

DATETIMEOFFSET 타입을 struct.unpack으로 파싱하여 Python datetime으로 변환.
pyodbc output_converter로 자동 변환 등록.

import pyodbc
import struct
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from config import settings

def _handle_datetimeoffset(dto_value):
    """DATETIMEOFFSET 타입 처리"""
    tup = struct.unpack("<6hI2h", dto_value)
    return datetime(tup[0], tup[1], tup[2], tup[3], tup[4], tup[5], tup[6] // 1000,
                    timezone(timedelta(hours=tup[7], minutes=tup[8])))

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
    """DB 연결 컨텍스트 매니저 (DATETIMEOFFSET 변환기 포함)"""
    conn = pyodbc.connect(get_connection_string())
    conn.add_output_converter(-155, _handle_datetimeoffset)
    try:
        yield conn
    finally:
        conn.close()

def execute_query(query: str, params: tuple = None):
    """SELECT 쿼리 실행"""

def execute_command(query: str, params: tuple = None) -> int:
    """INSERT/UPDATE/DELETE 실행, 영향받은 행 수 반환"""

def execute_insert_returning_id(query: str, params: tuple = None) -> int:
    """INSERT 후 SCOPE_IDENTITY()로 생성된 ID 반환"""

def test_connection() -> bool:
    """DB 연결 테스트"""

2-2. db/queries.py - SQL 쿼리 함수들

- insert_email(): 새 이메일 삽입 (gmail_id 중복 체크)
- get_unprocessed_emails(): processed=0인 이메일 조회
- mark_email_processed(): 이메일 처리 완료 표시
- insert_chunk(): 청크 삽입 (email_id, chroma_id 포함)
- get_chunks_by_chroma_ids(): Chroma ID로 청크 + 이메일 메타데이터 JOIN 조회
- get_sync_state() / update_sync_state(): 동기화 상태 관리
- get_newsletters(): 뉴스레터 목록 (페이징)
- get_newsletter_by_id(): 개별 뉴스레터 상세
- get_newsletter_count(): 총 개수
- get_email_ids_by_filters(): 날짜/발신인 필터로 email_id 목록 조회

2-3. vectorstore/chroma_store.py - Chroma 벡터 저장소

로컬 파일 기반 PersistentClient, 코사인 유사도 사용.

- add_embeddings(): 벡터 임베딩 추가
- search_similar(): 전체 유사 벡터 검색
- search_similar_filtered(): email_id $in 필터 적용 검색
- generate_chroma_id(): UUID v4 생성
- delete_by_ids(): ID로 벡터 삭제
- get_collection_count(): 컬렉션 벡터 수 조회

---
Step 3: Gmail 연동

3-1. 사전 준비 (수동)

1. https://console.cloud.google.com/에서 프로젝트 생성
2. Gmail API 활성화
3. OAuth 2.0 클라이언트 ID 생성 (데스크톱 앱 유형)
4. credentials.json 다운로드 → backend/gmail/credentials.json에 배치

3-2. 로컬 OAuth 인증 (Docker 실행 전 필수)

scripts/setup_gmail_auth.py 실행하여 token.json 생성.

3-3. gmail/auth.py

- get_gmail_service(): Gmail API 서비스 객체 반환 (토큰 만료 시 자동 갱신 + 저장)
- test_gmail_connection(): Gmail 연결 테스트 (라벨 목록 조회)

3-4. gmail/fetcher.py

두 가지 수집 방식:

1. fetch_new_newsletters(): 쿼리 기반 수집
   - 쿼리 필터: 'category:promotions OR label:newsletter'
   - messages.list로 최근 N개 조회
   - 각 메시지의 subject, from, body(html/text), date 추출
   - raw_email 테이블에 INSERT (gmail_id UNIQUE로 중복 방지)

2. fetch_emails_by_senders(): 발신인 기반 수집
   - SYNC_SENDERS 목록의 각 발신인별로 from:{sender} 쿼리
   - 페이지네이션으로 과거 이메일까지 수집 (발신인당 최대 500개)

헬퍼 함수:
- decode_base64(): Base64 URL-safe 디코딩
- extract_header(): 헤더에서 특정 값 추출
- extract_body(): 멀티파트 이메일 본문 재귀 추출 (HTML + Plain Text)
- extract_labels(): 내부 라벨 제외
- parse_date(): 이메일 날짜 파싱

3-5. scheduler.py

APScheduler BackgroundScheduler로 주기적 동기화.
발신인 기반 Gmail 동기화 + ETL 처리를 SYNC_INTERVAL_MINUTES 간격으로 실행.
sync 함수에서 asyncio.new_event_loop()로 비동기 ETL 처리 호출.

---
Step 4: ETL 파이프라인

4-1. utils/retry.py - 지수 백오프 재시도 유틸리티

async/sync 자동 감지 데코레이터.
asyncio.iscoroutinefunction()으로 대상 함수 타입 판별,
async 함수면 await + asyncio.sleep, sync 함수면 time.sleep 사용.

4-2. etl/preprocessor.py - HTML → 텍스트 변환

def preprocess_email(html_body: str, text_body: str) -> str:
    """
    1. HTML 우선 사용 (50자 이상), 없으면 text_body 사용
    2. BeautifulSoup으로 파싱
    3. 불필요 요소 제거: script, style, footer, nav, aside, header
    4. 1픽셀 트래킹 이미지, display:none 요소, 구독해지 링크 제거
    5. 이미지 alt 텍스트: 콘텐츠성 alt만 [이미지: alt] 형태로 보존
    6. 불필요 텍스트 패턴 제거 (구독/수신, 브라우저/앱 보기, 저작권 등)
    7. 풋터 자동 감지 및 절삭 (마지막 50줄 내 시그널 패턴 탐색, 70% 안전장치)
    8. 연속 공백/빈줄 정리
    """

풋터 감지 시그널: 주소 패턴, 구독 관리, 플랫폼 브랜딩, 프로모션 등 약 30개 패턴.
이미지 alt 필터: 소셜 미디어, UI 아이콘 등 무의미한 alt 텍스트 18개+ 키워드로 필터링.

4-3. etl/chunker.py - 텍스트 청킹

from langchain_text_splitters import RecursiveCharacterTextSplitter

splitter = RecursiveCharacterTextSplitter(
    chunk_size=512,
    chunk_overlap=50,
    separators=["\n\n", "\n", ". ", "? ", "! ", " "],
)

def chunk_email(text: str, metadata: dict) -> list[dict]:
    """텍스트를 청크로 분할, 각 청크에 메타데이터(subject, from_address, received_at, email_id, chunk_index, total_chunks) 첨부"""

4-4. etl/embedder.py - 임베딩 생성

from openai import AsyncOpenAI

EMBEDDING_MODEL = "text-embedding-3-small"
MAX_BATCH_SIZE = 100

@with_retry(max_retries=3, base_delay=1.0)
async def embed_chunks(texts: list[str]) -> list[list[float]]:
    """배치 처리로 OpenAI 임베딩 생성 (100개씩 분할)"""

@with_retry(max_retries=3, base_delay=1.0)
async def embed_single(text: str) -> list[float]:
    """단일 텍스트 임베딩"""

4-5. etl/pipeline.py - ETL 전체 흐름

async def process_single_email(email: dict) -> dict:
    """
    단일 이메일 처리:
    1. preprocess_email() → 정제된 텍스트
    2. chunk_email() → 청크 리스트
    3. embed_chunks() → 임베딩 리스트
    4. Chroma에 벡터 저장 (개별 add_embeddings 호출)
    5. MSSQL email_chunks에 INSERT (chroma_id 포함)
    6. raw_email.processed = 1로 업데이트
    """

async def process_unprocessed_emails(limit: int = 100) -> dict:
    """미처리 이메일 일괄 처리, 결과 요약 반환"""

---
Step 5: 쿼리 분석 + RAG 검색 + 답변

5-0. rag/query_analyzer.py - LLM 쿼리 분석 (Routing + HyDE + Multi-Query)

gpt-4o-mini에 JSON mode로 요청하여 검색 계획을 생성한다.
LLM이 오늘 날짜와 요일을 기준으로 직접 YYYY-MM-DD 날짜를 계산한다.

@dataclass
class QueryAnalysis:
    needs_retrieval: bool           # Simple Routing: 검색 필요 여부
    rewritten_query: str            # 검색용 서술형 변환
    hypothetical_document: str|None # HyDE: 가상 답변 문서 (150자 내외)
    multi_queries: list[str]        # Multi-Query: 쿼리 변형 3개
    date_from: date | None          # 시작 날짜 (LLM이 직접 계산)
    date_to: date | None            # 종료 날짜 (LLM이 직접 계산)
    sender_filter: str | None       # 발신인 필터
    keywords: list[str]             # 핵심 키워드

Routing 규칙:
- needs_retrieval=true: 뉴스레터 정보/콘텐츠에 대한 질문
- needs_retrieval=false: 인사말, 감사 표현, 시스템 관련 질문 → 직접 답변

HyDE 규칙:
- needs_retrieval=true일 때만 가상 답변 문서 생성 (150자 내외 서술형)
- 실제 뉴스레터 본문처럼 작성하여 벡터 검색 정확도 향상

Multi-Query 규칙:
- needs_retrieval=true일 때만 3개 쿼리 변형 생성
- 동의어, 다른 관점, 다른 표현으로 변형

날짜 필터 규칙:
- 명시적인 시간 표현이 있을 때만 설정 ("오늘", "최근", "지난주", "1월" 등)
- "~있어?", "~알려줘" 같은 질문 어미는 시간 표현이 아님 → null
- 확실한 시간 표현 없으면 반드시 null (과도한 필터 방지)

실패 시 fallback: needs_retrieval=true, 원본 query, 필터 없음.

5-1. rag/search.py - 다중 임베딩 벡터 검색 (HyDE + Multi-Query + 필터)

async def search_similar_chunks(
    query: str,
    hypothetical_doc: str | None = None,
    multi_queries: list[str] | None = None,
    top_k: int = 10,
    score_threshold: float = 0.3,
    date_from: date | None = None,
    date_to: date | None = None,
    sender: str | None = None,
) -> list[dict]:
    """
    1. 필터 존재 시: MSSQL에서 email_ids 조회 (get_email_ids_by_filters)
       - 필터 결과 0건이면 필터 없는 전체 검색으로 fallback
    2. 검색 텍스트 수집: [HyDE 문서] + [Multi-Query 변형들] + [원본 쿼리]
    3. 배치 임베딩 (1회 API 호출)
    4. 각 임베딩으로 Chroma 검색 + 결과 병합 (chroma_id 기준, best distance 유지)
    5. MSSQL에서 chroma_id로 메타데이터 조회
    6. 코사인 거리 → 유사도 점수 변환: score = 1 - (distance / 2)
    7. 점수 임계값 필터링 (>= 0.3)
    8. 점수 기준 정렬 (높은 순) + top_k 제한
    """

5-2. rag/agent.py - OpenAI Chat Completions 답변 생성

MODEL = "gpt-4o-mini"

@with_retry(max_retries=3, base_delay=1.0)
def generate_answer(query: str, chunks: list[dict]) -> dict:
    """검색된 청크 기반 답변 생성 (인용 번호 [1], [2] 형식)"""
    # 청크 없으면 '관련 뉴스레터를 찾지 못했습니다' 반환
    # 컨텍스트: [문서 1] 제목 (발신인, 날짜)\n내용 형식

@with_retry(max_retries=3, base_delay=1.0)
def generate_direct_answer(query: str) -> dict:
    """검색 불필요 시 직접 답변 (인사말, 시스템 질문 등)"""

def parse_citations_response(content: str, sources: list[dict]) -> dict:
    """응답을 프론트엔드 표시용으로 파싱"""
    # {text: 답변, citations: [{index, cited_text, document_index, source: {subject, from_address, received_at}}]}

---
Step 6: FastAPI 엔드포인트

main.py - Lifespan으로 스케줄러 시작/종료 관리, CORS 전체 허용.

class ChatRequest(BaseModel):
    query: str

class QueryAnalysisInfo(BaseModel):
    original_query: str
    needs_retrieval: bool
    rewritten_query: str
    hypothetical_document: str | None = None
    multi_queries: list[str] = []
    date_from: str | None = None
    date_to: str | None = None
    sender_filter: str | None = None
    keywords: list[str] = []
    chunks_found: int = 0

class ChatResponse(BaseModel):
    text: str
    citations: list[dict]
    sources: list[dict]
    analysis: QueryAnalysisInfo | None = None

엔드포인트 목록:

POST /chat           - RAG 채팅 (쿼리 분석 → 조건부 검색 → 답변 생성)
POST /sync           - 수동 Gmail 동기화 + ETL (설정된 SYNC_SENDERS 기준)
POST /sync/senders   - 발신인 지정 동기화 + ETL
GET  /newsletters    - 뉴스레터 목록 (페이징: skip, limit)
GET  /newsletters/{id} - 개별 뉴스레터 상세
GET  /stats          - 시스템 통계 (뉴스레터 수, 벡터 수, 스케줄러 상태)
GET  /health         - 헬스체크 (MSSQL, Chroma, Gmail 연결 확인)
GET  /               - 루트 (API 정보)

/chat 엔드포인트 흐름:
1. analyze_query() → QueryAnalysis (routing, HyDE, multi-query, 필터)
2. needs_retrieval=false → generate_direct_answer()
   needs_retrieval=true  → search_similar_chunks() → generate_answer()
3. parse_citations_response() → ChatResponse (분석 중간과정 포함)

---
Step 7: Streamlit 채팅 UI

frontend/app.py - BACKEND_URL 환경변수 지원 (기본값: http://backend:8000).

사이드바:
- 시스템 상태: 뉴스레터 수, 벡터 수, 스케줄러 상태 (새로고침 버튼)
- 동기화: "지금 동기화" 버튼 (최대 10분 타임아웃)
- 최근 뉴스레터: 최근 5개 목록 (제목, 발신인, 날짜, 처리 상태)

채팅 인터페이스:
- st.chat_message로 대화 표시
- 쿼리 분석 파이프라인 시각화 (5단계):
  1. Routing: 검색 필요/불필요 판단
  2. Query Rewrite: 원본 → 변환된 검색어
  3. HyDE: 가상 답변 문서
  4. Multi-Query: 쿼리 변형 목록
  5. 검색 실행: 필터 + 결과 청크 수
- 출처 보기: 인용 번호, 제목, 발신인, 날짜
- 대화 초기화 버튼

---
환경변수 (.env)

# MSSQL (직접 연결)
MSSQL_SERVER=192.168.1.100,1433      # IP,포트 또는 hostname,포트
MSSQL_DATABASE=project_pm
MSSQL_USER=sa
MSSQL_PASSWORD=YourStrongPassword123!

# OpenAI (임베딩 + 쿼리 분석 + 답변 생성)
OPENAI_API_KEY=sk-proj-...

# 선택 설정 (기본값 있음)
# CHROMA_PATH=./chroma_data
# GMAIL_TOKEN_PATH=./gmail/token.json
# GMAIL_CREDENTIALS_PATH=./gmail/credentials.json
# SYNC_INTERVAL_MINUTES=5

# 동기화 대상 발신인 (config.py에 기본값 설정됨)
# SYNC_SENDERS 기본값:
#   whatsup@newneek.co, dig@mk.co.kr, nytdirect@nytimes.com,
#   nytimes@e.newyorktimes.com, editorpicks@nytimes.com,
#   newsletters@theatlantic.com, modulabs01-gmail.com@send.stibee.com,
#   letter@khan.kr, contact@datarian.io

---
.gitignore

# API Keys & Secrets
.env
backend/gmail/credentials.json
backend/gmail/token.json

# Chroma Data
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

- [x] Google Cloud Console 프로젝트 생성 + Gmail API 활성화
- [x] OAuth 2.0 클라이언트 ID 생성 → credentials.json 다운로드
- [x] credentials.json을 backend/gmail/에 배치
- [x] OpenAI API 키 발급
- [x] Docker Desktop 설치 및 실행 확인
- [x] 원격 MSSQL 서버 접속 정보 확인
- [x] DBA에게 backend/db/schema.sql 전달하여 테이블 생성 요청
- [x] python scripts/setup_gmail_auth.py 실행하여 token.json 생성

---
구현 완료 현황
┌──────┬────────────────────────────────┬────────┐
│ 단계 │         구현 내용              │  상태  │
├──────┼────────────────────────────────┼────────┤
│ 1    │ MSSQL 스키마 생성              │  완료  │
├──────┼────────────────────────────────┼────────┤
│ 2    │ MSSQL 연결 + DATETIMEOFFSET    │  완료  │
├──────┼────────────────────────────────┼────────┤
│ 3    │ Gmail 로컬 인증                │  완료  │
├──────┼────────────────────────────────┼────────┤
│ 4    │ Gmail 연동 (쿼리 + 발신인)    │  완료  │
├──────┼────────────────────────────────┼────────┤
│ 5    │ ETL 파이프라인 + Chroma        │  완료  │
├──────┼────────────────────────────────┼────────┤
│ 6    │ 쿼리 분석 (Routing+HyDE+MQ)   │  완료  │
├──────┼────────────────────────────────┼────────┤
│ 7    │ RAG 검색 + 답변 생성           │  완료  │
├──────┼────────────────────────────────┼────────┤
│ 8    │ FastAPI 엔드포인트             │  완료  │
├──────┼────────────────────────────────┼────────┤
│ 9    │ Streamlit UI (파이프라인 시각화)│  완료  │
├──────┼────────────────────────────────┼────────┤
│ 10   │ 스케줄러 (발신인 기반 자동동기화)│  완료  │
└──────┴────────────────────────────────┴────────┘

---
참고 자료

- https://developers.google.com/workspace/gmail/api/quickstart/python
- https://learn.microsoft.com/en-us/sql/connect/python/pyodbc/python-sql-driver-pyodbc
- https://docs.trychroma.com/
- https://docs.anthropic.com/en/docs/build-with-claude/citations
- https://www.firecrawl.dev/blog/best-chunking-strategies-rag-2025
