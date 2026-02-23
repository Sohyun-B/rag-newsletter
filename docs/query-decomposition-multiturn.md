# 쿼리 분석 고도화 + 멀티턴 대화 지원

## 배경

### 현재 시스템의 문제

현재 쿼리 분석기는 사용자 질문을 받으면 **하나의 검색 쿼리**로 변환합니다.

```
"트럼프 관세 뉴스" → rewritten_query: "트럼프 관세 정책 관련 뉴스" → Chroma 검색 → 답변
```

이건 단일 주제 검색에는 잘 작동하지만, 실제 사용자들은 이런 질문도 합니다:

| 질문 유형 | 예시 | 현재 시스템 문제 |
|-----------|------|-----------------|
| **비교** | "뉴닉과 한겨레의 트럼프 보도 차이점?" | 하나의 쿼리로 두 뉴스레터를 동시에 검색 → 한쪽 결과만 나오거나 섞임 |
| **복합 주제** | "AI와 반도체 관련 뉴스" | "AI 반도체"로 합쳐져서 검색 → AI만 나오는 뉴스, 반도체만 나오는 뉴스를 놓침 |
| **시간 비교** | "지난달 초반과 후반의 시장 동향" | 날짜 필터가 하나뿐 → 두 시간대를 구분해서 검색 불가 |
| **요약** | "이번 주 주요 뉴스 정리해줘" | 단순 검색으로 처리 → query_type 구분 없이 일반 답변 |
| **후속 질문** | "그거 더 자세히 알려줘" | 이전 대화를 모름 → "그거"가 뭔지 알 수 없음 |

### 해결 접근: 쿼리 분해 (Query Decomposition)

핵심 아이디어는 **복잡한 질문을 독립적으로 검색 가능한 서브쿼리로 분해**하는 것입니다.

```
"뉴닉과 한겨레의 트럼프 보도 차이점?"
    ↓ 쿼리 분석 (1회 LLM 호출)
    ├── 서브쿼리1: "뉴닉 트럼프 관련 보도" (sender=뉴닉)
    └── 서브쿼리2: "한겨레 트럼프 관련 보도" (sender=한겨레)
    ↓ 각각 독립 검색 (병렬)
    ├── 뉴닉 결과: [청크1, 청크2, ...]
    └── 한겨레 결과: [청크3, 청크4, ...]
    ↓ 구조화된 컨텍스트로 답변 생성
    "뉴닉은 ~한 관점에서 보도한 반면, 한겨레는 ~한 관점에서..."
```

이 접근의 근거:
- UC Berkeley의 DecomposeRAG(2025) 연구에서 쿼리 분해가 복합 질문 정확도를 **28~44%** 향상시킨다고 보고
- 단순 질문은 서브쿼리 1개로 처리되므로 기존 파이프라인과 **완전히 동일** (회귀 없음)
- LLM 호출 횟수는 기존과 동일 (1회) — 프롬프트만 확장

### 해결 접근: 대화 맥락 주입 (Conversation-Aware Rewriting)

"그거 더 자세히"를 처리하려면, 이전 대화를 쿼리 분석 시점에 넘겨서 LLM이 참조를 해석하게 합니다.

```
[이전] 사용자: "트럼프 관세 뉴스 알려줘"
[이전] 어시스턴트: "트럼프 정부의 관세 정책은... [1] ..."
[현재] 사용자: "그거 더 자세히 알려줘"
    ↓ 쿼리 분석 (이전 대화 맥락 포함)
    → rewritten_query: "트럼프 관세 정책에 대한 상세한 뉴스레터 내용"
    ↓ 검색 + 답변 생성 (이전 대화도 LLM에 전달)
    → 일관된 후속 답변
```

**두 개선이 하나의 LLM 호출로 통합되는 이유**: 쿼리 분석 프롬프트에 (1) 대화 맥락과 (2) 의도 분류 + 분해 규칙을 함께 넣으면, 추가 API 호출 없이 한 번에 처리됩니다. 대화 맥락이 있어야 "그거를 비교해줘" 같은 복합 후속 질문도 올바르게 분해할 수 있기 때문에, 두 기능은 자연스럽게 같은 지점에서 합쳐집니다.

### 설계 결정 근거

| 대안 | 채택 여부 | 이유 |
|------|----------|------|
| 쿼리 분석 + 대화 맥락을 별도 LLM 호출로 분리 | X | 불필요한 추가 비용 + 지연. 한 프롬프트에서 처리 가능 |
| DB에 대화 저장 | X | 요구사항이 세션 내 후속 질문이므로 Streamlit session_state로 충분 |
| 무조건 모든 쿼리를 분해 | X | 단순 질문에 오버헤드. query_type으로 분기하여 단순=1개 서브쿼리 |
| 대화 히스토리 전체 전송 | X | 토큰 낭비. 최근 5쌍(10메시지)만 전송, 어시스턴트 메시지 truncate |

---

## 구현 명세

### 변경 파일 목록

| 파일 | 변경 내용 |
|------|-----------|
| `backend/rag/query_analyzer.py` | SubQuery 데이터클래스 추가, QueryAnalysis 구조 변경, 프롬프트 재작성, 대화 맥락 주입 |
| `backend/rag/search.py` | `search_with_sub_queries()` 추가 (병렬 서브쿼리 검색 + 결과 병합) |
| `backend/rag/agent.py` | 대화 히스토리 주입, `generate_structured_answer()` 추가 |
| `backend/rag/__init__.py` | 신규 export 추가 |
| `backend/main.py` | Message 모델, ChatRequest에 history 추가, /chat 분기 로직 |
| `frontend/app.py` | history 전송, render_analysis() 업데이트 |

### 1. query_analyzer.py

