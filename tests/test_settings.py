import base64
import hashlib
import hmac
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.models import Base, NotifyChannel
from backend.routers.settings import ChannelCreate, create_channel, test_channel
from backend.services.notifier import _build_dingtalk_webhook_url, notify_all_channels


class DingTalkWebhookTests(unittest.TestCase):
    def test_build_dingtalk_webhook_url_appends_signature(self):
        with patch("backend.services.notifier.time.time", return_value=1710000000.123):
            signed_url = _build_dingtalk_webhook_url(
                "https://oapi.dingtalk.com/robot/send?access_token=test",
                "secret-value",
            )

        query = parse_qs(urlsplit(signed_url).query)
        self.assertEqual(query["access_token"], ["test"])
        self.assertEqual(query["timestamp"], ["1710000000123"])

        expected_sign = base64.b64encode(
            hmac.new(
                b"secret-value",
                b"1710000000123\nsecret-value",
                digestmod=hashlib.sha256,
            ).digest()
        ).decode("utf-8")
        self.assertEqual(query["sign"], [expected_sign])


class SettingsChannelTests(unittest.IsolatedAsyncioTestCase):
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

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tempdir.cleanup()

    async def test_create_channel_accepts_dingtalk(self):
        async with self.session_factory() as session:
            channel = await create_channel(
                ChannelCreate(
                    channel_type="dingtalk",
                    name="钉钉群机器人",
                    webhook_url="https://oapi.dingtalk.com/robot/send?access_token=test",
                    send_key="secret-value",
                ),
                db=session,
            )

        self.assertEqual(channel.channel_type, "dingtalk")
        self.assertEqual(channel.name, "钉钉群机器人")
        self.assertEqual(
            channel.webhook_url,
            "https://oapi.dingtalk.com/robot/send?access_token=test",
        )
        self.assertEqual(channel.send_key, "secret-value")

    async def test_test_channel_uses_dingtalk_sender(self):
        async with self.session_factory() as session:
            channel = NotifyChannel(
                channel_type="dingtalk",
                name="DingTalk",
                webhook_url="https://oapi.dingtalk.com/robot/send?access_token=test",
                send_key="secret-value",
                is_active=True,
            )
            session.add(channel)
            await session.commit()
            await session.refresh(channel)
            channel_id = channel.id

        with patch(
            "backend.routers.settings.send_dingtalk",
            new=AsyncMock(return_value=True),
        ) as send_dingtalk:
            async with self.session_factory() as session:
                result = await test_channel(channel_id, db=session)

        self.assertEqual(result, {"ok": True, "message": "Test notification sent"})
        send_dingtalk.assert_awaited_once_with(
            "https://oapi.dingtalk.com/robot/send?access_token=test",
            "测试通知 - Twitter Monitor",
            "这是一条测试消息，如果你看到了说明推送配置成功！",
            "https://x.com",
            secret="secret-value",
        )

    async def test_notify_all_channels_dispatches_dingtalk(self):
        channels = [
            {
                "channel_type": "dingtalk",
                "webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=test",
                "send_key": "secret-value",
                "is_active": True,
            }
        ]

        with patch(
            "backend.services.notifier.send_dingtalk",
            new=AsyncMock(return_value=True),
        ) as send_dingtalk:
            result = await notify_all_channels(
                channels,
                "title",
                "content",
                "https://x.com/user/status/1",
                [{"type": "photo", "url": "https://pbs.twimg.com/media/example.jpg"}],
            )

        self.assertEqual(result, {"attempted": 1, "succeeded": 1})
        send_dingtalk.assert_awaited_once_with(
            "https://oapi.dingtalk.com/robot/send?access_token=test",
            "title",
            "content",
            "https://x.com/user/status/1",
            [{"type": "photo", "url": "https://pbs.twimg.com/media/example.jpg"}],
            secret="secret-value",
        )


if __name__ == "__main__":
    unittest.main()
