"""用户认证：注册、登录、JWT 令牌"""
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from backend.config import settings
from backend.storage.database import get_session
from backend.storage.models import User

security = HTTPBearer(auto_error=False)

TOKEN_EXPIRE_DAYS = 7


def hash_password(password: str) -> str:
  return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
  return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_access_token(user_id: str, username: str) -> str:
  expire = datetime.now(timezone.utc) + timedelta(days=TOKEN_EXPIRE_DAYS)
  payload = {"sub": user_id, "username": username, "exp": expire}
  return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> dict:
  try:
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
  except jwt.PyJWTError as e:
    raise HTTPException(401, "登录已过期，请重新登录") from e


def get_user_by_id(user_id: str) -> User | None:
  with get_session() as session:
    return session.get(User, user_id)


def get_user_by_username(username: str) -> User | None:
  with get_session() as session:
    return session.scalar(select(User).where(User.username == username))


def create_user(username: str, password: str) -> User:
  username = username.strip().lower()
  if len(username) < 3:
    raise ValueError("用户名至少 3 个字符")
  if len(password) < 6:
    raise ValueError("密码至少 6 个字符")

  with get_session() as session:
    existing = session.scalar(select(User).where(User.username == username))
    if existing:
      raise ValueError("用户名已存在")

    user = User(
      id=str(uuid.uuid4()),
      username=username,
      password_hash=hash_password(password),
      created_at=datetime.now(),
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def authenticate_user(username: str, password: str) -> User | None:
  user = get_user_by_username(username.strip().lower())
  if not user or not verify_password(password, user.password_hash):
    return None
  return user


async def get_current_user(
  credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> User:
  if not credentials:
    raise HTTPException(401, "未登录，请先登录")
  payload = decode_token(credentials.credentials)
  user_id = payload.get("sub")
  if not user_id:
    raise HTTPException(401, "无效的登录凭证")
  user = get_user_by_id(user_id)
  if not user:
    raise HTTPException(401, "用户不存在")
  return user


def serialize_user(user: User) -> dict:
  return {
    "id": user.id,
    "username": user.username,
    "created_at": user.created_at.isoformat(),
  }
