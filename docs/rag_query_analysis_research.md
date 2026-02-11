# 최신 RAG 쿼리 분석 기법 리서치 (2024-2026)

## 1. 현재 시스템 분석

### 현재 구현 (`backend/rag/query_analyzer.py`)

gpt-4o-mini에 JSON mode로 요청하여 고정된 스키마를 반환받는 방식.

```json
{
  "rewritten_query": "벡터 검색용 서술형 문장",
  "date_from": "YYYY-MM-DD 또는 null",
  "date_to": "YYYY-MM-DD 또는 null",
  "sender_filter": "발신인 또는 null",
  "keywords": ["핵심", "키워드"]
}
```

### 한계점

| 문제 | 설명 |
|------|------|
| 단일 패스 결정 | 한 번의 LLM 호출로 모든 검색 전략을 결정. 중간 결과를 보고 전략 수정 불가 |
| 고정 필터 스키마 | 날짜/발신인 두 가지 필터만 지원. 새 필터 추가 시 스키마+프롬프트+파싱 전부 수정 필요 |
| 검색 필요성 판단 불가 | 모든 질문에 무조건 벡터 검색 수행. "안녕하세요" 같은 인사말에도 불필요한 검색 발생 |
| 단일 쿼리 검색 | 복합 질문을 분해하지 않음. "AI 트렌드와 금융 규제 비교" 같은 질문에 하나의 검색만 수행 |
| 자기 교정 없음 | 검색 결과가 부족하거나 관련 없어도 재검색하지 않음 |

---

## 2. 최신 기법 상세 분석

### 2-1. HyDE (Hypothetical Document Embeddings)

**핵심 아이디어**: 사용자 질문을 그대로 임베딩하는 대신, LLM이 질문에 대한 가상의 답변 문서를 먼저 생성하고, 그 가상 문서를 임베딩하여 검색. 질문(짧고 추상적)과 문서(길고 구체적) 사이의 의미적 격차를 줄여 검색 정확도 향상.

**작동 방식**:
```
"최근 AI 관련 뉴스레터 있어?"
  → LLM이 가상 답변 생성: "최근 여러 뉴스레터에서 AI 기술 발전에 대해 다루었습니다.
     특히 생성형 AI의 기업 도입 사례, AI 규제 동향, 그리고..."
  → 가상 답변을 임베딩 → 이 임베딩으로 유사 문서 검색
```

**성능**: HyPE(HyDE 발전형) 연구에서 특정 데이터셋 기준 검색 정밀도 최대 42%p, 재현율 최대 45%p 개선 보고.

**장점**:
- 구현이 비교적 간단 (LLM 호출 1회 추가)
- 짧은 질문이나 키워드 위주 질문에서 검색 품질 큰 폭 개선
- 기존 벡터 검색 인프라를 그대로 활용 가능

**단점**:
- LLM 호출 1회 추가에 따른 지연 시간 증가
- 가상 문서가 부정확하면 오히려 잘못된 문서를 검색할 수 있음
- 사실 기반이 아닌 "환각 문서"를 생성할 수 있음

**뉴스레터 시스템 적합도**: **매우 높음**. 사용자가 짧은 질문("트럼프 관세?")을 던지는 경우가 많아 질문-문서 간 의미 격차가 크므로 HyDE가 효과적.

---

### 2-2. Multi-Query Expansion (다중 쿼리 확장)

**핵심 아이디어**: 하나의 사용자 질문에서 여러 관점의 대체 쿼리를 생성하고, 모든 쿼리에 대해 검색을 수행한 뒤 결과를 합침(union + deduplicate).

**작동 방식**:
```
"AI 규제 관련 소식 알려줘"
  → 쿼리 1: "인공지능 규제 정책 변화"
  → 쿼리 2: "AI 법안 및 가이드라인 동향"
  → 쿼리 3: "생성형 AI 관련 정부 규제 소식"
  → 3개 쿼리 각각 검색 → 결과 합산 → 중복 제거 → 재순위화
```

**성능**: 2025년 연구 기준 MQRF-RAG는 복잡한 다단계 문제에서 HyDE 단독 대비 약 7% 성능 향상.

**장점**:
- 질문의 다양한 해석을 커버하여 재현율(recall) 향상
- HyDE와 조합 시 시너지 효과
- 구현 복잡도가 상대적으로 낮음

**단점**:
- 검색 횟수 증가 (보통 3~5배)에 따른 비용 및 지연
- 결과 합산 시 노이즈 문서가 섞일 수 있음
- 리랭킹(reranking) 단계를 추가해야 효과적

