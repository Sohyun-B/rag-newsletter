import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime

from openai import OpenAI

from config import settings

logger = logging.getLogger(__name__)

client = OpenAI(api_key=settings.OPENAI_API_KEY)


@dataclass
class QueryAnalysis:
    needs_retrieval: bool
    rewritten_query: str
    hypothetical_document: str | None
    multi_queries: list[str]
    date_from: date | None
    date_to: date | None
    sender_filter: str | None
    keywords: list[str]


QUERY_ANALYSIS_PROMPT = """당신은 뉴스레터 검색 시스템의 쿼리 플래너입니다.
사용자의 자연어 질문을 분석하여, 벡터 검색과 SQL 필터에 사용할 검색 계획을 JSON으로 생성하세요.

오늘 날짜: {today} ({weekday})

JSON 형식:
{{
  "needs_retrieval": true/false,
  "rewritten_query": "벡터 유사도 검색에 최적화된 서술형 문장",
  "hypothetical_document": "이 질문에 대한 뉴스레터 본문 내용 (150자 내외 가상 답변)",
  "alternative_queries": ["쿼리 변형1", "쿼리 변형2", "쿼리 변형3"],
  "date_from": "YYYY-MM-DD 또는 null",
  "date_to": "YYYY-MM-DD 또는 null",
  "sender_filter": "발신인/뉴스레터명 또는 null",
  "keywords": ["핵심", "키워드"]
}}

지침:
1. needs_retrieval: 뉴스레터 정보/콘텐츠에 대한 질문이면 true.
   인사말(안녕하세요, 반갑습니다), 감사 표현, 시스템 관련 질문(사용법 등) → false.

2. rewritten_query: 질문형(~있어?, ~뭐야?)을 제거하고, 핵심 주제를 서술형으로 변환하세요.
   - "오늘 트럼프 관련 기사 있어?" → "트럼프 관련 뉴스레터 기사"
   - "AI 트렌드에 대해 알려줘" → "AI 트렌드 동향 분석"

3. hypothetical_document: needs_retrieval=true일 때만 생성하세요.
   실제 뉴스레터 본문처럼 서술형으로 작성하세요 (150자 내외).
   이 가상 답변은 벡터 검색의 정확도를 높이는 데 사용됩니다.
   needs_retrieval=false이면 null로 설정하세요.

4. alternative_queries: needs_retrieval=true일 때만 생성하세요.
   원본 질문을 동의어, 다른 관점, 다른 표현으로 3개 변형하세요.
   각 변형은 서술형으로 작성하세요.
   needs_retrieval=false이면 빈 배열 []로 설정하세요.

5. date_from / date_to: 명시적인 시간 표현이 있을 때만 설정하세요.
   - "오늘" → date_from="{today}", date_to="{today}"
   - "최근", "최신" → 최근 7일: date_from 계산, date_to="{today}"
   - "지난주" → 해당 주의 월~일 계산
   - "1월" → "2026-01-01"~"2026-01-31"
   - 중요: "~있어?", "~알려줘", "~뭐야?" 같은 질문 어미는 시간 표현이 아닙니다.
     "관세 관련 뉴스 있어?" → 날짜 필터 null (시간 표현 없음)
     "AI 트렌드 알려줘" → 날짜 필터 null (시간 표현 없음)
     "오늘 관세 뉴스 있어?" → 날짜 필터 설정 ("오늘"이라는 시간 표현 있음)
   - 확실한 시간 표현이 없으면 반드시 null로 두세요. 과도한 필터는 검색 결과를 없앱니다.

6. sender_filter: 특정 뉴스레터나 발신인이 언급된 경우만 기입하세요.

7. keywords: 검색의 핵심이 되는 키워드를 추출하세요."""

WEEKDAYS = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]


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


def analyze_query(query: str) -> QueryAnalysis:
    """gpt-4o-mini로 쿼리를 분석하여 검색 계획을 생성"""
    today = date.today()
    weekday = WEEKDAYS[today.weekday()]
    prompt = QUERY_ANALYSIS_PROMPT.format(today=today.isoformat(), weekday=weekday)

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

        sender = result.get("sender_filter")
        if sender == "null" or sender is None:
            sender = None

        hypothetical_doc = result.get("hypothetical_document")
        if hypothetical_doc == "null" or not needs_retrieval:
            hypothetical_doc = None

        alternative_queries = result.get("alternative_queries", [])
        if not needs_retrieval:
            alternative_queries = []

        analysis = QueryAnalysis(
            needs_retrieval=needs_retrieval,
            rewritten_query=result.get("rewritten_query") or query,
            hypothetical_document=hypothetical_doc,
            multi_queries=alternative_queries,
            date_from=_parse_date(result.get("date_from")) if needs_retrieval else None,
            date_to=_parse_date(result.get("date_to")) if needs_retrieval else None,
            sender_filter=sender if needs_retrieval else None,
            keywords=result.get("keywords", []),
        )

        logger.info(f"Query analysis: needs_retrieval={analysis.needs_retrieval}, "
                     f"multi_queries={len(analysis.multi_queries)}, "
                     f"has_hyde={'yes' if analysis.hypothetical_document else 'no'}")
        return analysis

    except Exception as e:
        logger.error(f"Query analysis failed, using original query: {e}")
        return QueryAnalysis(
            needs_retrieval=True,
            rewritten_query=query,
            hypothetical_document=None,
            multi_queries=[],
            date_from=None,
            date_to=None,
            sender_filter=None,
            keywords=[],
        )
