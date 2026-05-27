"""Agent 工具注册表（已废弃，保留仅用于兼容参考）

⚠️ 此模块已被 MCP 框架替代。新代码请使用:
  - app.mcp.MCPClient 进行工具发现和调用
  - app.mcp.server.MCPServer 注册新工具
  - app.mcp.servers.AnalectsServer / WebSearchServer 查看已有工具

此文件保留仅为:
  1. Git 历史可追溯工具设计的演进
  2. 供面试展示"从硬编码工具到 MCP 架构"的升级对比

原设计（已废弃）：
每个工具是一个可调用函数 + 给 LLM 看的描述和参数定义。
LLM 通过 Function Calling 决定调不调、调哪个、传什么参数。
"""

from dataclasses import dataclass, field
from typing import Any, Callable

from app.rag.retriever import retrieve


@dataclass
class Tool:
    """Agent 可用的一个工具"""
    name: str                              # 工具唯一标识
    description: str                       # 给 LLM 看的说明（何时用、做什么）
    parameters: dict                       # JSON Schema 参数定义
    execute: Callable[..., Any]            # 实际执行的 Python 函数


# ============================================================
# 内置工具定义
# ============================================================

def _search_analects(query: str) -> str:
    """从论语知识库检索相关章句，返回格式化的上下文字符串。"""
    results = retrieve(query, top_k=5)
    if not results:
        return "未在《论语》中找到相关内容。"
    lines = []
    for i, r in enumerate(results):
        chapter = r.get("chapter", "未知")
        verse = r.get("verse_index", 0) + 1
        text = r.get("text", "")
        lines.append(f"{i+1}. 《{chapter}》(第{verse}章): {text}")
    return "\n".join(lines)


TOOLS: list[Tool] = [
    Tool(
        name="search_analects",
        description="从《论语》知识库中检索相关章句。当用户询问论语原文、儒家概念、孔子观点、人生哲理时使用此工具。",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "检索关键词或问题，例如：仁的含义、学习的态度、君子之道",
                }
            },
            "required": ["query"],
        },
        execute=lambda query: _search_analects(query),
    ),
]


def get_tool_by_name(name: str) -> Tool | None:
    """按名称查找工具"""
    for tool in TOOLS:
        if tool.name == name:
            return tool
    return None


def get_tools_for_api() -> list[dict]:
    """返回 OpenAI SDK 兼容的 tools 参数格式"""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }
        for tool in TOOLS
    ]
