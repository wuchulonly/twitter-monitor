import json
import logging
import os
import re
import tempfile
from base64 import urlsafe_b64encode
from datetime import datetime, timezone
from inspect import isawaitable

from twikit import Client
from twikit.client.client import TwitterException
from twikit.x_client_transaction.transaction import (
    ClientTransaction,
    INDICES_REGEX,
    ON_DEMAND_FILE_REGEX,
)

from backend.config import settings

logger = logging.getLogger(__name__)
MAX_TWEET_PAGE_SIZE = 40


def _is_short_tco_url(url: str | None) -> bool:
    return bool(url) and url.startswith("https://t.co/")


def _pick_media_url(media, *attrs: str) -> str:
    for attr in attrs:
        value = getattr(media, attr, None)
        if value:
            return value
    return ""


def _serialize_tweet(tweet, username: str) -> dict:
    tweet_created_at = None
    if tweet.created_at:
        parsed_created_at = datetime.strptime(
            tweet.created_at, "%a %b %d %H:%M:%S %z %Y"
        )
        tweet_created_at = parsed_created_at.astimezone(timezone.utc).replace(
            tzinfo=None
        )

    media_items = []
    if tweet.media:
        for m in tweet.media:
            media_type = getattr(m, "type", "photo")
            if media_type in ("video", "animated_gif"):
                video_url = None
                video_info = getattr(m, "video_info", None)
                if video_info:
                    variants = video_info.get("variants", [])
                    mp4s = [v for v in variants if v.get("content_type") == "video/mp4"]
                    if mp4s:
                        video_url = max(mp4s, key=lambda v: v.get("bitrate", 0))["url"]
                fallback_url = _pick_media_url(m, "media_url_https", "media_url")
                thumbnail_url = _pick_media_url(m, "media_url", "media_url_https")
                media_items.append({
                    "type": media_type,
                    "url": video_url or fallback_url,
                    "thumbnail": thumbnail_url or None,
                })
            else:
                photo_url = _pick_media_url(m, "media_url", "media_url_https", "url")
                if not photo_url or _is_short_tco_url(photo_url):
                    continue
                media_items.append({
                    "type": "photo",
                    "url": photo_url,
                })

    return {
        "tweet_id": str(tweet.id),
        "author_username": username,
        "content": tweet.text or "",
        "media_urls": json.dumps(media_items) if media_items else None,
        "tweet_created_at": tweet_created_at,
    }


class SafeClientTransaction(ClientTransaction):
    # Regex for the new Twitter chunk map format:
    #   chunk_number:"ondemand.s"  (name map)
    #   chunk_number:"hash"        (hash map)
    _CHUNK_NAME_RE = re.compile(r'(\d+)\s*:\s*["\']ondemand\.s["\']')
    _CHUNK_HASH_RE_TEMPLATE = r'{chunk_id}\s*:\s*["\']([a-f0-9]+)["\']'

    def __init__(self):
        super().__init__()
        self._fallback_mode = False

    async def get_indices(self, home_page_response, session, headers):
        """Override to handle Twitter's new webpack chunk map format."""
        response = self.validate_response(
            home_page_response) or self.home_page_response
        response_text = str(response)

        on_demand_file = ON_DEMAND_FILE_REGEX.search(response_text)
        if not on_demand_file:
            # New format: find chunk number for "ondemand.s", then its hash
            chunk_name_match = self._CHUNK_NAME_RE.search(response_text)
            if chunk_name_match:
                chunk_id = chunk_name_match.group(1)
                chunk_hash_re = re.compile(
                    self._CHUNK_HASH_RE_TEMPLATE.format(chunk_id=chunk_id)
                )
                chunk_hash_match = chunk_hash_re.search(response_text)
                if chunk_hash_match:
                    od_hash = chunk_hash_match.group(1)
                    on_demand_file_url = (
                        f"https://abs.twimg.com/responsive-web/client-web/"
                        f"ondemand.s.{od_hash}a.js"
                    )
                    od_response = await session.request(
                        method="GET", url=on_demand_file_url, headers=headers,
                    )
                    key_byte_indices = [
                        m.group(2)
                        for m in INDICES_REGEX.finditer(od_response.text)
                    ]
                    if key_byte_indices:
                        key_byte_indices = list(map(int, key_byte_indices))
                        return key_byte_indices[0], key_byte_indices[1:]

            raise Exception("Couldn't get KEY_BYTE indices")

        # Original path
        on_demand_file_url = (
            f"https://abs.twimg.com/responsive-web/client-web/"
            f"ondemand.s.{on_demand_file.group(1)}a.js"
        )
        od_response = await session.request(
            method="GET", url=on_demand_file_url, headers=headers,
        )
        key_byte_indices = [
            m.group(2) for m in INDICES_REGEX.finditer(od_response.text)
        ]
        if not key_byte_indices:
            raise Exception("Couldn't get KEY_BYTE indices")
        key_byte_indices = list(map(int, key_byte_indices))
        return key_byte_indices[0], key_byte_indices[1:]

    async def init(self, session, headers):
        if not settings.twitter_transaction_fallback:
            await super().init(session, headers)
            return
        try:
            await super().init(session, headers)
        except Exception as exc:
            self._fallback_mode = True
            self.home_page_response = True
            logger.warning(
                "Falling back to a synthetic X-Client-Transaction-Id because Twikit failed to initialize: %s",
                exc,
            )

    def generate_transaction_id(
        self,
        method: str,
        path: str,
        response=None,
        key=None,
        animation_key=None,
        time_now=None,
    ):
        if self._fallback_mode:
            return urlsafe_b64encode(os.urandom(24)).decode().rstrip("=")
        try:
            return super().generate_transaction_id(
                method=method,
                path=path,
                response=response,
                key=key,
                animation_key=animation_key,
                time_now=time_now,
            )
        except Exception as exc:
            if not settings.twitter_transaction_fallback:
                raise
            self._fallback_mode = True
            logger.warning(
                "Falling back to a synthetic X-Client-Transaction-Id because Twikit failed to generate one: %s",
                exc,
            )
            return urlsafe_b64encode(os.urandom(24)).decode().rstrip("=")


