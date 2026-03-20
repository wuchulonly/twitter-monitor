import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.models import Base, MonitorTarget, Tweet, TwitterAccount
from backend.routers.tweets import get_tweet_list_meta, list_tweet_authors, list_tweets


class TweetAuthorSummaryTests(unittest.IsolatedAsyncioTestCase):
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

            first_monitor = MonitorTarget(
                twitter_username="OpenAI",
                check_interval=5,
                account_id=account.id,
            )
            second_monitor = MonitorTarget(
                twitter_username="NASA",
                check_interval=5,
                account_id=account.id,
            )
            session.add_all([first_monitor, second_monitor])
            await session.commit()
            await session.refresh(first_monitor)
            await session.refresh(second_monitor)

            self.first_monitor_id = first_monitor.id
            self.second_monitor_id = second_monitor.id

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tempdir.cleanup()

    async def test_list_tweet_authors_returns_counts_sorted_by_latest_fetch(self):
        now = datetime.utcnow()

        async with self.session_factory() as session:
            session.add_all(
                [
                    Tweet(
                        tweet_id="openai-1",
                        author_username="OpenAI",
                        content="first",
                        fetched_at=now - timedelta(minutes=10),
                        monitor_id=self.first_monitor_id,
                    ),
                    Tweet(
                        tweet_id="openai-2",
                        author_username="OpenAI",
                        content="second",
                        fetched_at=now - timedelta(minutes=5),
                        monitor_id=self.first_monitor_id,
                    ),
                    Tweet(
                        tweet_id="nasa-1",
                        author_username="NASA",
                        content="latest",
                        fetched_at=now,
                        monitor_id=self.second_monitor_id,
                    ),
                ]
            )
            await session.commit()

        async with self.session_factory() as session:
            result = await list_tweet_authors(db=session)

        self.assertEqual(
            [(item.author_username, item.tweet_count) for item in result],
            [("NASA", 1), ("OpenAI", 2)],
        )

    async def test_list_tweets_filters_multiple_authors_with_normalized_input(self):
        now = datetime.utcnow()

        async with self.session_factory() as session:
            session.add_all(
                [
                    Tweet(
                        tweet_id="openai-1",
                        author_username="OpenAI",
                        content="first",
                        fetched_at=now - timedelta(minutes=3),
                        monitor_id=self.first_monitor_id,
                    ),
                    Tweet(
                        tweet_id="nasa-1",
                        author_username="NASA",
                        content="second",
                        fetched_at=now - timedelta(minutes=2),
                        monitor_id=self.second_monitor_id,
                    ),
                    Tweet(
                        tweet_id="anthropic-1",
                        author_username="Anthropic",
                        content="third",
                        fetched_at=now - timedelta(minutes=1),
                        monitor_id=self.first_monitor_id,
                    ),
                ]
            )
            await session.commit()

        async with self.session_factory() as session:
            result = await list_tweets(
                author=[" @openai, NASA ", "@OPENAI"],
                page=1,
                size=20,
                db=session,
            )

        self.assertEqual(
            [(item.author_username, item.tweet_id) for item in result],
            [("NASA", "nasa-1"), ("OpenAI", "openai-1")],
        )

    async def test_list_tweets_orders_by_tweet_created_at_before_fetched_at(self):
        now = datetime.utcnow()

        async with self.session_factory() as session:
            session.add_all(
                [
                    Tweet(
                        tweet_id="older-created-later-fetched",
                        author_username="OpenAI",
                        content="older",
                        tweet_created_at=now - timedelta(hours=1),
                        fetched_at=now,
                        monitor_id=self.first_monitor_id,
                    ),
                    Tweet(
                        tweet_id="newer-created-earlier-fetched",
                        author_username="NASA",
                        content="newer",
                        tweet_created_at=now,
                        fetched_at=now - timedelta(hours=1),
                        monitor_id=self.second_monitor_id,
                    ),
                ]
            )
            await session.commit()

        async with self.session_factory() as session:
            result = await list_tweets(author=None, page=1, size=20, db=session)

        self.assertEqual(
            [item.tweet_id for item in result],
            ["newer-created-earlier-fetched", "older-created-later-fetched"],
        )

    async def test_list_tweets_can_filter_photo_only(self):
        now = datetime.utcnow()

        async with self.session_factory() as session:
            session.add_all(
                [
                    Tweet(
                        tweet_id="openai-photo",
                        author_username="OpenAI",
                        content="with photo",
                        media_urls=json.dumps(
                            [
                                {
                                    "type": "photo",
                                    "url": "https://pbs.twimg.com/media/example.jpg",
                                }
                            ]
                        ),
                        tweet_created_at=now - timedelta(minutes=2),
                        monitor_id=self.first_monitor_id,
                    ),
                    Tweet(
                        tweet_id="nasa-text",
                        author_username="NASA",
                        content="text only",
                        tweet_created_at=now - timedelta(minutes=1),
                        monitor_id=self.second_monitor_id,
                    ),
                    Tweet(
                        tweet_id="nasa-video",
                        author_username="NASA",
                        content="with video",
                        media_urls=json.dumps(
                            [
                                {
                                    "type": "video",
                                    "url": "https://video.twimg.com/ext_tw_video/example.mp4",
                                    "thumbnail": "https://pbs.twimg.com/ext_tw_video_thumb/example.jpg",
                                }
                            ]
                        ),
                        tweet_created_at=now,
                        monitor_id=self.second_monitor_id,
                    ),
                ]
            )
            await session.commit()

        async with self.session_factory() as session:
            result = await list_tweets(
                author=None,
                media_type="photo",
                page=1,
                size=20,
                db=session,
            )

        self.assertEqual(
            [item.tweet_id for item in result],
            ["openai-photo"],
        )

    async def test_list_tweets_can_filter_video_only_including_gifs(self):
        now = datetime.utcnow()

        async with self.session_factory() as session:
            session.add_all(
                [
                    Tweet(
                        tweet_id="openai-photo",
                        author_username="OpenAI",
                        content="with photo",
                        media_urls=json.dumps(
                            [
                                {
                                    "type": "photo",
                                    "url": "https://pbs.twimg.com/media/example.jpg",
                                }
                            ]
                        ),
                        tweet_created_at=now - timedelta(minutes=3),
                        monitor_id=self.first_monitor_id,
                    ),
                    Tweet(
                        tweet_id="nasa-gif",
                        author_username="NASA",
                        content="with gif",
                        media_urls=json.dumps(
                            [
                                {
                                    "type": "animated_gif",
                                    "url": "https://video.twimg.com/tweet_video/example.mp4",
                                    "thumbnail": "https://pbs.twimg.com/tweet_video_thumb/example.jpg",
                                }
                            ]
                        ),
                        tweet_created_at=now - timedelta(minutes=1),
                        monitor_id=self.second_monitor_id,
                    ),
                    Tweet(
                        tweet_id="nasa-video",
                        author_username="NASA",
                        content="with video",
                        media_urls=json.dumps(
                            [
                                {
                                    "type": "video",
                                    "url": "https://video.twimg.com/ext_tw_video/example.mp4",
                                    "thumbnail": "https://pbs.twimg.com/ext_tw_video_thumb/example.jpg",
                                }
                            ]
                        ),
                        tweet_created_at=now,
                        monitor_id=self.second_monitor_id,
                    ),
                ]
            )
            await session.commit()

        async with self.session_factory() as session:
            result = await list_tweets(
                author=None,
                media_type="video",
                page=1,
                size=20,
                db=session,
            )

        self.assertEqual(
            [item.tweet_id for item in result],
            ["nasa-video", "nasa-gif"],
        )

    async def test_get_tweet_list_meta_returns_total_pages_for_filtered_results(self):
        now = datetime.utcnow()

        async with self.session_factory() as session:
            session.add_all(
                [
                    Tweet(
                        tweet_id=f"openai-{index}",
                        author_username="OpenAI",
                        content=f"tweet {index}",
                        tweet_created_at=now - timedelta(minutes=index),
                        monitor_id=self.first_monitor_id,
                    )
                    for index in range(5)
                ]
                + [
                    Tweet(
                        tweet_id="nasa-1",
                        author_username="NASA",
                        content="other",
                        tweet_created_at=now,
                        monitor_id=self.second_monitor_id,
                    )
                ]
            )
            await session.commit()

        async with self.session_factory() as session:
            result = await get_tweet_list_meta(
                author=["@openai"],
                page=2,
                size=2,
                db=session,
            )

        self.assertEqual(result.total, 5)
        self.assertEqual(result.page, 2)
        self.assertEqual(result.size, 2)
        self.assertEqual(result.total_pages, 3)

    async def test_get_tweet_list_meta_counts_video_only_results(self):
        now = datetime.utcnow()

        async with self.session_factory() as session:
            session.add_all(
                [
                    Tweet(
                        tweet_id="openai-photo-1",
                        author_username="OpenAI",
                        content="photo 1",
                        media_urls=json.dumps(
                            [
                                {
                                    "type": "photo",
                                    "url": "https://pbs.twimg.com/media/example-1.jpg",
                                }
                            ]
                        ),
                        tweet_created_at=now - timedelta(minutes=2),
                        monitor_id=self.first_monitor_id,
                    ),
                    Tweet(
                        tweet_id="openai-text",
                        author_username="OpenAI",
                        content="text",
                        tweet_created_at=now - timedelta(minutes=1),
                        monitor_id=self.first_monitor_id,
                    ),
                    Tweet(
                        tweet_id="openai-video-1",
                        author_username="OpenAI",
                        content="video 1",
                        media_urls=json.dumps(
                            [
                                {
                                    "type": "video",
                                    "url": "https://video.twimg.com/ext_tw_video/example-1.mp4",
                                }
                            ]
                        ),
                        tweet_created_at=now,
                        monitor_id=self.first_monitor_id,
                    ),
                    Tweet(
                        tweet_id="openai-gif-1",
                        author_username="OpenAI",
                        content="gif 1",
                        media_urls=json.dumps(
                            [
                                {
                                    "type": "animated_gif",
                                    "url": "https://video.twimg.com/tweet_video/example-1.mp4",
                                }
                            ]
                        ),
                        tweet_created_at=now - timedelta(seconds=30),
                        monitor_id=self.first_monitor_id,
                    ),
                ]
            )
            await session.commit()

        async with self.session_factory() as session:
            result = await get_tweet_list_meta(
                author=["@openai"],
                media_type="video",
                page=1,
                size=1,
                db=session,
            )

        self.assertEqual(result.total, 2)
        self.assertEqual(result.page, 1)
        self.assertEqual(result.size, 1)
        self.assertEqual(result.total_pages, 2)
