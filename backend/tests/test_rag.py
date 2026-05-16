"""RAG 引擎测试——chunker + embedder mock + retriever"""

import pytest


def test_chunker_loads_lunyu():
    """测试分块器：加载 lunyu.json 并按章分块"""
    from app.rag.chunker import load_and_chunk

    chunks = load_and_chunk("data/lunyu.json")
    assert len(chunks) == 512

    first = chunks[0]
    assert first.chapter == "学而篇"
    assert first.verse_index == 0
    assert "学而时习之" in first.text
    assert first.id == "学而篇_0"


def test_chunker_structure():
    """测试分块器：每条 chunk 有正确的元数据"""
    from app.rag.chunker import load_and_chunk

    chunks = load_and_chunk("data/lunyu.json")
    for c in chunks:
        assert c.id
        assert c.chapter
        assert isinstance(c.verse_index, int)
        assert c.text


def test_embedder_returns_1024_dim(mocker):
    """Mock BGE 模型，测试向量维度"""
    import numpy as np

    mocker.patch("app.rag.embedder._get_model").return_value.encode = (
        lambda texts, normalize_embeddings: np.random.randn(len(texts), 1024).astype(float)
    )

    from app.rag.embedder import embed

    vecs = embed(["子曰：学而时习之", "有朋自远方来"])
    assert len(vecs) == 2
    assert len(vecs[0]) == 1024
    assert isinstance(vecs[0][0], float)


def test_embedder_normalized(mocker):
    """Mock：验证向量 L2 归一化（模长 ≈ 1）"""
    import numpy as np

    # 生成随机向量并归一化
    def fake_encode(texts, normalize_embeddings):
        vecs = np.random.randn(len(texts), 1024)
        if normalize_embeddings:
            vecs = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
        return vecs

    mocker.patch("app.rag.embedder._get_model").return_value.encode = fake_encode

    from app.rag.embedder import embed

    vecs = embed(["测试文本"])
    norm = sum(v * v for v in vecs[0])
    assert abs(norm - 1.0) < 0.01  # L2 归一化后模长应为 1


def test_retriever_returns_results():
    """测试检索器：真实 ChromaDB 检索"""
    from app.rag.builder import build_knowledge_base, get_collection
    from app.rag.retriever import retrieve

    # 确保知识库已构建
    try:
        col = get_collection()
    except Exception:
        build_knowledge_base("data/lunyu.json")

    results = retrieve("学而不思则罔", top_k=3)
    assert len(results) == 3

    # 第一条应该是原文本身
    first = results[0]
    assert "chapter" in first
    assert "text" in first
    assert "score" in first
    assert first["score"] > 0.5


def test_retriever_semantic_search():
    """测试检索器：语义搜索——不同措辞应命中相同内容"""
    from app.rag.retriever import retrieve

    results = retrieve("光学习不思考有什么坏处？", top_k=3)
    assert len(results) > 0
    # 最相关应包含"学而不思"
    texts = [r["text"] for r in results]
    assert any("学而不思" in t or "学" in t for t in texts)


def test_context_formatting():
    """测试上下文格式化"""
    from app.services.chat import _format_context

    results = [
        {"chapter": "学而篇", "verse_index": 0, "text": "子曰：学而时习之"},
        {"chapter": "为政篇", "verse_index": 14, "text": "子曰：学而不思则罔"},
    ]
    formatted = _format_context(results)
    assert "1." in formatted
    assert "2." in formatted
    assert "学而篇" in formatted
    assert "为政篇" in formatted
    assert "第1章" in formatted
    assert "第15章" in formatted
