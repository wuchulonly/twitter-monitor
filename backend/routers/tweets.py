import json
from datetime import datetime
from typing import Literal
from urllib.parse import quote, urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from backend.database import get_db
from backend.models import Tweet

router = APIRouter(prefix="/api/tweets", tags=["tweets"])
ALLOWED_MEDIA_HOSTS = {"pbs.twimg.com", "video.twimg.com"}
MEDIA_PROXY_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/134.0.0.0 Safari/537.36"
    ),
    "Referer": "https://x.com/",
    "Origin": "https://x.com",
}


class MediaItem(BaseModel):
    type: str  # "photo", "video", "animated_gif"
    url: str
    thumbnail: str | None = None


class TweetResponse(BaseModel):
    id: int
    tweet_id: str
    author_username: str
    content: str
    media_urls: list[MediaItem]
    tweet_created_at: datetime | None
    fetched_at: datetime
    is_notified: bool
    monitor_id: int

    class Config:
        from_attributes = True


class TweetAuthorSummary(BaseModel):
    author_username: str
    tweet_count: int


class TweetListMetaResponse(BaseModel):
    total: int
    page: int
    size: int
    total_pages: int


def _normalize_author(value: str | None) -> str:
    if not value:
        return ""
    normalized = value.strip()
    while normalized.startswith("@"):
        normalized = normalized[1:].strip()
    return normalized


def _normalize_author_filters(values: str | list[str] | None) -> list[str]:
    if not values:
        return []

    raw_values = [values] if isinstance(values, str) else values
    authors: list[str] = []
    seen: set[str] = set()

    for raw_value in raw_values:
        if not raw_value:
            continue
        for item in raw_value.replace("，", ",").split(","):
            author = _normalize_author(item)
            if not author:
                continue
            author_key = author.lower()
            if author_key in seen:
                continue
            seen.add(author_key)
            authors.append(author)

    return authors


def _apply_author_filters(query, author: str | list[str] | None):
    normalized_authors = _normalize_author_filters(author)
    if not normalized_authors:
        return query

    return query.where(
        func.lower(Tweet.author_username).in_(
            [item.lower() for item in normalized_authors]
        )
    )


def _media_present_condition():
    return and_(
        Tweet.media_urls.is_not(None),
        func.trim(Tweet.media_urls) != "[]",
    )


def _apply_media_filters(
    query,
    has_media: bool,
    media_type: Literal["photo", "video"] | None,
):
    if media_type == "photo":
        return query.where(
            _media_present_condition(),
            or_(
                Tweet.media_urls.like('%"type": "photo"%'),
                Tweet.media_urls.like('%"type":"photo"%'),
                func.trim(Tweet.media_urls).like('["%'),
            ),
        )

    if media_type == "video":
        return query.where(
            _media_present_condition(),
            or_(
                Tweet.media_urls.like('%"type": "video"%'),
                Tweet.media_urls.like('%"type":"video"%'),
                Tweet.media_urls.like('%"type": "animated_gif"%'),
                Tweet.media_urls.like('%"type":"animated_gif"%'),
            ),
        )

    if has_media:
        return query.where(_media_present_condition())

    return query


def _should_proxy_media_url(url: str | None) -> bool:
    if not url:
        return False

    parsed = urlparse(url)
    return (
        parsed.scheme in {"http", "https"}
        and parsed.hostname in ALLOWED_MEDIA_HOSTS
    )


def _proxy_media_url(url: str | None) -> str | None:
    if not _should_proxy_media_url(url):
        return url
    return f"/api/tweets/media?url={quote(url, safe='')}"


def _to_media_item(item_type: str, url: str, thumbnail: str | None = None) -> MediaItem:
    return MediaItem(
        type=item_type,
        url=_proxy_media_url(url) or url,
        thumbnail=_proxy_media_url(thumbnail),
    )


