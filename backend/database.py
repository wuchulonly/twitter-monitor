from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def run_startup_migrations():
    async with engine.begin() as conn:
        account_columns = {
            row[1]
            for row in (
                await conn.exec_driver_sql("PRAGMA table_info(twitter_accounts)")
            ).all()
        }
        columns = {
            row[1]
            for row in (
                await conn.exec_driver_sql("PRAGMA table_info(monitor_targets)")
            ).all()
        }

        if "rate_limited_until" not in account_columns:
            await conn.exec_driver_sql(
                "ALTER TABLE twitter_accounts ADD COLUMN rate_limited_until DATETIME"
            )

        if "oldest_cursor" not in columns:
            await conn.exec_driver_sql(
                "ALTER TABLE monitor_targets ADD COLUMN oldest_cursor VARCHAR(255)"
            )

        if "history_complete" not in columns:
            await conn.exec_driver_sql(
                "ALTER TABLE monitor_targets ADD COLUMN history_complete BOOLEAN NOT NULL DEFAULT 0"
            )


async def get_db():
    async with async_session() as session:
        yield session
