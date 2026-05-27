"""
Reranker 精排 — Cross-Encoder 两阶段检索的第二阶段

两阶段检索架构（面试核心考点）：
  粗筛（Bi-Encoder）：全库 512 条 → BGE 向量相似度 → Top-20，毫秒级
  精排（Cross-Encoder）：Top-20 → Reranker 逐对打分 → Top-5，百毫秒级

为什么不能全库用 Cross-Encoder？
  - Bi-Encoder：query 和 doc 独立编码，doc 向量可预计算，检索时只算 query 向量
    算一次 (1次编码) → 和预存的 512 个向量做点积 → O(n) 排序
  - Cross-Encoder：query 和 doc 拼一起送入模型，每次都要完整推理
    512 条 → 512 次模型推理 → ~30 秒（不可接受）
  - 所以 bi-encoder 粗筛，cross-encoder 精排，两阶段互补

Bi-Encoder vs Cross-Encoder 对比（面试必答）：
  |              | Bi-Encoder (Embedding)    | Cross-Encoder (Reranker)     |
  |--------------|--------------------------|------------------------------|
  | 输入         | query 或 doc 各自独立      | [query, doc] 拼接            |
  | 输出         | 各一个向量，算余弦相似度    | 直接输出相关性分数 (0~1)      |
  | 注意力       | query 和 doc 永不见面       | query 和 doc 在 Transformer 里互相看 |
  | 速度         | 极快（可预计算）            | 慢（每次都要完整推理）        |
  | 精度         | 中等                       | 高                           |
  | 角色         | 粗筛（召回 Top-20）         | 精排（精选 Top-5）            |

选型分析：
  - 本地：BAAI/bge-reranker-v2-m3，和 BGE Embedding 同家族，中文 C-MTEB 榜单 Top-3
  - API：阿里云 gte-rerank / Cohere rerank-multilingual-v3
  - 本项目用本地 CrossEncoder：零成本，架构统一，易于面试讲清楚两阶段原理
  - 未来换 API：继承 BaseReranker 重写 rerank() 即可
"""

import logging
import threading
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

# BGE-Reranker 模型标识
# v2-m3 是多语言版本，中文效果最优
# base 版本（~1.1GB，更快但精度略低）作为备选
MODEL_NAME = "BAAI/bge-reranker-v2-m3"

# Cross-Encoder 模型的最大输入长度
# 超过 512 token 的文本会被截断，但论语章句通常 <100 token，不会触发
MAX_LENGTH = 512

# ---------------------------------------------------------------------------
# 抽象基类 — 方便未来切换 API 版 reranker
# ---------------------------------------------------------------------------


class BaseReranker(ABC):
    """Reranker 接口抽象。

    子类只需要实现 _compute_scores(query, texts) → list[float]，
    基类的 rerank() 方法负责：构造输入对 → 调子类打分 → 排序 → 返回 Top-K。

    换阿里云 API 时：
      class AliyunReranker(BaseReranker):
          def _compute_scores(self, query, texts):
              # dashscope 调用，返回 scores
              ...
    """

    @abstractmethod
    def _compute_scores(self, query: str, texts: list[str]) -> list[float]:
        """子类实现：给 query 和 texts 逐对打分。

        Args:
            query: 用户查询
            texts: 候选文档文本列表

        Returns:
            和 texts 等长的分数列表，每个分数在 [0, 1] 范围
        """
        ...

    def rerank(
        self,
        query: str,
        candidates: list[dict],
        top_k: int = 5,
    ) -> list[dict]:
        """精排入口：粗筛结果 → Cross-Encoder 逐对打分 → 精选 Top-K。

        输入 candidates 来自 RRF 融合结果或向量检索结果，格式：
          [{"text": "...", "chapter": "...", "score": 0.85, ...}, ...]

        score 字段会被覆写为 reranker 分数（0~1），用于最终排序。

        Args:
            query: 用户查询
            candidates: 粗筛阶段返回的候选文档列表（通常 Top-20）
            top_k: 精排后返回的数量（通常 Top-5）

        Returns:
            按 reranker 分数降序排列的 Top-K 结果
        """
        if not candidates:
            return []

        texts = [c["text"] for c in candidates]

        # 调子类的打分方法
        scores = self._compute_scores(query, texts)

        # 覆写 score 字段为 reranker 分数
        for i, s in enumerate(scores):
            candidates[i]["score"] = round(float(s), 6)

        # 按 reranker 分降序、取 Top-K
        reranked = sorted(candidates, key=lambda c: c["score"], reverse=True)

        logger.debug(
            "Rerank 完成: query 长度=%d, %d 候选 → Top-%d",
            len(query), len(candidates), min(top_k, len(reranked)),
        )
        return reranked[:top_k]


