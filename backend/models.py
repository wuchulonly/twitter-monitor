from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TwitterAccount(Base):
    __tablename__ = "twitter_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(200), nullable=False)
    cookies_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rate_limited_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    monitors: Mapped[list["MonitorTarget"]] = relationship(back_populates="account")


class MonitorTarget(Base):
    __tablename__ = "monitor_targets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    twitter_username: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    check_interval: Mapped[int] = mapped_column(Integer, default=5)  # minutes
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_check: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    oldest_cursor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    history_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("twitter_accounts.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    account: Mapped["TwitterAccount"] = relationship(back_populates="monitors")
    tweets: Mapped[list["Tweet"]] = relationship(back_populates="monitor")


class Tweet(Base):
    __tablename__ = "tweets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tweet_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    author_username: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    media_urls: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array
    tweet_created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    is_notified: Mapped[bool] = mapped_column(Boolean, default=False)
    monitor_id: Mapped[int] = mapped_column(Integer, ForeignKey("monitor_targets.id"))

    monitor: Mapped["MonitorTarget"] = relationship(back_populates="tweets")


class NotifyChannel(Base):
    __tablename__ = "notify_channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_type: Mapped[str] = mapped_column(String(50), nullable=False)  # enterprise_wechat / serverchan / dingtalk
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    webhook_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    send_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
