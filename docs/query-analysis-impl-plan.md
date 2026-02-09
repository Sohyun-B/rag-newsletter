# 쿼리 분석(Query Analysis) 단계 추가 — Phase 1 구현 계획

## Context
현재 `/chat`은 사용자 질문을 그대로 임베딩하여 Chroma 유사도 검색만 수행한다.
"오늘 트럼프를 언급한 기사가 있었어?" 같은 질문에서 날짜 조건을 무시하고, 질문형 문장이라 유사도도 부정확하다.
LLM이 검색 전에 먼저 질문을 분석하는 단계를 추가한다.

## 현재 흐름 → 변경 후 흐름

```
[현재] 질문 → 임베딩 → Chroma 검색 → LLM 답변

[변경] 질문 → LLM 쿼리분석 → 조건부 검색 → LLM 답변
                  │                  │
                  ├ rewritten_query   ├ date 필터 있으면: MSSQL에서 email_id 조회 → Chroma where 필터 검색
                  ├ date_filter       └ date 필터 없으면: 기존 Chroma 검색 (rewritten_query 사용)
                  ├ sender_filter
                  └ keywords
```

## 핵심 설계 결정

**메타데이터 필터링 전략: MSSQL pre-filter → Chroma where 필터**
- Chroma 메타데이터에 `email_id`(int)가 이미 저장되어 있음 (etl/chunker.py에서 저장)
- 날짜/발신인 필터가 있으면 MSSQL에서 해당 조건의 email_id 목록을 먼저 조회
- Chroma `collection.query(where={"email_id": {"$in": email_ids}})` 로 필터 검색
- 이렇게 하면 날짜 범위 안의 결과만 정확히 반환됨 (post-filter 방식의 누락 문제 없음)

## 변경 파일 (6개)

### 1. `backend/rag/query_analyzer.py` — **신규**
gpt-4o-mini에 JSON mode로 쿼리 분석 요청.

```python
from openai import OpenAI
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json

@dataclass
class QueryAnalysis:
    rewritten_query: str        # 검색용 서술형 변환
    date_from: date | None      # 시작 날짜
    date_to: date | None        # 종료 날짜
    sender_filter: str | None   # 발신인 필터
    keywords: list[str]         # 핵심 키워드

QUERY_ANALYSIS_PROMPT = """사용자의 질문을 분석하여 뉴스레터 검색 계획을 JSON으로 생성하세요.

오늘 날짜: {today}

JSON 형식:
{{
  "rewritten_query": "질문을 검색에 적합한 서술형 문장으로 변환 (예: '트럼프 관련 뉴스레터 기사')",
  "date_filter": "none | today | this_week | last_N_days | YYYY-MM-DD~YYYY-MM-DD",
  "sender_filter": "발신인/뉴스레터 이름 (없으면 null)",
  "keywords": ["핵심", "키워드"]
}}

규칙:
- rewritten_query는 반드시 서술형 문장으로 (질문형 X)
- 시간 표현이 있으면 date_filter에 반영 ("오늘"→"today", "이번주"→"this_week", "최근 3일"→"last_3_days")
- 시간 표현이 없으면 date_filter는 "none"
- sender_filter는 특정 뉴스레터/발신인이 언급된 경우만
```

**날짜 변환 로직** (`_resolve_date_filter`):
- `"today"` → date_from=today, date_to=today
- `"this_week"` → date_from=이번주 월요일, date_to=today
- `"last_N_days"` → date_from=today-N, date_to=today
- `"YYYY-MM-DD~YYYY-MM-DD"` → 파싱
- `"none"` → None, None

### 2. `backend/db/queries.py` — 수정
`get_email_ids_by_filters()` 함수 추가.

