import json
import logging
from datetime import datetime, timedelta
from math import ceil

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import MonitorTarget, NotifyChannel, Tweet, TwitterAccount
from backend.services.notifier import notify_all_channels
from backend.services.twitter import MAX_TWEET_PAGE_SIZE, twitter_service

logger = logging.getLogger(__name__)

RECENT_FETCH_COUNT = 40
RATE_LIMIT_COOLDOWN_MINUTES = 15


def _is_newer_than_latest_known(
    tweet_data: dict,
    latest_known_at: datetime | None,
    latest_known_id: str | None,
) -> bool:
    if latest_known_at is None:
        return False

    tweet_created_at = tweet_data.get("tweet_created_at")
    if tweet_created_at is None:
        return False

    if tweet_created_at > latest_known_at:
        return True
    if tweet_created_at < latest_known_at:
        return False

    tweet_id = tweet_data.get("tweet_id")
    if tweet_id is None or latest_known_id is None:
        return False

    try:
        return int(str(tweet_id)) > int(str(latest_known_id))
    except (TypeError, ValueError):
        return str(tweet_id) != str(latest_known_id)


def _parse_media_items(raw_media_urls: str | None) -> list[dict]:
    if not raw_media_urls:
        return []

    try:
        media_items = json.loads(raw_media_urls)
    except (json.JSONDecodeError, TypeError):
        return []

    if not isinstance(media_items, list):
        return []

    return [item for item in media_items if isinstance(item, dict) and item.get("url")]


async def check_monitor_target(db: AsyncSession, target: MonitorTarget):
    """Check a single monitor target for new tweets and send notifications."""
    return await sync_monitor_target(db, target)


async def _load_monitor_sync_state(db: AsyncSession, target: MonitorTarget):
    existing_count_result = await db.execute(
        select(func.count(Tweet.id)).where(Tweet.monitor_id == target.id)
    )
    existing_count = int(existing_count_result.scalar_one() or 0)

    latest_known_result = await db.execute(
        select(Tweet.tweet_id, Tweet.tweet_created_at)
        .where(Tweet.monitor_id == target.id)
        .order_by(desc(Tweet.tweet_created_at), desc(Tweet.tweet_id))
        .limit(1)
    )
    latest_known_row = latest_known_result.first()

    return (
        existing_count,
        latest_known_row.tweet_id if latest_known_row else None,
        latest_known_row.tweet_created_at if latest_known_row else None,
    )


async def _load_active_channels(db: AsyncSession):
    channel_result = await db.execute(
        select(NotifyChannel).where(NotifyChannel.is_active == True)
    )
    return [
        {
            "channel_type": ch.channel_type,
            "webhook_url": ch.webhook_url,
            "send_key": ch.send_key,
            "is_active": ch.is_active,
        }
        for ch in channel_result.scalars().all()
    ]


async def _bootstrap_oldest_cursor(
    db: AsyncSession,
    target: MonitorTarget,
    account: TwitterAccount,
    existing_count: int,
):
    if target.history_complete or target.oldest_cursor is not None or existing_count == 0:
        return target.oldest_cursor

    bootstrap_result = await twitter_service.walk_user_tweets(
        account_id=account.id,
        cookies_json=account.cookies_json,
        username=target.twitter_username,
        max_pages=1,
        stop_after=RECENT_FETCH_COUNT,
    )

    if bootstrap_result["reached_end"] or not bootstrap_result["next_cursor"]:
        target.oldest_cursor = None
        target.history_complete = True
    else:
        target.oldest_cursor = bootstrap_result["next_cursor"]

    await db.commit()
    return target.oldest_cursor


def _is_rate_limit_error(message: str | None) -> bool:
    if not message:
        return False
    lowered = message.lower()
    return "429" in lowered or "rate limit" in lowered


def _build_rate_limit_message(account: TwitterAccount) -> str:
    if not account.rate_limited_until:
        return "Account is rate limited"
    return (
        "Account rate limited until "
        f"{account.rate_limited_until.isoformat(timespec='seconds')} UTC"
    )


async def _mark_account_rate_limited(
    db: AsyncSession,
    account: TwitterAccount,
    *,
    commit: bool = True,
):
    account.rate_limited_until = datetime.utcnow() + timedelta(
        minutes=RATE_LIMIT_COOLDOWN_MINUTES
    )
    if commit:
        await db.commit()


def _account_is_rate_limited(account: TwitterAccount) -> bool:
    return bool(
        account.rate_limited_until and account.rate_limited_until > datetime.utcnow()
    )