**뉴스레터 시스템 적합도**: **높음**. 동일 주제라도 뉴스레터마다 사용하는 용어가 다를 수 있어("AI" vs "인공지능" vs "GenAI"), 다중 쿼리 확장이 검색 누락을 줄여줌.

---

### 2-3. Adaptive RAG (적응형 RAG)

**핵심 아이디어**: 질문의 복잡도를 분류하여 서로 다른 검색 전략을 라우팅. 단순 질문은 검색 없이 LLM의 내부 지식으로 답변, 중간 복잡도는 단일 검색, 고복잡도는 반복 검색.

**작동 방식**:
```
질문 입력 → 복잡도 분류(간단/보통/복합) → 라우팅
  - 간단 ("안녕하세요"): LLM 직접 답변 (검색 생략)
  - 보통 ("AI 트렌드?"): 벡터 검색 1회 → 답변 생성
  - 복합 ("AI와 금융 비교"): 질문 분해 → 다단계 검색 → 중간 답변 종합
```

**장점**:
- 간단한 질문에 불필요한 검색 비용 절감
- 복합 질문에 대해 더 정확한 답변 가능
- LangGraph로 구현 시 상태 기반 흐름 제어가 명확

**단점**:
- 복잡도 분류기 자체의 정확도에 의존
- 라우팅 분기가 많아질수록 테스트 및 디버깅 복잡도 증가

**뉴스레터 시스템 적합도**: **매우 높음**. 비검색 질문과 실제 정보 질문을 구분하는 것만으로도 사용자 경험이 크게 개선.

---

### 2-4. Query Decomposition (쿼리 분해)

**핵심 아이디어**: 복합 질문을 독립적인 하위 질문으로 분해하여, 각 하위 질문에 대해 별도로 검색 및 답변을 수행한 뒤 최종 답변을 종합.

**작동 방식**:
```
"AI 트렌드와 금융 규제 변화를 비교해줘"
  → 하위 질문 1: "최근 AI 트렌드에 관한 뉴스레터"
  → 하위 질문 2: "최근 금융 규제 변화에 관한 뉴스레터"
  → 각각 검색 → 종합 답변 생성
```

**성능**: 2025년 Haystack/Deepset 연구 기준, 복합 질문에서 검색 관련 할루시네이션 40% 감소.

**장점**:
- 복합 질문에 대해 각 측면을 놓치지 않음
- 하위 질문별 답변의 품질이 더 높음

**단점**:
- LLM 호출 횟수 증가 (비용 및 지연 시간)
- 단순 질문에 불필요한 분해가 일어나면 오히려 성능 저하
- 하위 질문 간 의존성이 있는 경우 처리 복잡

**뉴스레터 시스템 적합도**: **중간**. 대부분 단일 주제 질문이므로 단독 적용보다는 Adaptive RAG와 조합하여 복합 질문에만 적용하는 것이 적절.

---

### 2-5. CRAG (Corrective RAG, 교정형 RAG)

**핵심 아이디어**: 검색된 문서의 관련성을 평가(grading)하고, 관련성이 낮으면 쿼리를 재작성하여 재검색.

**작동 방식**:
```
질문 → 벡터 검색 → 문서 관련성 평가(Correct / Ambiguous / Incorrect)
  - Correct: 문서 정제 후 답변 생성
  - Ambiguous: 원래 검색 + 쿼리 재작성 후 재검색 결과 병합
  - Incorrect: 쿼리 재작성 후 재검색으로 대체
```

**장점**:
- 검색 품질이 낮을 때 자동으로 보완
- LangGraph에서 참조 구현이 공개되어 있어 도입 용이
- Self-RAG와 상호 보완적 (CRAG는 문서 품질, Self-RAG는 답변 품질)

**단점**:
- 관련성 평가 자체에 LLM 호출 필요 (비용)
- 파이프라인 복잡도 증가

**뉴스레터 시스템 적합도**: **높음** (변형 적용 시). 웹 검색 폴백 대신 "쿼리 재작성 후 재검색"으로 대체하면 뉴스레터 시스템에 잘 맞는 자기 교정 루프 구축 가능.

---

### 2-6. Self-RAG (자기 반성형 RAG)

**핵심 아이디어**: LLM이 검색 결과를 받은 뒤 스스로 "이 검색 결과가 충분한가?", "이 문서가 질문과 관련 있는가?", "내 답변이 문서에 근거하는가?"를 판단하는 self-reflection 메커니즘 내장.

