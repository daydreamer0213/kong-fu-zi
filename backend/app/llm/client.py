import logging

from fastapi import HTTPException
from openai import (
    APIError,
    APITimeoutError,
    AuthenticationError,
    RateLimitError,
    AsyncOpenAI,
    OpenAI,
)

from app.config import settings
from app.utils.resilience import CircuitBreaker, retry_with_backoff
from app.utils.logging import get_logger

logger = logging.getLogger(__name__)
_log = get_logger("llm")

MODEL = "deepseek-chat"
TIMEOUT = 30.0  # 单次 API 调用超时秒数

# ---------------------------------------------------------------------------
# OpenAI SDK 客户端
# ---------------------------------------------------------------------------

_client = OpenAI(
    api_key=settings.deepseek_api_key,
    base_url=settings.deepseek_base_url,
    timeout=TIMEOUT,
)

_async_client = AsyncOpenAI(
    api_key=settings.deepseek_api_key,
    base_url=settings.deepseek_base_url,
    timeout=TIMEOUT,
)

# ---------------------------------------------------------------------------
# 熔断器 — 保护下游 DeepSeek API
#
# 连续 5 次 API 调用失败 → 熔断 30 秒 → 后续请求直接返回 503，不等超时
# 放在模块级全局，所有 LLM 调用共享同一个熔断器
# ---------------------------------------------------------------------------

_llm_circuit_breaker = CircuitBreaker(failure_threshold=5, timeout=30.0)


# ---------------------------------------------------------------------------
# 带重试的底层 API 调用（内部函数）
#
# 只负责"调 API + 重试"，不负责错误分类和熔断。
# 错误分类和熔断计数由上层的 chat() / chat_with_tools() / chat_stream() 处理。
#
# 为什么 retry 包在底层、熔断包在顶层？
#   - 重试 = 对付瞬时故障（网络抖动、限流），应该在最接近 API 的地方
#   - 熔断 = 对付持续故障（服务挂了），应该在调用入口处。一次重试3次全失败
#     对熔断器来说算 1 次失败，不算 4 次——因为是同一个语义操作。
# ---------------------------------------------------------------------------


@retry_with_backoff(
    max_retries=3,
    base_delay=1.0,
    retryable_exceptions=(RateLimitError, APITimeoutError, APIError),
)
def _chat_completion_create(messages: list[dict], temperature: float,
                            max_tokens: int, **extra):
    """同步 API 调用 + 指数退避重试。

    重试只针对瞬时故障：RateLimitError（被限流了，等一等就好）、
    APITimeoutError（网络超时）、APIError（5xx 服务端错误）。
    AuthenticationError 不重试——API Key 错了就是错了，重试 3 次也不会变对。
    """
    return _client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        **extra,
    )


@retry_with_backoff(
    max_retries=3,
    base_delay=1.0,
    retryable_exceptions=(RateLimitError, APITimeoutError, APIError),
)
async def _async_chat_completion_create(messages: list[dict], temperature: float,
                                        max_tokens: int):
    """异步流式 API 调用 + 指数退避重试"""
    return await _async_client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
    )


# ---------------------------------------------------------------------------
# 错误映射
# ---------------------------------------------------------------------------


def _log_token_usage(response):
    """记录 LLM API 的 token 消耗（结构化日志）。

    usage 字段：
      - prompt_tokens: 输入 token 数（system + history + user message）
      - completion_tokens: 输出 token 数（模型生成的文本）
      - total_tokens: 输入+输出

    面试时的 dashboard 场景：
      "每小时的 total_tokens 趋势图 → 看出用户活跃度波动
       每次请求的 prompt/completion 比例 → 用长对话用户消耗更高
       每月 token 总量 × 单价 → 成本预估"
    """
    usage = response.usage
    if usage:
        _log.info(
            "llm_call",
            model=MODEL,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
        )


