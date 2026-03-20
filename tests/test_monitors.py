import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.models import Base, Tweet, TwitterAccount
from backend.routers.monitors import (
    MonitorBackfillRequest,
    MonitorBulkCreate,
    MonitorCreate,
    backfill_monitor_tweets,
    bulk_create_monitors,
    create_monitor,
    delete_monitor,
)


class CreateMonitorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tempdir.name, "test.db")
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{self.db_path}",
            echo=False,
        )
        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with self.session_factory() as session:
            account = TwitterAccount(
                username="tester",
                email="",
                cookies_json="{}",
                is_active=True,
            )
            session.add(account)
            await session.commit()
            await session.refresh(account)
            self.account_id = account.id

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tempdir.cleanup()

    async def test_create_monitor_rejects_duplicate_after_normalizing_username(self):
        async with self.session_factory() as session:
            created = await create_monitor(
                MonitorCreate(
                    twitter_username="@OpenAI",
                    display_name="OpenAI",
                    check_interval=5,
                    account_id=self.account_id,
                ),
                db=session,
            )

        self.assertEqual(created.twitter_username, "OpenAI")
        self.assertEqual(created.display_name, "OpenAI")

        async with self.session_factory() as session:
            with self.assertRaises(HTTPException) as exc:
                await create_monitor(
                    MonitorCreate(
                        twitter_username="  openai  ",
                        display_name="OpenAI Again",
                        check_interval=5,
                        account_id=self.account_id,
                    ),
                    db=session,
                )

        self.assertEqual(exc.exception.status_code, 409)
        self.assertEqual(exc.exception.detail, "Already monitoring this user")

    async def test_create_monitor_rejects_blank_username(self):
        async with self.session_factory() as session:
            with self.assertRaises(HTTPException) as exc:
                await create_monitor(
                    MonitorCreate(
                        twitter_username=" @  ",
                        display_name="Blank",
                        check_interval=5,
                        account_id=self.account_id,
                    ),
                    db=session,
                )

        self.assertEqual(exc.exception.status_code, 400)
        self.assertEqual(exc.exception.detail, "Twitter username is required")

    async def test_bulk_create_monitors_summarizes_created_skipped_and_failed(self):
        async with self.session_factory() as session:
            await create_monitor(
                MonitorCreate(
                    twitter_username="@OpenAI",
                    display_name="OpenAI",
                    check_interval=5,
                    account_id=self.account_id,
                ),
                db=session,
            )

        async with self.session_factory() as session:
            result = await bulk_create_monitors(
                MonitorBulkCreate(
                    twitter_usernames=[
                        "@OpenAI",
                        " openai ",
                        "@Anthropic",
                        "anthropic",
                        " ",
                        "@xAI",
                    ],
                    check_interval=1,
                    account_id=self.account_id,
                ),
                db=session,
            )

        self.assertEqual(result.summary.total_requested, 6)
        self.assertEqual(result.summary.total_unique, 3)
        self.assertEqual(result.summary.created, 2)
        self.assertEqual(result.summary.skipped, 3)
        self.assertEqual(result.summary.failed, 1)
        self.assertEqual(
            [monitor.twitter_username for monitor in result.created],
            ["Anthropic", "xAI"],
        )
        self.assertEqual(
            [item.detail for item in result.skipped],
            [
                "Duplicate username in request",
                "Duplicate username in request",
                "Already monitoring this user",
            ],
        )
        self.assertEqual(result.failed[0].detail, "Twitter username is required")
        self.assertEqual(result.created[0].check_interval, 3)

    async def test_bulk_create_monitors_accepts_input_text(self):
        async with self.session_factory() as session:
            result = await bulk_create_monitors(
                MonitorBulkCreate(
                    input_text="\n@OpenAI, @Anthropic，@xAI\n",
                    check_interval=5,
                    account_id=self.account_id,
                ),
                db=session,
            )

        self.assertEqual(result.summary.total_requested, 3)
        self.assertEqual(result.summary.total_unique, 3)
        self.assertEqual(result.summary.created, 3)
        self.assertEqual(result.summary.skipped, 0)
        self.assertEqual(result.summary.failed, 0)
        self.assertEqual(
            [monitor.twitter_username for monitor in result.created],
            ["OpenAI", "Anthropic", "xAI"],
        )

    async def test_bulk_create_monitors_rejects_missing_usernames(self):
        async with self.session_factory() as session:
            with self.assertRaises(HTTPException) as exc:
                await bulk_create_monitors(
                    MonitorBulkCreate(
                        twitter_usernames=[],
                        input_text=" \n , ， ",
                        check_interval=5,
                        account_id=self.account_id,
                    ),
                    db=session,
                )

        self.assertEqual(exc.exception.status_code, 400)
        self.assertEqual(exc.exception.detail, "Twitter username is required")

    async def test_delete_monitor_removes_related_tweets(self):
        async with self.session_factory() as session:
            monitor = await create_monitor(
                MonitorCreate(
                    twitter_username="@OpenAI",
                    display_name="OpenAI",
                    check_interval=5,
                    account_id=self.account_id,
                ),
                db=session,
            )

        async with self.session_factory() as session:
            session.add(
                Tweet(
                    tweet_id="tweet-1",
                    author_username="OpenAI",
                    content="hello",
                    media_urls=None,
                    monitor_id=monitor.id,
                )
            )
            await session.commit()

        async with self.session_factory() as session:
            result = await delete_monitor(monitor.id, db=session)
            self.assertEqual(result, {"ok": True})
            self.assertIsNone(await session.get(Tweet, 1))

    async def test_backfill_monitor_tweets_uses_silent_history_sync(self):
        async with self.session_factory() as session:
            monitor = await create_monitor(
                MonitorCreate(
                    twitter_username="@OpenAI",
                    display_name="OpenAI",
                    check_interval=5,
                    account_id=self.account_id,
                ),
                db=session,
            )

        with patch(
            "backend.routers.monitors.backfill_monitor_history",
            new=AsyncMock(
                return_value={
                    "target": "OpenAI",
                    "status": "ok",
                    "new_tweets": 120,
                    "notified_tweets": 0,
                    "stored_count": 120,
                    "pages_fetched": 3,
                    "reached_end": True,
                    "error": None,
                }
            ),
        ) as backfill_monitor_history_mock:
            async with self.session_factory() as session:
                result = await backfill_monitor_tweets(
                    monitor.id,
                    MonitorBackfillRequest(batch_size=100, until_end=True),
                    db=session,
                )

        self.assertEqual(result.target, "OpenAI")
        self.assertEqual(result.new_tweets, 120)
        self.assertEqual(result.pages_fetched, 3)
        self.assertTrue(result.reached_end)
        backfill_monitor_history_mock.assert_awaited_once()
        args, kwargs = backfill_monitor_history_mock.await_args
        self.assertEqual(args[1].id, monitor.id)
        self.assertEqual(kwargs["batch_size"], 100)
        self.assertTrue(kwargs["until_end"])


if __name__ == "__main__":
    unittest.main()
