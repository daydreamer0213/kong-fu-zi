"""
BM25 关键词检索 — 倒排索引 + TF-IDF 增强版

面试核心考点：
1. BM25 是 TF-IDF 的改进版，解决了 TF 无上限膨胀的问题
2. 和语义检索（BGE向量）互补：语义找"意思相近"，关键词找"精确匹配"
3. 和 LlamaIndex 的 BM25Retriever 底层原理一致
4. 为什么不用 Elasticsearch？—— 512条数据，rank_bm25 库一行 pip 就够了

BM25 公式（了解即可，面试能说出三个参数就够了）：
  Score(D, Q) = Σ IDF(q_i) * [f(q_i,D) * (k1 + 1)] / [f(q_i,D) + k1 * (1 - b + b * |D|/avgdl)]

  三个关键参数：
  - k1 (默认1.5): 控制 TF 饱和速度。k1越大，词频影响越大
  - b  (默认0.75): 控制文档长度归一化程度。b=1完全归一化，b=0不归一化
  - IDF: 逆文档频率，稀有词权重更高

分词方案：
  - jieba 精确模式: 适合中文文本检索，切成最小粒度的词语
  - 例: "学而时习之" → ["学而", "时", "习", "之"]
  - 为什么不用字符级分词？—— 中文单字语义太弱，"学"一个字太宽泛
"""

import logging
import os
import threading
from pathlib import Path

from rank_bm25 import BM25Okapi

from app.config import settings
from app.rag.chunker import load_and_chunk

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 全局单例 — 和 embedder.py 中的 BGE 模型一样，懒加载 + 双重检查锁
# BM25Okapi 对象是有状态的（内部存了所有文档），只需构建一次
# ---------------------------------------------------------------------------
_bm25_index: BM25Okapi | None = None
_chunks_snapshot: list | None = None  # 和 BM25 索引一一对应的 chunk 列表
_lock = threading.Lock()


def _build_index():
    """
    构建 BM25 倒排索引。

    和 embedder.py 的 _get_model() 同理：懒加载 + 双重检查锁 + 全局单例。
    首次调用时加载论语数据、分词、建索引；之后直接复用。
    512条数据建索引 < 50ms，完全可以在启动时构建，不影响请求响应。

    面试时可以对比：
    - 内存倒排索引 (BM25Okapi): 512 条数据毫秒级，零运维
    - Elasticsearch: 需要独立服务，10 万条以上才有必要
    - LlamaIndex BM25Retriever: 底层也是 rank_bm25 或 Elasticsearch
    """
    global _bm25_index, _chunks_snapshot

    if _bm25_index is not None:
        return

    with _lock:
        if _bm25_index is not None:
            return

        # 找到 lunyu.json 的路径
        # Docker 环境中路径不同，通过环境变量判断
        data_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data")
        json_path = os.path.join(data_dir, "lunyu.json")
        if not os.path.exists(json_path):
            # Docker 环境下的备用路径
            json_path = "/app/data/lunyu.json"

        if not os.path.exists(json_path):
            logger.warning("论语数据文件未找到，BM25 索引构建失败: %s", json_path)
            return

        # 复用 chunker 的分块逻辑，保持和向量检索同样的 chunk 粒度
        # 这样 RRF 融合时两路结果的 chunk_id 可以直接对齐
        chunks = load_and_chunk(json_path)
        texts = [c.text for c in chunks]

        # ----- 分词 -----
        # jieba 精确模式：切成最小粒度的词语，保证检索精度
        # 例: "子曰学而时习之" → ["子曰", "学而", "时", "习", "之"]
        # 为什么不用搜索引擎模式（jieba.cut_for_search）？
        #   → 搜索模式会切出冗余长词（如"学而时习之"整体也算一个词），增加索引大小
        #   → 精确模式切出的短词更多，召回率更高，漏检风险更小
        try:
            import jieba
        except ImportError:
            logger.warning("jieba 未安装，BM25 检索将不可用")
            return

        tokenized = [list(jieba.cut(text)) for text in texts]

        # ----- 建索引 -----
        # BM25Okapi 内部做的事：
        # 1. 对每篇文档建词频表 (TF)
        # 2. 对每个词算 IDF = log[(N - df + 0.5) / (df + 0.5) + 1]
        #    - N = 文档总数
        #    - df = 出现该词的文档数
        #    - 加 0.5 是平滑项，防止除零
        # 3. 查询时：切词 → 每个词单独算 BM25 分 → 累加 → 排序
        _bm25_index = BM25Okapi(tokenized)
        _chunks_snapshot = chunks

        logger.info(
            "BM25 索引构建完成: %d 篇文档, 词汇量约 %d",
            len(texts),
            len(_bm25_index.idf),
        )


