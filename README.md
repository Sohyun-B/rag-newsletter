# Newsletter RAG System

Gmail 뉴스레터를 자동으로 수집하고, RAG(Retrieval-Augmented Generation) 기반으로 질문에 답변하는 시스템입니다.

## 주요 기능

- **Gmail 자동 수집**: 발신인 기반 이메일 수집 (5분 주기 스케줄러)
- **쿼리 분석**: gpt-4o-mini로 질문 의도 분류 → 단순/비교/복합 등 7가지 유형 처리
- **RAG 검색**: HyDE + Multi-Query + 병렬 서브쿼리 검색
- **멀티턴 대화**: 이전 대화 맥락을 반영한 연속 질문 지원
- **Streamlit 채팅 UI**: 쿼리 분석 파이프라인 시각화 + 출처 표시

## 기술 스택

| 구분 | 기술 |
|------|------|
| Backend | FastAPI (Python 3.12) |
| Frontend | Streamlit |
| LLM | OpenAI gpt-4o-mini (쿼리 분석 + 답변 생성) |
| Embedding | OpenAI text-embedding-3-small (1536차원) |
| Vector DB | Chroma (로컬 파일, 코사인 유사도) |
| Meta DB | MSSQL (원격 서버, newsletter 스키마) |
| Infra | Docker Compose |

## 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                    Docker Compose (로컬)                     │
│  ┌─────────────────┐         ┌─────────────────┐            │
│  │    Backend      │◄───────►│    Frontend     │            │
│  │   (FastAPI)     │         │   (Streamlit)   │            │
│  │   :8000         │         │   :8501         │            │
│  └────────┬────────┘         └─────────────────┘            │
│           │                                                  │
│           ▼                                                  │
│  ┌─────────────────┐                                        │
│  │  Chroma (파일)  │  ← 벡터 임베딩 (./chroma_data)         │
│  └─────────────────┘                                        │
└───────────────────────────────┬──────────────────────────────┘
                                │
                                ▼
                   ┌────────────────────────┐
                   │   원격 MSSQL Server    │
                   │ (이메일/청크 메타데이터)│
                   └────────────────────────┘
```

## RAG 파이프라인

```
질문
 │
 ▼
gpt-4o-mini 쿼리 분석
 ├─ needs_retrieval=false → 직접 답변
 └─ needs_retrieval=true
     ├─ query_type 분류 (simple / comparison / aggregation / ...)
     ├─ sub_queries 생성 (1~4개)
     └─ 각 서브쿼리: HyDE + Multi-Query + 원본 → 배치 임베딩
         │
         ├─ 필터 있음: MSSQL pre-filter → email_ids → Chroma $in 검색
         └─ 필터 없음: Chroma 전체 검색
             │
             ▼
         결과 병합 (중복 제거, 점수순 정렬)
             │
             ▼
         gpt-4o-mini 답변 생성 [인용 번호 [1][2] 형식]
```

## 프로젝트 구조

```
RAG/
├── docker-compose.yml
├── .env                          # API 키, DB 접속 정보 (.gitignore)
├── .env.example
├── backend/
│   ├── main.py                   # FastAPI 앱 진입점 + 스케줄러 시작
│   ├── config.py                 # pydantic-settings 환경변수 (SYNC_SENDERS 포함)
│   ├── scheduler.py              # APScheduler 주기적 Gmail 폴링
│   ├── db/
│   │   ├── connection.py         # MSSQL 연결 (pyodbc, DATETIMEOFFSET 핸들링)
│   │   ├── queries.py            # SQL 쿼리 함수
│   │   ├── schema.sql            # MSSQL 스키마 (DBA 전달용)
│   │   └── create_view.sql       # 뷰 생성 SQL
│   ├── gmail/
│   │   ├── auth.py               # Gmail OAuth2 인증/토큰 갱신
│   │   ├── fetcher.py            # 뉴스레터 수집 (쿼리 기반 + 발신인 기반)
│   │   ├── credentials.json      # Google OAuth 클라이언트 (.gitignore)
│   │   └── token.json            # OAuth 토큰 (.gitignore, 볼륨 마운트)
│   ├── etl/
│   │   ├── preprocessor.py       # HTML→텍스트, 풋터 제거, 패턴 정리
│   │   ├── chunker.py            # RecursiveCharacterTextSplitter (512토큰, 50오버랩)
│   │   ├── embedder.py           # OpenAI 임베딩 (배치 100개)
│   │   └── pipeline.py           # ETL 오케스트레이션
│   ├── vectorstore/
│   │   └── chroma_store.py       # Chroma 벡터 저장소
│   ├── rag/
│   │   ├── query_analyzer.py     # 쿼리 분석 (Routing + HyDE + Multi-Query + 분해)
│   │   ├── search.py             # 벡터 검색 + MSSQL 메타데이터 조회
│   │   └── agent.py              # 답변 생성 (단순/구조화)
│   └── utils/
│       └── retry.py              # 지수 백오프 재시도 (sync/async 자동 감지)
├── frontend/
│   └── app.py                    # Streamlit 채팅 UI
├── scripts/
│   └── setup_gmail_auth.py       # 로컬 Gmail OAuth 인증 스크립트
└── chroma_data/                  # Chroma 벡터 데이터 (Docker 볼륨)
```

## 시작하기

### 사전 준비

1. **Google Cloud Console**에서 프로젝트 생성 + Gmail API 활성화
2. OAuth 2.0 클라이언트 ID 생성 (데스크톱 앱) → `credentials.json` 다운로드 → `backend/gmail/`에 배치
3. DBA에게 `backend/db/schema.sql` 전달하여 MSSQL 테이블 생성 요청
4. OpenAI API 키 발급

### 환경 설정

```bash
cp .env.example .env
```

`.env` 파일 편집:

```env
# MSSQL
MSSQL_SERVER=192.168.1.100,1433
MSSQL_DATABASE=project_pm
MSSQL_USER=sa
MSSQL_PASSWORD=your-password

