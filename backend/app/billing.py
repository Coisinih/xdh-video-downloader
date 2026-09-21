import json
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from .auth import CurrentUser, require_csrf, require_user
from .config import settings
from .database import Database, utcnow_iso
from .entitlements import membership_for

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])


class CheckoutRequest(BaseModel):
    purchase_type: Literal["one_time", "subscription"] = "one_time"
    request_key: str = Field(min_length=16, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")


class CheckoutResponse(BaseModel):
    order_id: str
    checkout_url: str


class PortalResponse(BaseModel):
    url: str


class BillingStatusResponse(BaseModel):
    configured: bool
    one_time_amount_cents: int
    subscription_amount_cents: int
    currency: str
    membership: dict
    orders: list[dict]


@dataclass(frozen=True)
class CheckoutSession:
    id: str
    url: str
    expires_at: int


class BillingGateway(Protocol):
    def create_customer(self, email: str, user_id: str) -> str: ...
    def create_checkout(self, *, customer_id: str, user_id: str, email: str, order_id: str, purchase_type: str) -> CheckoutSession: ...
    def create_portal(self, customer_id: str) -> str: ...
    def construct_event(self, payload: bytes, signature: str) -> dict[str, Any]: ...


class StripeGateway:
    def _require_key(self) -> None:
        if not settings.stripe_secret_key:
            raise HTTPException(503, "Stripe 尚未配置，请先填写测试密钥")

    def create_customer(self, email: str, user_id: str) -> str:
        self._require_key()
        customer = stripe.Customer.create(
            email=email,
            metadata={"vidnest_user_id": user_id},
            api_key=settings.stripe_secret_key,
            idempotency_key=f"vidnest-customer-{user_id}",
        )
        return str(customer.id)

    def create_checkout(self, *, customer_id: str, user_id: str, email: str, order_id: str, purchase_type: str) -> CheckoutSession:
        self._require_key()
        price_id = settings.stripe_one_time_price_id if purchase_type == "one_time" else settings.stripe_subscription_price_id
        if not price_id:
            raise HTTPException(503, f"Stripe {'一次性' if purchase_type == 'one_time' else '订阅'}价格尚未配置")
        if not price_id.startswith("price_"):
            raise HTTPException(503, "Stripe 价格配置无效：请填写 price_ 开头的 Price ID，而不是 prod_ 产品 ID")
        metadata = {"vidnest_user_id": user_id, "vidnest_order_id": order_id, "purchase_type": purchase_type}
        params: dict[str, Any] = {
            "mode": "payment" if purchase_type == "one_time" else "subscription",
            "customer": customer_id,
            "client_reference_id": user_id,
            "line_items": [{"price": price_id, "quantity": 1}],
            "metadata": metadata,
            "success_url": f"{settings.frontend_url.rstrip('/')}?payment=success&session_id={{CHECKOUT_SESSION_ID}}#pricing",
            "cancel_url": f"{settings.frontend_url.rstrip('/')}?payment=cancelled#pricing",
            "expires_at": int((datetime.now(UTC) + timedelta(minutes=30)).timestamp()),
        }
        if purchase_type == "one_time":
            params["payment_intent_data"] = {"metadata": metadata}
        else:
            params["subscription_data"] = {"metadata": metadata}
        session = stripe.checkout.Session.create(
            **params,
            api_key=settings.stripe_secret_key,
            idempotency_key=f"vidnest-checkout-{order_id}",
        )
        if not session.url:
            raise HTTPException(502, "Stripe 未返回支付地址")
        return CheckoutSession(str(session.id), str(session.url), int(session.expires_at))

    def create_portal(self, customer_id: str) -> str:
        self._require_key()
        try:
            session = stripe.billing_portal.Session.create(
                customer=customer_id,
                return_url=f"{settings.frontend_url.rstrip('/')}#pricing",
                api_key=settings.stripe_secret_key,
            )
        except stripe.error.InvalidRequestError as exc:
            raise HTTPException(503, "请先在 Stripe Dashboard 启用 Customer Portal") from exc
        return str(session.url)

    def construct_event(self, payload: bytes, signature: str) -> dict[str, Any]:
        if not settings.stripe_webhook_secret:
            raise HTTPException(503, "Stripe Webhook Secret 尚未配置")
        try:
            event = stripe.Webhook.construct_event(payload, signature, settings.stripe_webhook_secret)
        except (ValueError, stripe.error.SignatureVerificationError) as exc:
            raise HTTPException(400, "Stripe Webhook 签名无效") from exc
        if isinstance(event, dict):
            return event
        return event.to_dict()


def get_gateway(request: Request) -> BillingGateway:
    return request.app.state.billing_gateway


def _customer(database: Database, gateway: BillingGateway, user: CurrentUser) -> str:
    row = database.fetchone("SELECT stripe_customer_id FROM billing_customers WHERE user_id = ?", (user.id,))
    if row:
        return str(row["stripe_customer_id"])
    customer_id = gateway.create_customer(user.email, user.id)
    try:
        database.execute(
            "INSERT INTO billing_customers(user_id, stripe_customer_id, created_at) VALUES (?, ?, ?)",
            (user.id, customer_id, utcnow_iso()),
        )
    except sqlite3.IntegrityError:
        row = database.fetchone("SELECT stripe_customer_id FROM billing_customers WHERE user_id = ?", (user.id,))
        if row:
            return str(row["stripe_customer_id"])
        raise
    return customer_id


def _order_dict(row) -> dict:
    return {
        "id": str(row["id"]),
        "purchase_type": str(row["purchase_type"]),
        "status": str(row["status"]),
        "amount_cents": int(row["amount_cents"]),
        "currency": str(row["currency"]),
        "created_at": str(row["created_at"]),
    }


@router.get("/status", response_model=BillingStatusResponse)
async def billing_status(request: Request, user: CurrentUser = Depends(require_user)):
    database = request.app.state.database
    orders = database.fetchall(
        "SELECT id, purchase_type, status, amount_cents, currency, created_at FROM billing_orders WHERE user_id = ? ORDER BY created_at DESC LIMIT 20",
        (user.id,),
    )
    return BillingStatusResponse(
        configured=bool(
            settings.stripe_secret_key
            and settings.stripe_one_time_price_id.startswith("price_")
            and settings.stripe_subscription_price_id.startswith("price_")
        ),
        one_time_amount_cents=settings.stripe_amount_cents,
        subscription_amount_cents=settings.stripe_amount_cents,
        currency=settings.stripe_currency,
        membership=membership_for(database, user.id).__dict__,
        orders=[_order_dict(row) for row in orders],
    )


@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout(
    payload: CheckoutRequest,
    request: Request,
    user: CurrentUser = Depends(require_csrf),
    gateway: BillingGateway = Depends(get_gateway),
):
    database = request.app.state.database
    if membership_for(database, user.id).is_vip:
        raise HTTPException(409, "当前会员仍在有效期内，无需重复购买")
    existing = database.fetchone(
        "SELECT id, stripe_session_url, expires_at, status FROM billing_orders WHERE user_id = ? AND request_key = ?",
        (user.id, payload.request_key),
    )
    if existing:
        if existing["status"] == "pending" and existing["stripe_session_url"] and existing["expires_at"] and datetime.fromisoformat(existing["expires_at"]) > datetime.now(UTC):
            return CheckoutResponse(order_id=str(existing["id"]), checkout_url=str(existing["stripe_session_url"]))
        raise HTTPException(409, "该支付请求已处理，请刷新会员状态")

    pending = database.fetchone(
        "SELECT id, stripe_session_url, expires_at FROM billing_orders WHERE user_id = ? AND status IN ('creating', 'pending') ORDER BY created_at DESC LIMIT 1",
        (user.id,),
    )
    if pending and pending["stripe_session_url"] and pending["expires_at"] and datetime.fromisoformat(pending["expires_at"]) > datetime.now(UTC):
        return CheckoutResponse(order_id=str(pending["id"]), checkout_url=str(pending["stripe_session_url"]))
    if pending:
        database.execute("UPDATE billing_orders SET status = 'expired', updated_at = ? WHERE id = ?", (utcnow_iso(), pending["id"]))

    order_id = secrets.token_urlsafe(18)
    now = utcnow_iso()
    try:
        database.execute(
            """INSERT INTO billing_orders(id, user_id, purchase_type, status, amount_cents, currency, request_key, created_at, updated_at)
               VALUES (?, ?, ?, 'creating', ?, ?, ?, ?, ?)""",
            (order_id, user.id, payload.purchase_type, settings.stripe_amount_cents, settings.stripe_currency.lower(), payload.request_key, now, now),
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "已有支付请求正在处理中") from exc

    try:
        customer_id = _customer(database, gateway, user)
        session = gateway.create_checkout(customer_id=customer_id, user_id=user.id, email=user.email, order_id=order_id, purchase_type=payload.purchase_type)
        expires_at = datetime.fromtimestamp(session.expires_at, UTC).isoformat()
        database.execute(
            """UPDATE billing_orders SET status = 'pending', stripe_session_id = ?, stripe_session_url = ?, expires_at = ?, updated_at = ?
               WHERE id = ?""",
            (session.id, session.url, expires_at, utcnow_iso(), order_id),
        )
        return CheckoutResponse(order_id=order_id, checkout_url=session.url)
    except HTTPException:
        database.execute("UPDATE billing_orders SET status = 'failed', updated_at = ? WHERE id = ?", (utcnow_iso(), order_id))
        raise
    except stripe.error.StripeError as exc:
        database.execute("UPDATE billing_orders SET status = 'failed', updated_at = ? WHERE id = ?", (utcnow_iso(), order_id))
        raise HTTPException(502, "Stripe 暂时无法创建支付页面，请稍后重试") from exc
    except Exception:
        database.execute("UPDATE billing_orders SET status = 'failed', updated_at = ? WHERE id = ?", (utcnow_iso(), order_id))
        raise


@router.post("/portal", response_model=PortalResponse)
async def create_portal(
    request: Request,
    user: CurrentUser = Depends(require_csrf),
    gateway: BillingGateway = Depends(get_gateway),
):
    row = request.app.state.database.fetchone("SELECT stripe_customer_id FROM billing_customers WHERE user_id = ?", (user.id,))
    if not row:
        raise HTTPException(404, "尚未创建 Stripe 客户资料")
    return PortalResponse(url=gateway.create_portal(str(row["stripe_customer_id"])))


def _object_value(obj: dict, key: str, default=None):
    value = obj.get(key, default)
    return value if value is not None else default


def _subscription_period_end(subscription: dict) -> str | None:
    timestamp = subscription.get("current_period_end")
    if not timestamp:
        items = ((subscription.get("items") or {}).get("data") or [])
        timestamps = [item.get("current_period_end") for item in items if item.get("current_period_end")]
        timestamp = max(timestamps) if timestamps else subscription.get("ended_at")
    return datetime.fromtimestamp(int(timestamp), UTC).isoformat() if timestamp else None


def _resolve_user_id(database: Database, obj: dict) -> str | None:
    metadata = obj.get("metadata") or {}
    if metadata.get("vidnest_user_id"):
        return str(metadata["vidnest_user_id"])
    customer_id = obj.get("customer")
    row = database.fetchone("SELECT user_id FROM billing_customers WHERE stripe_customer_id = ?", (str(customer_id),)) if customer_id else None
    return str(row["user_id"]) if row else None


def _complete_checkout(connection, session: dict, event_created: int) -> None:
    metadata = session.get("metadata") or {}
    order_id = metadata.get("vidnest_order_id")
    if not order_id:
        return
    order = connection.execute("SELECT * FROM billing_orders WHERE id = ?", (str(order_id),)).fetchone()
    if not order or order["stripe_session_id"] != session.get("id"):
        raise ValueError("Webhook 中的订单与 Checkout Session 不匹配")
    if int(session.get("amount_total") or -1) != int(order["amount_cents"]) or str(session.get("currency") or "").lower() != str(order["currency"]).lower():
        raise ValueError("Stripe 实收金额或币种与本地订单不匹配")
    paid = session.get("payment_status") in {"paid", "no_payment_required"}
    purchase_type = str(order["purchase_type"])
    status = "paid" if paid else "pending"
    connection.execute(
        """UPDATE billing_orders SET status = ?, stripe_payment_intent_id = COALESCE(?, stripe_payment_intent_id),
           stripe_subscription_id = COALESCE(?, stripe_subscription_id), updated_at = ? WHERE id = ?""",
        (status, session.get("payment_intent"), session.get("subscription"), utcnow_iso(), order_id),
    )
    if paid and purchase_type == "one_time":
        starts_at = datetime.now(UTC)
        ends_at = starts_at + timedelta(days=30)
        connection.execute(
            """INSERT INTO membership_grants(order_id, user_id, starts_at, ends_at)
               VALUES (?, ?, ?, ?) ON CONFLICT(order_id) DO NOTHING""",
            (order_id, order["user_id"], starts_at.isoformat(), ends_at.isoformat()),
        )


def _sync_subscription(connection, database: Database, subscription: dict, event_created: int) -> None:
    subscription_id = str(subscription.get("id") or "")
    user_id = _resolve_user_id(database, subscription)
    if not subscription_id or not user_id:
        raise ValueError("无法将 Stripe 订阅关联到本地用户")
    existing = connection.execute(
        "SELECT last_event_created FROM billing_subscriptions WHERE stripe_subscription_id = ?",
        (subscription_id,),
    ).fetchone()
    if existing and int(existing["last_event_created"]) > event_created:
        return
    connection.execute(
        """INSERT INTO billing_subscriptions(stripe_subscription_id, user_id, status, current_period_end, cancel_at_period_end, last_event_created, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(stripe_subscription_id) DO UPDATE SET
             user_id=excluded.user_id, status=excluded.status, current_period_end=excluded.current_period_end,
             cancel_at_period_end=excluded.cancel_at_period_end, last_event_created=excluded.last_event_created, updated_at=excluded.updated_at""",
        (
            subscription_id,
            user_id,
            str(subscription.get("status") or "unknown"),
            _subscription_period_end(subscription),
            1 if subscription.get("cancel_at_period_end") else 0,
            event_created,
            utcnow_iso(),
        ),
    )
    connection.execute(
        "UPDATE billing_orders SET status = 'paid', stripe_subscription_id = ?, updated_at = ? WHERE user_id = ? AND purchase_type = 'subscription' AND status IN ('creating', 'pending')",
        (subscription_id, utcnow_iso(), user_id),
    )


def process_event(database: Database, event: dict) -> str:
    event_id = str(event.get("id") or "")
    event_type = str(event.get("type") or "")
    event_created = int(event.get("created") or 0)
    obj = ((event.get("data") or {}).get("object") or {})
    if not event_id or not event_type or not isinstance(obj, dict):
        raise ValueError("Stripe 事件格式无效")

    with database.transaction(immediate=True) as connection:
        existing = connection.execute("SELECT status FROM billing_webhook_events WHERE stripe_event_id = ?", (event_id,)).fetchone()
        if existing and existing["status"] == "processed":
            return "duplicate"
        if existing:
            connection.execute("UPDATE billing_webhook_events SET status = 'processing', error = NULL WHERE stripe_event_id = ?", (event_id,))
        else:
            connection.execute(
                "INSERT INTO billing_webhook_events(stripe_event_id, event_type, status, received_at) VALUES (?, ?, 'processing', ?)",
                (event_id, event_type, utcnow_iso()),
            )

        if event_type in {"checkout.session.completed", "checkout.session.async_payment_succeeded"}:
            _complete_checkout(connection, obj, event_created)
        elif event_type in {"checkout.session.expired", "checkout.session.async_payment_failed"}:
            connection.execute("UPDATE billing_orders SET status = ?, updated_at = ? WHERE stripe_session_id = ? AND status != 'paid'", ("expired" if event_type.endswith("expired") else "failed", utcnow_iso(), obj.get("id")))
        elif event_type in {"customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"}:
            _sync_subscription(connection, database, obj, event_created)
        elif event_type == "invoice.payment_failed" and obj.get("subscription"):
            connection.execute("UPDATE billing_orders SET updated_at = ? WHERE stripe_subscription_id = ?", (utcnow_iso(), str(obj["subscription"])))
        elif event_type == "charge.refunded" and obj.get("refunded") and obj.get("payment_intent"):
            order = connection.execute("SELECT id FROM billing_orders WHERE stripe_payment_intent_id = ?", (str(obj["payment_intent"]),)).fetchone()
            if order:
                connection.execute("UPDATE billing_orders SET status = 'refunded', updated_at = ? WHERE id = ?", (utcnow_iso(), order["id"]))
                connection.execute("UPDATE membership_grants SET revoked_at = ? WHERE order_id = ?", (utcnow_iso(), order["id"]))

        connection.execute(
            "UPDATE billing_webhook_events SET status = 'processed', processed_at = ? WHERE stripe_event_id = ?",
            (utcnow_iso(), event_id),
        )
    return "processed"


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
    gateway: BillingGateway = Depends(get_gateway),
):
    if not stripe_signature:
        raise HTTPException(400, "缺少 Stripe-Signature")
    payload = await request.body()
    if len(payload) > 1024 * 1024:
        raise HTTPException(413, "Webhook 请求体过大")
    event = gateway.construct_event(payload, stripe_signature)
    try:
        outcome = process_event(request.app.state.database, event)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"received": True, "outcome": outcome}