class TwitterService:
    def __init__(self):
        self._clients: dict[int, Client] = {}  # account_id -> Client

    def _parse_cookie_header(self, cookie_header: str) -> dict[str, str]:
        cookies: dict[str, str] = {}
        for part in cookie_header.split(";"):
            segment = part.strip()
            if not segment or "=" not in segment:
                continue
            name, value = segment.split("=", 1)
            name = name.strip()
            if not name:
                continue
            cookies[name] = value.strip()
        return cookies

    def _cookies_from_list(self, items: list) -> dict[str, str]:
        cookies: dict[str, str] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("Name")
            value = item.get("value") or item.get("Value")
            if not name or value is None:
                continue
            cookies[str(name)] = str(value)
        return cookies

    def _normalize_cookies(self, cookies_input: str) -> dict[str, str]:
        text = cookies_input.strip()
        if not text:
            raise TwitterException("Cookies text is required.")

        parsed: dict | list | str
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = text

        cookies: dict[str, str] = {}
        if isinstance(parsed, str):
            cookies = self._parse_cookie_header(parsed)
        elif isinstance(parsed, list):
            cookies = self._cookies_from_list(parsed)
        elif isinstance(parsed, dict):
            nested = parsed.get("cookies")
            if isinstance(nested, list):
                cookies = self._cookies_from_list(nested)
            elif isinstance(nested, dict):
                cookies = {
                    str(key): str(value)
                    for key, value in nested.items()
                    if value is not None
                }
            else:
                cookies = {
                    str(key): str(value)
                    for key, value in parsed.items()
                    if value is not None and not isinstance(value, (dict, list))
                }

        if not cookies:
            raise TwitterException(
                "No cookies found. Paste Twikit JSON, a browser cookie JSON array, or a Cookie header string."
            )

        missing = [name for name in ("auth_token", "ct0") if not cookies.get(name)]
        if missing:
            raise TwitterException(
                f"Imported cookies are missing required values: {', '.join(missing)}."
            )
        return cookies

    def _create_client(self) -> Client:
        proxy = settings.twitter_proxy_url.strip() or None
        timeout = settings.twitter_proxy_timeout
        client = Client("en-US", proxy=proxy, timeout=timeout)
        client.client_transaction = SafeClientTransaction()
        return client

    def _save_cookies_json(self, client: Client) -> str:
        fd, tmp_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        try:
            client.save_cookies(tmp_path)
            with open(tmp_path, encoding="utf-8") as f:
                return f.read()
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    async def get_client(self, account_id: int, cookies_json: str) -> Client:
        """Get or create a twikit Client from stored cookies."""
        if account_id in self._clients:
            return self._clients[account_id]

        client = self._create_client()
        fd, tmp_path = tempfile.mkstemp(suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(cookies_json)
            client.load_cookies(tmp_path)
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        self._clients[account_id] = client
        return client

    def remove_client(self, account_id: int):
        """Remove cached client (e.g. when cookies expire)."""
        self._clients.pop(account_id, None)

    async def import_cookies(
        self,
        cookies_input: str,
        *,
        username: str | None = None,
    ) -> dict:
        cookies = self._normalize_cookies(cookies_input)
        client = self._create_client()
        client.set_cookies(cookies, clear_cookies=True)
        try:
            settings_response, _ = await client.v11.settings()
            resolved_username = settings_response.get("screen_name")
            if not resolved_username:
                user = await client.user()
                resolved_username = user.screen_name
        except Exception as exc:
            logger.error("Cookie import validation failed: %s", exc)
            raise TwitterException(f"Imported cookies are invalid or expired: {exc}")
        if username and username.lstrip("@").strip().lower() != resolved_username.lower():
            logger.info(
                "Imported cookies resolved to @%s instead of the provided @%s",
                resolved_username,
                username,
            )

        return {
            "status": "success",
            "username": resolved_username,
            "cookies_json": self._save_cookies_json(client),
        }

    async def get_user_tweets(
        self,
        account_id: int,
        cookies_json: str,
        username: str,
        count: int = 20,
        max_pages: int = 1,
        cursor: str | None = None,
    ) -> list[dict]:
        """Fetch tweets from a user's timeline, paging until the requested count is met."""
        collected: list[dict] = []

        async def collect_tweet(tweet_data: dict):
            collected.append(tweet_data)
            return len(collected) < count

        await self.walk_user_tweets(
            account_id=account_id,
            cookies_json=cookies_json,
            username=username,
            max_pages=max_pages,
            stop_after=max(count, 1),
            cursor=cursor,
            handle_tweet=collect_tweet,
        )
        return collected

    async def walk_user_tweets(
        self,
        account_id: int,
        cookies_json: str,
        username: str,
        *,
        page_size: int = MAX_TWEET_PAGE_SIZE,
        max_pages: int | None = 1,
        stop_after: int | None = None,
        cursor: str | None = None,
        after_page=None,
        handle_tweet=None,
    ) -> dict:
        """Walk tweet pages and process each tweet incrementally."""
        client = await self.get_client(account_id, cookies_json)
        try:
            user = await client.get_user_by_screen_name(username)
            fetch_count = max(1, min(page_size, MAX_TWEET_PAGE_SIZE))
            tweets = await client.get_user_tweets(
                user.id,
                "Tweets",
                count=fetch_count,
                cursor=cursor,
            )

            seen_ids: set[str] = set()
            page_number = 0
            processed_count = 0
            reached_end = False
            next_cursor = cursor

            while True:
                if not tweets:
                    reached_end = True
                    next_cursor = None
                    break

                page_number += 1
                for tweet in tweets:
                    tweet_id = str(tweet.id)
                    if tweet_id in seen_ids:
                        continue
                    seen_ids.add(tweet_id)
                    processed_count += 1

                    if handle_tweet is not None:
                        should_continue = handle_tweet(_serialize_tweet(tweet, username))
                        if isawaitable(should_continue):
                            should_continue = await should_continue
                        if should_continue is False:
                            return {
                                "processed_count": processed_count,
                                "pages_fetched": page_number,
                                "reached_end": False,
                                "next_cursor": getattr(tweets, "next_cursor", None),
                            }

                next_cursor = getattr(tweets, "next_cursor", None)

                if after_page is not None:
                    after_page_result = after_page(
                        {
                            "page_number": page_number,
                            "processed_count": processed_count,
                            "next_cursor": next_cursor,
                        }
                    )
                    if isawaitable(after_page_result):
                        await after_page_result

                if stop_after is not None and processed_count >= stop_after:
                    return {
                        "processed_count": processed_count,
                        "pages_fetched": page_number,
                        "reached_end": False,
                        "next_cursor": next_cursor,
                    }

                if (
                    max_pages is not None
                    and page_number >= max(max_pages, 1)
                ):
                    break

                if not next_cursor:
                    reached_end = True
                    next_cursor = None
                    break

                tweets = await client.get_user_tweets(
                    user.id,
                    "Tweets",
                    count=fetch_count,
                    cursor=next_cursor,
                )
            return {
                "processed_count": processed_count,
                "pages_fetched": page_number,
                "reached_end": reached_end,
                "next_cursor": next_cursor,
            }
        except Exception as e:
            logger.error(f"Failed to fetch tweets for @{username}: {e}")
            # If cookie expired, remove cached client
            if "unauthorized" in str(e).lower() or "403" in str(e):
                self.remove_client(account_id)
            raise


twitter_service = TwitterService()
