"""
结构化日志 — structlog 配置 + trace_id 上下文

面试可讲的设计点：
1. 每条日志都是 JSON，可被 ELK/Loki/Grafana 索引和搜索
2. trace_id 贯穿整个请求链路——从前端请求到 LLM API 调用，全部串联
3. 关键节点打点：请求耗时、Agent 迭代次数、工具调用、token 用量
4. 开发环境人类可读（彩色），生产环境 JSON 输出

structlog 的核心概念：
  - bound_logger = logger.bind(trace_id="xxx", user_id=123)
    → 之后所有 log.xxx() 都自动带上这些字段
  - "bind 一次，后面所有日志自动带上"是 structlog 和标准 logging 最大的区别

和 print / logging.info 的对比：
  print("token 用了 2850")           → 人看得懂，机器搜不到
  logger.info("token_used", count=2850) → 人和机器都能用，ELK 可以出 dashboard
"""

import contextvars
import logging
import sys
import time
import uuid

import structlog

# ---------------------------------------------------------------------------
# 全局 contextvars — 线程/协程安全的上下文变量
# ---------------------------------------------------------------------------
# contextvars 是 Python 3.7+ 标准库，每个线程/协程有独立的值，
# 不需要显式传递参数。比 threading.local 更强：asyncio 协程切换时自动恢复。
# ---------------------------------------------------------------------------

trace_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")
user_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("user_id", default="")


def set_trace_id(tid: str | None = None) -> str:
    """设置当前请求的 trace_id。不传则自动生成 UUID。"""
    tid = tid or uuid.uuid4().hex[:12]
    trace_id_ctx.set(tid)
    return tid


def get_trace_id() -> str:
    return trace_id_ctx.get()


def set_user_id(uid: str):
    user_id_ctx.set(uid)


# ---------------------------------------------------------------------------
# structlog 配置
# ---------------------------------------------------------------------------
# 处理器链（和 Python logging 的 Handler 类似，但 structlog 叫 Processor）：
#   1. add_log_level    → 加 "level": "info"
#   2. add_logger_name  → 加 "logger": "app.services.agent"
#   3. set_exc_info     → 格式化异常堆栈
#   4. TimeStamper      → 加 "timestamp": "2026-05-27T14:30:00.123Z"
#   5. trace_id injector → 加 "trace_id": "abc123"
#   6. JSONRenderer     → 输出 JSON 字符串（或 ConsoleRenderer 用于开发）
# ---------------------------------------------------------------------------


def _inject_context(_, __, event_dict: dict) -> dict:
    """把 contextvars 中的上下文注入每条日志"""
    tid = trace_id_ctx.get()
    if tid:
        event_dict["trace_id"] = tid
    uid = user_id_ctx.get()
    if uid:
        event_dict["user_id"] = uid
    return event_dict


def setup_logging(dev_mode: bool = True):
    """初始化结构化日志（在 main.py lifespan 中调用）。

    Args:
        dev_mode: True=彩色控制台输出, False=JSON 输出（生产环境）
    """
    # 标准库 logging → structlog 桥接
    # 已有的 logger = logging.getLogger(__name__) 也能输出结构化的第三方库日志
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,       # "level": "info"
            structlog.stdlib.add_logger_name,     # "logger": "..."
            structlog.stdlib.PositionalArgumentsFormatter(),  # %s 格式支持
            structlog.processors.TimeStamper(fmt="iso"),      # "timestamp"
            structlog.dev.set_exc_info,           # 异常堆栈
            _inject_context,                      # trace_id + user_id
            structlog.dev.ConsoleRenderer()
            if dev_mode
            else structlog.processors.JSONRenderer(),  # 开发vs生产
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # 同时配置标准库 root logger（让第三方库的日志也走 structlog 格式化）
    # 不上 handler：structlog 通过 LoggerFactory 自己管理输出
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """获取结构化 logger（替代 logging.getLogger）"""
    return structlog.get_logger(name or __name__)


# ---------------------------------------------------------------------------
# 请求日志中间件（ASGI middleware — FastAPI 原生支持）
# ---------------------------------------------------------------------------


class RequestLoggingMiddleware:
    """每个 HTTP 请求自动：生成 trace_id → 记录开始 → 记录结束+耗时。

    不需要在每个路由函数里手写日志——中间件一劳永逸。

    日志格式（结构化的"请求日记"）：
      request_start: method=POST, path=/api/chat, trace_id=abc123
      request_end:   status=200, duration_ms=1523, trace_id=abc123
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        # 只处理 HTTP 请求，跳过 WebSocket/lifespan
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        tid = set_trace_id()
        method = scope.get("method", "?")
        path = scope.get("path", "?")

        logger = get_logger("http")
        start = time.perf_counter()

        # 记录请求开始
        logger.info(
            "request_start",
            method=method,
            path=path,
        )

        # 包裹 send，在响应发出时记录状态码和耗时
        status_code = [0]

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_code[0] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.info(
                "request_end",
                method=method,
                path=path,
                status=status_code[0],
                duration_ms=round(duration_ms, 1),
            )


# ---------------------------------------------------------------------------
# 便捷函数 — 在 Agent/LLM 层打点
# ---------------------------------------------------------------------------

_agent_logger = None


def get_agent_logger():
    global _agent_logger
    if _agent_logger is None:
        _agent_logger = get_logger("agent")
    return _agent_logger
