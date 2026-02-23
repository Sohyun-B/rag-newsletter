import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime

from openai import OpenAI

from config import settings

logger = logging.getLogger(__name__)

client = OpenAI(api_key=settings.OPENAI_API_KEY)


@dataclass
class SubQuery:
    """독립적으로 검색 가능한 하위 쿼리"""
    query: str
    hypothetical_document: str | None
    multi_queries: list[str]
    date_from: date | None
    date_to: date | None
    sender_filter: str | None
    purpose: str


@dataclass
class QueryAnalysis:
    needs_retrieval: bool
    query_type: str                     # simple|comparison|aggregation|temporal_comparison|multi_topic|opinion|multi_hop
    rewritten_query: str
    sub_queries: list[SubQuery]
    keywords: list[str]
    aggregation_instruction: str | None


QUERY_ANALYSIS_PROMPT = """당신은 뉴스레터 검색 시스템의 쿼리 플래너입니다.
사용자의 자연어 질문을 분석하여 검색 계획을 JSON으로 생성하세요.

오늘 날짜: {today} ({weekday})
{conversation_context}
JSON 형식:
{{
  "needs_retrieval": true/false,
  "query_type": "simple | comparison | aggregation | temporal_comparison | multi_topic | opinion | multi_hop",
  "rewritten_query": "전체 질문을 대화 맥락을 반영하여 서술형으로 변환",
  "sub_queries": [
    {{
      "query": "검색용 서술형 쿼리",
      "hypothetical_document": "이 쿼리에 대한 가상 뉴스레터 본문 (150자 내외) 또는 null",
      "alternative_queries": ["변형1", "변형2"],
      "date_from": "YYYY-MM-DD 또는 null",
      "date_to": "YYYY-MM-DD 또는 null",
      "sender_filter": "발신인 또는 null",
      "purpose": "이 서브쿼리로 찾으려는 정보"
    }}
  ],
  "keywords": ["핵심", "키워드"],
  "aggregation_instruction": "서브쿼리 결과를 종합하는 방법 (복합 질문만, 단순 질문은 null)"
}}

=== needs_retrieval 판단 ===
- true: 뉴스레터 정보/콘텐츠에 대한 질문
- false: 인사말(안녕하세요), 감사 표현, 시스템 사용법 질문
  → sub_queries는 빈 배열 [], aggregation_instruction은 null

=== query_type 분류 ===
- simple: 단일 주제 검색 ("AI 트렌드 알려줘", "트럼프 관세 뉴스")
- comparison: 두 대상 비교 ("뉴닉과 한겨레의 트럼프 보도 차이점")
- aggregation: 요약/정리 ("이번 주 주요 뉴스 정리해줘")
- temporal_comparison: 시간대별 비교 ("지난달 초반과 후반의 시장 동향 비교")
- multi_topic: 여러 주제 검색 ("AI와 반도체 관련 뉴스")
- opinion: 논조/관점 분석 ("AI 규제에 대한 뉴스레터들의 논조는?")
- multi_hop: 연쇄 추론 ("A가 보도한 B 기술이 C에 미치는 영향")

=== sub_queries 생성 규칙 ===
1. simple, aggregation, opinion → sub_queries **1개**
2. comparison → 비교 대상별 분리 (2개)
   예: "뉴닉과 한겨레 비교" → [{{"query":"뉴닉 트럼프 보도", "sender_filter":"newneek"}}, {{"query":"한겨레 트럼프 보도", "sender_filter":"khan"}}]
3. temporal_comparison → 시간대별 분리 (2개)
   예: "1월과 2월 비교" → [{{"query":"시장 동향", "date_from":"2026-01-01", "date_to":"2026-01-31"}}, {{"query":"시장 동향", "date_from":"2026-02-01", "date_to":"2026-02-28"}}]
4. multi_topic → 주제별 분리 (2~3개)
   예: "AI와 반도체" → [{{"query":"AI 트렌드"}}, {{"query":"반도체 산업 동향"}}]
5. multi_hop → 추론 단계별 분리 (2~3개)
6. 각 sub_query는 **독립적으로** 검색 가능해야 함
7. 최대 4개까지

=== sub_query 내부 필드 ===
- query: 질문형 제거, 핵심 주제를 서술형으로
- hypothetical_document: needs_retrieval=true일 때만. 실제 뉴스레터 본문처럼 150자 내외 서술형
- alternative_queries: 동의어/다른 표현으로 2개 변형
- date_from / date_to: 명시적 시간 표현이 있을 때만 YYYY-MM-DD
  - "오늘" → 오늘 날짜
  - "최근", "최신" → 최근 7일
  - "지난주" → 해당 주의 월~일
  - "~있어?", "~알려줘" 같은 질문 어미는 시간 표현이 **아님** → null
  - 확실한 시간 표현 없으면 반드시 null
- sender_filter: 특정 뉴스레터/발신인 언급 시만
- purpose: 이 서브쿼리가 전체 답변에서 담당하는 역할

=== aggregation_instruction ===
- 복합 질문(sub_queries 2개 이상)에서만 작성
- 서브쿼리 결과를 어떻게 종합할지 LLM에게 지시
- 예: "두 뉴스레터의 보도 관점과 논조를 비교 분석해주세요"
- 예: "두 시기의 동향을 시간순으로 정리하고 변화를 분석해주세요"
- 단순 질문은 null

=== 대화 맥락 처리 ===
- 이전 대화가 제공된 경우, 현재 질문이 이전 대화를 참조하는지 확인
- "그거", "더 자세히", "다른 건?", "아까 말한" 등의 참조 표현이 있으면
  rewritten_query와 sub_queries에 구체적인 내용을 반영
- 예: 이전에 "트럼프 관세"를 논의했고 현재 "더 자세히 알려줘" →
  rewritten_query: "트럼프 관세 정책에 대한 상세한 뉴스레터 내용"
"""

