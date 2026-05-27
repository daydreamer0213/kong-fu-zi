"""RAG 扩展模块单元测试 — keyword_search / fusion / reranker"""
import pytest
from unittest.mock import MagicMock, patch

from app.rag.fusion import rrf_fusion


# ============================================================
# RRF 融合
# ============================================================

class TestRRFFusion:
    def test_merges_two_lists(self):
        a = [
            {"id": "doc1", "text": "text1", "chapter": "c1"},
            {"id": "doc2", "text": "text2", "chapter": "c2"},
        ]
        b = [
            {"id": "doc3", "text": "text3", "chapter": "c3"},
        ]
        result = rrf_fusion(a, b, top_k=5)
        assert len(result) == 3

    def test_dedup_across_lists(self):
        """同一 doc 出现在两路检索中，RRF 应去重"""
        a = [{"id": "shared", "text": "t", "chapter": "c"}]
        b = [{"id": "shared", "text": "t", "chapter": "c"}]
        result = rrf_fusion(a, b, top_k=5)
        assert len(result) == 1

    def test_both_hit_ranks_higher_than_single_hit(self):
        """被两路都命中的文档排名高于只被一路命中的"""
        a = [
            {"id": "both", "text": "t1", "chapter": "c1"},
            {"id": "a_only", "text": "t2", "chapter": "c2"},
        ]
        b = [
            {"id": "b_only", "text": "t3", "chapter": "c3"},
            {"id": "both", "text": "t1", "chapter": "c1"},
        ]
        result = rrf_fusion(a, b, top_k=5)
        # both 应排第一（两路命中）
        assert result[0]["id"] == "both"

    def test_respects_top_k(self):
        a = [{"id": f"doc{i}", "text": f"t{i}", "chapter": "c"} for i in range(10)]
        b = [{"id": f"doc{i}b", "text": f"t{i}", "chapter": "c"} for i in range(10)]
        result = rrf_fusion(a, b, top_k=5)
        assert len(result) == 5

    def test_empty_input(self):
        assert rrf_fusion([], top_k=5) == []

    def test_single_list(self):
        a = [{"id": "d1", "text": "t1", "chapter": "c"}]
        result = rrf_fusion(a, top_k=5)
        assert len(result) == 1
        assert result[0]["id"] == "d1"

    def test_score_is_rrf_value(self):
        """返回的 score 字段应为 RRF 分数，非原始分数"""
        a = [{"id": "x", "text": "t", "chapter": "c", "score": 0.99}]
        result = rrf_fusion(a, top_k=5)
        # RRF 分数远小于 0.99
        assert result[0]["score"] < 0.5

    def test_k_parameter_affects_scores(self):
        """更大的 k 让排名差异更平滑"""
        a = [{"id": f"d{i}", "text": "t", "chapter": "c"} for i in range(3)]
        result_small_k = rrf_fusion(a, k=1, top_k=3)
        result_large_k = rrf_fusion(a, k=100, top_k=3)
        # 两组的 score 应该不同
        assert result_small_k[0]["score"] != result_large_k[0]["score"]


# ============================================================
# BM25 关键词检索
# ============================================================

class TestKeywordSearch:
    def test_returns_correct_format(self):
        """BM25 检索结果格式应和向量检索一致"""
        from app.rag.keyword_search import keyword_search
        results = keyword_search("子曰", top_k=3)
        assert isinstance(results, list)
        if results:
            r = results[0]
            assert "id" in r
            assert "text" in r
            assert "chapter" in r
            assert "score" in r

    def test_returns_empty_for_impossible_query(self):
        from app.rag.keyword_search import keyword_search
        results = keyword_search("zzz_not_in_analects_zzz", top_k=3)
        assert results == []

    def test_results_ordered_by_score(self):
        """分数应降序排列"""
        from app.rag.keyword_search import keyword_search
        results = keyword_search("仁", top_k=5)
        if len(results) >= 2:
            for i in range(len(results) - 1):
                assert results[i]["score"] >= results[i + 1]["score"]


# ============================================================
# Reranker
# ============================================================

class TestReranker:
    def test_base_reranker_interface(self):
        from app.rag.reranker import BaseReranker

        class MockReranker(BaseReranker):
            def _compute_scores(self, query, texts):
                # 简单打分：文本越长分越高（用于测试）
                return [float(len(t)) for t in texts]

        reranker = MockReranker()
        candidates = [
            {"text": "short", "chapter": "c1", "score": 0.9},
            {"text": "much longer text here", "chapter": "c2", "score": 0.5},
        ]
        result = reranker.rerank("query", candidates, top_k=2)
        # "much longer text here" 应排第一（分数更高）
        assert result[0]["text"] == "much longer text here"
        assert result[1]["text"] == "short"

    def test_rerank_respects_top_k(self):
        from app.rag.reranker import BaseReranker

        class MockReranker(BaseReranker):
            def _compute_scores(self, query, texts):
                return list(range(len(texts)))  # 递增分数

        candidates = [{"text": f"t{i}", "chapter": "c", "score": 0} for i in range(10)]
        result = MockReranker().rerank("q", candidates, top_k=3)
        assert len(result) == 3

    def test_get_reranker_returns_singleton(self):
        from app.rag.reranker import get_reranker
        r1 = get_reranker()
        r2 = get_reranker()
        assert r1 is r2
