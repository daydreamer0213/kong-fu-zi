"""Agent 循环 — ReAct 模式的 LLM 自主推理

替代了原来的 classify_intent → retrieve → chat 流程。
Agent 自己决定：要不要查书、查什么、查几次、什么时候回答。
"""

import json
import logging
import time

from fastapi import HTTPException

from app.llm.client import chat_with_tools
from app.llm.prompts import get_agent_system_prompt
from app.rag.retriever import retrieve
from app.services.tools import get_tool_by_name, get_tools_for_api

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 5
MAX_DURATION_SECONDS = 120


def run_agent(user_message: str, history: list[dict] | None = None) -> dict:
    """运行 Agent 循环，返回最终回复和来源。

    Args:
        user_message: 用户当前消息
        history: 历史消息列表 [{"role":"...", "content":"..."}, ...]

    Returns:
        {"reply": "最终回复文本", "sources": [...], "tool_calls": 调用工具次数}
    """
    messages = [{"role": "system", "content": get_agent_system_prompt()}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    tools = get_tools_for_api()
    collected_sources: list[dict] = []
    tool_call_count = 0
    iteration = 0
    start_time = time.time()

    while iteration < MAX_ITERATIONS:
        if time.time() - start_time > MAX_DURATION_SECONDS:
            return _build_result(
                "夫子沉思良久，未能尽言，子其谅之。", collected_sources, tool_call_count
            )

        try:
            response = chat_with_tools(messages=messages, tools=tools)
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("Agent LLM 调用异常")
            raise HTTPException(status_code=500, detail="对话服务异常") from e

        msg = response.choices[0].message

        # 情况1：LLM 选择了调用工具
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_name = tc.function.name
                tool = get_tool_by_name(tool_name)
                if tool is None:
                    continue

                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    continue

                # 工具执行
                result = tool.execute(**args)
                tool_call_count += 1

                # 搜索工具的结果收集为 sources
                if tool_name == "search_analects":
                    collected_sources = [
                        {"chapter": r["chapter"], "text": r["text"], "score": r["score"]}
                        for r in retrieve(args.get("query", user_message), top_k=5)
                    ]

                # 追加 assistant 消息（含 tool_calls）
                messages.append({
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {"id": tc.id, "type": "function",
                         "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    ],
                })
                # 追加 tool 消息（工具返回结果）
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

            iteration += 1
            continue

        # 情况2：LLM 直接回复（无工具调用）→ 最终回答
        content = msg.content or ""
        return _build_result(content.strip(), collected_sources, tool_call_count)

    return _build_result(
        "夫子思之良久，曰：此事说来话长，不若改日再论。",
        collected_sources, tool_call_count
    )


def _build_result(reply: str, sources: list[dict], tool_calls: int) -> dict:
    return {"reply": reply, "sources": sources, "tool_calls": tool_calls}
