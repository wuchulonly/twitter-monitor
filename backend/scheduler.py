import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from backend.config import settings
from backend.database import async_session
from backend.services.monitor import run_all_checks

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def scheduled_check():
    """Periodic job to check all monitor targets."""
    logger.info("Running scheduled tweet check...")
    async with async_session() as db:
        summary = await run_all_checks(db)
    logger.info("Scheduled tweet check completed: %s", summary)


def start_scheduler():
    scheduler.add_job(
        scheduled_check,
        "interval",
        minutes=settings.default_check_interval,
        id="tweet_check",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"Scheduler started (interval: {settings.default_check_interval} min)")


def stop_scheduler():
    scheduler.shutdown(wait=False)
