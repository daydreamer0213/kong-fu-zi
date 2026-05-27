"""
对话摘要 — 滑动窗口上下文管理

上下文窗口策略（面试可讲）：
  最近 5 轮 → 保留完整原文（用户能感知的短期记忆）
  5 轮以上 → LLM 压缩为摘要（保留脉络，省 token）
  摘要限制 300 字 ≈ 200 tokens，不到一轮完整对话的 10%

和截断方案的对比：
  截断（之前）：超过 10 轮直接丢弃 → 丢失上下文，用户感觉"助手失忆了"
  摘要（现在）：超过 5 轮压缩保留 → "助手记得之前聊过大方向，但忘了细节"
  用户感知：后者明显更智能

增量摘要策略：
  每次新消息触发检查 → 如果总轮数 > 5 → 把最早的溢出轮数摘要化
  → 合并到已有摘要 → 存回 Conversation.summary
  → 下次 get_chat_history 时自动注入到消息列表最前面
"""

import logging

from sqlalchemy.orm import Session

from app.models.database import Conversation, Message

logger = logging.getLogger(__name__)

# 保留完整原文的轮数
MAX_FULL_ROUNDS = 5  # 10 条消息

# 摘要长度上限（字符数）
MAX_SUMMARY_CHARS = 300


def maybe_summarize(db: Session, conversation_id: int):
    """如果对话轮数超出限制，对溢出部分做增量摘要。

    在 add_messages() 之后调用——每次新增一轮对话后检查。
    只在确实需要时调 LLM（轻量级，额外开销 ~200ms）。
    """
    # 统计总轮数（user 消息数 = 对话轮数）
    total_rounds = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id, Message.role == "user")
        .count()
    )

    if total_rounds <= MAX_FULL_ROUNDS:
        return  # 还不够 5 轮，不需要摘要

    # 取出超出 5 轮的那部分消息（最早的溢出轮）
    overflow_count = (total_rounds - MAX_FULL_ROUNDS) * 2  # 每轮 2 条（user+assistant）
    overflow_messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
        .limit(overflow_count)
        .all()
    )

    if not overflow_messages:
        return

    # 格式化为文本
    new_content = _format_messages(overflow_messages)
    existing_summary = _get_existing_summary(db, conversation_id)

    # 调 LLM 生成/更新摘要
    summary = _generate_summary(new_content, existing_summary)

    # 存回数据库
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if conv:
        conv.summary = summary[:MAX_SUMMARY_CHARS]
        db.commit()
        logger.debug("对话 %d 摘要已更新 (%d 字)", conversation_id, len(summary))


def inject_summary(messages: list[dict], db: Session, conversation_id: int) -> list[dict]:
    """在消息列表前插入摘要（作为 system 消息）。

    由 get_chat_history() 调用——在返回给 LLM 的消息列表前注入。
    """
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv or not conv.summary:
        return messages

    summary_msg = {
        "role": "system",
        "content": f"[前情提要] {conv.summary}",
    }
    return [summary_msg] + messages


# ---------------------------------------------------------------------------
# 内部
# ---------------------------------------------------------------------------

_SUMMARIZE_PROMPT = """将以下对话内容合并为一段简洁的摘要（不超过300字）。

如果已有旧摘要：将旧摘要和新内容整合，保持连贯。
如果没有旧摘要：从对话中提取关键讨论点。

只记录实质讨论内容——跳过寒暄、跳过纯问候、跳过无信息量的对话。
用第三人称叙述，如"用户询问了..."、"助手解释了..."。

旧摘要：{existing}

新对话：
{new_messages}

摘要："""


def _generate_summary(new_content: str, existing: str) -> str:
    """调 LLM 生成/更新摘要"""
    prompt = _SUMMARIZE_PROMPT.replace("{existing}", existing or "（无）")
    prompt = prompt.replace("{new_messages}", new_content[:2000])  # 截断过长输入

    try:
        from app.llm.client import chat
        return chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=300,
        ).strip()
    except Exception:
        logger.exception("摘要生成失败")
        return existing or ""  # 失败不丢旧摘要


def _format_messages(messages: list[Message]) -> str:
    """把消息列表格式化为纯文本"""
    lines = []
    for m in messages:
        role = "用户" if m.role == "user" else "助手"
        content = (m.content or "")[:300]  # 每条截断
        lines.append(f"{role}：{content}")
    return "\n".join(lines)


def _get_existing_summary(db: Session, conversation_id: int) -> str:
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    return conv.summary if conv and conv.summary else ""
