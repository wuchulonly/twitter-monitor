import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import MonitorTarget, Tweet, TwitterAccount
from backend.services.monitor import backfill_monitor_history

router = APIRouter(prefix="/api/monitors", tags=["monitors"])


class MonitorCreate(BaseModel):
    twitter_username: str
    display_name: str | None = None
    check_interval: int = 5
    account_id: int


class MonitorBulkCreate(BaseModel):
    twitter_usernames: list[str] | None = None
    input_text: str | None = None
    check_interval: int = 5
    account_id: int


class MonitorResponse(BaseModel):
    id: int
    twitter_username: str
    display_name: str | None
    avatar_url: str | None
    check_interval: int
    is_active: bool
    last_check: datetime | None
    history_complete: bool
    account_id: int
    created_at: datetime

    class Config:
        from_attributes = True


class MonitorBulkItemResult(BaseModel):
    twitter_username: str
    detail: str


class MonitorBulkSummary(BaseModel):
    total_requested: int
    total_unique: int
    created: int
    skipped: int
    failed: int


class MonitorBulkResponse(BaseModel):
    created: list[MonitorResponse]
    skipped: list[MonitorBulkItemResult]
    failed: list[MonitorBulkItemResult]
    summary: MonitorBulkSummary


class MonitorBackfillRequest(BaseModel):
    batch_size: int = 100
    until_end: bool = False


class MonitorBackfillResponse(BaseModel):
    target: str
    status: str
    new_tweets: int
    notified_tweets: int
    stored_count: int
    pages_fetched: int
    reached_end: bool
    error: str | None = None


def normalize_username(value: str) -> str:
    return value.strip().lstrip("@").strip()