def _handle_api_error(e: Exception) -> HTTPException:
    """把 OpenAI SDK 异常转为 HTTPException，给出中文提示。

    AuthenticationError → 500（配置问题，不是用户问题）
    RateLimitError    → 429（真正应该返回的限流状态码）
    APITimeoutError   → 504（上游超时）
    APIError          → 502（上游挂了）
    其他              → 500（兜底）
    """
    if isinstance(e, AuthenticationError):
        return HTTPException(status_code=500, detail="LLM 认证失败，请检查 API Key")
    if isinstance(e, RateLimitError):
        return HTTPException(status_code=429, detail="夫子正在沉思，请稍后再问")
    if isinstance(e, APITimeoutError):
        return HTTPException(status_code=504, detail="夫子正在沉思，请稍后再问")
    if isinstance(e, APIError):
        return HTTPException(status_code=502, detail="夫子暂时无法作答，请稍后再问")
    logger.exception("LLM 调用异常")
    return HTTPException(status_code=500, detail="对话服务异常，请稍后重试")


def chat(
    messages: list[dict],
    temperature: float = 1.1,
    max_tokens: int = 1024,
) -> str:
    """把消息列表发给 DeepSeek，返回模型回复文本。

    调用链路：
      熔断器检查 → 重试装饰器 → OpenAI API
      ├─ 熔断中 → 直接抛 CircuitBreakerOpenError → 外层降级
      ├─ 瞬时故障 → 重试最多 3 次
      └─ 持续故障 → 熔断器记失败次数 → 达到阈值触发熔断
    """
    if not _llm_circuit_breaker.allow_request():
        logger.warning("LLM 调用被熔断器拦截")
        raise HTTPException(status_code=503, detail="夫子小憩片刻，请稍后再问")

    try:
        response = _chat_completion_create(
            messages=messages, temperature=temperature, max_tokens=max_tokens,
        )
        _llm_circuit_breaker.on_success()
        _log_token_usage(response)
        content = response.choices[0].message.content
        if content is None:
            return ""  # 模型拒绝或空回复
        return content
    except (APIError, APITimeoutError, AuthenticationError, RateLimitError, IndexError) as e:
        _llm_circuit_breaker.on_failure()
        raise _handle_api_error(e) from e


def chat_with_tools(
    messages: list[dict],
    temperature: float = 0.8,
    max_tokens: int = 1024,
    tools: list[dict] | None = None,
):
    """调 LLM，返回完整 response 对象（含 tool_calls 字段）。

    和 chat() 的区别：
    - chat() 只返回文本字符串（用于普通对话）
    - chat_with_tools() 返回完整对象（用于 Agent 循环，需要检查 tool_calls）

    同样经过熔断器 + 重试保护。
    """
    if not _llm_circuit_breaker.allow_request():
        logger.warning("LLM tool-call 被熔断器拦截")
        raise HTTPException(status_code=503, detail="夫子小憩片刻，请稍后再问")

    try:
        extra: dict = {}
        if tools:
            extra["tools"] = tools
            extra["tool_choice"] = "auto"

        response = _chat_completion_create(
            messages=messages, temperature=temperature, max_tokens=max_tokens, **extra,
        )
        _llm_circuit_breaker.on_success()
        _log_token_usage(response)
        return response
    except (APIError, APITimeoutError, AuthenticationError, RateLimitError, IndexError) as e:
        _llm_circuit_breaker.on_failure()
        raise _handle_api_error(e) from e


async def chat_stream(
    messages: list[dict],
    temperature: float = 1.1,
    max_tokens: int = 1024,
):
    """流式对话：每获得一个 token 就 yield 出去。

    同样经过熔断器 + 重试保护。
    注意：流式响应的重试只发生在建立连接阶段——
    已经开始流式推 token 后不重试（会丢已推送的内容）。
    """
    if not _llm_circuit_breaker.allow_request():
        logger.warning("LLM 流式调用被熔断器拦截")
        raise HTTPException(status_code=503, detail="夫子小憩片刻，请稍后再问")

    try:
        stream = await _async_chat_completion_create(
            messages=messages, temperature=temperature, max_tokens=max_tokens,
        )
        _llm_circuit_breaker.on_success()
        async for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content
    except (APIError, APITimeoutError, AuthenticationError, RateLimitError, IndexError) as e:
        _llm_circuit_breaker.on_failure()
        raise _handle_api_error(e) from e
