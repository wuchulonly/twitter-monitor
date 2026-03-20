import os
import tempfile
import unittest
import json
from datetime import datetime, timedelta
from unittest.mock import ANY, AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.models import Base, MonitorTarget, Tweet, TwitterAccount
from backend.services.monitor import (
    RATE_LIMIT_COOLDOWN_MINUTES,
    backfill_monitor_history,
    check_monitor_target,
    run_all_checks,
)


class CheckMonitorTargetTests(unittest.IsolatedAsyncioTestCase):
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

            monitor = MonitorTarget(
                twitter_username="elonmusk",
                display_name="Elon Musk",
                check_interval=5,
                account_id=account.id,
            )
            session.add(monitor)
            await session.commit()
            await session.refresh(monitor)
            self.monitor_id = monitor.id

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tempdir.cleanup()

    async def run_fake_walk(self, tweets, **kwargs):
        handle_tweet = kwargs["handle_tweet"]
        for tweet in tweets:
            should_continue = await handle_tweet(tweet)
            if should_continue is False:
                break
        return {
            "processed_count": len(tweets),
            "pages_fetched": 1,
            "reached_end": False,
            "next_cursor": "cursor-2",
        }

    async def test_recent_check_only_fetches_one_page_and_sets_resume_cursor(self):
        first_tweet_time = datetime(2026, 3, 20, 8, 0, 0)
        second_tweet_time = first_tweet_time - timedelta(minutes=5)
        fake_tweets = [
            {
                "tweet_id": "200",
                "author_username": "elonmusk",
                "content": "latest",
                "media_urls": None,
                "tweet_created_at": first_tweet_time,
            },
            {
                "tweet_id": "199",
                "author_username": "elonmusk",
                "content": "older",
                "media_urls": None,
                "tweet_created_at": second_tweet_time,
            },
        ]

        async def fake_walk(**kwargs):
            return await self.run_fake_walk(fake_tweets, **kwargs)

        with patch(
            "backend.services.monitor.twitter_service.walk_user_tweets",
            new=AsyncMock(side_effect=fake_walk),
        ) as walk_user_tweets, patch(
            "backend.services.monitor.notify_all_channels",
            new=AsyncMock(return_value={"succeeded": 1}),
        ) as notify_all_channels:
            async with self.session_factory() as session:
                monitor = await session.get(MonitorTarget, self.monitor_id)
                result = await check_monitor_target(session, monitor)

                tweets = (
                    await session.execute(
                        select(Tweet).where(Tweet.monitor_id == self.monitor_id)
                    )
                ).scalars().all()

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["new_tweets"], 2)
        self.assertEqual(result["notified_tweets"], 0)
        self.assertEqual(result["stored_count"], 2)
        self.assertEqual(len(tweets), 2)
        self.assertFalse(any(tweet.is_notified for tweet in tweets))
        notify_all_channels.assert_not_awaited()
        walk_user_tweets.assert_awaited_once_with(
            account_id=self.account_id,
            cookies_json="{}",
            username="elonmusk",
            max_pages=1,
            stop_after=40,
            handle_tweet=ANY,
        )

        async with self.session_factory() as session:
            monitor = await session.get(MonitorTarget, self.monitor_id)
            self.assertEqual(monitor.oldest_cursor, "cursor-2")
            self.assertFalse(monitor.history_complete)

    async def test_existing_monitor_notifies_only_truly_newer_tweets(self):
        latest_known_time = datetime(2026, 3, 20, 8, 0, 0)
        fake_tweets = [
            {
                "tweet_id": "200",
                "author_username": "elonmusk",
                "content": "new",
                "media_urls": json.dumps(
                    [
                        {
                            "type": "photo",
                            "url": "https://pbs.twimg.com/media/example.jpg",
                        }
                    ]
                ),
                "tweet_created_at": latest_known_time + timedelta(minutes=5),
            },
            {
                "tweet_id": "050",
                "author_username": "elonmusk",
                "content": "older",
                "media_urls": None,
                "tweet_created_at": latest_known_time - timedelta(minutes=5),
            },
        ]

        async def fake_walk(**kwargs):
            return await self.run_fake_walk(fake_tweets, **kwargs)

        async with self.session_factory() as session:
            session.add(
                Tweet(
                    tweet_id="100",
                    author_username="elonmusk",
                    content="known",
                    media_urls=None,
                    tweet_created_at=latest_known_time,
                    monitor_id=self.monitor_id,
                )
            )
            await session.commit()

        with patch(
            "backend.services.monitor.twitter_service.walk_user_tweets",
            new=AsyncMock(side_effect=fake_walk),
        ) as walk_user_tweets, patch(
            "backend.services.monitor.notify_all_channels",
            new=AsyncMock(return_value={"succeeded": 1}),
        ) as notify_all_channels:
            async with self.session_factory() as session:
                monitor = await session.get(MonitorTarget, self.monitor_id)
                result = await check_monitor_target(session, monitor)

                tweets = (
                    await session.execute(
                        select(Tweet).where(Tweet.monitor_id == self.monitor_id)
                    )
                ).scalars().all()

        tweets_by_id = {tweet.tweet_id: tweet for tweet in tweets}

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["new_tweets"], 2)
        self.assertEqual(result["notified_tweets"], 1)
        self.assertEqual(len(tweets_by_id), 3)
        self.assertTrue(tweets_by_id["200"].is_notified)
        self.assertFalse(tweets_by_id["050"].is_notified)
        notify_all_channels.assert_awaited_once()
        walk_user_tweets.assert_awaited_once_with(
            account_id=self.account_id,
            cookies_json="{}",
            username="elonmusk",
            max_pages=1,
            stop_after=40,
            handle_tweet=ANY,
        )

    async def test_existing_monitor_skips_notification_for_newer_text_only_tweet(self):
        latest_known_time = datetime(2026, 3, 20, 8, 0, 0)
        fake_tweets = [
            {
                "tweet_id": "200",
                "author_username": "elonmusk",
                "content": "new text only",
                "media_urls": None,
                "tweet_created_at": latest_known_time + timedelta(minutes=5),
            }
        ]

        async def fake_walk(**kwargs):
            return await self.run_fake_walk(fake_tweets, **kwargs)

        async with self.session_factory() as session:
            session.add(
                Tweet(
                    tweet_id="100",
                    author_username="elonmusk",
                    content="known",
                    media_urls=None,
                    tweet_created_at=latest_known_time,
                    monitor_id=self.monitor_id,
                )
            )
            await session.commit()

        with patch(
            "backend.services.monitor.twitter_service.walk_user_tweets",
            new=AsyncMock(side_effect=fake_walk),
        ) as walk_user_tweets, patch(
            "backend.services.monitor.notify_all_channels",
            new=AsyncMock(return_value={"succeeded": 1}),
        ) as notify_all_channels:
            async with self.session_factory() as session:
                monitor = await session.get(MonitorTarget, self.monitor_id)
                result = await check_monitor_target(session, monitor)

                tweets = (
                    await session.execute(
                        select(Tweet).where(Tweet.monitor_id == self.monitor_id)
                    )
                ).scalars().all()

        tweets_by_id = {tweet.tweet_id: tweet for tweet in tweets}

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["new_tweets"], 1)
        self.assertEqual(result["notified_tweets"], 0)
        self.assertEqual(len(tweets_by_id), 2)
        self.assertFalse(tweets_by_id["200"].is_notified)
        notify_all_channels.assert_not_awaited()
        walk_user_tweets.assert_awaited_once_with(
            account_id=self.account_id,
            cookies_json="{}",
            username="elonmusk",
            max_pages=1,
            stop_after=40,
            handle_tweet=ANY,
        )

    async def test_backfill_uses_saved_oldest_cursor_and_commits_progress(self):
        first_page_time = datetime(2026, 3, 20, 8, 0, 0)
        second_page_time = first_page_time - timedelta(hours=1)
        fake_tweets = [
            {
                "tweet_id": "300",
                "author_username": "elonmusk",
                "content": "older 1",
                "media_urls": None,
                "tweet_created_at": second_page_time,
            },
            {
                "tweet_id": "299",
                "author_username": "elonmusk",
                "content": "older 2",
                "media_urls": None,
                "tweet_created_at": second_page_time - timedelta(minutes=5),
            },
        ]

        async with self.session_factory() as session:
            monitor = await session.get(MonitorTarget, self.monitor_id)
            monitor.oldest_cursor = "cursor-older"
            session.add(
                Tweet(
                    tweet_id="400",
                    author_username="elonmusk",
                    content="known",
                    media_urls=None,
                    tweet_created_at=first_page_time,
                    monitor_id=self.monitor_id,
                )
            )
            await session.commit()

        async def fake_walk(**kwargs):
            handle_tweet = kwargs["handle_tweet"]
            after_page = kwargs["after_page"]
            for tweet in fake_tweets:
                await handle_tweet(tweet)
            await after_page(
                {
                    "page_number": 1,
                    "processed_count": 2,
                    "next_cursor": "cursor-even-older",
                }
            )
            return {
                "processed_count": 2,
                "pages_fetched": 1,
                "reached_end": False,
                "next_cursor": "cursor-even-older",
            }

        with patch(
            "backend.services.monitor.twitter_service.walk_user_tweets",
            new=AsyncMock(side_effect=fake_walk),
        ) as walk_user_tweets:
            async with self.session_factory() as session:
                monitor = await session.get(MonitorTarget, self.monitor_id)
                result = await backfill_monitor_history(session, monitor, batch_size=100)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["new_tweets"], 2)
        self.assertEqual(result["stored_count"], 3)
        self.assertFalse(result["reached_end"])
        walk_user_tweets.assert_awaited_once_with(
            account_id=self.account_id,
            cookies_json="{}",
            username="elonmusk",
            cursor="cursor-older",
            max_pages=3,
            after_page=ANY,
            handle_tweet=ANY,
        )

        async with self.session_factory() as session:
            monitor = await session.get(MonitorTarget, self.monitor_id)
            self.assertEqual(monitor.oldest_cursor, "cursor-even-older")
            self.assertFalse(monitor.history_complete)

    async def test_rate_limited_account_skips_remote_fetch(self):
        future_time = datetime.utcnow() + timedelta(minutes=RATE_LIMIT_COOLDOWN_MINUTES)

        async with self.session_factory() as session:
            account = await session.get(TwitterAccount, self.account_id)
            account.rate_limited_until = future_time
            await session.commit()

        with patch(
            "backend.services.monitor.twitter_service.walk_user_tweets",
            new=AsyncMock(),
        ) as walk_user_tweets:
            async with self.session_factory() as session:
                monitor = await session.get(MonitorTarget, self.monitor_id)
                result = await check_monitor_target(session, monitor)

        self.assertEqual(result["status"], "rate_limited")
        self.assertIn("Account rate limited until", result["error"])
        walk_user_tweets.assert_not_awaited()

    async def test_run_all_checks_reports_one_failure_per_rate_limited_account(self):
        async with self.session_factory() as session:
            session.add(
                MonitorTarget(
                    twitter_username="tesla",
                    display_name="Tesla",
                    check_interval=5,
                    account_id=self.account_id,
                )
            )
            await session.commit()

        async def failing_walk(**kwargs):
            raise Exception('status: 429, message: "Rate limit exceeded\\n"')

        with patch(
            "backend.services.monitor.twitter_service.walk_user_tweets",
            new=AsyncMock(side_effect=failing_walk),
        ):
            async with self.session_factory() as session:
                summary = await run_all_checks(session)

        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["checked"], 0)
        self.assertEqual(len(summary["failures"]), 1)
        self.assertEqual(summary["failures"][0]["target"], "elonmusk")


if __name__ == "__main__":
    unittest.main()
