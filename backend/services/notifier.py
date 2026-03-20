import base64
import hashlib
import hmac
import logging
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

logger = logging.getLogger(__name__)


def _format_media_text(media_items: list[dict]) -> str:
    """Format media items as text links for notifications."""
    if not media_items:
        return ""
    lines = []
    for i, item in enumerate(media_items, 1):
        media_type = item.get("type", "photo")
        url = item.get("url", "")
        if media_type == "photo":
            lines.append(f"[图片{i}]({url})")
        elif media_type == "video":
            lines.append(f"[视频{i}]({url})")
        elif media_type == "animated_gif":
            lines.append(f"[GIF{i}]({url})")
    return "\n".join(lines)


def _build_dingtalk_webhook_url(webhook_url: str, secret: str | None = None) -> str:
    if not secret:
        return webhook_url

    timestamp = str(int(time.time() * 1000))
    string_to_sign = f"{timestamp}\n{secret}"
    signature = base64.b64encode(
        hmac.new(
            secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
    ).decode("utf-8")

    parsed = urlsplit(webhook_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["timestamp"] = timestamp
    query["sign"] = signature

    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )


async def send_enterprise_wechat(webhook_url: str, title: str, content: str, tweet_url: str, media_items: list[dict] | None = None) -> bool:
    """Send notification via Enterprise WeChat webhook (markdown message)."""
    media_text = _format_media_text(media_items or [])
    markdown_content = (
        f"## {title}\n\n"
        f"{content}\n\n"
        + (f"{media_text}\n\n" if media_text else "")
        + f"[查看原文]({tweet_url})"
    )
    payload = {
        "msgtype": "markdown",
        "markdown": {"content": markdown_content},
    }
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(webhook_url, json=payload, timeout=10)
            data = resp.json()
            if data.get("errcode") != 0:
                logger.error(f"WeChat webhook error: {data}")
                return False
            return True
    except Exception as e:
        logger.error(f"WeChat webhook failed: {e}")
        return False


async def send_serverchan(send_key: str, title: str, content: str, tweet_url: str, media_items: list[dict] | None = None) -> bool:
    """Send notification via ServerChan (Server酱)."""
    media_text = _format_media_text(media_items or [])
    desp = f"{content}\n\n" + (f"{media_text}\n\n" if media_text else "") + f"[查看原文]({tweet_url})"
    url = f"https://sctapi.ftqq.com/{send_key}.send"
    payload = {"title": title, "desp": desp}
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, data=payload, timeout=10)
            data = resp.json()
            if data.get("code") != 0:
                logger.error(f"ServerChan error: {data}")
                return False
            return True
    except Exception as e:
        logger.error(f"ServerChan failed: {e}")
        return False


async def send_dingtalk(
    webhook_url: str,
    title: str,
    content: str,
    tweet_url: str,
    media_items: list[dict] | None = None,
    secret: str | None = None,
) -> bool:
    """Send notification via DingTalk custom robot webhook."""
    media_text = _format_media_text(media_items or [])
    markdown_text = (
        f"### {title}\n\n"
        f"{content}\n\n"
        + (f"{media_text}\n\n" if media_text else "")
        + f"[查看原文]({tweet_url})"
    )
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": markdown_text,
        },
    }
    signed_webhook_url = _build_dingtalk_webhook_url(webhook_url, secret)

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(signed_webhook_url, json=payload, timeout=10)
            data = resp.json()
            if data.get("errcode") != 0:
                logger.error(f"DingTalk webhook error: {data}")
                return False
            return True
    except Exception as e:
        logger.error(f"DingTalk webhook failed: {e}")
        return False


async def notify_all_channels(
    channels: list[dict],
    title: str,
    content: str,
    tweet_url: str,
    media_items: list[dict] | None = None,
) -> dict[str, int]:
    """Send notification to all active channels and report delivery stats."""
    attempted = 0
    succeeded = 0
    for ch in channels:
        if not ch.get("is_active"):
            continue
        if ch["channel_type"] == "enterprise_wechat" and ch.get("webhook_url"):
            attempted += 1
            if await send_enterprise_wechat(
                ch["webhook_url"], title, content, tweet_url, media_items
            ):
                succeeded += 1
        elif ch["channel_type"] == "serverchan" and ch.get("send_key"):
            attempted += 1
            if await send_serverchan(
                ch["send_key"], title, content, tweet_url, media_items
            ):
                succeeded += 1
        elif ch["channel_type"] == "dingtalk" and ch.get("webhook_url"):
            attempted += 1
            if await send_dingtalk(
                ch["webhook_url"],
                title,
                content,
                tweet_url,
                media_items,
                secret=ch.get("send_key"),
            ):
                succeeded += 1
    return {"attempted": attempted, "succeeded": succeeded}
