"""
MemoryServer — 用户长期记忆 MCP Server

提供 2 个工具：
  remember(fact)  → 存一条记忆，用户主动要求"帮我记住xxx"
  recall(query)   → 语义检索历史记忆，Agent 对话中自己决定何时查

设计要点（面试可讲）：
  1. 记忆是 RAG 的另一种应用——知识库是对论语做 RAG，
     记忆是对用户历史对话做 RAG。同样的架构，不同的数据源。
  2. Agent 自主决定何时 recall——不是每轮都查，而是需要上下文时主动调。
     这和 LLM 的 attention window 互补：窗口内的是短期记忆，这里是长期记忆。
  3. 存什么由用户控制（remember），查什么由 Agent 控制（recall），
     画像提取（未来第二步）由系统控制——三层记忆，职责分离。
"""

import logging

from app.mcp.protocol import ServerInfo, ToolDefinition
from app.mcp.server import MCPServer
from app.models import memory as mem

logger = logging.getLogger(__name__)


class MemoryServer(MCPServer):
    """用户长期记忆服务"""

    def __init__(self):
        super().__init__(ServerInfo(name="memory-server", version="0.1.0"))

        self.register_tool(
            ToolDefinition(
                name="remember",
                description=(
                    "记住用户明确告知的关键信息。只在用户说'记住xxx'、"
                    "'帮我记xxx'等明确要求时使用。不能自行推断用户信息。"
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "fact": {
                            "type": "string",
                            "description": "用户要求记住的信息，保留原话，不自行改写",
                        }
                    },
                    "required": ["fact"],
                },
            ),
            handler=self._remember,
        )

        self.register_tool(
            ToolDefinition(
                name="recall",
                description=(
                    "检索用户之前要求记住的信息。用于：1) 用户问'我之前说过什么'"
                    "2) 对话中需要历史上下文时 3) 需要回顾用户偏好或需求时"
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "检索关键词或问题，如'学习计划'、'喜欢的章节'",
                        }
                    },
                    "required": ["query"],
                },
            ),
            handler=self._recall,
        )

    # ------------------------------------------------------------------
    # 工具 handler
    # ------------------------------------------------------------------

    def _remember(self, arguments: dict) -> str:
        fact = arguments.get("fact", "").strip()
        if not fact:
            return "未提供需要记住的信息。"

        # 截断过长输入（记忆不是存储全文，是存储关键信息）
        if len(fact) > 500:
            fact = fact[:497] + "..."

        # 从 contextvar 获取当前用户 ID
        user_id = _get_current_user_id()
        if user_id is None:
            return "[记忆服务未就绪] 无法确定当前用户。"

        return mem.save_fact(user_id, fact)

    def _recall(self, arguments: dict) -> str:
        query = arguments.get("query", "").strip()
        if not query:
            return "未提供检索查询。"

        user_id = _get_current_user_id()
        if user_id is None:
            return "[记忆服务未就绪] 无法确定当前用户。"

        top_k = min(arguments.get("top_k", 5), 10)  # 上限 10 条
        result = mem.recall_facts(user_id, query, top_k=top_k)

        if "尚无记忆" in result:
            return result

        return (
            f'检索到的用户记忆（查询: "{query}"）：\n'
            f"{result}\n\n"
            "请基于以上记忆信息调整回复——这些是用户之前特意嘱咐记住的内容。"
        )


# ---------------------------------------------------------------------------
# 获取当前用户 ID
# ---------------------------------------------------------------------------

def _get_current_user_id() -> int | None:
    """从 structlog 的 contextvar 获取当前请求的 user_id。

    user_id 在 auth.py 的 get_current_user() 中被设置到 contextvar。
    MemoryServer 不依赖 FastAPI 的 Depends——通过 contextvar 解耦。
    """
    from app.utils.logging import user_id_ctx
    uid = user_id_ctx.get()
    if uid:
        try:
            return int(uid)
        except (ValueError, TypeError):
            return None
    return None
