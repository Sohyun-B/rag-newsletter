import logging
import asyncio
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config import settings

logger = logging.getLogger(__name__)

# 스케줄러 인스턴스
scheduler = BackgroundScheduler()


def run_async(coro):
    """동기 함수에서 비동기 함수 실행"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def sync_job():
    """
    스케줄러에서 실행되는 동기화 작업
    Gmail 동기화 + ETL 처리
    """
    from gmail import fetch_emails_by_senders
    from etl import process_unprocessed_emails

    logger.info(f"Scheduled sync job started (senders: {len(settings.SYNC_SENDERS)})")

    try:
        # 발신인 기반 Gmail 동기화
        inserted = fetch_emails_by_senders(settings.SYNC_SENDERS)
        logger.info(f"Gmail sync: {len(inserted)} new emails")

        # ETL 처리
        etl_result = run_async(process_unprocessed_emails())
        logger.info(f"ETL: {etl_result.get('processed', 0)} emails processed")

    except Exception as e:
        logger.error(f"Sync job failed: {e}")


def start_scheduler():
    """스케줄러 시작"""
    if scheduler.running:
        logger.warning("Scheduler already running")
        return

    # 동기화 작업 추가
    scheduler.add_job(
        sync_job,
        trigger=IntervalTrigger(minutes=settings.SYNC_INTERVAL_MINUTES),
        id="gmail_sync",
        name="Gmail Sync & ETL",
        replace_existing=True
    )

    scheduler.start()
    logger.info(f"Scheduler started (interval: {settings.SYNC_INTERVAL_MINUTES} minutes)")


def stop_scheduler():
    """스케줄러 종료"""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


def get_scheduler_status() -> dict:
    """스케줄러 상태 조회"""
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": str(job.next_run_time) if job.next_run_time else None
        })

    return {
        "running": scheduler.running,
        "jobs": jobs
    }
