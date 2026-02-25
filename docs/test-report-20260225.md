# 시스템 동작 테스트 보고서

**테스트 일자**: 2026-02-25
**테스트 대상**: 최근 커밋 `e4e10ec` — 쿼리 분해(Query Decomposition) + 멀티턴 대화 지원

---

## 테스트 환경

- Docker Compose 실행 중 (rag-backend-1, rag-frontend-1)
- 수집 데이터: 뉴스레터 **1,359건**, 벡터 **10,202개**
- MSSQL, Chroma, Gmail 연결 모두 정상

```json
GET /health
{
  "status": "healthy",
  "mssql": true,
  "chroma": true,
  "gmail": true,
  "scheduler": {
    "running": true,
    "jobs": [{ "id": "gmail_sync", "name": "Gmail Sync & ETL" }]
  }
}
```

---

## 테스트 1 — 인사말 (needs_retrieval=false, 직접 답변)

**목적**: Routing이 검색 불필요 케이스를 올바르게 판단하는지 확인

**입력**
```
질문: "안녕하세요"
history: []
```

**중간 과정 (쿼리 분석 결과)**
```json
"analysis": {
  "needs_retrieval": false,
  "query_type": "simple",
  "rewritten_query": "안녕하세요",
  "sub_queries": [],
  "keywords": [],
  "aggregation_instruction": null,
  "chunks_found": 0
}
```
→ `needs_retrieval=false` 판단 → 벡터 검색 없이 `generate_direct_answer()` 호출

**최종 답변**
> 안녕하세요! 어떻게 도와드릴까요? 뉴스레터에 대한 질문이 있으시면 언제든지 물어봐 주세요.

**결과**: ✅ 정상 — 불필요한 검색 없이 즉시 답변

---

## 테스트 2 — 단순 검색 (simple, 서브쿼리 1개)

**목적**: HyDE + Multi-Query 생성 및 벡터 검색 전 과정 확인

**입력**
```
질문: "트럼프 관세 관련 뉴스 알려줘"
history: []
```

**중간 과정 (쿼리 분석 결과)**
```json
"analysis": {
  "needs_retrieval": true,
  "query_type": "simple",
  "rewritten_query": "트럼프 관세 관련 뉴스레터 내용을 알려주세요.",
  "sub_queries": [
    {
      "query": "트럼프 관세 뉴스",
      "hypothetical_document": "최근 트럼프 전 대통령의 관세 정책 변화에 대한 뉴스가 보도되었습니다. 새로운 세금이 특정 수입품에 부과될 예정이며, 이는 내년부터 시행됩니다.",
      "multi_queries": [
        "트럼프의 관세 정책",
        "트럼프 관세 관련 최근 동향"
      ],
      "date_from": null,
      "date_to": null,
      "sender_filter": null,
      "purpose": "트럼프의 관세 관련 최근 동향을 파악하기 위함"
    }
  ],
  "keywords": ["트럼프", "관세", "정책"],
  "aggregation_instruction": null,
  "chunks_found": 10
}
```

**검색 파이프라인 동작 순서**
1. HyDE 문서 (1개) + Multi-Query 변형 (2개) + 원본 쿼리 (1개) = 총 **4개 텍스트** 동시 임베딩
2. 각 임베딩으로 Chroma 검색 → 결과 병합 (chroma_id 기준 best score 유지)
3. MSSQL에서 chroma_id → 이메일 메타데이터 조회
4. 유사도 점수 임계값(0.3) 필터링 → top 10 반환

**최종 답변 (요약)**
> 트럼프 대통령의 관세 관련 뉴스는 여러 가지가 있습니다. 최근에는 관세 전쟁이 확대되고 있으며, 특히 한국산 전체 제품에 25%의 상호관세가 부과될 예정입니다. 이 내용은 이재명 대통령에게 통보된 서한에 포함되어 있으며, 한국 정부는 이에 대한 대응 방안을 마련하고 있습니다[3]. 또한, 미국의 연방법원인 국제무역법원이 트럼프의 관세 정책이 불법이라는 판결을 내린 사례도 있습니다[2]. ...

**검색된 상위 출처 (점수순)**

