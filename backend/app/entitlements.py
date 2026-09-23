import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime

from fastapi import HTTPException

from .config import settings
from .database import Database, utcnow_iso


ACTIVE_SUBSCRIPTION_STATUSES = {"active", "trialing"}


@dataclass(frozen=True)
class Entitlement:
    is_vip: bool
    source: str | None
    expires_at: str | None
    subscription_status: str | None
    cancel_at_period_end: bool


def membership_for(database: Database, user_id: str) -> Entitlement:
    now = datetime.now(UTC)
    grant = database.fetchone(
        """SELECT ends_at FROM membership_grants
           WHERE user_id = ? AND revoked_at IS NULL AND ends_at > ?
           ORDER BY ends_at DESC LIMIT 1""",
        (user_id, now.isoformat()),
    )
    subscription = database.fetchone(
        """SELECT status, current_period_end, cancel_at_period_end
           FROM billing_subscriptions WHERE user_id = ? ORDER BY updated_at DESC LIMIT 1""",
        (user_id,),
    )
    subscription_active = bool(
        subscription
        and subscription["status"] in ACTIVE_SUBSCRIPTION_STATUSES
        and subscription["current_period_end"]
        and datetime.fromisoformat(subscription["current_period_end"]) > now
    )
    if subscription_active:
        return Entitlement(True, "subscription", str(subscription["current_period_end"]), str(subscription["status"]), bool(subscription["cancel_at_period_end"]))
    if grant:
        return Entitlement(True, "one_time", str(grant["ends_at"]), str(subscription["status"]) if subscription else None, bool(subscription["cancel_at_period_end"]) if subscription else False)
    return Entitlement(False, None, None, str(subscription["status"]) if subscription else None, bool(subscription["cancel_at_period_end"]) if subscription else False)


def require_vip(database: Database, user_id: str) -> Entitlement:
    entitlement = membership_for(database, user_id)
    if not entitlement.is_vip:
        raise HTTPException(403, "此功能仅限 VIP 会员使用")
    return entitlement


def remaining_free_downloads(database: Database, user_id: str) -> int | None:
    """下载不再限量：登录用户（含免费用户）均可不限次数下载。

    返回 None 表示"没有剩余额度这个概念"，前端据此显示"不限次数"。
    """
    return None


def consume_download(database: Database, user_id: str, request_key: str) -> int | None:
    """保留调用点，便于将来恢复下载配额；当前规则是登录用户不限次下载。"""
    return None


def anonymous_client_hash(client_address: str) -> str:
    return hashlib.sha256(f"vidnest-anonymous:{client_address}".encode("utf-8")).hexdigest()


def consume_anonymous_download(database: Database, client_address: str, request_key: str) -> int:
    """未登录用户每天有免费下载额度（默认 5 次）；登录后不限次数。"""
    client_hash = anonymous_client_hash(client_address)
    today = date.today().isoformat()
    limit = settings.free_daily_downloads
    with database.transaction(immediate=True) as connection:
        existing = connection.execute(
            "SELECT 1 FROM anonymous_action_requests WHERE client_hash = ? AND action = 'download' AND request_key = ?",
            (client_hash, request_key),
        ).fetchone()
        row = connection.execute(
            "SELECT count FROM anonymous_daily_usage WHERE client_hash = ? AND usage_date = ? AND action = 'download'",
            (client_hash, today),
        ).fetchone()
        count = int(row["count"] if row else 0)
        if existing:
            return max(0, limit - count)
        if count >= limit:
            raise HTTPException(429, f"今日 {limit} 次免费下载额度已用完，登录后可不限次数下载")
        connection.execute(
            "INSERT INTO anonymous_action_requests(client_hash, action, request_key, created_at) VALUES (?, 'download', ?, ?)",
            (client_hash, request_key, utcnow_iso()),
        )
        connection.execute(
            """INSERT INTO anonymous_daily_usage(client_hash, usage_date, action, count) VALUES (?, ?, 'download', 1)
               ON CONFLICT(client_hash, usage_date, action) DO UPDATE SET count = count + 1""",
            (client_hash, today),
        )
        return max(0, limit - count - 1)


def consume_ai_summary(database: Database, user_id: str) -> int | None:
    """非 VIP 用户的每日 AI 总结配额（默认 3 次）。

    真正扣减发生在"总结生成成功"之后，生成失败不扣次数。
    返回剩余次数；VIP 返回 None（不限次）。
    """
    if membership_for(database, user_id).is_vip:
        return None
    limit = settings.free_daily_ai_summaries
    today = date.today().isoformat()
    with database.transaction(immediate=True) as connection:
        row = connection.execute(
            "SELECT count FROM daily_usage WHERE user_id = ? AND usage_date = ? AND action = 'ai_summary'",
            (user_id, today),
        ).fetchone()
        count = int(row["count"] if row else 0)
        connection.execute(
            """INSERT INTO daily_usage(user_id, usage_date, action, count) VALUES (?, ?, 'ai_summary', 1)
               ON CONFLICT(user_id, usage_date, action) DO UPDATE SET count = count + 1""",
            (user_id, today),
        )
        return max(0, limit - count - 1)


def remaining_ai_summaries(database: Database, user_id: str) -> int | None:
    """非 VIP 用户今日剩余的 AI 总结次数；VIP 返回 None（不限次）。"""
    if membership_for(database, user_id).is_vip:
        return None
    row = database.fetchone(
        "SELECT count FROM daily_usage WHERE user_id = ? AND usage_date = ? AND action = 'ai_summary'",
        (user_id, date.today().isoformat()),
    )
    return max(0, settings.free_daily_ai_summaries - int(row["count"] if row else 0))


def require_ai_summary_quota(database: Database, user_id: str) -> int | None:
    """生成前只做"检查"：额度用完直接拒绝；真正扣减发生在生成成功之后。"""
    remaining = remaining_ai_summaries(database, user_id)
    if remaining is not None and remaining <= 0:
        raise HTTPException(429, f"今日 {settings.free_daily_ai_summaries} 次 AI 总结额度已用完，开通 VIP 可不限次数使用")
    return remaining