# ---------------------------------------------------------------------------
# 本地 BGE-Reranker 实现
# ---------------------------------------------------------------------------

# 全局单例 — 和 embedder.py 中 BGE Embedding 模型同理
# CrossEncoder 对象 ~2.2GB，懒加载 + 双重检查锁
_reranker_model = None
_lock = threading.Lock()


def _get_model():
    """懒加载 BGE CrossEncoder 模型。

    CrossEncoder 和 SentenceTransformer (Bi-Encoder) 的区别：
    - SentenceTransformer.encode(text) → 1024维向量
    - CrossEncoder.predict([(query, doc)]) → 一个浮点数分数
    两者都在 sentence_transformers 包内，只是用途不同。
    """
    global _reranker_model
    if _reranker_model is not None:
        return _reranker_model

    with _lock:
        if _reranker_model is not None:
            return _reranker_model

        from app.config import settings

        # 和 embedder.py 同一流程：检查本地缓存 → 没有就从 ModelScope 下载
        model_path = _find_or_download_model(settings.model_cache_dir)

        from sentence_transformers import CrossEncoder
        _reranker_model = CrossEncoder(
            model_path,
            max_length=MAX_LENGTH,
        )
        logger.info("Reranker 模型加载完成: %s", model_path)

    return _reranker_model


def _find_or_download_model(cache_dir: str) -> str:
    """找到本地模型路径，本地没有就从 ModelScope 下载"""
    import os
    expected_path = os.path.join(cache_dir, MODEL_NAME)

    if os.path.isdir(expected_path):
        return expected_path

    from modelscope import snapshot_download
    logger.info("Reranker 模型未缓存，从 ModelScope 下载到 %s ...", expected_path)
    return snapshot_download(MODEL_NAME, cache_dir=cache_dir)


class LocalReranker(BaseReranker):
    """BGE-Reranker-v2-m3 本地 Cross-Encoder 实现。

    跨语言模型，输入格式: query + passage 拼接，输出一个分数。

    分数含义：
      - > 0.5: 文档和查询相关
      - < 0.3: 基本不相关
      - sigmoid 之后的原始分数，不是严格的概率值，但在同一次查询内可比
    """

    def _compute_scores(self, query: str, texts: list[str]) -> list[float]:
        model = _get_model()

        # CrossEncoder.predict() 的输入格式：[(query, doc1), (query, doc2), ...]
        # 内部会做 tokenize → 拼成 [CLS] query [SEP] doc [SEP] → forward → logit → sigmoid
        pairs = [[query, text] for text in texts]
        scores = model.predict(pairs)

        # predict 返回 numpy array 或 list
        # 确保转为 float 列表
        if hasattr(scores, 'tolist'):
            return scores.tolist()
        return list(scores)


# ---------------------------------------------------------------------------
# 便捷函数 — 和 retriever.retrieve() 风格一致
# ---------------------------------------------------------------------------

# 全局单例
_reranker: LocalReranker | None = None


def get_reranker() -> LocalReranker:
    """获取 reranker 单例"""
    global _reranker
    if _reranker is None:
        _reranker = LocalReranker()
    return _reranker


def rerank(query: str, candidates: list[dict], top_k: int = 5) -> list[dict]:
    """精排便捷函数：粗筛结果 → Reranker 精排 → Top-K。

    典型调用链：
      # 粗筛
      vec = retrieve(query, top_k=10)
      bm25 = keyword_search(query, top_k=10)
      # 融合
      candidates = rrf_fusion(vec, bm25, top_k=20)
      # 精排
      final = rerank(query, candidates, top_k=5)

    Args:
        query: 用户查询
        candidates: 粗筛/融合后的候选列表
        top_k: 精排返回数量

    Returns:
        精排后的 Top-K，score 字段为 reranker 分数
    """
    return get_reranker().rerank(query, candidates, top_k)
