"""
用户记忆 — SQLite 轻量存储 + BGE 向量语义检索

和对话消息的区别：
  - Message: 对话历史流水，被动记录
  - MemoryFact: 用户主动要求记住的关键信息，跨对话持久，主动检索
"""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings


def _get_db_path() -> str:
    """从 database_url 提取 SQLite 文件路径"""
    url = settings.database_url
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "")
    return "./data/kong.db"


def _get_conn() -> sqlite3.Connection:
    db_path = _get_db_path()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_memory_table():
    """确保 memory_facts 表存在"""
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memory_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            fact_text TEXT NOT NULL,
            embedding TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()


def save_fact(user_id: int, fact: str) -> str:
    """存一条记忆，返回确认消息"""
    # 向量化
    embedding_list = _embed_fact(fact)
    embedding_json = json.dumps(embedding_list) if embedding_list else None

    conn = _get_conn()
    conn.execute(
        "INSERT INTO memory_facts (user_id, fact_text, embedding) VALUES (?, ?, ?)",
        (user_id, fact, embedding_json),
    )
    conn.commit()

    # 统计该用户总记忆数
    count = conn.execute(
        "SELECT COUNT(*) FROM memory_facts WHERE user_id = ?", (user_id,)
    ).fetchone()[0]
    conn.close()

    return f"已记住。子之记忆，吾已存 {count} 则。"


def recall_facts(user_id: int, query: str, top_k: int = 5) -> str:
    """语义检索用户记忆，返回格式化的相关记忆文本"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, fact_text, embedding FROM memory_facts WHERE user_id = ?",
        (user_id,),
    ).fetchall()
    conn.close()

    if not rows:
        return "子尚无记忆留存。若有所嘱，可告吾记之。"

    # 如果只有少量记忆，直接返回全部
    if 0 < len(rows) <= 3:
        return "\n".join(f"- {r['fact_text']}" for r in rows)

    # 语义检索：embed query → 和每条记忆的向量算余弦相似度
    query_emb = _embed_fact(query)
    if not query_emb:
        # 没有 embedding（BGE 模型加载失败）→ 返回最近的记忆
        recent = sorted(rows, key=lambda r: r["id"], reverse=True)[:top_k]
        return "\n".join(f"- {r['fact_text']}" for r in recent)

    scored = []
    for r in rows:
        if r["embedding"]:
            try:
                emb = json.loads(r["embedding"])
                sim = _cosine_sim(query_emb, emb)
                scored.append((sim, r["fact_text"]))
            except (json.JSONDecodeError, ValueError):
                continue

    if not scored:
        return "子之记忆尚在，然未能寻得相关者。"

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_k]
    return "\n".join(f"- {text}" for _, text in top)


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------

def _embed_fact(text: str) -> list[float] | None:
    """用 BGE 对事实文本做向量化"""
    try:
        from app.rag.embedder import embed
        embeddings = embed([text])
        return embeddings[0] if embeddings else None
    except Exception:
        return None


def _cosine_sim(a: list[float], b: list[float]) -> float:
    """余弦相似度（向量已 L2 归一化时等价于点积）"""
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    # BGE 输出已归一化，点积即余弦相似度
    # 但为安全起见还是除一下模长
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def get_fact_count(user_id: int) -> int:
    """获取用户记忆总数"""
    conn = _get_conn()
    count = conn.execute(
        "SELECT COUNT(*) FROM memory_facts WHERE user_id = ?", (user_id,)
    ).fetchone()[0]
    conn.close()
    return count
