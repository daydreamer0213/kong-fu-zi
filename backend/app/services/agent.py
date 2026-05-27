"""Agent 循环 — ReAct 模式的 LLM 自主推理

替代了原来的 classify_intent → retrieve → chat 流程。
Agent 自己决定：要不要查书、查什么、查几次、什么时候回答。

升级为 MCP 架构 + Skill 机制：
  - 工具来源从 tools.py → MCPClient.discover_tools()
  - 工具执行从 tool.execute() → MCPClient.call_tool()
  - Prompt 从 Skill 定义中获取，不同 Skill 有不同角色侧重
  - 工具可按 Skill 的 allowed_tools 过滤（如 poetry 模式不用 web_search）
"""

import json
import logging
import time

from fastapi import HTTPException

from app.llm.client import chat, chat_with_tools  # noqa: F401  chat 用于 _simple_chat_reply
from app.llm.prompts import get_agent_system_prompt
from app.mcp import get_mcp_client
from app.rag.retriever import retrieve  # noqa: F401  供 E2E 测试 mock
from app.skills import get_skill_registry

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 5
MAX_DURATION_SECONDS = 120


def run_agent(
    user_message: str,
    history: list[dict] | None = None,
    skill_name: str | None = None,
    profile_text: str = "",
) -> dict:
    """运行 Agent 循环，带降级兜底、Skill 支持和用户画像。

    降级链: L0(Agent+工具) → L1(纯LLM) → L2(固定回复)
    Skill: 可选的角色模式，影响 System Prompt 和可用工具集
    Profile: 跨对话的用户画像，注入 System Prompt 让角色感知用户背景

    Args:
        user_message: 用户当前消息
        history: 历史消息列表
        skill_name: Skill 名称，None=默认 "teaching"
        profile_text: 格式化后的画像文本（来自 format_profile_for_prompt）

    Returns:
        {"reply": "最终回复文本", "sources": [...], "tool_calls": 调用工具次数}
    """
    # ---- L0: 完整 Agent 模式 ----
    try:
        return _agent_loop_with_tools(user_message, history, skill_name, profile_text)
    except HTTPException as e:
        if e.status_code not in (502, 503, 504):
            raise
        logger.warning("Agent L0 失败 (status=%d), 降级到 L1", e.status_code)
    except Exception:
        logger.exception("Agent L0 异常, 降级到 L1")

    # ---- L1: 纯 LLM 对话（无工具，不检索） ----
    try:
        return _simple_chat_reply(user_message, history, skill_name)
    except Exception:
        logger.exception("Agent L1 失败, 降级到 L2")

    # ---- L2: 固定回复（零 API 依赖） ----
    return _build_result(
        "夫子思之良久，未能作答。子其谅之，不若改日再论。",
        [], 0,
    )


def _resolve_skill(skill_name: str | None):
    """解析 Skill 名称，返回 (Skill | None, system_prompt: str, allowed_tools: set | None)

    None 的 allowed_tools 表示"全部可用"。
    如果指定了不存在的 Skill 或没注册默认 Skill，回退到旧版静态 Prompt。
    """
    registry = get_skill_registry()
    skill = registry.resolve(skill_name)

    if skill:
        allowed = set(skill.allowed_tools) if skill.allowed_tools else None
        return skill, skill.system_prompt, allowed

    # 没有注册任何 Skill（启动时遗漏了）→ 回退到旧版动态 Prompt
    mcp = get_mcp_client()
    tool_defs = mcp.list_tools()
    return None, get_agent_system_prompt(tool_defs), None


def _agent_loop_with_tools(
    user_message: str,
    history: list[dict] | None = None,
    skill_name: str | None = None,
    profile_text: str = "",
) -> dict:
    """Agent 循环 — LangGraph 版本。

    画像注入：如果 profile_text 非空，拼接到 System Prompt 末尾。
    """
    from app.services.agent_graph import run_agent_graph

    mcp = get_mcp_client()
    skill, system_prompt, allowed_tools = _resolve_skill(skill_name)

    # 注入用户画像（在工具描述之前，角色设定之后）
    if profile_text:
        system_prompt = system_prompt + "\n\n" + profile_text

    # 获取并过滤工具
    all_tools = mcp.discover_tools()
    if allowed_tools is not None:
        tools = [t for t in all_tools if t["function"]["name"] in allowed_tools]
        logger.debug(
            "Skill '%s' 过滤工具: %d → %d",
            skill.name if skill else "default",
            len(all_tools), len(tools),
        )
    else:
        tools = all_tools

    # 委托给 LangGraph 版 Agent 循环
    return run_agent_graph(
        system_prompt=system_prompt,
        tools=tools,
        user_message=user_message,
        history=history,
    )


def _simple_chat_reply(
    user_message: str,
    history: list[dict] | None = None,
    skill_name: str | None = None,
) -> dict:
    """降级方案 L1——纯 LLM 对话，不带工具也不检索。

    L1 降级时也用 Skill 的 System Prompt——保持人格一致性。
    """
    from app.llm.client import chat
    from app.llm.prompts import get_system_prompt

    # 尝试用 Skill 的 Prompt，失败则回退基础版
    registry = get_skill_registry()
    skill = registry.resolve(skill_name)
    sys_prompt = skill.system_prompt if skill else get_system_prompt()

    messages = [{"role": "system", "content": sys_prompt}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    reply = chat(messages)
    return _build_result(reply, [], 0)


def _build_result(reply: str, sources: list[dict], tool_calls: int) -> dict:
    return {"reply": reply, "sources": sources, "tool_calls": tool_calls}
