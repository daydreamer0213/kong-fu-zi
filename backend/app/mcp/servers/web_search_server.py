"""
WebSearchServer — 联网搜索 MCP Server

提供 1 个工具：
  web_search(query) → Tavily Search API 实时联网搜索

和论语知识库的关系：
  - 论语相关的问题 → AnalectsServer 的 hybrid_search（本地，零延迟，高精度）
  - 现代事物、外部知识 → WebSearchServer 的 web_search（联网，实时信息）

这形成了知识边界的自然划分：
  Agent 先尝试本地知识库（论语），查不到或超出范围时才联网。
  和 System Prompt 里的"对现代事物一无所知"形成闭环——
  不知道的就上网搜，搜不到才坦言"此非吾所能知也"。

为什么选 Tavily Search API？
  - 专为 AI Agent 设计的搜索 API，返回结构化结果
  - 自带内容摘要，省去自己爬取+清洗的步骤
  - 国内可直接访问，比 DuckDuckGo 可靠
  - 免费额度足够开发和学习使用
  - API 设计天然适配 MCP 工具模型：query in → text out
"""

import logging
import os

from app.config import settings
from app.mcp.protocol import ServerInfo, ToolDefinition
from app.mcp.server import MCPServer

logger = logging.getLogger(__name__)

# 最大返回结果数
MAX_RESULTS = 5


class WebSearchServer(MCPServer):
    """联网搜索服务——基于 Tavily Search API"""

    def __init__(self):
        super().__init__(ServerInfo(name="web-search-server", version="0.1.0"))

        self.register_tool(
            ToolDefinition(
                name="web_search",
                description=(
                    "搜索互联网获取实时信息。适用场景："
                    "1. 用户询问现代事物、时事、其他领域知识（超出《论语》范畴）"
                    "2. 用户要求查找最新资料或外部信息"
                    "3. 本地知识库检索无结果时，可尝试联网搜索"
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "搜索关键词。用中文或英文均可，建议用简洁的关键词组合",
                        }
                    },
                    "required": ["query"],
                },
            ),
            handler=self._web_search,
        )

    def _web_search(self, arguments: dict) -> str:
        """调 Tavily Search API 执行搜索，返回格式化结果文本。

        返回给 LLM 的文本包含标题+URL+摘要，
        LLM 可以据此判断哪些结果有用，并在回复中引用。
        """
        query = arguments.get("query", "").strip()
        if not query:
            return "[搜索失败] 未提供搜索关键词。"

        # 获取 API Key
        api_key = os.getenv("TAVILY_API_KEY", "")
        if not api_key:
            # 尝试从 settings 获取
            api_key = getattr(settings, "tavily_api_key", "")

        if not api_key:
            return (
                "[搜索服务未配置] TAVILY_API_KEY 未设置。"
                "请在 .env 文件中添加: TAVILY_API_KEY=your-key"
            )

        try:
            from tavily import TavilyClient
        except ImportError:
            logger.warning("tavily-python 未安装")
            return "[搜索服务不可用] tavily-python 库未安装。请执行: pip install tavily-python"

        try:
            client = TavilyClient(api_key=api_key)
            response = client.search(
                query=query,
                search_depth="basic",       # basic=快速, advanced=深入但慢
                max_results=MAX_RESULTS,     # 返回结果数
                include_answer=True,         # Tavily 生成的综合回答（类似 AI Overview）
            )

            return _format_search_results(response, query)

        except Exception as e:
            logger.exception("Tavily 搜索异常: query=%s", query)
            return f"[搜索出错] {e}"


def _format_search_results(response: dict, query: str) -> str:
    """将 Tavily API 返回的结构化结果格式化为 LLM 可读文本。

    Tavily 返回格式:
      {
        "answer": "AI 生成的综合回答（如果 include_answer=True）",
        "results": [
          {"title": "...", "url": "...", "content": "摘要..."},
          ...
        ]
      }

    输出格式:
      [Tavily 综合回答]
      ...

      【搜索结果】
      1. 标题
         URL: ...
         摘要: ...
    """
    lines = [f'联网搜索结果（查询: "{query}"）:\n']

    # Tavily 综合回答（AI 生成的总结，通常质量不错）
    answer = response.get("answer", "")
    if answer:
        lines.append(f"[综合回答] {answer}\n")

    results = response.get("results", [])
    if not results:
        lines.append("未找到相关结果。")
        return "\n".join(lines)

    lines.append("【搜索结果】")
    for i, r in enumerate(results):
        title = r.get("title", "无标题")
        url = r.get("url", "")
        content = r.get("content", "")

        # 截断过长的摘要，保留关键信息
        if len(content) > 300:
            content = content[:300] + "..."

        lines.append(f"{i + 1}. {title}")
        if url:
            lines.append(f"   链接: {url}")
        if content:
            lines.append(f"   摘要: {content}")
        lines.append("")  # 空行分隔

    return "\n".join(lines)
