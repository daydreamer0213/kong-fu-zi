from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.models.database import init_db
from app.routers import auth, chat
from app.mcp import get_mcp_client
from app.mcp.servers import AnalectsServer, MemoryServer, WebSearchServer
from app.models.memory import init_memory_table
from app.skills import get_skill_registry
from app.skills.builtin import BUILTIN_SKILLS
from app.utils.logging import RequestLoggingMiddleware, setup_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动时初始化所有组件"""
    # 0. 先初始化结构化日志
    setup_logging(dev_mode=True)

    # 1. 数据库
    init_db()
    init_memory_table()

    # 2. MCP Server
    mcp = get_mcp_client()
    mcp.register(AnalectsServer())
    mcp.register(WebSearchServer())
    mcp.register(MemoryServer())
    mcp.initialize()
    logger.info("MCP 框架初始化完成，共 %d 个 Server", len(mcp._servers))

    # 3. Skill 注册
    skill_registry = get_skill_registry()
    for skill in BUILTIN_SKILLS:
        skill_registry.register(skill)
    logger.info("Skill 注册完成，共 %d 个模式", len(skill_registry.list_all()))

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


# 中间件顺序（Starlette LIFO——后加的先执行）：
#   ① RequestLoggingMiddleware（最外层）— 生成 trace_id，记录请求耗时
#   ② CORSMiddleware — CORS 头
#   ③ PreflightMiddleware（最内层）— 短路 OPTIONS
app.add_middleware(PreflightMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestLoggingMiddleware)


@app.get("/health")
async def health():
    """健康检查接口"""
    return {"status": "ok", "message": "子曰：吾道一以贯之"}
