from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.models.database import init_db
from app.routers import auth, chat


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动时初始化数据库表"""
    init_db()
    yield


app = FastAPI(
    title="孔夫子AI聊天助手",
    version="0.1.0",
    description="以孔子风格对话，结合论语知识库的智能助手",
    lifespan=lifespan,
)

app.include_router(chat.router)
app.include_router(auth.router)

# Starlette 处理中间件是 LIFO：先加的为最内层，后加的最外层最先处理请求。
# 所以：PreflightMiddleware 先加（内层），CORSMiddleware 后加（外层）。
# 请求流：CORSMiddleware → PreflightMiddleware → 路由。
# OPTIONS 时 CORSMiddleware 先加 CORS 头，再传给 PreflightMiddleware 返回 200。
from starlette.types import ASGIApp, Scope, Receive, Send


class PreflightMiddleware:
    """短路 OPTIONS 预检请求，避免落到 POST-only 路由上导致 400。"""
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "http" and scope["method"] == "OPTIONS":
            headers = [(b"content-length", b"0")]
            await send({"type": "http.response.start", "status": 200, "headers": headers})
            await send({"type": "http.response.body", "body": b""})
            return
        await self.app(scope, receive, send)


# 内层：先加 PreflightMiddleware
app.add_middleware(PreflightMiddleware)

# 外层：后加 CORSMiddleware → 第一个处理请求 → 给 OPTIONS 加 CORS 头
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    """健康检查接口"""
    return {"status": "ok", "message": "子曰：吾道一以贯之"}
