def retrieve(query: str, top_k: int = 5) -> list[dict]:
    """根据用户查询从论语知识库中检索最相关的章句。

    Returns:
        [{"text": "...", "chapter": "...", "verse_index": 0, "score": 0.9}, ...]
    """
    from app.rag.builder import get_collection
    from app.rag.embedder import embed

    collection = get_collection()
    results = collection.query(query_embeddings=embed([query]), n_results=top_k)

    items = []
    if not results["ids"] or not results["ids"][0]:
        return items

    for i, doc_id in enumerate(results["ids"][0]):
        metadata = results["metadatas"][0][i] or {}
        distance = results["distances"][0][i] if results["distances"] else 0
        score = round(1 / (1 + distance), 4)
        items.append({
            "id": doc_id,
            "text": results["documents"][0][i],
            "chapter": metadata.get("chapter", ""),
            "verse_index": metadata.get("verse_index", 0),
            "score": score,
        })
    return items