WEEKDAYS = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]

VALID_QUERY_TYPES = {
    "simple", "comparison", "aggregation",
    "temporal_comparison", "multi_topic", "opinion", "multi_hop",
}


def _build_conversation_context(history: list[dict] | None) -> str:
    """이전 대화를 프롬프트에 삽입할 형태로 포맷"""
    if not history:
        return ""

    lines = ["\n이전 대화 맥락:"]
    for msg in history:
        role = "사용자" if msg["role"] == "user" else "어시스턴트"
        content = msg["content"]
        if msg["role"] == "assistant" and len(content) > 200:
            content = content[:200] + "..."
        lines.append(f"  {role}: {content}")

    return "\n".join(lines) + "\n"


def _parse_date(value) -> date | None:
    if value is None or value == "null":
        return None
    if isinstance(value, str):
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            logger.warning(f"Failed to parse date: {value}")
            return None
    return None


def _parse_sub_queries(raw_list: list[dict], needs_retrieval: bool) -> list[SubQuery]:
    """JSON 응답의 sub_queries 배열을 SubQuery 리스트로 파싱"""
    if not raw_list or not needs_retrieval:
        return []

    sub_queries = []
    for item in raw_list[:4]:  # 최대 4개
        sender = item.get("sender_filter")
        if sender == "null" or sender is None:
            sender = None

        hypo_doc = item.get("hypothetical_document")
        if hypo_doc == "null" or not hypo_doc:
            hypo_doc = None

        alt_queries = item.get("alternative_queries", [])
        if not isinstance(alt_queries, list):
            alt_queries = []

        sub_queries.append(SubQuery(
            query=item.get("query", ""),
            hypothetical_document=hypo_doc,
            multi_queries=alt_queries[:3],
            date_from=_parse_date(item.get("date_from")),
            date_to=_parse_date(item.get("date_to")),
            sender_filter=sender,
            purpose=item.get("purpose", ""),
        ))

    return sub_queries


def analyze_query(
    query: str,
    conversation_history: list[dict] | None = None,
) -> QueryAnalysis:
    """gpt-4o-mini로 쿼리를 분석하여 검색 계획을 생성"""
    today = date.today()
    weekday = WEEKDAYS[today.weekday()]
    conversation_context = _build_conversation_context(conversation_history)
    prompt = QUERY_ANALYSIS_PROMPT.format(
        today=today.isoformat(),
        weekday=weekday,
        conversation_context=conversation_context,
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=1024,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": query},
            ],
        )

        result = json.loads(response.choices[0].message.content)

        needs_retrieval = result.get("needs_retrieval", True)

        query_type = result.get("query_type", "simple")
        if query_type not in VALID_QUERY_TYPES:
            query_type = "simple"

        sub_queries = _parse_sub_queries(
            result.get("sub_queries", []),
            needs_retrieval,
        )

        # needs_retrieval=true인데 sub_queries가 비어있으면 fallback
        # 새 스키마에서 하위 필드들은 sub_queries 배열 내부에 있으므로 최상위에서 읽지 않음
        if needs_retrieval and not sub_queries:
            sub_queries = [SubQuery(
                query=result.get("rewritten_query") or query,
                hypothetical_document=None,
                multi_queries=[],
                date_from=None,
                date_to=None,
                sender_filter=None,
                purpose="전체 검색",
            )]

        aggregation = result.get("aggregation_instruction")
        if aggregation == "null":
            aggregation = None
        if not needs_retrieval or len(sub_queries) <= 1:
            aggregation = None

        analysis = QueryAnalysis(
            needs_retrieval=needs_retrieval,
            query_type=query_type if needs_retrieval else "simple",
            rewritten_query=result.get("rewritten_query") or query,
            sub_queries=sub_queries,
            keywords=result.get("keywords", []),
            aggregation_instruction=aggregation,
        )

        logger.info(
            f"Query analysis: type={analysis.query_type}, "
            f"sub_queries={len(analysis.sub_queries)}, "
            f"needs_retrieval={analysis.needs_retrieval}"
        )
        return analysis

    except Exception as e:
        logger.error(f"Query analysis failed, using fallback: {e}")
        return QueryAnalysis(
            needs_retrieval=True,
            query_type="simple",
            rewritten_query=query,
            sub_queries=[SubQuery(
                query=query,
                hypothetical_document=None,
                multi_queries=[],
                date_from=None,
                date_to=None,
                sender_filter=None,
                purpose="전체 검색",
            )],
            keywords=[],
            aggregation_instruction=None,
        )
