# 기능 구현 계획: 쿼리 분석 (Query Analysis) 단계 추가

## 현재 문제점

현재 `/chat` 엔드포인트는 사용자 질문을 **그대로** 임베딩으로 변환하여 유사도 검색을 수행한다.

```
사용자: "오늘 트럼프를 언급한 기사가 있었어?"
    │
    ▼
"오늘 트럼프를 언급한 기사가 있었어?" → 임베딩 → 코사인 유사도 검색
    │
    ▼
관련 없는 결과 반환 (날짜 필터 없음, 질문형 문장이라 유사도 부정확)
```

### 구체적 문제

1. **날짜/시간 조건 무시**: "오늘", "이번 주", "최근 3일" 같은 시간 표현을 이해하지 못함
2. **질문형 → 유사도 불일치**: 질문 형태 문장은 정보성 문장(뉴스레터 본문)과 임베딩 유사도가 낮음
3. **복합 질문 미분해**: "트럼프와 AI 규제에 대한 뉴스레터를 비교해줘" 같은 복합 질문을 처리 못함
4. **단일 검색만 수행**: 검색 결과가 부실해도 재시도하지 않음

---

## 최신 RAG 기법 조사

### 업계 트렌드: Agentic RAG

2025-2026년 RAG 분야의 핵심 트렌드는 **검색 전 추론(Reasoning Before Retrieval)**이다.
기존 "검색 → 생성" 2단계에서, "분석 → 검색 → 평가 → (재검색) → 생성" 루프로 진화했다.

> "Standard RAG — the retrieve-then-generate pattern that dominated 2023–2024 — is increasingly obsolete."
> — UCStrategies, 2026

### 주요 기법 정리

| 기법 | 설명 | 우리 시스템 적용 가능성 |
|------|------|------------------------|
| **Query Routing** | LLM이 질문 유형을 분류하여 검색 전략 결정 (벡터검색 / 메타데이터필터 / 웹검색) | **높음** - 날짜 조건 유무에 따라 분기 |
| **Query Reformulation** | 질문형 문장을 검색에 적합한 서술형으로 변환 | **높음** - "~있었어?" → "트럼프 관련 뉴스" |
| **Query Decomposition** | 복합 질문을 여러 서브쿼리로 분해 후 병렬 검색 | **중간** - 복잡한 질문 대응 |
| **Metadata Filtering** | LLM이 질문에서 날짜/발신자 등 메타데이터 조건 추출 → SQL WHERE 절 생성 | **높음** - 핵심 개선 포인트 |
| **Document Grading** | 검색된 문서의 관련성을 LLM이 평가, 부실하면 재검색 | **중간** - 품질 개선 |
| **HyDE** | 가상의 답변 문서를 먼저 생성 → 그걸로 유사도 검색 | **낮음** - 비용 대비 효과 불확실 |
| **Step-Back Prompting** | 구체적 질문에서 한 단계 뒤로 물러나 더 넓은 맥락으로 검색 | **낮음** - 뉴스레터 도메인에선 불필요 |

### 참고 자료

