import json

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.database import Conversation, Message

MAX_HISTORY_MESSAGES = 20  # 最近 10 轮对话


def create_conversation(db: Session, user_id: int, first_message: str) -> Conversation:
    """创建新对话，标题取首条消息前 30 字。"""
    title = first_message[:30]
    conv = Conversation(user_id=user_id, title=title)
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


def get_conversations(db: Session, user_id: int) -> list[Conversation]:
    """获取用户的所有对话列表（按更新时间倒序）。"""
    return (
        db.query(Conversation)
        .filter(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc())
        .all()
    )


def get_conversation(db: Session, conversation_id: int, user_id: int) -> Conversation:
    """获取单条对话详情（含所有消息）。仅允许对话所属用户访问。"""
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")
    if conv.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权访问此对话")
    return conv


def delete_conversation(db: Session, conversation_id: int, user_id: int):
    """删除对话（级联删除所有关联消息）。仅允许对话所属用户。"""
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")
    if conv.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权删除此对话")
    db.delete(conv)
    db.commit()


def add_messages(
    db: Session,
    conversation_id: int,
    user_message: str,
    assistant_reply: str,
    sources: list[dict] | None = None,
):
    """保存一轮对话（用户消息 + 助手回复）。"""
    db.add(Message(conversation_id=conversation_id, role="user", content=user_message))
    db.add(Message(
        conversation_id=conversation_id,
        role="assistant",
        content=assistant_reply,
        sources=json.dumps(sources, ensure_ascii=False) if sources else None,
    ))
    # 更新对话的 updated_at
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if conv:
        from datetime import datetime, timezone
        conv.updated_at = datetime.now(timezone.utc)
    db.commit()


def get_chat_history(db: Session, conversation_id: int) -> list[dict]:
    """获取对话历史，返回 LLM 需要的 messages 格式。

    只取最近 MAX_HISTORY_MESSAGES 条（10轮），超出的旧消息不传给 LLM。
    """
    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(MAX_HISTORY_MESSAGES)
        .all()
    )
    messages.reverse()  # 正序
    return [{"role": m.role, "content": m.content} for m in messages]