def _format_tweet(t: Tweet) -> TweetResponse:
    media: list[MediaItem] = []
    if t.media_urls:
        try:
            raw = json.loads(t.media_urls)
            for item in raw:
                if isinstance(item, str):
                    # 兼容旧数据：纯 URL 字符串视为图片
                    media.append(_to_media_item("photo", item))
                elif isinstance(item, dict):
                    media.append(
                        _to_media_item(
                            item.get("type", "photo"),
                            item.get("url", ""),
                            item.get("thumbnail"),
                        )
                    )
        except (json.JSONDecodeError, TypeError):
            pass
    return TweetResponse(
        id=t.id,
        tweet_id=t.tweet_id,
        author_username=t.author_username,
        content=t.content,
        media_urls=media,
        tweet_created_at=t.tweet_created_at,
        fetched_at=t.fetched_at,
        is_notified=t.is_notified,
        monitor_id=t.monitor_id,
    )


async def _close_proxy_stream(response: httpx.Response, client: httpx.AsyncClient):
    await response.aclose()
    await client.aclose()


@router.get("", response_model=list[TweetResponse])
async def list_tweets(
    author: list[str] | None = Query(None),
    has_media: bool = False,
    media_type: Literal["photo", "video"] | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    sort_time = func.coalesce(Tweet.tweet_created_at, Tweet.fetched_at)
    query = select(Tweet).order_by(desc(sort_time), desc(Tweet.fetched_at), desc(Tweet.id))
    query = _apply_author_filters(query, author)
    query = _apply_media_filters(query, has_media, media_type)
    query = query.offset((page - 1) * size).limit(size)

    result = await db.execute(query)
    return [_format_tweet(t) for t in result.scalars().all()]


@router.get("/authors", response_model=list[TweetAuthorSummary])
async def list_tweet_authors(db: AsyncSession = Depends(get_db)):
    latest_activity_at = func.max(
        func.coalesce(Tweet.tweet_created_at, Tweet.fetched_at)
    ).label("latest_activity_at")
    result = await db.execute(
        select(
            Tweet.author_username,
            func.count(Tweet.id).label("tweet_count"),
            latest_activity_at,
        )
        .group_by(Tweet.author_username)
        .order_by(desc(latest_activity_at), Tweet.author_username)
    )
    return [
        TweetAuthorSummary(
            author_username=row.author_username,
            tweet_count=row.tweet_count,
        )
        for row in result
    ]


@router.get("/meta", response_model=TweetListMetaResponse)
async def get_tweet_list_meta(
    author: list[str] | None = Query(None),
    has_media: bool = False,
    media_type: Literal["photo", "video"] | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    count_query = _apply_author_filters(
        select(func.count(Tweet.id)),
        author,
    )
    count_query = _apply_media_filters(count_query, has_media, media_type)
    total = int((await db.execute(count_query)).scalar_one() or 0)
    total_pages = max((total + size - 1) // size, 1)

    return TweetListMetaResponse(
        total=total,
        page=page,
        size=size,
        total_pages=total_pages,
    )


@router.get("/media")
async def proxy_tweet_media(url: str, request: Request):
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in ALLOWED_MEDIA_HOSTS:
        raise HTTPException(status_code=400, detail="Unsupported media URL")

    headers = dict(MEDIA_PROXY_HEADERS)
    range_header = request.headers.get("range")
    if range_header:
        headers["Range"] = range_header

    client = httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(30.0, connect=10.0))
    upstream = await client.send(client.build_request("GET", url, headers=headers), stream=True)

    if upstream.status_code >= 400:
        await _close_proxy_stream(upstream, client)
        raise HTTPException(status_code=upstream.status_code, detail="Failed to fetch media")

    response_headers = {}
    for header in (
        "content-length",
        "content-range",
        "accept-ranges",
        "cache-control",
        "etag",
        "last-modified",
    ):
        value = upstream.headers.get(header)
        if value:
            response_headers[header] = value

    return StreamingResponse(
        upstream.aiter_bytes(),
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "application/octet-stream"),
        headers=response_headers,
        background=BackgroundTask(_close_proxy_stream, upstream, client),
    )


@router.get("/{tweet_db_id}", response_model=TweetResponse)
async def get_tweet(tweet_db_id: int, db: AsyncSession = Depends(get_db)):
    tweet = await db.get(Tweet, tweet_db_id)
    if not tweet:
        raise HTTPException(status_code=404, detail="Tweet not found")
    return _format_tweet(tweet)
