from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import TwitterAccount
from backend.services.twitter import twitter_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


class CookieImportRequest(BaseModel):
    cookies: str
    email: str | None = None
    username: str | None = None


class AccountResponse(BaseModel):
    id: int
    username: str
    email: str
    is_active: bool
    has_cookies: bool
    last_login: datetime | None
    created_at: datetime

    class Config:
        from_attributes = True


class ImportResponse(BaseModel):
    status: str
    account: AccountResponse | None = None
    message: str | None = None


def build_account_response(account: TwitterAccount) -> AccountResponse:
    return AccountResponse(
        id=account.id,
        username=account.username,
        email=account.email,
        is_active=account.is_active,
        has_cookies=bool(account.cookies_json),
        last_login=account.last_login,
        created_at=account.created_at,
    )


async def upsert_account(
    db: AsyncSession,
    *,
    username: str,
    email: str | None,
    cookies_json: str,
):
    result = await db.execute(
        select(TwitterAccount).where(TwitterAccount.username == username)
    )
    account = result.scalar_one_or_none()
    resolved_email = (email or "").strip()

    if account:
        if resolved_email:
            account.email = resolved_email
        account.cookies_json = cookies_json
        account.is_active = True
        account.last_login = datetime.utcnow()
        twitter_service.remove_client(account.id)
    else:
        account = TwitterAccount(
            username=username,
            email=resolved_email,
            cookies_json=cookies_json,
            is_active=True,
            last_login=datetime.utcnow(),
        )
        db.add(account)

    await db.commit()
    await db.refresh(account)
    return account


@router.post("/import-cookies", response_model=ImportResponse)
async def import_cookies(req: CookieImportRequest, db: AsyncSession = Depends(get_db)):
    try:
        result = await twitter_service.import_cookies(
            req.cookies,
            username=req.username.strip() if req.username else None,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cookie import failed: {str(e)}")

    account = await upsert_account(
        db,
        username=result["username"],
        email=req.email.strip() if req.email else None,
        cookies_json=result["cookies_json"],
    )

    return ImportResponse(
        status="success",
        account=build_account_response(account),
        message=f"Cookies imported for @{account.username}.",
    )


@router.get("/accounts", response_model=list[AccountResponse])
async def list_accounts(db: AsyncSession = Depends(get_db)):
    """List all Twitter accounts."""
    result = await db.execute(select(TwitterAccount))
    accounts = result.scalars().all()
    return [build_account_response(a) for a in accounts]


@router.delete("/accounts/{account_id}")
async def delete_account(account_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a Twitter account."""
    account = await db.get(TwitterAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    await db.delete(account)
    await db.commit()
    twitter_service.remove_client(account_id)
    return {"ok": True}
