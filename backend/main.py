import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import settings
from db import test_connection, get_newsletters, get_newsletter_by_id, get_newsletter_count
from vectorstore import get_collection_count
from gmail import sync_gmail, fetch_emails_by_senders, test_gmail_connection
from etl import process_unprocessed_emails
from rag import (
    search_similar_chunks, search_with_sub_queries,
    generate_answer, generate_structured_answer,
    parse_citations_response, analyze_query, generate_direct_answer,
)
from scheduler import start_scheduler, stop_scheduler, get_scheduler_status

# 동기화 중복 실행 방지 락
_sync_lock = asyncio.Lock()

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# Lifespan 컨텍스트 매니저
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 시작 시
    logger.info("Starting Newsletter RAG Backend...")
    start_scheduler()
    yield
    # 종료 시
    logger.info("Shutting down...")
    stop_scheduler()


# FastAPI 앱 생성
app = FastAPI(
    title="Newsletter RAG API",
    description="뉴스레터 기반 RAG 시스템 API",
    version="1.1.0",
    lifespan=lifespan
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============ Request/Response Models ============

class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    query: str
    history: list[Message] = []


class SubQueryInfo(BaseModel):
    query: str
    hypothetical_document: str | None = None
    multi_queries: list[str] = []
    date_from: str | None = None
    date_to: str | None = None
    sender_filter: str | None = None
    purpose: str = ""


class QueryAnalysisInfo(BaseModel):
    original_query: str
    needs_retrieval: bool
    query_type: str = "simple"
    rewritten_query: str
    sub_queries: list[SubQueryInfo] = []
    keywords: list[str] = []
    aggregation_instruction: str | None = None
    chunks_found: int = 0


class ChatResponse(BaseModel):
    text: str
    citations: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    analysis: QueryAnalysisInfo | None = None


class SyncResponse(BaseModel):
    gmail_result: dict[str, Any]
    etl_result: dict[str, Any]


class HealthResponse(BaseModel):
    status: str
    mssql: bool
    chroma: bool
    gmail: bool
    scheduler: dict[str, Any]


# ============ Helpers ============

def _trim_history(history: list[Message], max_pairs: int = 5) -> list[dict]:
    """최근 N쌍(user+assistant)만 유지, dict 변환"""
    messages = [{"role": m.role, "content": m.content} for m in history]
    limit = max_pairs * 2
    if len(messages) > limit:
        messages = messages[-limit:]
    return messages


# ============ Endpoints ============

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """헬스체크: MSSQL, Chroma, Gmail 연결 상태 확인"""
    mssql_ok = test_connection()
    chroma_count = get_collection_count()
    gmail_ok = test_gmail_connection()
    scheduler_status = get_scheduler_status()

    return HealthResponse(
        status="healthy" if mssql_ok else "degraded",
        mssql=mssql_ok,
        chroma=chroma_count >= 0,
        gmail=gmail_ok,
        scheduler=scheduler_status
    )


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    RAG 채팅 엔드포인트

    1. 대화 히스토리 정리
    2. 쿼리 분석 (의도 분류 + 쿼리 분해 + 대화 맥락 해석)
    3. 분기: 직접 답변 / 단순 검색 / 복합 검색
    4. 답변 생성 + 인용 파싱
    """
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    logger.info(f"Chat request: {request.query[:50]}...")

    try:
        # 0. 대화 히스토리 정리 (최근 5쌍)
        history = _trim_history(request.history, max_pairs=5)

        # 1. 쿼리 분석 (대화 맥락 포함)
        analysis = analyze_query(request.query, conversation_history=history)
        logger.info(
            f"Query analysis: type={analysis.query_type}, "
            f"sub_queries={len(analysis.sub_queries)}, "
            f"needs_retrieval={analysis.needs_retrieval}"
        )

        if not analysis.needs_retrieval:
            # 검색 불필요 → 직접 답변
            result = await asyncio.to_thread(
                generate_direct_answer, request.query, conversation_history=history
            )
            chunks = []

        elif len(analysis.sub_queries) == 1:
            # 단순 쿼리 → 기존 파이프라인
            sq = analysis.sub_queries[0]
            chunks = await search_similar_chunks(
                query=sq.query,
                hypothetical_doc=sq.hypothetical_document,
                multi_queries=sq.multi_queries,
                date_from=sq.date_from,
                date_to=sq.date_to,
                sender=sq.sender_filter,
            )
            result = await asyncio.to_thread(
                generate_answer, request.query, chunks, conversation_history=history
            )

        else:
            # 복합 쿼리 → 병렬 서브쿼리 검색 + 구조화 답변
            merged, per_subquery = await search_with_sub_queries(analysis.sub_queries)
            chunks = merged
            result = await asyncio.to_thread(
                generate_structured_answer,
                request.query,
                per_subquery,
                analysis.aggregation_instruction,
                history,
            )

        # 응답 파싱
        parsed = parse_citations_response(result["content"], result["sources"])

        # 서브쿼리 정보 구성
        sub_query_infos = [
            SubQueryInfo(
                query=sq.query,
                hypothetical_document=sq.hypothetical_document,
                multi_queries=sq.multi_queries,
                date_from=str(sq.date_from) if sq.date_from else None,
                date_to=str(sq.date_to) if sq.date_to else None,
                sender_filter=sq.sender_filter,
                purpose=sq.purpose,
            )
            for sq in analysis.sub_queries
        ]

        analysis_info = QueryAnalysisInfo(
            original_query=request.query,
            needs_retrieval=analysis.needs_retrieval,
            query_type=analysis.query_type,
            rewritten_query=analysis.rewritten_query,
            sub_queries=sub_query_infos,
            keywords=analysis.keywords,
            aggregation_instruction=analysis.aggregation_instruction,
            chunks_found=len(chunks),
        )

        return ChatResponse(
            text=parsed["text"],
            citations=parsed["citations"],
            sources=[{
                "subject": s.get("subject", ""),
                "from_address": s.get("from_address", ""),
                "received_at": str(s.get("received_at", ""))[:10],
                "score": s.get("score", 0)
            } for s in result["sources"]],
            analysis=analysis_info,
        )

    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class SyncBySendersRequest(BaseModel):
    senders: list[str]
    max_per_sender: int = 500


@app.post("/sync/senders")
async def sync_by_senders(request: SyncBySendersRequest):
    """발신인 기준으로 과거 이메일 수집 + ETL"""
    logger.info(f"Sync by senders: {request.senders}")

    if _sync_lock.locked():
        raise HTTPException(status_code=409, detail="동기화가 이미 실행 중입니다. 잠시 후 다시 시도해주세요.")

    async with _sync_lock:
        try:
            inserted = await asyncio.to_thread(
                fetch_emails_by_senders, request.senders, request.max_per_sender
            )
            etl_result = await process_unprocessed_emails()

            return {
                "inserted_count": len(inserted),
                "inserted_emails": [
                    {"id": e["id"], "subject": e["subject"], "from": e["from_address"]}
                    for e in inserted
                ],
                "etl_result": etl_result
            }

        except Exception as e:
            logger.error(f"Sync by senders error: {e}")
            raise HTTPException(status_code=500, detail=str(e))


@app.post("/sync")
async def manual_sync():
    """수동 Gmail 동기화 + ETL 실행 (설정된 발신인 기준)"""
    logger.info(f"Manual sync triggered (senders: {settings.SYNC_SENDERS})")

    if _sync_lock.locked():
        raise HTTPException(status_code=409, detail="동기화가 이미 실행 중입니다. 잠시 후 다시 시도해주세요.")

    async with _sync_lock:
        try:
            inserted = await asyncio.to_thread(
                fetch_emails_by_senders, settings.SYNC_SENDERS
            )
            etl_result = await process_unprocessed_emails()

            return {
                "gmail_result": {
                    "inserted_count": len(inserted),
                    "senders": settings.SYNC_SENDERS,
                },
                "etl_result": etl_result,
            }

        except Exception as e:
            logger.error(f"Sync error: {e}")
            raise HTTPException(status_code=500, detail=str(e))


@app.get("/newsletters")
async def list_newsletters(skip: int = 0, limit: int = 20):
    """수집된 뉴스레터 목록 조회"""
    try:
        newsletters = get_newsletters(skip=skip, limit=limit)
        total = get_newsletter_count()

        return {
            "total": total,
            "skip": skip,
            "limit": limit,
            "items": [{
                "id": n["id"],
                "subject": n["subject"],
                "from_address": n["from_address"],
                "received_at": str(n["received_at"])[:10] if n["received_at"] else "",
                "processed": n["processed"]
            } for n in newsletters]
        }

    except Exception as e:
        logger.error(f"List newsletters error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/newsletters/{newsletter_id}")
async def get_newsletter(newsletter_id: int):
    """특정 뉴스레터 상세 조회"""
    try:
        newsletter = get_newsletter_by_id(newsletter_id)

        if not newsletter:
            raise HTTPException(status_code=404, detail="Newsletter not found")

        return {
            "id": newsletter["id"],
            "gmail_id": newsletter["gmail_id"],
            "subject": newsletter["subject"],
            "from_address": newsletter["from_address"],
            "received_at": str(newsletter["received_at"]) if newsletter["received_at"] else "",
            "body_text": newsletter.get("body_text", ""),
            "labels": newsletter.get("labels", "[]"),
            "processed": newsletter["processed"]
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get newsletter error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stats")
async def get_stats():
    """시스템 통계 조회"""
    try:
        newsletter_count = get_newsletter_count()
        vector_count = get_collection_count()
        scheduler_status = get_scheduler_status()

        return {
            "newsletters": newsletter_count,
            "vectors": vector_count,
            "scheduler": scheduler_status
        }

    except Exception as e:
        logger.error(f"Stats error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# 루트 엔드포인트
@app.get("/")
async def root():
    return {
        "name": "Newsletter RAG API",
        "version": "1.1.0",
        "docs": "/docs"
    }
