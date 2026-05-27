"""
RRF (Reciprocal Rank Fusion) — 混合检索结果融合

面试核心考点：
1. RRF 为什么不用分数直接加权？ → 向量相似度分(0.3~1.0) 和 BM25 分(0~50+)
   不在同一尺度，直接加权无意义。RRF 只看排名，排名天然可比。
2. k 参数的作用？ → 平滑系数，k=60 是经验值。k 越小，高排名文档优势越大。
3. 和 LlamaIndex 的 HybridFusionRetriever 底层完全一致。

RRF 公式:
  RRFscore(d) = Σ 1 / (k + rank_i(d))

  d    = 某篇文档
  i    = 第 i 路检索（如向量检索、BM25检索）
  rank_i(d) = 文档 d 在第 i 路检索中的排名（从 1 开始）
  k    = 平滑常数，默认 60

直观理解：
  - 某文档在向量检索排第 1、BM25 排第 5：
    RRF = 1/(60+1) + 1/(60+5) = 0.01639 + 0.01538 = 0.03177

  - 某文档在向量检索排第 3、BM25 排第 2：
    RRF = 1/(60+3) + 1/(60+2) = 0.01587 + 0.01613 = 0.03200

  → 后者总分更高（虽然最高排名不如前者），体现了"两路都认可"的价值

思考：什么时候用 RRF，什么时候用加权融合？
  - RRF: 两路检索评分尺度不同（向量 vs BM25），用排名融合最安全
  - 加权融合: 两路评分尺度相同（如两个向量检索），可以用 lambda * score_A + (1-lambda) * score_B
  - 本项目显然用 RRF

进一步优化（面试加分项）：
  - RRF 融合后可再加 BGE-Reranker 做精排：粗筛 Top-20 → Reranker 精排 Top-5
  - 称为"两阶段检索"，是生产级 RAG 的标准架构
"""

import logging

logger = logging.getLogger(__name__)

# 平滑常数 k=60 的研究来源：
# Cormack et al. (2009) "Reciprocal Rank Fusion outperforms Condorcet and
# individual rank learning methods". k=60 在 TREC 数据集上效果最优。
# 实践中 60 几乎不需要调整——调的是各路检索的 top_k 配比。
K = 60


def rrf_fusion(
    *result_lists: list[dict],
    k: int = K,
    top_k: int = 5,
) -> list[dict]:
    """
    多路检索结果融合（Reciprocal Rank Fusion）。

    使用场景：
      vector_results = retrieve(query, top_k=10)       # 语义检索 10 条
      bm25_results = keyword_search(query, top_k=10)    # 关键词检索 10 条
      final = rrf_fusion(vector_results, bm25_results, top_k=5)  # 融合取 5 条

    为什么不直接各取 5 条拼起来？
      → 两路可能召回同一篇文档（"学而时习之"语义和关键词都命中）
      → 直接拼接会重复，且无法判断"被两路都命中的文档"比"只被一路命中的"更好
      → RRF 融合自动去重 + 重新排序

    Args:
        *result_lists: 各路检索结果，每路是 [{"id":..., "text":..., ...}, ...]
                       列表顺序即排名顺序（索引 0 = 排名第 1）
        k: RRF 平滑常数，默认 60
        top_k: 融合后返回的结果数量

    Returns:
        融合后的 Top-K 结果，结构同输入。新增 rrf_score 字段用于调试。

    面试数值直觉：
      - 排名 1 对 RRF 的贡献: 1/61 ≈ 0.016
      - 排名 10 对 RRF 的贡献: 1/70 ≈ 0.014
      - 排名 60 对 RRF 的贡献: 1/120 ≈ 0.008
      → 排名越靠后，贡献降得越慢（平滑），不会因为某路排第 15 就被完全忽略
      → 这就是 k=60 的意义：不让头部文档优势过大，给中尾部文档机会
    """
    if not result_lists:
        return []

    # ----- RRF 核心计算 -----
    # rrf_scores: {doc_id: accumulated_rrf_score}
    # doc_map:   {doc_id: full_doc_info} 用于最后返回完整信息
    rrf_scores: dict[str, float] = {}
    doc_map: dict[str, dict] = {}

    for rank_list in result_lists:
        for rank, doc in enumerate(rank_list):
            doc_id = doc.get("id", "")
            if not doc_id:
                continue

            # 核心公式：score = 1 / (k + rank)
            # rank 从 0 开始（enumerate 默认），但 RRF 公式规定从 1 开始
            # 即：排在第 1 个 → rank=0 → RRF 用 (k + 0 + 1) = (k + 1)
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0) + 1.0 / (k + rank + 1)

            # 每篇文档只存一次完整信息
            # 如果同一篇文档被多路检索命中，保留先出现的版本
            if doc_id not in doc_map:
                doc_map[doc_id] = dict(doc)

    if not rrf_scores:
        return []

    # ----- 按 RRF 分数排序 -----
    sorted_ids = sorted(rrf_scores, key=rrf_scores.get, reverse=True)

    results = []
    for doc_id in sorted_ids[:top_k]:
        doc = doc_map[doc_id]
        doc["score"] = round(rrf_scores[doc_id], 6)  # 覆写为 RRF 分数
        results.append(doc)

    logger.debug(
        "RRF 融合完成: %d 路检索 → %d 个独立文档 → Top-%d",
        len(result_lists), len(rrf_scores), len(results),
    )
    return results
