import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import settings
from app.rag.chunker import load_and_chunk
from app.rag.embedder import embed

COLLECTION_NAME = "analects"


def get_chroma_client() -> chromadb.PersistentClient:
    """获取 ChromaDB 持久化客户端"""
    return chromadb.PersistentClient(
        path=settings.chroma_persist_dir,
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def build_knowledge_base(json_path: str):
    """构建论语知识库：加载 → 分块 → 向量化 → 写入 ChromaDB。

    如果 Collection 已有数据，先清空再重建。
    """
    client = get_chroma_client()

    # 删除旧 Collection（如果存在），新建一个
    try:
        client.delete_collection(COLLECTION_NAME)
    except ValueError:
        pass  # Collection 不存在，正常情况
    collection = client.create_collection(
        name=COLLECTION_NAME,
        metadata={"description": "论语全文向量库，按章分块"}
    )

    # 分块
    chunks = load_and_chunk(json_path)
    texts = [c.text for c in chunks]

    # 向量化
    embeddings = embed(texts)

    # 写入 ChromaDB
    collection.add(
        ids=[c.id for c in chunks],
        documents=texts,
        embeddings=embeddings,
        metadatas=[
            {"chapter": c.chapter, "verse_index": c.verse_index}
            for c in chunks
        ],
    )

    return len(chunks)


def get_collection():
    """获取已构建的 Collection（只读，不重建）"""
    client = get_chroma_client()
    return client.get_collection(COLLECTION_NAME)
