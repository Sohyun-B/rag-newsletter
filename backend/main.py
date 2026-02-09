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
from rag import search_similar_chunks, generate_answer, parse_citations_response, analyze_query
from scheduler import start_scheduler, stop_scheduler, get_scheduler_status

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
    version="1.0.0",
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

class ChatRequest(BaseModel):
    query: str


class QueryAnalysisInfo(BaseModel):
    original_query: str
    rewritten_query: str
    date_from: str | None
    date_to: str | None
    sender_filter: str | None
    keywords: list[str]
    chunks_found: int


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

    1. 쿼리로 유사 청크 검색
    2. OpenAI Chat Completions API로 답변 생성
    3. 파싱된 답변 + 인용 정보 반환
    """
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    logger.info(f"Chat request: {request.query[:50]}...")

    try:
        # 1. 쿼리 분석
        analysis = analyze_query(request.query)
        logger.info(f"Query analysis: {analysis}")

        # 2. 분석 결과로 검색 (rewritten_query + 필터)
        chunks = await search_similar_chunks(
            query=analysis.rewritten_query,
            top_k=10,
            date_from=analysis.date_from,
            date_to=analysis.date_to,
            sender=analysis.sender_filter,
        )

        # 3. 원본 질문으로 답변 생성
        result = generate_answer(request.query, chunks)

        # 응답 파싱
        parsed = parse_citations_response(result["content"], result["sources"])

        analysis_info = QueryAnalysisInfo(
            original_query=request.query,
            rewritten_query=analysis.rewritten_query,
            date_from=str(analysis.date_from) if analysis.date_from else None,
            date_to=str(analysis.date_to) if analysis.date_to else None,
            sender_filter=analysis.sender_filter,
            keywords=analysis.keywords,
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

    try:
        inserted = fetch_emails_by_senders(request.senders, request.max_per_sender)

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


@app.post("/sync", response_model=SyncResponse)
async def manual_sync():
    """
    수동 Gmail 동기화 + ETL 실행
    """
    logger.info("Manual sync triggered")

    try:
        # Gmail 동기화
        gmail_result = sync_gmail()

        # ETL 처리
        etl_result = await process_unprocessed_emails()

        return SyncResponse(
            gmail_result=gmail_result,
            etl_result=etl_result
        )

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
        "version": "1.0.0",
        "docs": "/docs"
    }
