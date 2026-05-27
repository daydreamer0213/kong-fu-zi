"""
用户记忆 — SQLAlchemy ORM + BGE 向量语义检索

和论语 RAG 的对比（面试可讲）：
  相同：同一套 BGE embedding + 余弦相似度 + Top-K 模式
  不同：论语用 ChromaDB（512条, HNSW索引），记忆用 SQLAlchemy（<50条/用户, Python循环）
  选型逻辑：数据量决定索引策略。"512条杀鸡不用牛刀，50条更不需要"

存储设计：
  MemoryFact 表（database.py ORM 模型）：
    user_id: 所属用户
    fact_text: 用户要求记住的原文
    embedding_json: BGE 1024维向量，存为 JSON 字符串

Profile（用户画像）为什么不用向量检索？
  Profile 是一个用户一份摘要 JSON，不是多条事实。
  使用时直接加载 → 注入 System Prompt，不需要"搜索"。
  和 Memory 的"50条中找最相关的5条"是不同的访问模式。
"""

import json
import logging

from sqlalchemy import func

from app.models.database import MemoryFact, SessionLocal

logger = logging.getLogger(__name__)


def save_fact(user_id: int, fact: str) -> str:
    """存一条记忆：BGE 向量化 → 写 ORM → 返回确认消息"""
    embedding_list = _embed_fact(fact)
    embedding_json = json.dumps(embedding_list) if embedding_list else None

    db = SessionLocal()
    try:
        fact_obj = MemoryFact(
            user_id=user_id,
            fact_text=fact,
            embedding_json=embedding_json,
        )
        db.add(fact_obj)
        db.commit()

        count = db.query(func.count(MemoryFact.id)).filter(
            MemoryFact.user_id == user_id
        ).scalar()
        return f"已记住。子之记忆，吾已存 {count} 则。"
    finally:
        db.close()


def recall_facts(user_id: int, query: str, top_k: int = 5) -> str:
    """语义检索用户记忆：embed query → 和每条记忆向量算余弦相似度 → Top-K"""
    db = SessionLocal()
    try:
        rows = db.query(MemoryFact).filter(
            MemoryFact.user_id == user_id
        ).all()
    finally:
        db.close()

    if not rows:
        return "子尚无记忆留存。若有所嘱，可告吾记之。"

    # ≤3 条直接返回全部，不需要向量检索
    if len(rows) <= 3:
        return "\n".join(f"- {r.fact_text}" for r in rows)

    # 语义检索
    query_emb = _embed_fact(query)
    if not query_emb:
        recent = sorted(rows, key=lambda r: r.id, reverse=True)[:top_k]
        return "\n".join(f"- {r.fact_text}" for r in recent)

    scored = []
    for r in rows:
        if r.embedding_json:
            try:
                emb = json.loads(r.embedding_json)
                sim = _cosine_sim(query_emb, emb)
                scored.append((sim, r.fact_text))
            except (json.JSONDecodeError, ValueError):
                continue

    if not scored:
        return "子之记忆尚在，然未能寻得相关者。"

    scored.sort(key=lambda x: x[0], reverse=True)
    return "\n".join(f"- {text}" for _, text in scored[:top_k])


def get_fact_count(user_id: int) -> int:
    """获取用户记忆总数"""
    db = SessionLocal()
    try:
        return db.query(func.count(MemoryFact.id)).filter(
            MemoryFact.user_id == user_id
        ).scalar()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 内部工具——和 app.rag.embedder 复用同一个 BGE 模型
# ---------------------------------------------------------------------------

def _embed_fact(text: str) -> list[float] | None:
    try:
        from app.rag.embedder import embed
        embeddings = embed([text])
        return embeddings[0] if embeddings else None
    except Exception:
        return None


def _cosine_sim(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
