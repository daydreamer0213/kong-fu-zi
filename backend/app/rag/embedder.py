import os

_model = None

MODEL_NAME = "BAAI/bge-large-zh-v1.5"


def _get_model():
    """懒加载 BGE 模型——首次调用时从 ModelScope 下载到 E 盘，之后复用。

    核心流程：
    1. 先检查本地缓存 E:/ai-models/BAAI/bge-large-zh-v1.5 是否存在
    2. 如果有，直接加载本地模型
    3. 如果没有，通过 ModelScope（modelscope.cn，国内直达）下载
    """
    global _model
    if _model is None:
        from app.config import settings

        model_dir = _find_or_download_model(settings.model_cache_dir)

        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(model_dir)
    return _model


def _find_or_download_model(cache_dir: str) -> str:
    """找到本地模型路径，本地没有就从 ModelScope 下载"""
    expected_path = os.path.join(cache_dir, MODEL_NAME)

    if os.path.isdir(expected_path):
        return expected_path

    from modelscope import snapshot_download
    return snapshot_download(MODEL_NAME, cache_dir=cache_dir)


def embed(texts: list[str]) -> list[list[float]]:
    """将文本列表转为向量列表。

    每条文本对应一个 1024 维浮点数向量，已 L2 归一化（适合余弦相似度检索）。
    """
    model = _get_model()
    embeddings = model.encode(texts, normalize_embeddings=True)
    return embeddings.tolist()
