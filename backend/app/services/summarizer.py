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

    增量策略（避免重复摘要）：
      第6轮后：溢出=第1轮 → 生成摘要S1
      第7轮后：溢出=第1-2轮 → 只取"新增溢出"=第2轮 → 把S1当旧摘要，合并S1+第2轮→S2
      第8轮后：溢出=第1-3轮 → 只取"新增溢出"=第3轮 → 合并S2+第3轮→S3

    这样每次只处理新增的溢出轮数（通常2条消息），旧内容已在摘要中。
    """
    total_rounds = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id, Message.role == "user")
        .count()
    )

    if total_rounds <= MAX_FULL_ROUNDS:
        return

    existing_summary = _get_existing_summary(db, conversation_id)

    # 取全部消息（按时间正序）
    all_messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
        .all()
    )

    total_overflow = (total_rounds - MAX_FULL_ROUNDS) * 2  # 当前总共溢出多少条

    # 如果有旧摘要，只取"新溢出"的消息——旧溢出已经包含在旧摘要里了
    if existing_summary:
        # 上一次的溢出量 = 总溢出 - 本轮新增的2条
        prev_overflow = total_overflow - 2
        if prev_overflow > 0:
            new_overflow_msgs = all_messages[prev_overflow:total_overflow]
        else:
            new_overflow_msgs = all_messages[:total_overflow]
    else:
        # 第一次生成摘要，取全部溢出
        new_overflow_msgs = all_messages[:total_overflow]

    if not new_overflow_msgs:
        return

    new_content = _format_messages(new_overflow_msgs)

    # 调 LLM 合并：旧摘要 + 新溢出 → 更新后的摘要
    summary = _generate_summary(new_content, existing_summary)

    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if conv:
        conv.summary = summary[:MAX_SUMMARY_CHARS]
        db.commit()
        logger.debug(
            "对话 %d 摘要已更新: +%d条消息 → %d字",
            conversation_id, len(new_overflow_msgs), len(summary),
        )


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

## 内容取舍优先级（字数紧张时按此顺序丢弃）：
1. 保留：用户明确表达的观点偏好、身份信息、持续关注的主题
2. 保留：助手引用的核心论语章句和关键论述
3. 可丢弃：一般性问答的具体措辞（只留结论，不引原文）
4. 可丢弃：寒暄、问候、过渡性对话
5. 优先丢弃：最早讨论的内容——越久远的越先被精简

只记录实质讨论内容。用第三人称叙述，如"用户询问了..."、"助手解释了..."。

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
