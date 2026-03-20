from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import NotifyChannel
from backend.services.notifier import (
    send_dingtalk,
    send_enterprise_wechat,
    send_serverchan,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])
ALLOWED_CHANNEL_TYPES = {"enterprise_wechat", "serverchan", "dingtalk"}


class ChannelCreate(BaseModel):
    channel_type: str  # enterprise_wechat / serverchan / dingtalk
    name: str
    webhook_url: str | None = None
    send_key: str | None = None


class ChannelResponse(BaseModel):
    id: int
    channel_type: str
    name: str
    webhook_url: str | None
    send_key: str | None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/channels", response_model=list[ChannelResponse])
async def list_channels(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(NotifyChannel))
    return result.scalars().all()


@router.post("/channels", response_model=ChannelResponse)
async def create_channel(req: ChannelCreate, db: AsyncSession = Depends(get_db)):
    if req.channel_type not in ALLOWED_CHANNEL_TYPES:
        raise HTTPException(status_code=400, detail="Invalid channel type")

    channel = NotifyChannel(
        channel_type=req.channel_type,
        name=req.name,
        webhook_url=req.webhook_url,
        send_key=req.send_key,
    )
    db.add(channel)
    await db.commit()
    await db.refresh(channel)
    return channel


@router.put("/channels/{channel_id}", response_model=ChannelResponse)
async def update_channel(
    channel_id: int, req: ChannelCreate, db: AsyncSession = Depends(get_db)
):
    if req.channel_type not in ALLOWED_CHANNEL_TYPES:
        raise HTTPException(status_code=400, detail="Invalid channel type")

    channel = await db.get(NotifyChannel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    channel.channel_type = req.channel_type
    channel.name = req.name
    channel.webhook_url = req.webhook_url
    channel.send_key = req.send_key
    await db.commit()
    await db.refresh(channel)
    return channel


@router.delete("/channels/{channel_id}")
async def delete_channel(channel_id: int, db: AsyncSession = Depends(get_db)):
    channel = await db.get(NotifyChannel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    await db.delete(channel)
    await db.commit()
    return {"ok": True}


@router.post("/channels/{channel_id}/test")
async def test_channel(channel_id: int, db: AsyncSession = Depends(get_db)):
    """Send a test notification through this channel."""
    channel = await db.get(NotifyChannel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    title = "测试通知 - Twitter Monitor"
    content = "这是一条测试消息，如果你看到了说明推送配置成功！"
    tweet_url = "https://x.com"

    success = False
    if channel.channel_type == "enterprise_wechat" and channel.webhook_url:
        success = await send_enterprise_wechat(channel.webhook_url, title, content, tweet_url)
    elif channel.channel_type == "serverchan" and channel.send_key:
        success = await send_serverchan(channel.send_key, title, content, tweet_url)
    elif channel.channel_type == "dingtalk" and channel.webhook_url:
        success = await send_dingtalk(
            channel.webhook_url,
            title,
            content,
            tweet_url,
            secret=channel.send_key,
        )

    if not success:
        raise HTTPException(status_code=500, detail="Notification send failed")
    return {"ok": True, "message": "Test notification sent"}