| 순위 | 제목 | 발신인 | 날짜 | score |
|------|------|--------|------|-------|
| 1 | 트럼프 관세 최대 피해자가 다름 아닌 미국 기업이라고? | NEWNEEK | 2025-08-13 | 0.796 |
| 2 | 어? 그건 너의 권한이 아닌데?⚖️ | 디그(dig) | 2025-06-02 | 0.791 |
| 3 | 직장인이라면 알아야 할 주 4일제의 모든 것 🗓️ | NEWNEEK | 2025-07-09 | 0.786 |

**결과**: ✅ 정상

---

## 테스트 3 — 비교 쿼리 (comparison, 서브쿼리 2개 병렬)

**목적**: 쿼리 분해 + 병렬 서브쿼리 검색 + 구조화 답변 생성 확인

**입력**
```
질문: "뉴닉이랑 경향신문 점선면의 트럼프 관세 보도 비교해줘"
history: []
```

**중간 과정 (쿼리 분석 결과)**
```json
"analysis": {
  "needs_retrieval": true,
  "query_type": "comparison",
  "rewritten_query": "뉴닉과 경향신문의 트럼프 관세 보도 내용을 비교 분석해주세요.",
  "sub_queries": [
    {
      "query": "뉴닉의 트럼프 관세 보도",
      "hypothetical_document": "최근 뉴닉에서는 트럼프의 관세 정책에 대한 비판적인 시각과 함께 경제에 미치는 영향을 분석하는 기사를 보도했습니다.",
      "multi_queries": [
        "뉴닉에서 보도한 트럼프 관세",
        "트럼프 관세에 대한 뉴닉의 입장"
      ],
      "sender_filter": "newneek",
      "purpose": "뉴닉의 트럼프 관세 보도 내용을 분석하기 위해"
    },
    {
      "query": "경향신문의 트럼프 관세 보도",
      "hypothetical_document": "경향신문은 트럼프의 관세 정책이 국제 무역에 미치는 영향과 전문가 인터뷰를 포함한 기사를 다루었습니다.",
      "multi_queries": [
        "경향신문에서 보도한 트럼프 관세",
        "트럼프 관세에 대한 경향신문의 관점"
      ],
      "sender_filter": "kyunghyang",
      "purpose": "경향신문의 트럼프 관세 보도 내용을 분석하기 위해"
    }
  ],
  "aggregation_instruction": "두 뉴스레터의 트럼프 관세 보도 내용을 비교 분석하여 차이점과 공통점을 정리해주세요.",
  "chunks_found": 15
}
```

**검색 파이프라인 동작 순서**
1. `search_with_sub_queries()` — 서브쿼리 2개를 `asyncio.gather`로 **병렬 실행**
2. 서브쿼리 1: `sender_filter="newneek"` → MSSQL `from_address LIKE %newneek%` → email_ids 필터 → Chroma 검색
3. 서브쿼리 2: `sender_filter="kyunghyang"` → MSSQL `from_address LIKE %kyunghyang%` → **0건 매칭** → 전체 검색 fallback
4. 두 결과를 `purpose` 키로 분리 저장 → `_build_structured_context()`로 섹션 구분 컨텍스트 생성
5. `generate_structured_answer()` 호출 (aggregation_instruction 포함)

**최종 답변 (요약)**
> ### 공통점
> 1. **관세의 영향**: 두 뉴스레터 모두 트럼프의 관세 정책이 미국 경제와 세계 경제에 미치는 영향이 크다는 점을 강조하고 있습니다. 경향신문에서는 "관세 인상의 영향이 예상보다 크고 인플레이션을 유발할 가능성"을 언급하며, 뉴닉은 미국 기업들이 관세로 인해 생산비 증가에 직면하고 있다고 지적했습니다[1][11].
>
> ### 차이점
> 1. **보도 접근 방식**: 뉴닉은 관세 정책을 통해 발생하는 구체적인 산업 피해(예: 자동차 업계의 생산비 증가)에 좀 더 중점을 두고 있으며... 반면 경향신문은 트럼프의 정책에 대한 대중의 반응, 특히 국민들의 시위와 반대 운동을 더 강조합니다[11][12].

**결과**: 🟡 부분 정상

**발견된 문제**: `sender_filter="kyunghyang"`이 DB의 실제 `from_address` 값인 `letter@khan.kr`와 매칭되지 않음
→ 경향신문 서브쿼리가 전체 검색으로 fallback되어 뉴닉 결과가 양쪽 모두에 혼입됨
→ LLM이 비교 답변을 생성하지만 실제로는 경향신문 청크를 거의 사용하지 못한 상태

