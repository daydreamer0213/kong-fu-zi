"""
AnalectsServer — 论语知识库 MCP Server

提供 3 个工具，覆盖不同检索策略：

  hybrid_search(query)     → 混合检索（向量 + BM25 + RRF + Rerank）
                            完整两阶段链路，精度最高，推荐默认使用
  search_analects(query)   → 纯 BGE 语义向量检索
                            适合模糊概念查询（"什么是仁"）
  search_by_keyword(keyword) → 纯 BM25 关键词检索
                              适合精确匹配（"巧言令色"）

工具分层的设计意图（面试可讲）：
  - Agent 默认优先用 hybrid_search——一站式，精度最高
  - 当 hybrid_search 返回空或结果不理想时，Agent 可分别调 search_analects
    和 search_by_keyword，自主对比两路结果——展示多工具编排能力
  - 三工具的设计不是冗余，是给 Agent 提供"不同精度的检索子弹"

和 RAG 全链路的关系：
  向量:  app.rag.retriever.retrieve()
  BM25:  app.rag.keyword_search.keyword_search()
  RRF:   app.rag.fusion.rrf_fusion()
  Rerank:app.rag.reranker.rerank()

  hybrid_search 内部调上述四个函数完成完整链路。
"""

import logging

from app.mcp.protocol import ServerInfo, ToolDefinition
from app.mcp.server import MCPServer

logger = logging.getLogger(__name__)


class AnalectsServer(MCPServer):
    """论语知识库检索服务"""

    def __init__(self):
        super().__init__(ServerInfo(name="analects-server", version="0.1.0"))

        # 注册 3 个工具
        self.register_tool(
            ToolDefinition(
                name="hybrid_search",
                description=(
                    "从《论语》知识库中混合检索相关章句（推荐优先使用）。"
                    "内部使用语义检索+关键词检索+RRF融合+Reranker精排，"
                    "精度最高，适合大多数场景。"
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "检索查询，可以是自然语言问题或关键词",
                        }
                    },
                    "required": ["query"],
                },
            ),
            handler=self._hybrid_search,
        )

        self.register_tool(
            ToolDefinition(
                name="search_analects",
                description=(
                    "纯语义向量检索——从《论语》中找语义相近的章句。"
                    "适合模糊概念查询（如'仁的含义'），不依赖精确关键词匹配。"
                    "当 hybrid_search 结果不理想时可用此工具单独检索。"
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "自然语言查询，如'什么是仁'、'学习的态度'",
                        }
                    },
                    "required": ["query"],
                },
            ),
            handler=self._search_analects,
        )

        self.register_tool(
            ToolDefinition(
                name="search_by_keyword",
                description=(
                    "纯关键词检索——在《论语》中精确匹配关键词。"
                    "适合查找包含特定词语的章句（如'巧言令色'、'君子'）。"
                    "当 hybrid_search 结果不理想或需要精确词匹配时使用。"
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "keyword": {
                            "type": "string",
                            "description": "精确匹配的关键词，如'巧言令色'、'学而时习之'",
                        }
                    },
                    "required": ["keyword"],
                },
            ),
            handler=self._search_by_keyword,
        )

    # ------------------------------------------------------------------
    # 工具 handler
    # ------------------------------------------------------------------

    def _hybrid_search(self, arguments: dict) -> str:
        """混合检索完整链路：向量 + BM25 → RRF 融合 → Reranker 精排。

        链路：
          1. retrieve(query, top_k=10)        → 向量粗筛
          2. keyword_search(query, top_k=10)  → BM25 粗筛
          3. rrf_fusion(两路, top_k=15)       → RRF 融合
          4. rerank(query, top15, top_k=5)    → Reranker 精排
          5. 格式化结果文本

        为什么先融合再精排而不是先精排再融合？
          → Reranker 的输入是融合后的候选集，确保精排看到的是"两路都覆盖"的结果。
            先各自精排再融合会丢失"一路排低但另一路排高"的文档。
        """
        from app.rag.fusion import rrf_fusion
        from app.rag.keyword_search import keyword_search
        from app.rag.reranker import rerank
        from app.rag.retriever import retrieve

        query = arguments.get("query", "").strip()
        if not query:
            return "未提供检索查询。"

        # 阶段一：两路粗筛
        vec_results = retrieve(query, top_k=10)
        bm25_results = keyword_search(query, top_k=10)

        # RRF 融合（两路合并去重，按排名融合排序）
        fused = rrf_fusion(vec_results, bm25_results, top_k=15)

        if not fused:
            return "未在《论语》中找到相关内容。不若换个角度再问？"

        # 阶段二：Reranker 精排
        ranked = rerank(query, fused, top_k=5)

        return _format_results(ranked)

    def _search_analects(self, arguments: dict) -> str:
        """纯 BGE 语义向量检索"""
        from app.rag.retriever import retrieve

        query = arguments.get("query", "").strip()
        if not query:
            return "未提供检索查询。"

        results = retrieve(query, top_k=5)
        if not results:
            return "未在《论语》中找到相关内容。"
        return _format_results(results)

    def _search_by_keyword(self, arguments: dict) -> str:
        """纯 BM25 关键词检索"""
        from app.rag.keyword_search import keyword_search

        keyword = arguments.get("keyword", "").strip()
        if not keyword:
            return "未提供检索关键词。"

        results = keyword_search(keyword, top_k=5)
        if not results:
            return f"《论语》中未找到包含'{keyword}'的章句。"
        return _format_results(results)


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _format_results(results: list[dict]) -> str:
    """将检索结果列表格式化为 LLM 易读的文本。

    格式示例：
      1. 《学而篇》(第1章): 子曰：学而时习之，不亦说乎？...
      2. 《为政篇》(第11章): 子曰：温故而知新，可以为师矣。
      ...

    LLM 拿到这个文本后，可以据此引用原文并标注篇名。
    score 字段不传给 LLM——LLM 不需要知道检索分数，
    它只需要知道"这些是按相关度排序的结果"。
    """
    if not results:
        return "未找到相关章句。"

    lines = []
    for i, r in enumerate(results):
        chapter = r.get("chapter", "未知")
        verse = r.get("verse_index", 0) + 1
        text = r.get("text", "")
        lines.append(f"{i + 1}. 《{chapter}》(第{verse}章): {text}")

    return "\n".join(lines)