**핵심 판단 단계**:
1. **Retrieve**: 검색이 필요한지 스스로 결정
2. **IsRel**: 검색된 문서가 질문과 관련 있는지 평가
3. **IsSup**: 생성한 답변이 문서에 의해 뒷받침되는지 검증
4. **IsUse**: 최종 답변이 유용한지 자기 평가

**장점**:
- 할루시네이션 감소 (문서 근거 검증)
- 관련 없는 문서를 걸러내어 답변 품질 향상

**단점**:
- 원래 논문은 fine-tuning 기반이라 구현 비용이 높음
- 프롬프트 기반 근사 구현 시 LLM 호출 횟수 크게 증가

**뉴스레터 시스템 적합도**: **낮음**. 소규모 시스템에서는 과도한 복잡도. "관련성 점수가 낮으면 다시 검색" 정도의 간소화된 로직(CRAG)이 더 현실적.

---

### 2-7. Agentic RAG (에이전트형 RAG) - Tool Use 기반

**핵심 아이디어**: LLM을 자율적 에이전트로 취급하여, 검색 도구를 선택적으로 사용하고 결과를 평가하며 필요시 반복 검색. OpenAI Function Calling / Tool Use를 활용.

**현재 방식 vs Tool Use 방식**:
```
# 현재: 고정 JSON 스키마
질문 → JSON 생성 {rewritten_query, date_from, ...} → 고정 파이프라인

# Tool Use: LLM이 도구를 자율 선택
질문 → LLM이 판단 → search_by_topic() 호출
                    → filter_by_date() 호출
                    → 또는 no_retrieval_needed()
                    → 결과 보고 추가 검색 결정
```

**도구 정의 예시**:
```python
tools = [
    {
        "name": "search_by_topic",
        "description": "주제 기반 벡터 검색. 의미적으로 유사한 뉴스레터 문서를 반환.",
        "parameters": {"query": "str", "top_k": "int"}
    },
    {
        "name": "filter_by_date",
        "description": "날짜 범위로 이메일을 필터링.",
        "parameters": {"date_from": "str", "date_to": "str"}
    },
    {
        "name": "filter_by_sender",
        "description": "발신인으로 이메일을 필터링.",
        "parameters": {"sender": "str"}
    },
    {
        "name": "no_retrieval_needed",
        "description": "검색 불필요. 인사말이나 일반 대화에 사용.",
        "parameters": {}
    }
]
```

**장점**:
- 가장 유연한 접근법 (새 도구 추가 시 스키마 변경 불필요)
- OpenAI function calling과 자연스럽게 통합
- 복합 질문에 대해 다단계 검색을 자율적으로 수행
- 하드코딩된 JSON 스키마가 완전히 불필요

**단점**:
- LLM 호출 횟수가 예측 불가능 (비용 관리 어려움)
- 에이전트가 무한 루프에 빠질 수 있음 (최대 반복 횟수 제한 필요)
- 디버깅 및 테스트가 어려움
- 지연 시간 증가

**뉴스레터 시스템 적합도**: **높음** (단순화된 버전 적용 시). 최대 반복 횟수를 2~3회로 제한하면 유연성과 제어 가능성을 모두 확보 가능.

---

### 2-8. DeepRAG (단계적 추론 검색)

**핵심 아이디어**: 2025년 2월 발표. 검색 보강 추론을 마르코프 결정 과정(MDP)으로 모델링. 각 추론 단계에서 "외부 검색이 필요한가, 내부 지식으로 충분한가"를 이진 결정하여 최소한의 검색으로 최대 정확도 달성.

**성능**: 정확도 21.99% 향상, 검색 효율성도 동시에 개선.

**뉴스레터 시스템 적합도**: **낮음**. fine-tuning 기반이라 소규모 시스템에서 구현하기 어려움.

---

### 2-9. RQ-RAG (Rewrite, Decompose, Disambiguate)

**핵심 아이디어**: 하나의 모델이 질문에 따라 재작성(rewrite), 분해(decompose), 명확화(disambiguate) 중 적절한 전략을 선택. 각 반복에서 다양한 검색 쿼리를 생성하여 서로 다른 컨텍스트를 탐색.

**뉴스레터 시스템 적합도**: **중간**. 개념은 좋으나 fine-tuning 기반이라, 프롬프트 기반 근사 구현으로 핵심 아이디어만 차용하는 것이 현실적.

---

## 3. 기법 비교 요약표