def keyword_search(query: str, top_k: int = 5) -> list[dict]:
    """
    BM25 关键词检索。

    和 retrieve() (语义向量检索) 互补：
    - 向量检索擅长: "仁是个什么玩意儿" → 能找到"仁"相关的章句（语义相似）
    - BM25 擅长:   "巧言令色" → 精确找到包含这四个字的章句（词匹配）
    - 同一概念的两种表达，分别对应两种检索的优势场景

    Args:
        query: 用户查询文本
        top_k: 返回结果数量

    Returns:
        [{"id": "学而篇_0", "text": "...", "chapter": "...",
          "verse_index": 0, "score": 12.5}, ...]
        score 是 BM25 原始分数，不是 [0,1] 范围。越高越相关。
        这个分数和向量相似度分数不在同一尺度，所以 RRF 融合时用排名不用分数。

    面试时可对比：
    - BM25 优点: 精确匹配、可解释（为什么这篇排前面？因为包含了查询词A和B）
    - BM25 缺点: 不理解同义词（"仁"和"爱人"在 BM25 看来是两个完全不相关的词）
    - 语义检索优点: 理解同义词和语义，但"巧言令色"可能被模糊匹配成"巧言善辩"
    - 结论: 两者互补，混合检索 = 两种检索的召回取并集，再用 RRF 排序
    """
    _build_index()

    if _bm25_index is None or _chunks_snapshot is None:
        return []

    # ----- 分词 -----
    # jieba 精确模式切词。
    #
    # 潜在问题（可以用来面试讲）：
    #   现代汉语词 vs 古汉语词不匹配。例：用户搜"学习"→jieba 切成["学习"]
    #   但论语里"学而时习之"→jieba 切成["学而", "时", "习", "之"]
    #   "学习"这个现代词汇在古文分词语料里根本不存在 → BM25 返回 0 条。
    #
    # 解决方案：短 query（≤4字）额外追加单字作为回退 token。
    #   例："学习" → ["学习", "学", "习"] → 至少"学"字能命中
    #   这本质上是字符级 n-gram 回退，在中文 IR 中是常见做法。
    #   面试时可以对比：Elasticsearch 的 ICU 分词器也有类似的分词链机制。
    import jieba
    tokens = list(jieba.cut(query))

    # 字符级回退：短 query 的 jieba 精确切词可能过于保守
    # （单字词权重本来就低，加进去不会破坏排序，但可以防止彻底漏检）
    if len(query) <= 4:
        for char in query:
            if char.strip() and char not in tokens:
                tokens.append(char)

    # ----- BM25 打分 -----
    # get_scores() 对每篇文档算一个 BM25 分数
    # 内部公式（对每篇文档 D）:
    #   score = 0
    #   for each query_term q_i:
    #     score += IDF(q_i) * [f(q_i,D) * (k1+1)] / [f(q_i,D) + k1*(1-b+b*len(D)/avgdl)]
    # 所有 query_term 的分数累加，总和即该文档和查询的相关度
    scores = _bm25_index.get_scores(tokens)

    # ----- Top-K 选取 -----
    # np.argsort 返回从小到大的排序索引，取最后 top_k 个（最大分数）
    import numpy as np
    top_indices = np.argsort(scores)[-top_k:][::-1]  # [::-1] 倒序 → 从大到小

    results = []
    for idx in top_indices:
        if scores[idx] <= 0:
            continue  # 分数为 0 = 没有任何查询词命中，跳过
        chunk = _chunks_snapshot[idx]
        results.append({
            "id": chunk.id,
            "text": chunk.text,
            "chapter": chunk.chapter,
            "verse_index": chunk.verse_index,
            "score": round(float(scores[idx]), 4),
        })

    logger.debug(
        "BM25 检索完成: query='%s', top_k=%d, 实际返回 %d 条",
        query, top_k, len(results),
    )
    return results
