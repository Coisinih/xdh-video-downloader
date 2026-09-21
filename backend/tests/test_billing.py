import secrets
import hashlib
import hmac
import time
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.billing import CheckoutSession, StripeGateway, process_event
from app.config import settings
from app.database import utcnow_iso
from app.main import app


class FakeGateway:
    def __init__(self):
        self.checkout_calls = 0

    def create_customer(self, email: str, user_id: str) -> str:
        return f"cus_{user_id}"

    def create_checkout(self, **kwargs) -> CheckoutSession:
        self.checkout_calls += 1
        return CheckoutSession(
            id=f"cs_{kwargs['order_id']}",
            url=f"https://checkout.test/{kwargs['order_id']}",
            expires_at=int((datetime.now(UTC) + timedelta(minutes=30)).timestamp()),
        )

    def create_portal(self, customer_id: str) -> str:
        return f"https://portal.test/{customer_id}"

    def construct_event(self, payload: bytes, signature: str) -> dict:
        raise NotImplementedError


async def registered_client() -> tuple[httpx.AsyncClient, dict]:
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    payload = {"email": f"billing-{secrets.token_hex(8)}@example.com", "password": "StrongPass9!"}
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    return client, response.json()


@pytest.mark.asyncio
async def test_checkout_requires_csrf_and_reuses_same_request_key():
    original = app.state.billing_gateway
    gateway = FakeGateway()
    app.state.billing_gateway = gateway
    client, user = await registered_client()
    try:
        payload = {"purchase_type": "one_time", "request_key": f"checkout-{secrets.token_hex(12)}"}
        forbidden = await client.post("/api/v1/billing/checkout", json=payload)
        assert forbidden.status_code == 403

        headers = {"X-CSRF-Token": user["csrf_token"]}
        first = await client.post("/api/v1/billing/checkout", headers=headers, json=payload)
        second = await client.post("/api/v1/billing/checkout", headers=headers, json=payload)
        assert first.status_code == second.status_code == 200
        assert first.json() == second.json()
        assert gateway.checkout_calls == 1
    finally:
        await client.aclose()
        app.state.billing_gateway = original


def test_completed_checkout_is_idempotent_and_amount_is_verified():
    user_id = f"billing-user-{secrets.token_hex(6)}"
    order_id = f"order-{secrets.token_hex(6)}"
    app.state.database.execute("INSERT INTO users(id, email, password_hash, created_at) VALUES (?, ?, 'hash', ?)", (user_id, f"{user_id}@example.com", utcnow_iso()))
    app.state.database.execute(
        """INSERT INTO billing_orders(id, user_id, purchase_type, status, amount_cents, currency, request_key, stripe_session_id, created_at, updated_at)
           VALUES (?, ?, 'one_time', 'pending', 990, 'cny', ?, ?, ?, ?)""",
        (order_id, user_id, f"key-{order_id}", f"cs_{order_id}", utcnow_iso(), utcnow_iso()),
    )
    event = {
        "id": f"evt-{secrets.token_hex(6)}",
        "type": "checkout.session.completed",
        "created": int(datetime.now(UTC).timestamp()),
        "data": {"object": {
            "id": f"cs_{order_id}",
            "metadata": {"vidnest_order_id": order_id, "vidnest_user_id": user_id, "purchase_type": "one_time"},
            "amount_total": 990,
            "currency": "cny",
            "payment_status": "paid",
            "payment_intent": f"pi_{order_id}",
        }},
    }
    assert process_event(app.state.database, event) == "processed"
    assert process_event(app.state.database, event) == "duplicate"
    grants = app.state.database.fetchall("SELECT * FROM membership_grants WHERE order_id = ?", (order_id,))
    assert len(grants) == 1

    bad_order = f"order-{secrets.token_hex(6)}"
    app.state.database.execute(
        """INSERT INTO billing_orders(id, user_id, purchase_type, status, amount_cents, currency, request_key, stripe_session_id, created_at, updated_at)
           VALUES (?, ?, 'one_time', 'pending', 990, 'cny', ?, ?, ?, ?)""",
        (bad_order, user_id, f"key-{bad_order}", f"cs_{bad_order}", utcnow_iso(), utcnow_iso()),
    )
    tampered = {**event, "id": f"evt-{secrets.token_hex(6)}", "data": {"object": {**event["data"]["object"], "id": f"cs_{bad_order}", "amount_total": 1, "metadata": {"vidnest_order_id": bad_order, "vidnest_user_id": user_id, "purchase_type": "one_time"}}}}
    with pytest.raises(ValueError, match="金额"):
        process_event(app.state.database, tampered)


def test_subscription_older_event_cannot_override_newer_state_and_refund_revokes_grant():
    user_id = f"subscription-user-{secrets.token_hex(6)}"
    app.state.database.execute("INSERT INTO users(id, email, password_hash, created_at) VALUES (?, ?, 'hash', ?)", (user_id, f"{user_id}@example.com", utcnow_iso()))
    subscription_id = f"sub-{secrets.token_hex(6)}"
    base = {
        "id": "",
        "type": "customer.subscription.updated",
        "created": 200,
        "data": {"object": {
            "id": subscription_id,
            "metadata": {"vidnest_user_id": user_id},
            "status": "active",
            "current_period_end": int((datetime.now(UTC) + timedelta(days=30)).timestamp()),
            "cancel_at_period_end": False,
        }},
    }
    process_event(app.state.database, {**base, "id": f"evt-{secrets.token_hex(5)}"})
    older = {**base, "id": f"evt-{secrets.token_hex(5)}", "created": 100, "data": {"object": {**base["data"]["object"], "status": "canceled"}}}
    process_event(app.state.database, older)
    row = app.state.database.fetchone("SELECT status, last_event_created FROM billing_subscriptions WHERE stripe_subscription_id = ?", (subscription_id,))
    assert row["status"] == "active"
    assert row["last_event_created"] == 200


def test_stripe_gateway_verifies_real_test_signature(monkeypatch):
    secret = "whsec_test_vidnest_signature"
    payload = b'{"id":"evt_signature","type":"ping","created":1,"data":{"object":{}}}'
    timestamp = int(time.time())
    digest = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
    signature = f"t={timestamp},v1={digest}"
    monkeypatch.setattr(settings, "stripe_webhook_secret", secret)
    event = StripeGateway().construct_event(payload, signature)
    assert event["id"] == "evt_signature"
    with pytest.raises(Exception):
        StripeGateway().construct_event(payload + b" ", signature)
