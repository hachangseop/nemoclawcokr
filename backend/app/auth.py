"""Google OAuth 로그인 + JWT 세션.
흐름: /api/v1/auth/google/login → Google → /api/v1/auth/google/callback
      → 사용자 생성/조회 → JWT 발급 → FRONTEND_URL/auth/callback?token=... 리다이렉트.
필요 env: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, JWT_SECRET, FRONTEND_URL
선택: GOOGLE_REDIRECT_URI (기본값은 Render 공개 주소 기준)
"""
import os
import time
import urllib.parse

import httpx
import jwt

from sqlalchemy.orm import Session

from . import models, credits as credit_engine

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


def _cfg(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def redirect_uri() -> str:
    return _cfg("GOOGLE_REDIRECT_URI",
                "https://nemoclawcokr.onrender.com/api/v1/auth/google/callback")


def google_login_url() -> str:
    client_id = _cfg("GOOGLE_CLIENT_ID")
    if not client_id:
        raise RuntimeError("GOOGLE_CLIENT_ID not set")
    q = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "prompt": "select_account",
    })
    return f"{GOOGLE_AUTH_URL}?{q}"


def exchange_code(code: str) -> dict:
    data = {
        "client_id": _cfg("GOOGLE_CLIENT_ID"),
        "client_secret": _cfg("GOOGLE_CLIENT_SECRET"),
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri(),
    }
    r = httpx.post(GOOGLE_TOKEN_URL, data=data, timeout=20)
    r.raise_for_status()
    return r.json()


def fetch_userinfo(access_token: str) -> dict:
    r = httpx.get(GOOGLE_USERINFO_URL,
                  headers={"Authorization": f"Bearer {access_token}"},
                  timeout=20)
    r.raise_for_status()
    return r.json()


def get_or_create_user(db: Session, email: str, name: str | None,
                       google_sub: str) -> tuple[models.User, bool]:
    """(user, created) 반환. 첫 생성 시 100 크레딧 지급."""
    user = db.query(models.User).filter(
        models.User.google_sub == google_sub).first()
    if not user:
        user = db.query(models.User).filter(
            models.User.email == email).first()
        if user:
            user.google_sub = google_sub  # 기존 dev 계정과 연결
        else:
            user = models.User(email=email, name=name or email.split("@")[0],
                               google_sub=google_sub)
            db.add(user)
            db.commit()
            db.refresh(user)
            credit_engine.earn(db, user.id, 100, "signup_bonus")
            return user, True
        db.commit()
        db.refresh(user)
    return user, False


def issue_token(user: models.User) -> str:
    secret = _cfg("JWT_SECRET")
    if not secret:
        raise RuntimeError("JWT_SECRET not set")
    now = int(time.time())
    return jwt.encode({"sub": str(user.id), "email": user.email,
                       "iat": now, "exp": now + 60 * 60 * 24 * 30},
                      secret, algorithm="HS256")


def verify_token(token: str) -> dict:
    secret = _cfg("JWT_SECRET")
    if not secret:
        raise RuntimeError("JWT_SECRET not set")
    return jwt.decode(token, secret, algorithms=["HS256"])


def frontend_url() -> str:
    return _cfg("FRONTEND_URL", "").rstrip("/")
