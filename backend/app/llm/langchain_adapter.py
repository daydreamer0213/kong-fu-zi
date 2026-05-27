"""
LangChain ChatModel 适配器 — 把项目自有的 DeepSeek 客户端包成标准接口

面试核心价值：
  LangChain 的 BaseChatModel 是 LLM 提供商的标准抽象层。
  实现这个接口后，所有依赖 ChatModel 的 LangChain 组件都可以直接挂我们的
  DeepSeek 后端——不换代码，只换 model 参数。

BaseChatModel 需要实现的三个核心：
  1. _llm_type       — 返回 "deepseek"（标识提供商）
  2. _generate()     — 非流式调用，输入消息列表 → 输出 ChatResult
  3. _stream()       — 流式调用，输入消息列表 → 逐 token yield

和现有 client.py 的关系：
  - client.py 是「自家实现」——熔断器、重试、错误映射全在手
  - 这个 adapter 是「标准门面」——让外部 LangChain 组件能接入
  - adapter 内部调 client.py 的 _chat_completion_create，韧性层不变

面试时对比：
  "我手写了 DeepSeek 客户端，又包了 LangChain 的 ChatModel 接口。
   两者都能用，前者性能最优（零抽象开销），后者兼容性最强（对接 LangChain 生态）。
   生产环境选哪个取决于团队技术栈——如果团队统一用 LangChain，这个 adapter
   就是桥梁；如果是轻量微服务，直接用 client.py 更简洁。"
"""

from typing import Any, Iterator, Optional

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import (
    BaseChatModel,
    generate_from_stream,
)
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from app.llm.client import MODEL, _chat_completion_create, _llm_circuit_breaker
from app.utils.logging import get_logger

_log = get_logger("llm.langchain")


# ---------------------------------------------------------------------------
# 消息格式转换 — LangChain 消息对象 ↔ OpenAI dict
# ---------------------------------------------------------------------------
# LangChain 用强类型消息对象（SystemMessage, HumanMessage 等），
# OpenAI SDK 用纯 dict（{"role":"system","content":"..."}）。
# 这个映射表处理双向转换。
# ---------------------------------------------------------------------------


def _lc_to_dict(msg: BaseMessage) -> dict:
    """LangChain 消息 → OpenAI dict"""
    if isinstance(msg, SystemMessage):
        return {"role": "system", "content": msg.content}
    if isinstance(msg, HumanMessage):
        return {"role": "user", "content": msg.content}
    if isinstance(msg, AIMessage):
        d: dict = {"role": "assistant", "content": msg.content}
        # 如果消息含 tool_calls（从工具调用返回的 AIMessage），保留它们
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            d["tool_calls"] = [
                {
                    "id": tc.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": tc.get("name", ""),
                        "arguments": tc.get("args", {}),
                    },
                }
                if isinstance(tc, dict)
                else {
                    "id": tc.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": tc["function"]["name"],
                        "arguments": tc["function"]["arguments"],
                    },
                }
                for tc in msg.tool_calls
            ]
        return d
    if isinstance(msg, ToolMessage):
        return {
            "role": "tool",
            "tool_call_id": msg.tool_call_id,
            "content": msg.content,
        }
    # 兜底：其他类型当 user 消息处理
    return {"role": "user", "content": str(msg.content)}


def _dict_to_ai_message(data: dict) -> AIMessage:
    """OpenAI dict → LangChain AIMessage"""
    msg = AIMessage(content=data.get("content", "") or "")
    if data.get("tool_calls"):
        msg.tool_calls = data["tool_calls"]
    return msg


# ---------------------------------------------------------------------------
# DeepSeekChatModel
# ---------------------------------------------------------------------------


class DeepSeekChatModel(BaseChatModel):
    """LangChain 兼容的 DeepSeek ChatModel。

    用法：
        from app.llm.langchain_adapter import DeepSeekChatModel

        model = DeepSeekChatModel(temperature=0.8)
        response = model.invoke([HumanMessage(content="什么是仁？")])
        print(response.content)  # "仁者，爱人也..."

    invoke / stream / batch 等方法是 BaseChatModel 提供的通用逻辑，
    我们只需要实现 _generate 和 _stream。

    熔断器和重试保护在底层 _chat_completion_create 中，这里不需要重复处理。
    """

    # LangChain 用 Pydantic 管理参数，这两个是 ChatModel 的核心可配字段
    temperature: float = 0.8
    max_tokens: int = 1024

    @property
    def _llm_type(self) -> str:
        """标识 LLM 提供商——LangChain 内部用于日志和追踪"""
        return "deepseek"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """非流式生成——调 DeepSeek API，返回完整回复。

        内部调 client.py 的 _chat_completion_create，自动走熔断+重试。
        """
        # 转换消息格式
        dicts = [_lc_to_dict(m) for m in messages]

        # 调底层 API（已有重试+熔断保护）
        response = _chat_completion_create(
            messages=dicts,
            temperature=kwargs.get("temperature", self.temperature),
            max_tokens=kwargs.get("max_tokens", self.max_tokens),
        )

        # 熔断器在 client.py 的 chat_with_tools / chat 中更新，
        # 这里直接调了 _chat_completion_create，需要手动维护熔断器状态
        _llm_circuit_breaker.on_success()

        msg = response.choices[0].message
        ai_msg = _dict_to_ai_message({
            "content": msg.content,
            "tool_calls": _format_tool_calls(msg.tool_calls) if msg.tool_calls else None,
        })

        # 构造 ChatResult
        generation = ChatGeneration(message=ai_msg)
        return ChatResult(generations=[generation])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        """流式生成——逐 token yield。

        注意：流式不支持重试（已开始推 token 后不能重来），
        但熔断器仍然保护连接建立阶段。
        """
        from openai import AsyncOpenAI
        from app.config import settings

        if not _llm_circuit_breaker.allow_request():
            raise RuntimeError("LLM 熔断中，请稍后重试")

        import asyncio

        dicts = [_lc_to_dict(m) for m in messages]

        async def _async_stream():
            client = AsyncOpenAI(
                api_key=settings.deepseek_api_key,
                base_url=settings.deepseek_base_url,
            )
            stream = await client.chat.completions.create(
                model=MODEL,
                messages=dicts,
                temperature=kwargs.get("temperature", self.temperature),
                max_tokens=kwargs.get("max_tokens", self.max_tokens),
                stream=True,
            )
            chunks = []
            async for chunk in stream:
                chunks.append(chunk)
            return chunks

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        try:
            chunks = loop.run_until_complete(_async_stream())
            _llm_circuit_breaker.on_success()
        except Exception:
            _llm_circuit_breaker.on_failure()
            raise

        for chunk in chunks:
            delta = chunk.choices[0].delta
            if delta.content:
                yield ChatGenerationChunk(
                    message=AIMessage(content=delta.content)
                )


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _format_tool_calls(tool_calls) -> list[dict] | None:
    """把 OpenAI SDK 的 tool_calls 转为 LangChain 兼容格式"""
    if not tool_calls:
        return None
    formatted = []
    for tc in tool_calls:
        formatted.append({
            "id": tc.id,
            "name": tc.function.name,
            "args": tc.function.arguments,
        })
    return formatted