async def sync_monitor_target(
    db: AsyncSession,
    target: MonitorTarget,
):
    """Sync only the most recent page for a monitor target."""
    result = {
        "target": target.twitter_username,
        "status": "ok",
        "new_tweets": 0,
        "notified_tweets": 0,
        "stored_count": 0,
        "pages_fetched": 0,
        "reached_end": False,
        "error": None,
    }

    # Get the associated Twitter account
    account = await db.get(TwitterAccount, target.account_id)
    if not account or not account.cookies_json or not account.is_active:
        logger.warning(f"Skipping @{target.twitter_username}: account unavailable")
        result["status"] = "error"
        result["error"] = "Account unavailable"
        return result
    if _account_is_rate_limited(account):
        result["status"] = "rate_limited"
        result["error"] = _build_rate_limit_message(account)
        return result

    channels = await _load_active_channels(db)
    existing_count, latest_known_id, latest_known_at = await _load_monitor_sync_state(
        db, target
    )

    new_count = 0
    notified_count = 0

    async def handle_tweet(tweet_data: dict):
        nonlocal new_count, notified_count

        existing = await db.execute(
            select(Tweet).where(Tweet.tweet_id == tweet_data["tweet_id"])
        )
        existing_tweet = existing.scalar_one_or_none()
        if existing_tweet:
            updated = False

            if existing_tweet.content != tweet_data["content"]:
                existing_tweet.content = tweet_data["content"]
                updated = True

            if existing_tweet.media_urls != tweet_data["media_urls"]:
                existing_tweet.media_urls = tweet_data["media_urls"]
                updated = True

            if existing_tweet.tweet_created_at != tweet_data["tweet_created_at"]:
                existing_tweet.tweet_created_at = tweet_data["tweet_created_at"]
                updated = True

            if updated:
                logger.info(
                    "Refreshed cached tweet media/content for %s",
                    tweet_data["tweet_id"],
                )
            return True

        tweet = Tweet(
            tweet_id=tweet_data["tweet_id"],
            author_username=tweet_data["author_username"],
            content=tweet_data["content"],
            media_urls=tweet_data["media_urls"],
            tweet_created_at=tweet_data["tweet_created_at"],
            monitor_id=target.id,
        )
        db.add(tweet)
        new_count += 1

        should_notify = _is_newer_than_latest_known(
            tweet_data, latest_known_at, latest_known_id
        )
        media_items = _parse_media_items(tweet_data.get("media_urls"))

        if should_notify and media_items:
            display = target.display_name or target.twitter_username
            title = f"@{display} 发布了新推文"
            content_preview = tweet_data["content"][:200]
            tweet_url = f"https://x.com/{target.twitter_username}/status/{tweet_data['tweet_id']}"

            notify_result = await notify_all_channels(
                channels, title, content_preview, tweet_url, media_items
            )
            if notify_result["succeeded"] > 0:
                tweet.is_notified = True
                notified_count += 1

        return True

    try:
        walk_result = await twitter_service.walk_user_tweets(
            account_id=account.id,
            cookies_json=account.cookies_json,
            username=target.twitter_username,
            max_pages=1,
            stop_after=RECENT_FETCH_COUNT,
            handle_tweet=handle_tweet,
        )
    except Exception as e:
        logger.error(f"Error fetching tweets for @{target.twitter_username}: {e}")
        result["error"] = str(e)
        if _is_rate_limit_error(result["error"]):
            await _mark_account_rate_limited(db, account)
            result["status"] = "rate_limited"
            result["error"] = _build_rate_limit_message(account)
            return result
        result["status"] = "error"
        return result

    account.rate_limited_until = None
    if target.oldest_cursor is None:
        if walk_result["reached_end"] or not walk_result["next_cursor"]:
            target.history_complete = True
            target.oldest_cursor = None
        else:
            target.oldest_cursor = walk_result["next_cursor"]

    # Update last check time
    target.last_check = datetime.utcnow()
    await db.commit()

    result["new_tweets"] = new_count
    result["notified_tweets"] = notified_count
    result["stored_count"] = existing_count + new_count
    result["pages_fetched"] = walk_result["pages_fetched"]
    result["reached_end"] = walk_result["reached_end"]
    if new_count:
        logger.info(f"@{target.twitter_username}: {new_count} new tweets")
    return result