- [Agentic RAG: A Survey (arXiv 2501.09136)](https://arxiv.org/abs/2501.09136)
- [Reasoning RAG via System 1 or System 2 (arXiv 2506.10408)](https://arxiv.org/html/2506.10408v1)
- [HuggingFace - Agentic RAG with query reformulation and self-query](https://huggingface.co/learn/cookbook/en/agent_rag)
- [Comprehensive Agentic RAG: Query Routing, Document Grading, Query Rewriting](https://sajalsharma.com/posts/comprehensive-agentic-rag/)
- [Dify - Agentic RAG: Smarter Retrieval with Autonomous Reasoning](https://dify.ai/blog/agentic-rag-smarter-retrieval-with-autonomous-reasoning)
- [LlamaIndex - Agentic Retrieval Guide](https://www.llamaindex.ai/blog/rag-is-dead-long-live-agentic-retrieval)
- [Advanced Metadata Filtering for RAG Agents](https://www.theaiautomators.com/laser-focus-your-rag-agents-with-advanced-metadata-filtering/)

---

## 구현 계획

### 목표 워크플로우 (Before vs After)

**Before (현재)**:
```
질문 → 임베딩 → Chroma 유사도 검색 → LLM 답변
```

**After (개선)**:
```
질문 → [1단계: 쿼리 분석] → [2단계: 조건부 검색] → [3단계: 결과 평가] → LLM 답변
            │                       │                       │
            ├─ 날짜 조건 추출       ├─ 메타데이터 필터링     ├─ 관련성 평가
            ├─ 키워드 추출          ├─ 벡터 유사도 검색      └─ 부실 시 재검색
            ├─ 쿼리 리라이팅        └─ 결과 병합
            └─ 서브쿼리 분해
```

### 상세 설계

#### 1단계: 쿼리 분석 (`rag/query_analyzer.py` 신규)

LLM에게 사용자 질문을 분석하게 하여 **구조화된 검색 계획**을 생성한다.

```python
# 입력
"오늘 트럼프를 언급한 기사가 있었어?"

# LLM 분석 결과 (JSON)
{
    "rewritten_query": "트럼프 관련 뉴스레터 기사",      # 검색용 서술형 변환
    "date_filter": {
        "type": "relative",                              # relative | absolute | none
        "value": "today"                                  # today, this_week, last_3_days, ...
    },
    "keywords": ["트럼프"],                               # 핵심 키워드
    "sender_filter": null,                                # 특정 발신인 필터 (있는 경우)
    "sub_queries": null                                   # 복합 질문이면 서브쿼리 리스트
}
```

**구현 방식**: OpenAI `gpt-4o-mini`에 JSON 응답 형식을 지정하여 호출.

```python
QUERY_ANALYSIS_PROMPT = """사용자의 질문을 분석하여 뉴스레터 검색 계획을 JSON으로 생성하세요.

오늘 날짜: {today}

분석 항목:
1. rewritten_query: 질문을 검색에 적합한 서술형 문장으로 변환
2. date_filter: 시간 조건이 있으면 추출 (today, this_week, last_N_days, YYYY-MM-DD~YYYY-MM-DD)
3. keywords: 핵심 검색 키워드
4. sender_filter: 특정 발신인/뉴스레터 이름이 언급되면 추출
5. sub_queries: 복합 질문이면 분해, 단일 질문이면 null
"""
```

#### 2단계: 조건부 검색 (`rag/search.py` 수정)

분석 결과에 따라 검색 전략을 조합한다.

```
                    ┌─ date_filter 있음 → MSSQL에서 날짜 범위 내 email_id 조회
쿼리 분석 결과 ─────┤
                    └─ date_filter 없음 → 전체 대상
                            │
                            ▼
                    Chroma 벡터 유사도 검색 (rewritten_query 사용)
                            │
                            ▼
                    결과 병합 (날짜 필터가 있었으면 교집합)
```

**핵심 변경**: `search_similar_chunks()`에 메타데이터 필터 파라미터 추가.

```python
# 현재
async def search_similar_chunks(query: str, top_k: int = 10)

# 변경 후
async def search_similar_chunks(
    query: str,
    top_k: int = 10,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    sender: str | None = None,
    keywords: list[str] | None = None,
)
```

**Chroma 메타데이터 필터링**: Chroma의 `where` 파라미터를 활용하거나,
MSSQL에서 조건에 맞는 `chroma_id` 목록을 먼저 조회한 후 Chroma에서 해당 ID만 검색.

#### 3단계: 결과 평가 (선택적, Phase 2)

검색 결과가 부실한 경우(예: 유사도 점수 전부 낮음) LLM이 쿼리를 재작성하여 재검색.

```python
if all(chunk["score"] < 0.3 for chunk in chunks):
    # 쿼리 재작성 후 재검색 (최대 1회)
    rewritten = rewrite_query(original_query, chunks)
    chunks = await search_similar_chunks(rewritten, ...)
```

---

### 변경 파일 목록

| 파일 | 변경 유형 | 설명 |
|------|-----------|------|
| `backend/rag/query_analyzer.py` | **신규** | 쿼리 분석 모듈 (LLM 기반) |
| `backend/rag/search.py` | 수정 | 메타데이터 필터 파라미터 추가 |
| `backend/rag/__init__.py` | 수정 | `analyze_query` 내보내기 추가 |
| `backend/main.py` | 수정 | `/chat`에서 분석 → 검색 → 답변 파이프라인 적용 |
| `backend/db/queries.py` | 수정 | 날짜/발신인 기반 chroma_id 조회 쿼리 추가 |
| `backend/vectorstore/chroma_store.py` | 수정 | ID 필터 기반 검색 함수 추가 |

### `/chat` 엔드포인트 변경 후 흐름

```python
@app.post("/chat")
async def chat(request: ChatRequest):
    # 1. 쿼리 분석
    analysis = analyze_query(request.query)

    # 2. 분석 결과로 조건부 검색
    chunks = await search_similar_chunks(
        query=analysis.rewritten_query,
        date_from=analysis.date_from,
        date_to=analysis.date_to,
        sender=analysis.sender_filter,
        keywords=analysis.keywords,
    )

    # 3. 답변 생성
    result = generate_answer(request.query, chunks)  # 원본 질문으로 답변
    parsed = parse_citations_response(result["content"], result["sources"])
    return ChatResponse(...)
```

---

## 구현 단계 (Phase)

### Phase 1: 쿼리 분석 + 메타데이터 필터링 (핵심)
- `query_analyzer.py` 구현
- `search.py`에 날짜/발신인 필터 추가
- `/chat` 파이프라인 연결

**효과**: "오늘 트럼프 기사" → 날짜 필터 + 키워드 검색 가능

### Phase 2: 쿼리 리라이팅 + 결과 평가
- 질문형 → 서술형 변환이 실제 검색 품질에 미치는 영향 측정
- 결과 부실 시 재검색 루프 추가

**효과**: 검색 정확도 향상, 빈 결과 감소

### Phase 3: 서브쿼리 분해 (복합 질문 대응)
- 복합 질문을 서브쿼리로 분해 → 병렬 검색 → 결과 통합
- "A와 B를 비교해줘" 같은 질문 대응

**효과**: 복잡한 질문에 대한 답변 품질 향상

---

## 비용 고려

쿼리 분석에 LLM 호출이 1회 추가된다.

| 단계 | 모델 | 예상 토큰 | 비용 (per query) |
|------|------|-----------|------------------|
| 쿼리 분석 | gpt-4o-mini | ~300 input + ~100 output | ~$0.00006 |
| 임베딩 | text-embedding-3-small | ~50 | ~$0.000001 |
| 답변 생성 | gpt-4o-mini | ~2000 input + ~500 output | ~$0.0005 |

쿼리 분석 추가 비용은 전체의 약 10%로, 무시할 수 있는 수준이다.