| 기법 | 구현 난이도 | 추가 LLM 호출 | 검색 품질 개선 | 뉴스레터 적합도 |
|------|-----------|--------------|--------------|---------------|
| HyDE | **낮음** | +1회 | **높음** | **매우 높음** |
| Multi-Query Expansion | 낮음 | +1회 | 높음 (재현율) | **높음** |
| Adaptive RAG (라우팅) | 낮~중 | +0~1회 | 중간 | **매우 높음** |
| Query Decomposition | 중간 | +1~2회 | 높음 (복합 질문) | 중간 |
| CRAG (교정형) | 중간 | +1~2회 | 높음 | **높음** (변형) |
| Agentic RAG (Tool Use) | 중~높 | 가변 | 매우 높음 | **높음** (단순화) |
| Self-RAG | 높음 | +2~4회 | 매우 높음 | 낮음 |
| DeepRAG | 매우 높음 | 가변 | 매우 높음 | 낮음 |
| RQ-RAG | 높음 | +2~3회 | 높음 | 중간 |

---

## 4. 단계별 적용 권장안

### Phase 1: 즉시 적용 (저비용, 고효과)

**목표**: 기존 파이프라인 구조를 유지하면서 검색 품질 대폭 개선

| 기법 | 적용 내용 |
|------|----------|
| HyDE | `rewritten_query`를 임베딩하는 대신, LLM이 생성한 가상 답변 문서를 임베딩하여 검색 |
| Multi-Query | `rewritten_query` 1개 대신 3개의 변형 쿼리를 생성하여 각각 검색 후 합산 |
| 간단한 라우팅 | 질문이 검색을 필요로 하는지 판단하는 분류 단계 추가 (인사말/감사 → 검색 생략) |

### Phase 2: 중기 개선 (유연성 확보)

**목표**: 하드코딩된 스키마 제거, 자기 교정 기능 추가

| 기법 | 적용 내용 |
|------|----------|
| Tool Use 기반 Agentic 전환 | 고정 JSON 스키마를 OpenAI function calling으로 대체. 도구 추가만으로 기능 확장 |
| CRAG 스타일 관련성 평가 | 검색 결과의 관련성을 평가하고, 낮으면 쿼리 재작성 후 재검색 |

### Phase 3: 장기 개선 (최대 유연성)

**목표**: 전체 RAG 파이프라인을 상태 기계로 통합

| 기법 | 적용 내용 |
|------|----------|
| LangGraph 기반 상태 기계 | 전체 파이프라인을 그래프로 구현. Adaptive RAG + CRAG + Agentic을 하나의 그래프에 통합 |

---

## 5. 참고 자료

- [Agentic RAG Survey (arXiv 2025)](https://arxiv.org/abs/2501.09136)
- [Query Decomposition for RAG (arXiv 2025)](https://arxiv.org/abs/2510.18633)
- [Advanced RAG: Query Decomposition (Haystack)](https://haystack.deepset.ai/blog/query-decomposition)
- [RQ-RAG: Learning to Refine Queries](https://arxiv.org/html/2404.00610v1)
- [A-RAG: Scaling Agentic RAG](https://arxiv.org/html/2602.03442v1)
- [Corrective RAG - LangGraph Tutorial](https://langchain-ai.github.io/langgraph/tutorials/rag/langgraph_crag/)
- [Adaptive RAG - LangGraph Tutorial](https://langchain-ai.github.io/langgraph/tutorials/rag/langgraph_adaptive_rag/)
- [8 RAG Architecture Diagrams (Humanloop 2025)](https://humanloop.com/blog/rag-architectures)
- [Advanced RAG Techniques (Pinecone)](https://www.pinecone.io/learn/advanced-rag-techniques/)
- [DeepRAG (arXiv 2025)](https://arxiv.org/abs/2502.01142)
- [HyDE, Query Expansion, Multi-Query RAG (Medium 2026)](https://medium.com/@mudassar.hakim/retrieval-is-the-bottleneck-hyde-query-expansion-and-multi-query-rag-explained-for-production-c1842bed7f8a)
- [Adaptive RAG Explained (Meilisearch 2025)](https://www.meilisearch.com/blog/adaptive-rag)
- [OpenAI Function Calling Docs](https://platform.openai.com/docs/guides/function-calling)
- [OpenAI Structured Outputs Docs](https://platform.openai.com/docs/guides/structured-outputs)
- [NirDiamant/RAG_Techniques (GitHub)](https://github.com/NirDiamant/RAG_Techniques)
