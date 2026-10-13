"""Stripe 웹훅 스켈레톤. 서명 검증은 표준 방식으로 수행.
STRIPE_WEBHOOK_SECRET 설정 시 검증, 미설정 시 개발 모드로 통과(경고 로그).
"""
import hashlib
import hmac
import json
import logging
import os
import time

log = logging.getLogger(__name__)


def verify_stripe_signature(payload: bytes, sig_header: str, secret: str) -> bool:
    # Stripe-Signature: t=...,v1=...
    try:
        parts = dict(p.split("=", 1) for p in sig_header.split(","))
        signed = f"{parts['t']}.{payload.decode()}".encode()
        expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
        if abs(time.time() - int(parts["t"])) > 300:
            return False
        return hmac.compare_digest(expected, parts["v1"])
    except Exception:
        return False


def handle_event(db, event: dict) -> str:
    """이벤트 타입별 처리. 크레딧 적립/구독 상태 반영."""
    from . import credits as credit_engine, models
    etype = event.get("type", "")
    obj = event.get("data", {}).get("object", {})

    if etype == "checkout.session.completed":
        # 크레딧 패키지 일회성 결제 완료 → 적립
        email = obj.get("customer_email") or obj.get("metadata", {}).get("email")
        pack_credits = int(obj.get("metadata", {}).get("credits", 0) or 0)
        if email and pack_credits > 0:
            user = db.query(models.User).filter(models.User.email == email).first()
            if user:
                credit_engine.earn(db, user.id, pack_credits, "purchase",
                                   ref_id=obj.get("id"))
                return f"credited {pack_credits} to {email}"
        return "checkout completed (no credit mapping)"

    if etype in ("customer.subscription.created", "customer.subscription.updated"):
        email = obj.get("metadata", {}).get("email")
        if email:
            user = db.query(models.User).filter(models.User.email == email).first()
            if user:
                sub = db.query(models.Subscription).filter(
                    models.Subscription.stripe_subscription_id == obj.get("id")).first()
                if not sub:
                    sub = models.Subscription(user_id=user.id,
                                              stripe_subscription_id=obj.get("id"),
                                              plan=obj.get("metadata", {}).get("plan", "pro"))
                    db.add(sub)
                sub.status = obj.get("status", "active")
                db.commit()
                return f"subscription {sub.status}"
        return "subscription event (no user mapping)"

    return f"ignored event {etype}"


def webhook_secret() -> str | None:
    return os.environ.get("STRIPE_WEBHOOK_SECRET")