#### 데이터 모델

기존 QueryAnalysis의 flat 필드(hypothetical_document, multi_queries, date_from 등)를 SubQuery로 구조화.

```python
@dataclass
class SubQuery:
    """독립적으로 검색 가능한 하위 쿼리"""
    query: str                          # 검색용 서술형 쿼리
    hypothetical_document: str | None   # HyDE 가상 문서
    multi_queries: list[str]            # 대체 쿼리 변형 2개
    date_from: date | None
    date_to: date | None
    sender_filter: str | None
    purpose: str                        # 이 서브쿼리의 목적

@dataclass
class QueryAnalysis:
    needs_retrieval: bool
    query_type: str                     # "simple"|"comparison"|"aggregation"|"temporal_comparison"|"multi_topic"|"opinion"|"multi_hop"
    rewritten_query: str                # 전체 질문의 서술형 변환
    sub_queries: list[SubQuery]         # 단순=1개, 복합=2~4개
    keywords: list[str]
    aggregation_instruction: str | None # 서브쿼리 결과 종합 방법 (복합 질문만)
```

- 단순 질문: sub_queries 1개 → 기존 파이프라인과 동일
- 복합 질문: sub_queries 2~4개 → 각각 독립 검색 후 구조화 답변

#### 프롬프트

- 의도 분류: query_type 7종 (simple, comparison, aggregation, temporal_comparison, multi_topic, opinion, multi_hop)
- 쿼리 분해: query_type에 따라 sub_queries 1~4개 생성
- 대화 맥락: `{conversation_context}` 자리에 이전 대화 삽입

query_type별 분해 규칙:
- simple/aggregation/opinion → sub_queries 1개
- comparison → 비교 대상별 분리
- temporal_comparison → 시간대별 분리
- multi_topic → 주제별 분리
- multi_hop → 추론 단계별 분리

#### analyze_query() 시그니처

```python
def analyze_query(query: str, conversation_history: list[dict] | None = None) -> QueryAnalysis:
```

- conversation_history 기본값 None → 하위 호환
- 대화 맥락을 프롬프트에 주입 (어시스턴트 메시지는 200자로 truncate)
- JSON 파싱 실패 시 fallback: needs_retrieval=True, sub_queries 1개(원본 쿼리)

### 2. search.py

#### search_with_sub_queries() 추가

```python
async def search_with_sub_queries(
    sub_queries: list[SubQuery],
    top_k_per_query: int = 10,
    final_top_k: int = 15,
    score_threshold: float = 0.3,
) -> tuple[list[dict], dict[str, list[dict]]]:
```

- 각 SubQuery에 대해 기존 `search_similar_chunks()`를 `asyncio.gather()`로 병렬 호출
- 결과를 per_subquery_chunks (purpose별) + merged_chunks (전체 통합, 중복 제거)로 반환
- 기존 search_similar_chunks()는 변경 없음

### 3. agent.py

#### generate_answer() / generate_direct_answer() 대화 히스토리 주입

```python
def generate_answer(query, chunks, conversation_history=None):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *_format_history_for_answer(conversation_history),
        {"role": "user", "content": f"문서:\n{context}\n\n질문: {query}"}
    ]
```

#### generate_structured_answer() 신규

```python
def generate_structured_answer(
    query, per_subquery_chunks, aggregation_instruction, conversation_history=None
):
```

- 컨텍스트를 서브쿼리 purpose별 섹션으로 구성
- 시스템 프롬프트에 aggregation_instruction 추가

### 4. main.py

#### API 모델

```python
class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    query: str
    history: list[Message] = []

class QueryAnalysisInfo(BaseModel):
    original_query: str
    needs_retrieval: bool
    query_type: str = "simple"
    rewritten_query: str
    sub_queries: list[dict] = []
    keywords: list[str] = []
    aggregation_instruction: str | None = None
    chunks_found: int = 0
```

#### /chat 분기 로직

- needs_retrieval=false → generate_direct_answer(history)
- sub_queries 1개 → search_similar_chunks() + generate_answer(history)
- sub_queries 2+개 → search_with_sub_queries() + generate_structured_answer(history)

### 5. frontend/app.py

- 최근 10개 메시지(5쌍)를 history로 API에 전송
- render_analysis()에 query_type, sub_queries, aggregation_instruction 표시

---

## 토큰 비용 분석

| 구성 요소 | 단순 쿼리 (기존 대비) | 복합 쿼리 (3 서브쿼리) |
|-----------|----------------------|----------------------|
| 쿼리 분석 | +500 토큰 (히스토리) | 동일 |
| 임베딩 | 동일 (4텍스트) | 12텍스트 (3x) |
| 답변 생성 | +500 토큰 (히스토리) | +1500 토큰 (섹션별 컨텍스트 + 히스토리) |
| **추가 비용** | **~$0.00015/쿼리** | **~$0.001/쿼리** |

---

## 검증 방법

1. **단순 쿼리 회귀 테스트**: "트럼프 관세 뉴스" → 기존과 동일 결과 (sub_queries 1개, query_type="simple")
2. **비교 쿼리**: "뉴닉과 한겨레의 트럼프 보도 차이점" → query_type="comparison", sub_queries 2개
3. **요약 쿼리**: "이번 주 주요 뉴스 정리해줘" → query_type="aggregation", 날짜 필터 적용
4. **후속 질문**: "트럼프 관세 뉴스" → "그거 더 자세히 알려줘" → rewritten_query에 "트럼프 관세" 반영
5. **대화 맥락 답변**: 이전 답변 참조하여 일관된 답변 생성
6. **하위 호환**: history 없이 POST /chat → 기존과 동일 동작
7. **docker-compose up 후 Streamlit에서 E2E 테스트**
