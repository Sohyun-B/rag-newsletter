# Newsletter RAG System

Gmail 뉴스레터를 자동으로 수집하고, RAG(Retrieval-Augmented Generation) 기반으로 질문에 답변하는 시스템입니다.

## 주요 기능

- **Gmail 자동 수집**: 프로모션/뉴스레터 라벨 이메일 자동 수집 (5분 주기)
- **RAG 검색**: 뉴스레터 내용 기반 유사도 검색
- **Claude Citations**: 출처 명시와 함께 답변 생성
- **Streamlit 채팅 UI**: 웹 기반 대화형 인터페이스

## 기술 스택

| 구분 | 기술 |
|------|------|
| Backend | FastAPI (Python 3.12) |
| Frontend | Streamlit |
| LLM | Claude (Anthropic API, Citations 활용) |
| Embedding | OpenAI text-embedding-3-small |
| Vector DB | Chroma (로컬 파일) |
| Meta DB | MSSQL (원격 서버) |
| Infra | Docker Compose |

## 프로젝트 구조

```
RAG/
├── docker-compose.yml
├── .env.example
├── backend/
│   ├── main.py              # FastAPI 앱 (엔드포인트 정의)
│   ├── config.py            # 환경변수 설정
│   ├── scheduler.py         # APScheduler (5분 주기 동기화)
│   ├── db/                  # MSSQL 연결 및 쿼리
│   ├── gmail/               # Gmail API 연동
│   ├── etl/                 # 전처리, 청킹, 임베딩
│   ├── vectorstore/         # Chroma 벡터 저장소
│   └── rag/                 # 검색 + Claude 답변 생성
├── frontend/
│   └── app.py               # Streamlit 채팅 UI
├── scripts/
│   └── setup_gmail_auth.py  # Gmail OAuth 인증 스크립트
└── chroma_data/             # Chroma 벡터 데이터 (볼륨)
```

## 구현 현황

### Backend API

| 엔드포인트 | 메서드 | 설명 | 상태 |
|------------|--------|------|------|
| `/health` | GET | 시스템 헬스체크 (MSSQL, Chroma, Gmail) | ✅ |
| `/chat` | POST | RAG 기반 질문 답변 | ✅ |
| `/sync` | POST | 수동 Gmail 동기화 + ETL | ✅ |
| `/newsletters` | GET | 뉴스레터 목록 조회 | ✅ |
| `/newsletters/{id}` | GET | 뉴스레터 상세 조회 | ✅ |
| `/stats` | GET | 시스템 통계 | ✅ |

### 핵심 모듈

| 모듈 | 기능 | 상태 |
|------|------|------|
| Gmail Fetcher | 뉴스레터 필터링 및 수집 | ✅ |
| ETL Pipeline | HTML 전처리 → 청킹 → 임베딩 | ✅ |
| Vector Search | Chroma 유사도 검색 | ✅ |
| Claude Agent | Citations API 답변 생성 | ✅ |
| Scheduler | 5분 주기 자동 동기화 | ✅ |

### Frontend

| 기능 | 상태 |
|------|------|
| 채팅 인터페이스 | ✅ |
| 출처(Citations) 표시 | ✅ |
| 시스템 상태 모니터링 | ✅ |
| 수동 동기화 버튼 | ✅ |
| 최근 뉴스레터 목록 | ✅ |

## 시작하기

### 사전 준비

1. **Google Cloud Console**에서 Gmail API 활성화 및 OAuth 클라이언트 생성
2. `credentials.json`을 `backend/gmail/`에 배치
3. API 키 발급: OpenAI, Anthropic
4. MSSQL 서버에 스키마 생성 (`backend/db/schema.sql` 참고)

### 환경 설정

```bash
# .env 파일 생성
cp .env.example .env

# .env 파일 편집
MSSQL_SERVER=your-server
MSSQL_DATABASE=your-db
MSSQL_USER=your-user
MSSQL_PASSWORD=your-password
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
```

### Gmail 인증 (최초 1회)

```bash
python scripts/setup_gmail_auth.py
```

브라우저에서 Google 로그인 후 `token.json`이 생성됩니다.

### 실행

```bash
docker-compose up --build
```

- Backend API: http://localhost:8000
- Frontend UI: http://localhost:8501
- API 문서: http://localhost:8000/docs

## 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                    Docker Compose                           │
│  ┌─────────────────┐         ┌─────────────────┐           │
│  │    Backend      │◄───────►│    Frontend     │           │
│  │   (FastAPI)     │         │   (Streamlit)   │           │
│  │   :8000         │         │   :8501         │           │
│  └────────┬────────┘         └─────────────────┘           │
│           │                                                 │
│           ▼                                                 │
│  ┌─────────────────┐                                       │
│  │  Chroma (파일)  │  ← 벡터 임베딩                        │
│  └─────────────────┘                                       │
└───────────────────────────────┬─────────────────────────────┘
                                │
                                ▼
                   ┌────────────────────────┐
                   │   원격 MSSQL Server    │
                   │   (메타데이터 저장)    │
                   └────────────────────────┘
```

## 설정 상세

### 뉴스레터 필터

```
category:promotions OR label:newsletter
```

Gmail에서 프로모션 탭 또는 newsletter 라벨이 있는 이메일을 수집합니다.

### 청킹 설정

- **방식**: RecursiveCharacterTextSplitter
- **크기**: 512 토큰
- **오버랩**: 50 토큰

### 재시도 정책

API 호출 실패 시 지수 백오프로 재시도합니다.
- 최대 3회
- 대기 시간: 1초 → 2초 → 4초

## 라이선스

MIT License