def normalize_display_name(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def build_monitor_response(monitor: MonitorTarget) -> MonitorResponse:
    return MonitorResponse(
        id=monitor.id,
        twitter_username=monitor.twitter_username,
        display_name=monitor.display_name,
        avatar_url=monitor.avatar_url,
        check_interval=monitor.check_interval,
        is_active=monitor.is_active,
        last_check=monitor.last_check,
        history_complete=monitor.history_complete,
        account_id=monitor.account_id,
        created_at=monitor.created_at,
    )


def get_bulk_usernames(req: MonitorBulkCreate) -> list[str]:
    usernames = list(req.twitter_usernames or [])
    if req.input_text:
        usernames.extend(
            value for value in re.split(r"[\n,，]+", req.input_text) if value.strip()
        )
    return usernames


async def ensure_account_exists(account_id: int, db: AsyncSession) -> TwitterAccount:
    account = await db.get(TwitterAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Twitter account not found")
    return account


@router.get("", response_model=list[MonitorResponse])
async def list_monitors(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(MonitorTarget))
    return [build_monitor_response(m) for m in result.scalars().all()]


@router.post("", response_model=MonitorResponse)
async def create_monitor(req: MonitorCreate, db: AsyncSession = Depends(get_db)):
    normalized_username = normalize_username(req.twitter_username)
    normalized_display_name = normalize_display_name(req.display_name)
    if not normalized_username:
        raise HTTPException(status_code=400, detail="Twitter username is required")

    # Verify account exists
    await ensure_account_exists(req.account_id, db)

    # Check duplicate
    existing = await db.execute(
        select(MonitorTarget).where(
            func.lower(MonitorTarget.twitter_username) == normalized_username.lower(),
            MonitorTarget.account_id == req.account_id,
        ).limit(1)
    )
    if existing.scalars().first():
        raise HTTPException(status_code=409, detail="Already monitoring this user")

    monitor = MonitorTarget(
        twitter_username=normalized_username,
        display_name=normalized_display_name or None,
        check_interval=max(req.check_interval, 3),  # minimum 3 minutes
        account_id=req.account_id,
    )
    db.add(monitor)
    await db.commit()
    await db.refresh(monitor)
    return build_monitor_response(monitor)


@router.post("/bulk", response_model=MonitorBulkResponse)
async def bulk_create_monitors(
    req: MonitorBulkCreate, db: AsyncSession = Depends(get_db)
):
    await ensure_account_exists(req.account_id, db)

    raw_usernames = get_bulk_usernames(req)
    if not raw_usernames:
        raise HTTPException(status_code=400, detail="Twitter username is required")

    unique_usernames: list[str] = []
    seen_usernames: set[str] = set()
    skipped: list[MonitorBulkItemResult] = []
    failed: list[MonitorBulkItemResult] = []

    for raw_username in raw_usernames:
        normalized_username = normalize_username(raw_username)
        if not normalized_username:
            failed.append(
                MonitorBulkItemResult(
                    twitter_username="",
                    detail="Twitter username is required",
                )
            )
            continue

        username_key = normalized_username.lower()
        if username_key in seen_usernames:
            skipped.append(
                MonitorBulkItemResult(
                    twitter_username=normalized_username,
                    detail="Duplicate username in request",
                )
            )
            continue

        seen_usernames.add(username_key)
        unique_usernames.append(normalized_username)

    existing_by_username: dict[str, MonitorTarget] = {}
    if seen_usernames:
        existing_result = await db.execute(
            select(MonitorTarget).where(
                MonitorTarget.account_id == req.account_id,
                func.lower(MonitorTarget.twitter_username).in_(seen_usernames),
            )
        )
        existing_by_username = {
            monitor.twitter_username.lower(): monitor
            for monitor in existing_result.scalars().all()
        }

    created_monitors: list[MonitorTarget] = []
    normalized_interval = max(req.check_interval, 3)
    for username in unique_usernames:
        username_key = username.lower()
        if username_key in existing_by_username:
            skipped.append(
                MonitorBulkItemResult(
                    twitter_username=username,
                    detail="Already monitoring this user",
                )
            )
            continue

        monitor = MonitorTarget(
            twitter_username=username,
            check_interval=normalized_interval,
            account_id=req.account_id,
        )
        db.add(monitor)
        created_monitors.append(monitor)

    if created_monitors:
        await db.commit()
        for monitor in created_monitors:
            await db.refresh(monitor)

    return MonitorBulkResponse(
        created=[build_monitor_response(monitor) for monitor in created_monitors],
        skipped=skipped,
        failed=failed,
        summary=MonitorBulkSummary(
            total_requested=len(raw_usernames),
            total_unique=len(unique_usernames),
            created=len(created_monitors),
            skipped=len(skipped),
            failed=len(failed),
        ),
    )


@router.delete("/{monitor_id}")
async def delete_monitor(monitor_id: int, db: AsyncSession = Depends(get_db)):
    monitor = await db.get(MonitorTarget, monitor_id)
    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")
    await db.execute(delete(Tweet).where(Tweet.monitor_id == monitor_id))
    await db.delete(monitor)
    await db.commit()
    return {"ok": True}


@router.post("/{monitor_id}/backfill", response_model=MonitorBackfillResponse)
async def backfill_monitor_tweets(
    monitor_id: int,
    req: MonitorBackfillRequest,
    db: AsyncSession = Depends(get_db),
):
    monitor = await db.get(MonitorTarget, monitor_id)
    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")

    batch_size = max(req.batch_size, 1)
    result = await backfill_monitor_history(
        db,
        monitor,
        batch_size=batch_size,
        until_end=req.until_end,
    )

    if result["status"] != "ok":
        detail = result["error"] or "Backfill failed"
        status_code = 429 if result["status"] == "rate_limited" or "429" in detail or "rate limit" in detail.lower() else 502
        raise HTTPException(status_code=status_code, detail=detail)

    return MonitorBackfillResponse(**result)


@router.patch("/{monitor_id}", response_model=MonitorResponse)
async def update_monitor(
    monitor_id: int,
    is_active: bool | None = None,
    check_interval: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    monitor = await db.get(MonitorTarget, monitor_id)
    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")
    if is_active is not None:
        monitor.is_active = is_active
    if check_interval is not None:
        monitor.check_interval = max(check_interval, 3)
    await db.commit()
    await db.refresh(monitor)
    return build_monitor_response(monitor)
