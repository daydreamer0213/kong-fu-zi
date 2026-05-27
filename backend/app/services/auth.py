from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models.database import SessionLocal, User

bearer_scheme = HTTPBearer()


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def get_db() -> Session:
    """FastAPI 依赖：每个请求一个数据库会话，请求结束自动关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================
# 注册 & 登录
# ============================================================


def register(db: Session, username: str, password: str) -> User:
    """注册新用户。用户名已存在则抛出 400。"""
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=400, detail="此用户名已被注册")

    user = User(
        username=username,
        password_hash=_hash_password(password),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="此用户名已被注册")
    db.refresh(user)
    return user


def login(db: Session, username: str, password: str) -> str:
    """校验用户名密码，通过则返回 JWT access_token。

    Raises 401 if credentials are invalid.
    """
    user = db.query(User).filter(User.username == username).first()
    if not user or not _verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    return _create_token(user.id)


# ============================================================
# JWT 工具
# ============================================================


def _create_token(user_id: int) -> str:
    """用用户 ID 签发 JWT"""
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> int:
    """解析 JWT 拿到 user_id。token 无效或过期则抛出 401。"""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="无效的认证凭证")

    return int(payload["sub"])


# ============================================================
# 鉴权依赖（保护路由用）
# ============================================================


def get_current_user(
    db: Session = Depends(get_db),
    cred: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> User:
    """FastAPI 依赖：从请求头 Bearer Token 解析当前用户。

    用法——在路由函数参数里加：
        user: User = Depends(get_current_user)
    """
    user_id = decode_token(cred.credentials)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")

    # 注入到结构化日志上下文——后续所有日志自动带上 user_id
    from app.utils.logging import set_user_id
    set_user_id(str(user.id))

    return user
