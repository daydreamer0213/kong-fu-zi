"""
Agent 循环 — LangGraph 版本

用 LangGraph StateGraph 替代手写 while 循环。
功能完全等价，但编排方式从"命令式循环"变为"声明式图"。

面试对比要点：
  旧版（手写 while）:
    - 控制流用 if/continue/break，分散在循环体中
    - 工具执行内嵌在 LLM 调用后面
    - 加并行工具调用需要改循环结构

  新版（LangGraph）:
    - 控制流 = 节点 + 条件边，一眼看清
    - 每个节点是纯函数，输入 state → 输出 partial state
    - 加并行工具只需在 tools 节点里用 asyncio.gather

LangGraph 三个核心概念：
  1. State（TypedDict）: 贯穿整个图，每个节点读/写它
  2. Node（节点）: 纯函数 state → partial_state
  3. Edge（边）: 普通边(固定流向) / 条件边(根据 state 动态路由)

图结构：
  START → agent → [有tool_calls?] → tools → agent → ... → END
                    └─ 无tool_calls ─→ END
"""

import json
import logging
import time
from typing import Annotated, Literal, TypedDict

from langgraph.graph import END, StateGraph

from app.llm.client import chat_with_tools
from app.mcp import get_mcp_client
from app.rag.retriever import retrieve
from app.utils.logging import get_logger

logger = logging.getLogger(__name__)
_log = get_logger("agent")

MAX_ITERATIONS = 5
MAX_DURATION_SECONDS = 120

# ---------------------------------------------------------------------------
# State — 用 TypedDict（LangGraph 标准方式）
# ---------------------------------------------------------------------------
# LangGraph 的 state 合并是 shallow merge：节点返回的 dict 中的 key 会覆盖
# state 中的同名 key。messages 字段用 operator.add 做 reducer（追加而非覆盖）。
# ---------------------------------------------------------------------------


class AgentState(TypedDict):
    messages: Annotated[list[dict], lambda x, y: x + y]  # reducer: 追加而非覆盖
    tools: list[dict]          # OpenAI 格式的工具列表（只读，不变）
    iteration: int             # 当前循环次数
    tool_call_count: int       # 工具调用累计次数
    sources: list[dict]        # 论语引用 [{"chapter":..., "text":..., "score":...}, ...]
    start_time: float          # 循环开始时间戳


# ---------------------------------------------------------------------------
# 节点函数
# ---------------------------------------------------------------------------


def _agent_node(state: AgentState) -> dict:
    """LLM 调用节点。

    把当前 conversation + tools 发给 DeepSeek，
    拿到的 assistant 消息通过 messages reducer 追加到 state。
    """
    messages = state["messages"]
    tools = state.get("tools", [])

    response = chat_with_tools(messages=messages, tools=tools)
    msg = response.choices[0].message

    # 构造 assistant 消息（纯 dict，不用 LangChain 消息类型）
    assistant_msg: dict = {"role": "assistant", "content": msg.content or ""}
    if msg.tool_calls:
        assistant_msg["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in msg.tool_calls
        ]

    logger.debug("agent_node: %d tool_calls", len(msg.tool_calls) if msg.tool_calls else 0)
    return {"messages": [assistant_msg]}  # reducer 会自动追加


