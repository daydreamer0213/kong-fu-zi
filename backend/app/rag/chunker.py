import json
from pathlib import Path
from typing import Iterator


class Chunk:
    """一个论语知识块"""

    def __init__(self, chunk_id: str, text: str, chapter: str, verse_index: int):
        self.id = chunk_id            # 如 "学而第一_0"
        self.text = text              # 原文
        self.chapter = chapter        # 篇名
        self.verse_index = verse_index  # 篇内序号


def load_and_chunk(json_path: str) -> list[Chunk]:
    """从 lunyu.json 加载并按章分块。

    每章为一个 chunk，保留篇名和序号。
    """
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    chunks: list[Chunk] = []
    for chapter_data in data:
        chapter = chapter_data["chapter"]
        for idx, text in enumerate(chapter_data["paragraphs"]):
            chunk_id = f"{chapter}_{idx}"
            chunks.append(Chunk(
                chunk_id=chunk_id,
                text=text,
                chapter=chapter,
                verse_index=idx,
            ))
    return chunks
