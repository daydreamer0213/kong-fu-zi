from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker

from app.config import settings

engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
    profile_json = Column(Text, nullable=True)  # JSON: 用户画像 {"identity":"","preferences":[],...}
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    conversations = relationship("Conversation", back_populates="user")


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String(100), default="新对话")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation",
                            cascade="all,delete", order_by="Message.created_at")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False)
    role = Column(String(10), nullable=False)       # "user" or "assistant"
    content = Column(Text, nullable=False)
    sources = Column(Text, nullable=True)            # JSON string, 仅 assistant 消息有
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    conversation = relationship("Conversation", back_populates="messages")


class MemoryFact(Base):
    """用户长期记忆 — 跨对话持久化的关键事实。

    和 Message 的区别：
      - Message: 对话历史流水，被动记录，对话结束不再主动检索
      - MemoryFact: 用户要求记住的信息，跨对话持久，Agent 通过 recall 主动检索

    向量检索用 BGE embedding + 余弦相似度，不做 ChromaDB 索引（用户记忆 < 50 条）。
    """

    __tablename__ = "memory_facts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    fact_text = Column(Text, nullable=False)
    embedding_json = Column(Text, nullable=True)  # BGE 1024维向量, JSON格式
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


def init_db():
    """创建所有表（如果不存在）。启动时调用一次。"""
    Base.metadata.create_all(bind=engine)
