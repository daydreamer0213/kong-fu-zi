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

logger = logging.getLogger(__name__)

MODEL = "deepseek-chat"
TIMEOUT = 30.0  # 单次 API 调用超时秒数

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


def _handle_api_error(e: Exception) -> HTTPException:
    """把 OpenAI SDK 异常转为 HTTPException，给出中文提示"""
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
    """把消息列表发给 DeepSeek，返回模型回复文本。"""
    try:
        response = _client.chat.completions.create(
            model=MODEL,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content = response.choices[0].message.content
        if content is None:
            return ""  # 模型拒绝或空回复
        return content
    except (APIError, APITimeoutError, AuthenticationError, RateLimitError, IndexError) as e:
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
    """
    try:
        kwargs: dict = dict(
            model=MODEL,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        return _client.chat.completions.create(**kwargs)
    except (APIError, APITimeoutError, AuthenticationError, RateLimitError, IndexError) as e:
        raise _handle_api_error(e) from e


async def chat_stream(
    messages: list[dict],
    temperature: float = 1.1,
    max_tokens: int = 1024,
):
    """流式对话：每获得一个 token 就 yield 出去。"""
    try:
        stream = await _async_client.chat.completions.create(
            model=MODEL,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content
    except (APIError, APITimeoutError, AuthenticationError, RateLimitError, IndexError) as e:
        raise _handle_api_error(e) from e