---

## 테스트 4 — 멀티턴 대화 (대화 맥락 반영)

**목적**: 이전 대화를 참조하는 모호한 질문에서 맥락 반영 여부 확인

**입력**
```
질문: "더 자세히 알려줘"
history: [
  { "role": "user", "content": "트럼프 관세 관련 뉴스 알려줘" },
  { "role": "assistant", "content": "트럼프 대통령의 관세 정책은 자주 변경되며 혼란을 일으키고 있습니다." }
]
```

**중간 과정 (쿼리 분석 결과)**
```json
"analysis": {
  "needs_retrieval": true,
  "query_type": "simple",
  "rewritten_query": "트럼프 대통령의 관세 정책에 대한 상세한 뉴스레터 내용",
  "sub_queries": [
    {
      "query": "트럼프의 관세 정책과 관련된 최신 뉴스",
      "hypothetical_document": "...",
      "multi_queries": [ "트럼프 관세 정책 상세 내용", "트럼프 관세 최신 현황" ],
      "date_from": null, "date_to": null, "sender_filter": null,
      "purpose": "트럼프 관세 정책의 상세한 최신 동향 파악"
    }
  ],
  "aggregation_instruction": null,
  "chunks_found": 10
}
```

**핵심 확인 포인트**

| 항목 | 원본 질문 | 분석 결과 |
|------|-----------|-----------|
| 입력 | `"더 자세히 알려줘"` (주제 없음) | `rewritten_query`: `"트럼프 대통령의 관세 정책에 대한 상세한 뉴스레터 내용"` |
| 방식 | 모호한 지시어 | 이전 대화의 "트럼프 관세" 주제를 반영해 구체화 |

**최종 답변 (요약)**
> 트럼프 대통령의 관세 정책은 여러 차원에서 논란을 일으켰습니다. 최근 주요 내용은 다음과 같습니다.
> 1. **관세 부과 결정과 법원이 개입**: 트럼프는 '국가 비상사태'를 선언하고 멕시코와 캐나다에 25%, 기타 교역국에는 10%의 기본 관세와 최대 40%의 상호 관세를 부과했습니다. 그러나 최근 미국의 연방법원인 국제무역법원(CIT)은 트럼프의 관세 정책이 불법이라는 판결을 내렸습니다[1][9]. ...

**결과**: ✅ 정상 — "더 자세히 알려줘"가 이전 주제를 정확히 이어받아 검색

---

## 종합 결과

| # | 테스트 항목 | 파이프라인 경로 | 결과 |
|---|------------|----------------|------|
| 1 | 인사말 | Routing → 직접 답변 | ✅ |
| 2 | 단순 검색 | Routing → simple → HyDE+MQ → 검색 → 답변 | ✅ |
| 3 | 비교 쿼리 | Routing → comparison → 서브쿼리 2개 병렬 → 구조화 답변 | 🟡 |
| 4 | 멀티턴 | 대화 맥락 → rewritten_query 에 반영 → 검색 → 답변 | ✅ |

---

## 발견된 문제 및 개선 필요 사항

### sender_filter 매칭 실패 (비교/발신인 필터 쿼리)

**현상**: LLM이 `"kyunghyang"`, `"khan"` 등 추정 이름으로 sender_filter를 생성하지만, DB `from_address`는 `letter@khan.kr` 형태의 실제 이메일 주소

**영향**: sender_filter가 있는 서브쿼리가 항상 0건 매칭 → 전체 검색 fallback → 필터 효과 없음

**원인**: 쿼리 분석 LLM이 실제 DB의 이메일 주소를 모름

**해결 방향**: `QUERY_ANALYSIS_PROMPT`에 `SYNC_SENDERS` 목록을 주입하여 LLM이 정확한 이메일 주소를 사용하도록 유도

```python
# query_analyzer.py 프롬프트에 추가 예시
SENDER_LIST = "\n".join(f"- {s}" for s in settings.SYNC_SENDERS)
prompt = QUERY_ANALYSIS_PROMPT.format(
    today=...,
    weekday=...,
    conversation_context=...,
    sender_list=SENDER_LIST,   # 추가
)
```