async def backfill_monitor_history(
    db: AsyncSession,
    target: MonitorTarget,
    *,
    batch_size: int = 100,
    until_end: bool = False,
):
    """Continue walking older timeline pages from the persisted oldest cursor."""
    result = {
        "target": target.twitter_username,
        "status": "ok",
        "new_tweets": 0,
        "notified_tweets": 0,
        "stored_count": 0,
        "pages_fetched": 0,
        "reached_end": False,
        "error": None,
    }

    account = await db.get(TwitterAccount, target.account_id)
    if not account or not account.cookies_json or not account.is_active:
        logger.warning(f"Skipping @{target.twitter_username}: account unavailable")
        result["status"] = "error"
        result["error"] = "Account unavailable"
        return result
    if _account_is_rate_limited(account):
        result["status"] = "rate_limited"
        result["error"] = _build_rate_limit_message(account)
        return result

    existing_count, _, _ = await _load_monitor_sync_state(db, target)
    result["stored_count"] = existing_count

    if target.history_complete:
        result["reached_end"] = True
        return result

    cursor = await _bootstrap_oldest_cursor(db, target, account, existing_count)
    if target.history_complete:
        result["reached_end"] = True
        return result

    requested_pages = None if until_end else max(1, ceil(batch_size / MAX_TWEET_PAGE_SIZE))
    new_count = 0

    async def handle_tweet(tweet_data: dict):
        nonlocal new_count

        existing = await db.execute(
            select(Tweet).where(Tweet.tweet_id == tweet_data["tweet_id"])
        )
        existing_tweet = existing.scalar_one_or_none()
        if existing_tweet:
            updated = False

            if existing_tweet.content != tweet_data["content"]:
                existing_tweet.content = tweet_data["content"]
                updated = True

            if existing_tweet.media_urls != tweet_data["media_urls"]:
                existing_tweet.media_urls = tweet_data["media_urls"]
                updated = True

            if existing_tweet.tweet_created_at != tweet_data["tweet_created_at"]:
                existing_tweet.tweet_created_at = tweet_data["tweet_created_at"]
                updated = True

            if updated:
                logger.info(
                    "Refreshed cached tweet media/content for %s",
                    tweet_data["tweet_id"],
                )
            return True

        db.add(
            Tweet(
                tweet_id=tweet_data["tweet_id"],
                author_username=tweet_data["author_username"],
                content=tweet_data["content"],
                media_urls=tweet_data["media_urls"],
                tweet_created_at=tweet_data["tweet_created_at"],
                monitor_id=target.id,
            )
        )
        new_count += 1
        return True

    async def after_page(page_info: dict):
        target.oldest_cursor = page_info["next_cursor"]
        target.history_complete = not page_info["next_cursor"]
        target.last_check = datetime.utcnow()
        account.rate_limited_until = None
        await db.commit()

    try:
        walk_result = await twitter_service.walk_user_tweets(
            account_id=account.id,
            cookies_json=account.cookies_json,
            username=target.twitter_username,
            cursor=cursor,
            max_pages=requested_pages,
            after_page=after_page,
            handle_tweet=handle_tweet,
        )
    except Exception as e:
        logger.error(f"Error backfilling tweets for @{target.twitter_username}: {e}")
        result["error"] = str(e)
        if _is_rate_limit_error(result["error"]):
            await _mark_account_rate_limited(db, account)
            result["status"] = "rate_limited"
            result["error"] = _build_rate_limit_message(account)
        else:
            result["status"] = "error"
        result["new_tweets"] = new_count
        result["stored_count"] = existing_count + new_count
        result["reached_end"] = target.history_complete
        return result

    result["new_tweets"] = new_count
    result["stored_count"] = existing_count + new_count
    result["pages_fetched"] = walk_result["pages_fetched"]
    result["reached_end"] = walk_result["reached_end"] or target.history_complete
    return result


async def run_all_checks(db: AsyncSession):
    """Run checks for all active monitor targets."""
    result = await db.execute(
        select(MonitorTarget).where(MonitorTarget.is_active == True)
    )
    targets = result.scalars().all()

    summary = {
        "total": len(targets),
        "checked": 0,
        "new_tweets": 0,
        "notified_tweets": 0,
        "failures": [],
    }
    blocked_accounts: set[int] = set()

    for target in targets:
        if target.account_id in blocked_accounts:
            continue
        check_result = await check_monitor_target(db, target)
        summary["new_tweets"] += check_result["new_tweets"]
        summary["notified_tweets"] += check_result["notified_tweets"]
        if check_result["status"] == "ok":
            summary["checked"] += 1
        elif check_result["status"] == "rate_limited":
            blocked_accounts.add(target.account_id)
            summary["failures"].append(
                {
                    "target": check_result["target"],
                    "error": check_result["error"],
                }
            )
        else:
            summary["failures"].append(
                {
                    "target": check_result["target"],
                    "error": check_result["error"],
                }
            )

    return summary