def _tools_node(state: AgentState) -> dict:
    """工具执行节点。

    LLM 一次可返回多个 tool_calls，它们互不依赖，用线程池并行执行。
    示例：LLM 同时调 hybrid_search + web_search → 两个各自跑 → 等最慢的完成。
    总耗时从 T1+T2 → max(T1, T2)。

    为什么用 ThreadPoolExecutor 而不是 asyncio？
      MCP Server 的 handler 是同步函数（调 ChromaDB、BGE、Tavily 都是同步 IO），
      线程池天然适合包装同步函数做并行，不用改成 async/await。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    mcp = get_mcp_client()
    messages = state["messages"]
    last_msg = messages[-1]
    tool_calls = last_msg.get("tool_calls", [])

    if not tool_calls:
        return {
            "messages": [],
            "iteration": state.get("iteration", 0),
            "tool_call_count": state.get("tool_call_count", 0),
            "sources": state.get("sources", []),
        }

    new_count = state.get("tool_call_count", 0)
    sources: list[dict] = list(state.get("sources", []))

    # 准备每个工具调用——解析参数，生成任务
    tasks: list[dict] = []
    for tc in tool_calls:
        tool_name = tc["function"]["name"]
        try:
            args = json.loads(tc["function"]["arguments"])
        except (json.JSONDecodeError, KeyError):
            args = {}
        tasks.append({
            "id": tc["id"],
            "name": tool_name,
            "args": args,
        })

    # 并行提交所有任务到线程池
    # max_workers 限制在工具数内，无需无限开线程
    max_workers = min(len(tasks), 8)
    results_map: dict[str, dict] = {}  # tool_call_id → {result, duration_ms}

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_run_single_tool, task): task
            for task in tasks
        }
        for future in as_completed(futures):
            task = futures[future]
            try:
                result = future.result()
                results_map[task["id"]] = result
            except Exception as e:
                _log.warning("tools_node_failed", tool=task["name"], error=str(e))
                results_map[task["id"]] = {
                    "result_text": f"[工具执行异常] {e}",
                    "duration_ms": 0,
                }

    # 按 tool_calls 原始顺序组装结果（保留顺序供 LLM 理解上下文）
    tool_msgs: list[dict] = []
    for tc in tool_calls:
        tid = tc["id"]
        tool_name = tc["function"]["name"]
        result = results_map.get(tid, {"result_text": "[工具未执行]", "duration_ms": 0})
        result_text = result["result_text"]
        duration_ms = result["duration_ms"]

        new_count += 1
        _log.info(
            "tool_call",
            tool=tool_name,
            duration_ms=round(duration_ms, 1),
            result_len=len(result_text),
        )

        # 收集 sources
        if tool_name in ("hybrid_search", "search_analects", "search_by_keyword"):
            if not sources:
                try:
                    args = _parse_args_from_task(tasks, tid)
                    query = args.get("query") or args.get("keyword", "")
                    sources = [
                        {"chapter": r["chapter"], "text": r["text"], "score": r["score"]}
                        for r in retrieve(query, top_k=5)
                    ]
                except Exception:
                    _log.warning("sources_collection_failed", tool=tool_name)

        tool_msgs.append({
            "role": "tool",
            "tool_call_id": tid,
            "content": result_text,
        })

    logger.debug("tools_node: 并行执行 %d 工具, 累计=%d", len(tool_calls), new_count)
    return {
        "messages": tool_msgs,
        "iteration": state.get("iteration", 0) + 1,
        "tool_call_count": new_count,
        "sources": sources,
    }


def _run_single_tool(task: dict) -> dict:
    """在线程池中执行单个工具调用（线程安全——每个线程独立调用 MCP）。"""
    mcp = get_mcp_client()
    tool_start = time.perf_counter()
    result_text = mcp.call_tool(task["name"], task["args"])
    duration_ms = (time.perf_counter() - tool_start) * 1000
    return {"result_text": result_text, "duration_ms": duration_ms}


def _parse_args_from_task(tasks: list[dict], tool_call_id: str) -> dict:
    for t in tasks:
        if t["id"] == tool_call_id:
            return t["args"]
    return {}


# ---------------------------------------------------------------------------
# 条件边
# ---------------------------------------------------------------------------


def _should_continue(state: AgentState) -> Literal["tools", "__end__"]:
    """条件路由：LLM 回复后 → tools 还是 END？"""
    messages = state["messages"]
    last_msg = messages[-1]

    if state.get("iteration", 0) >= MAX_ITERATIONS:
        logger.info("Agent 达到最大迭代次数 %d", MAX_ITERATIONS)
        return "__end__"

    start = state.get("start_time", 0)
    if start and (time.time() - start) > MAX_DURATION_SECONDS:
        logger.info("Agent 超时")
        return "__end__"

    if last_msg.get("tool_calls"):
        return "tools"

    return "__end__"


# ---------------------------------------------------------------------------
# 图构建
# ---------------------------------------------------------------------------

_compiled_graph = None


def _build_graph():
    """构建并编译 Agent 图（编译一次，缓存复用）"""
    global _compiled_graph
    if _compiled_graph is not None:
        return _compiled_graph

    graph = StateGraph(AgentState)

    graph.add_node("agent", _agent_node)
    graph.add_node("tools", _tools_node)
    graph.set_entry_point("agent")

    graph.add_conditional_edges(
        "agent",
        _should_continue,
        {"tools": "tools", "__end__": END},
    )
    graph.add_edge("tools", "agent")

    _compiled_graph = graph.compile()
    logger.info("LangGraph Agent 图编译完成")
    return _compiled_graph


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------


def run_agent_graph(
    system_prompt: str,
    tools: list[dict],
    user_message: str,
    history: list[dict] | None = None,
) -> dict:
    """用 LangGraph 运行 Agent 循环。

    Args:
        system_prompt: Skill 对应的 System Prompt
        tools: OpenAI 格式的工具列表（已按 Skill 过滤）
        user_message: 用户当前消息
        history: 历史消息列表 [{"role":"...","content":"..."}, ...]

    Returns:
        {"reply": "...", "sources": [...], "tool_calls": N}
    """
    # 构建初始消息列表（不含 assistant/tool 消息 — 那由 Agent 循环产生）
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    start = time.perf_counter()
    _log.info("agent_start", tool_count=len(tools), msg_preview=user_message[:80])

    initial_state = AgentState(
        messages=messages,
        tools=tools,
        iteration=0,
        tool_call_count=0,
        sources=[],
        start_time=time.time(),
    )

    graph = _build_graph()
    final_state = graph.invoke(initial_state)

    # 提取最终回复 — 最后一条 assistant 消息
    last_msg = final_state["messages"][-1]
    reply = last_msg.get("content", "") or ""

    tool_calls = final_state.get("tool_call_count", 0)
    iterations = final_state.get("iteration", 0)
    duration_ms = (time.perf_counter() - start) * 1000

    _log.info(
        "agent_end",
        iterations=iterations,
        tool_calls=tool_calls,
        reply_len=len(reply),
        duration_ms=round(duration_ms, 1),
        reply_preview=reply[:100],
    )

    return {
        "reply": reply.strip(),
        "sources": final_state.get("sources", []),
        "tool_calls": tool_calls,
    }
