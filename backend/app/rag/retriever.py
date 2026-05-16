def retrieve(query: str, top_k: int = 5) -> list[dict]:
    """根据用户查询从论语知识库中检索最相关的章句。"""
    from app.rag.builder import get_collection
    from app.rag.embedder import embed

    Returns:
        [{"text": "原文...", "chapter": "篇名", "verse_index": 序号, "score": 相似度分数}, ...]
    """
    collection = get_collection()
    results = collection.query(query_embeddings=embed([query]), n_results=top_k)

    items = []
    if not results["ids"] or not results["ids"][0]:
        return items

    for i, doc_id in enumerate(results["ids"][0]):
        metadata = results["metadatas"][0][i] or {}
        distance = results["distances"][0][i] if results["distances"] else 0
        # ChromaDB 返回欧氏距离，转成相似度分数（越小越相似 → 越大越相似）
        score = round(1 / (1 + distance), 4)
        items.append({
            "id": doc_id,
            "text": results["documents"][0][i],
            "chapter": metadata.get("chapter", ""),
            "verse_index": metadata.get("verse_index", 0),
            "score": score,
        })
    return items
