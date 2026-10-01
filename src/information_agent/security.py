import hashlib
import hmac
import secrets
import time

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from information_agent.config import settings
from information_agent.db import get_db
from information_agent.models import User


bearer = HTTPBearer(auto_error=False)
TOKEN_AGE_SECONDS = 7 * 24 * 60 * 60


def password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"{salt.hex()}:{digest.hex()}"


def password_matches(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split(":", 1)
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1)
        return hmac.compare_digest(digest, bytes.fromhex(digest_hex))
    except (ValueError, TypeError):
        return False


def issue_token(user_id: str) -> str:
    payload = f"{user_id}.{int(time.time()) + TOKEN_AGE_SECONDS}"
    signature = hmac.new(settings.app_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    try:
        user_id, expiry, signature = credentials.credentials.rsplit(".", 2)
        payload = f"{user_id}.{expiry}"
        expected = hmac.new(settings.app_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if int(expiry) < time.time() or not hmac.compare_digest(signature, expected):
            raise ValueError("expired or invalid token")
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="登录已失效") from None
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status_code=401, detail="账号不存在")
    return user
