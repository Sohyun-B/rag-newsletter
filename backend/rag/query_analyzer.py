import json
import logging
from dataclasses import dataclass
from datetime import date, datetime

from openai import OpenAI

from config import settings

logger = logging.getLogger(__name__)

client = OpenAI(api_key=settings.OPENAI_API_KEY)


@dataclass
class QueryAnalysis:
    rewritten_query: str
    date_from: date | None
    date_to: date | None
    sender_filter: str | None
    keywords: list[str]


QUERY_ANALYSIS_PROMPT = """당신은 뉴스레터 검색 시스템의 쿼리 플래너입니다.
사용자의 자연어 질문을 분석하여, 벡터 검색과 SQL 필터에 사용할 검색 계획을 JSON으로 생성하세요.

오늘 날짜: {today} ({weekday})

JSON 형식:
{{
  "rewritten_query": "벡터 유사도 검색에 최적화된 서술형 문장",
  "date_from": "YYYY-MM-DD 또는 null",
  "date_to": "YYYY-MM-DD 또는 null",
  "sender_filter": "발신인/뉴스레터명 또는 null",
  "keywords": ["핵심", "키워드"]
}}

지침:
1. rewritten_query: 질문형(~있어?, ~뭐야?)을 제거하고, 핵심 주제를 서술형으로 변환하세요.
   - "오늘 트럼프 관련 기사 있어?" → "트럼프 관련 뉴스레터 기사"
   - "AI 트렌드에 대해 알려줘" → "AI 트렌드 동향 분석"

2. date_from / date_to: 오늘 날짜를 기준으로 직접 계산하여 YYYY-MM-DD로 기입하세요.
   - "오늘" → date_from="{today}", date_to="{today}"
   - "가장 최근", "최신" → 최근 7일: date_from 계산, date_to="{today}"
   - "지난주" → 해당 주의 월~일 계산
   - "1월" → "2026-01-01"~"2026-01-31"
   - 시간 표현이 전혀 없는 순수 주제 질문만 null로 두세요.

3. sender_filter: 특정 뉴스레터나 발신인이 언급된 경우만 기입하세요.

4. keywords: 검색의 핵심이 되는 키워드를 추출하세요."""

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
            max_tokens=512,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": query},
            ],
        )

        result = json.loads(response.choices[0].message.content)

        sender = result.get("sender_filter")
        if sender == "null" or sender is None:
            sender = None

        analysis = QueryAnalysis(
            rewritten_query=result.get("rewritten_query", query),
            date_from=_parse_date(result.get("date_from")),
            date_to=_parse_date(result.get("date_to")),
            sender_filter=sender,
            keywords=result.get("keywords", []),
        )

        logger.info(f"Query analysis: {analysis}")
        return analysis

    except Exception as e:
        logger.error(f"Query analysis failed, using original query: {e}")
        return QueryAnalysis(
            rewritten_query=query,
            date_from=None,
            date_to=None,
            sender_filter=None,
            keywords=[],
        )