# OpenAI
OPENAI_API_KEY=sk-proj-...

# 선택 설정 (기본값 있음)
# SYNC_INTERVAL_MINUTES=5
# SYNC_SENDERS=sender1@example.com,sender2@example.com
```

### Gmail 인증 (최초 1회, 로컬에서 실행)

```bash
python scripts/setup_gmail_auth.py
```

브라우저에서 Google 로그인 후 `backend/gmail/token.json`이 생성됩니다.

### 실행

```bash
docker-compose up --build
```

| 서비스 | URL |
|--------|-----|
| Frontend UI | http://localhost:8501 |
| Backend API | http://localhost:8000 |
| API 문서 | http://localhost:8000/docs |

## API 엔드포인트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/chat` | RAG 채팅 (쿼리 분석 → 검색 → 답변) |
| POST | `/sync` | 수동 Gmail 동기화 + ETL (SYNC_SENDERS 기준) |
| POST | `/sync/senders` | 발신인 지정 동기화 + ETL |
| GET | `/newsletters` | 뉴스레터 목록 (skip, limit) |
| GET | `/newsletters/{id}` | 뉴스레터 상세 |
| GET | `/stats` | 시스템 통계 (뉴스레터 수, 벡터 수, 스케줄러 상태) |
| GET | `/health` | 헬스체크 (MSSQL, Chroma, Gmail) |

### `/chat` 요청 형식

```json
{
  "query": "트럼프 관세 관련 뉴스 알려줘",
  "history": [
    {"role": "user", "content": "이전 질문"},
    {"role": "assistant", "content": "이전 답변"}
  ]
}
```

## 설정 상세

### 동기화 대상 발신인 (SYNC_SENDERS)

`config.py`의 기본값:
```
whatsup@newneek.co, dig@mk.co.kr, nytdirect@nytimes.com,
letter@khan.kr, contact@datarian.io, ...
```

환경변수 `SYNC_SENDERS`로 덮어쓸 수 있습니다 (쉼표 구분).

### 쿼리 유형 분류

| 유형 | 설명 | 예시 |
|------|------|------|
| simple | 단일 주제 | "AI 트렌드 알려줘" |
| comparison | 두 대상 비교 | "뉴닉과 한겨레의 트럼프 보도 차이" |
| aggregation | 요약/정리 | "이번 주 주요 뉴스 정리" |
| temporal_comparison | 시간대별 비교 | "1월과 2월 시장 동향 비교" |
| multi_topic | 여러 주제 | "AI와 반도체 관련 뉴스" |
| opinion | 논조/관점 분석 | "AI 규제에 대한 뉴스레터 논조" |
| multi_hop | 연쇄 추론 | "A가 보도한 B 기술이 C에 미치는 영향" |

### 재시도 정책

API 호출 실패 시 지수 백오프 재시도 (sync/async 모두 적용):
- 최대 3회, 대기 시간: 1초 → 2초 → 4초

## MSSQL 스키마

```sql
newsletter.raw_email       -- 원본 이메일 (gmail_id UNIQUE)
newsletter.email_chunks    -- ETL 청크 (chroma_id로 Chroma와 연결)
newsletter.sync_state      -- Gmail 동기화 히스토리 ID
newsletter.vw_chunks_with_email  -- 청크+이메일 조인 뷰
```

전체 DDL: `backend/db/schema.sql`
