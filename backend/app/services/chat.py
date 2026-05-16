import json

from app.llm.client import chat as llm_chat, chat_stream as llm_chat_stream
from app.llm.prompts import get_system_prompt, get_rag_prompt
from app.rag.retriever import retrieve

# ============================================================
# 意图分类
# ============================================================

CLASSIFY_PROMPT = """判断用户消息的意图类别。

- 回答"求教"：用户寻求知识解答、人生指导、情感倾诉、两难抉择——任何引用《论语》能增强回答深度的场景
- 回答"闲聊"：纯粹寒暄、说笑、测试、没有实质内容的互动

只回答"求教"或"闲聊"两个字，不要解释。

用户消息：你好啊孔子
类别：闲聊

用户消息：学而时习之是什么意思
类别：求教

用户消息：面试失败了，好迷茫
类别：求教

用户消息：{user_message}
类别："""


def classify_intent(user_message: str) -> str:
    """调用 LLM 判断用户意图：闲聊 or 求教。"""
    reply = llm_chat(
        messages=[{"role": "user", "content": CLASSIFY_PROMPT.replace("{user_message}", user_message)}],
        temperature=0.0,
        max_tokens=4,
    )
    if "求教" in reply:
        return "求教"
    return "闲聊"


# ============================================================
# 基础回复（支持历史）
# ============================================================


def _build_messages(user_message: str, history: list[dict] | None = None) -> list[dict]:
    """组装标准消息列表：[system_prompt] + history + [user_message]"""
    messages = [{"role": "system", "content": get_system_prompt()}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})
    return messages


def generate_reply(user_message: str, history: list[dict] | None = None) -> str:
    """闲聊模式回复（可选历史消息）。"""
    return llm_chat(_build_messages(user_message, history))


def generate_rag_reply(user_message: str, history: list[dict] | None = None) -> dict:
    """RAG 模式回复（可选历史消息）。

    Returns:
        {"reply": "...", "sources": [...]}
    """
    results = retrieve(user_message, top_k=5)
    if not results:
        return {"reply": generate_reply(user_message, history), "sources": []}

    context = _format_context(results)
    rag_prompt = get_rag_prompt(context, user_message)
    # RAG prompt 作为 user 消息，system prompt 独立放前面
    messages = [{"role": "system", "content": get_system_prompt()}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": rag_prompt})

    reply = llm_chat(messages, temperature=0.8)
    sources = [{"chapter": r["chapter"], "text": r["text"], "score": r["score"]} for r in results]
    return {"reply": reply, "sources": sources}


async def generate_reply_stream(user_message: str, history: list[dict] | None = None):
    """流式闲聊。"""
    messages = _build_messages(user_message, history)
    async for token in llm_chat_stream(messages):
        yield f'data: {{"token":"{_escape_sse(token)}"}}\n\n'
    yield "data: [DONE]\n\n"


async def generate_rag_reply_stream(user_message: str, history: list[dict] | None = None):
    """流式 RAG。"""
    results = retrieve(user_message, top_k=5)
    if not results:
        async for event in generate_reply_stream(user_message, history):
            yield event
        return

    context = _format_context(results)
    rag_prompt = get_rag_prompt(context, user_message)
    messages = [{"role": "system", "content": get_system_prompt()}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": rag_prompt})

    async for token in llm_chat_stream(messages, temperature=0.8):
        yield f'data: {{"token":"{_escape_sse(token)}"}}\n\n'

    sources = [{"chapter": r["chapter"], "text": r["text"], "score": r["score"]} for r in results]
    yield f"data: [SOURCES]{json.dumps(sources, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


# ============================================================
# 智能路由（基础版——无状态，保留兼容）
# ============================================================


def generate_smart_reply(user_message: str) -> dict:
    """智能回复（无历史）。"""
    intent = classify_intent(user_message)
    if intent == "求教":
        result = generate_rag_reply(user_message)
        result["intent"] = intent
        return result
    return {"intent": intent, "reply": generate_reply(user_message), "sources": []}


async def generate_smart_reply_stream(user_message: str):
    """智能流式（无历史）。"""
    intent = classify_intent(user_message)
    if intent == "求教":
        async for event in generate_rag_reply_stream(user_message):
            yield event
    else:
        async for event in generate_reply_stream(user_message):
            yield event


# ============================================================
# 智能路由（有状态版——带历史 + 自动存消息）
# ============================================================


def generate_smart_reply_with_history(
    user_message: str,
    history: list[dict],
) -> dict:
    """智能回复（带历史），调此函数前已从 DB 取好 history。"""
    intent = classify_intent(user_message)
    if intent == "求教":
        result = generate_rag_reply(user_message, history)
        result["intent"] = intent
        return result
    return {"intent": intent, "reply": generate_reply(user_message, history), "sources": []}


async def generate_smart_reply_stream_with_history(
    user_message: str,
    history: list[dict],
):
    """智能流式（带历史）。"""
    intent = classify_intent(user_message)
    if intent == "求教":
        async for event in generate_rag_reply_stream(user_message, history):
            yield event
    else:
        async for event in generate_reply_stream(user_message, history):
            yield event


# ============================================================
# 工具函数
# ============================================================


def _format_context(results: list[dict]) -> str:
    lines = []
    for i, r in enumerate(results):
        chapter = r.get("chapter", "未知")
        verse = r.get("verse_index", 0) + 1
        text = r.get("text", "")
        lines.append(f"{i+1}. 《{chapter}》(第{verse}章): {text}")
    return "\n".join(lines)


def _escape_sse(text: str) -> str:
    if not text:
        return ""
    return (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )
