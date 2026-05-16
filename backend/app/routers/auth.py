from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.services.auth import get_current_user, get_db, login, register

router = APIRouter(prefix="/api/auth", tags=["auth"])


class AuthRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=50, description="用户名")
    password: str = Field(..., min_length=6, max_length=128, description="密码")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    username: str


@router.post("/register", response_model=UserResponse, status_code=201)
def auth_register(request: AuthRequest, db: Session = Depends(get_db)):
    """注册新用户"""
    user = register(db, request.username, request.password)
    return UserResponse(id=user.id, username=user.username)


@router.post("/login", response_model=TokenResponse)
def auth_login(request: AuthRequest, db: Session = Depends(get_db)):
    """登录，返回 JWT access_token"""
    token = login(db, request.username, request.password)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
def auth_me(user=Depends(get_current_user)):
    """返回当前登录用户信息（需要 Bearer Token）"""
    return UserResponse(id=user.id, username=user.username)