```python
def get_email_ids_by_filters(
    date_from: date | None = None,
    date_to: date | None = None,
    sender: str | None = None,
) -> list[int]:
    """날짜/발신인 조건으로 email_id 목록 조회"""
    # WHERE 절 동적 구성
    # received_at BETWEEN ? AND ?
    # from_address LIKE ?
    # SELECT DISTINCT re.id FROM newsletter.raw_email re
    #   INNER JOIN newsletter.email_chunks ec ON ec.email_id = re.id
    # email_chunks에 있는 것만 (Chroma에 벡터가 있는 것)
```

### 3. `backend/vectorstore/chroma_store.py` — 수정
`search_similar_filtered()` 함수 추가.

```python
def search_similar_filtered(
    query_embedding: list[float],
    email_ids: list[int],
    top_k: int = 10,
) -> dict:
    """email_id 필터를 적용한 유사 벡터 검색"""
    return collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        where={"email_id": {"$in": email_ids}},
        include=["documents", "metadatas", "distances"],
    )
```

### 4. `backend/rag/search.py` — 수정
필터 파라미터 수용 + 분기 로직.

```python
async def search_similar_chunks(
    query: str,
    top_k: int = 10,
    score_threshold: float = 0.3,
    date_from: date | None = None,
    date_to: date | None = None,
    sender: str | None = None,
) -> list[dict[str, Any]]:
    # 1. 쿼리 임베딩
    # 2. 필터 존재 시: MSSQL에서 email_ids 조회 → Chroma filtered search
    #    필터 없으면: 기존 Chroma search
    # 3. MSSQL에서 메타데이터 조회 + 점수 변환 + 필터링 + 정렬
```

### 5. `backend/rag/__init__.py` — 수정
```python
from .query_analyzer import analyze_query  # 추가
```

### 6. `backend/main.py` — 수정
`/chat` 엔드포인트에 쿼리 분석 단계 삽입.

```python
@app.post("/chat")
async def chat(request: ChatRequest):
    # 1. 쿼리 분석 (NEW)
    analysis = analyze_query(request.query)
    logger.info(f"Query analysis: {analysis}")

    # 2. 분석 결과로 검색 (rewritten_query + 필터)
    chunks = await search_similar_chunks(
        query=analysis.rewritten_query,
        date_from=analysis.date_from,
        date_to=analysis.date_to,
        sender=analysis.sender_filter,
    )

    # 3. 원본 질문으로 답변 생성 (기존과 동일)
    result = generate_answer(request.query, chunks)
    ...
```

## __init__.py / 모듈 export 변경

- `backend/rag/__init__.py`: `analyze_query` 추가 export
- `backend/vectorstore/__init__.py`: `search_similar_filtered` 추가 export
- `backend/db/__init__.py`: `get_email_ids_by_filters` 추가 export

## 비용 고려

쿼리 분석에 LLM 호출이 1회 추가된다.

| 단계 | 모델 | 예상 토큰 | 비용 (per query) |
|------|------|-----------|------------------|
| 쿼리 분석 | gpt-4o-mini | ~300 input + ~100 output | ~$0.00006 |
| 임베딩 | text-embedding-3-small | ~50 | ~$0.000001 |
| 답변 생성 | gpt-4o-mini | ~2000 input + ~500 output | ~$0.0005 |

쿼리 분석 추가 비용은 전체의 약 10%로, 무시할 수 있는 수준이다.

## 검증
1. `docker compose up --build -d`
2. 날짜 필터 테스트:
   ```bash
   curl -X POST http://localhost:8000/chat \
     -H "Content-Type: application/json" \
     -d '{"query":"오늘 뉴스레터에서 뭐가 왔어?"}'
   ```
3. 일반 질문 테스트 (필터 없음 - 기존 동작 유지 확인):
   ```bash
   curl -X POST http://localhost:8000/chat \
     -H "Content-Type: application/json" \
     -d '{"query":"AI 트렌드에 대해 알려줘"}'
   ```
4. 로그에서 쿼리 분석 결과 확인: `Query analysis: QueryAnalysis(rewritten_query=..., date_from=..., ...)`
