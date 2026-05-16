import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.models.database import SessionLocal, User
from app.services.auth import get_current_user, get_db
from app.services.chat import (
    generate_smart_reply,
    generate_smart_reply_stream,
    generate_smart_reply_stream_with_history,
    generate_smart_reply_with_history,
)
from app.services.conversation import (
    add_messages,
    create_conversation,
    get_chat_history,
    get_conversation,
    get_conversations,
    delete_conversation,
)

router = APIRouter(prefix="/api/chat", tags=["chat"])


# ============================================================
# Pydantic 模型
# ============================================================

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)


class MessageRequest(ChatRequest):
    conversation_id: int | None = Field(default=None, description="对话ID，不传则新建对话")


class SourceRef(BaseModel):
    chapter: str
    text: str
    score: float


class ChatResponse(BaseModel):
    reply: str
    sources: list[SourceRef] = []
    intent: str = ""
    conversation_id: int


# ============================================================
# 核心端点（JWT 认证 + 对话持久化）
# ============================================================


@router.post("", response_model=ChatResponse)
def chat(
    request: MessageRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """主对话入口——自动判断意图、管理对话历史、保存消息。

    不传 conversation_id 则新建对话，传入则追加到已有对话。
    """
    # 1. 获取或创建对话
    if request.conversation_id:
        conv = get_conversation(db, request.conversation_id, user.id)
    else:
        conv = create_conversation(db, user.id, request.message)

    # 2. 取历史
    history = get_chat_history(db, conv.id)

    # 3. 判断意图 + 生成
    result = generate_smart_reply_with_history(request.message, history)

    # 4. 保存消息
    add_messages(db, conv.id, request.message, result["reply"], result.get("sources"))

    return ChatResponse(
        reply=result["reply"],
        sources=[SourceRef(**s) for s in result.get("sources", [])],
        intent=result.get("intent", ""),
        conversation_id=conv.id,
    )


@router.post("/stream")
async def chat_stream(
    request: MessageRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """主对话入口（流式）——SSE 逐 token 推送。"""
    if request.conversation_id:
        conv = get_conversation(db, request.conversation_id, user.id)
    else:
        conv = create_conversation(db, user.id, request.message)

    history = get_chat_history(db, conv.id)

    async def sse_with_conv_id():
        yield f"data: [CONV_ID]{conv.id}\n\n"
        async for event in _stream_with_save(
            conv.id, request.message,
            generate_smart_reply_stream_with_history(request.message, history),
        ):
            yield event

    return StreamingResponse(
        sse_with_conv_id(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )


# ============================================================
# 对话管理端点
# ============================================================


class ConvItem(BaseModel):
    id: int
    title: str
    created_at: str
    updated_at: str


class ConvDetail(BaseModel):
    id: int
    title: str
    messages: list[dict]


@router.get("/conversations", response_model=list[ConvItem])
def list_conversations(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取当前用户的所有对话列表。"""
    convs = get_conversations(db, user.id)
    return [
        ConvItem(
            id=c.id,
            title=c.title,
            created_at=c.created_at.isoformat(),
            updated_at=c.updated_at.isoformat(),
        )
        for c in convs
    ]


@router.get("/conversations/{conv_id}", response_model=ConvDetail)
def get_conversation_detail(
    conv_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取一条对话的全部消息。"""
    from app.services.conversation import get_conversation
    conv = get_conversation(db, conv_id, user.id)
    return ConvDetail(
        id=conv.id,
        title=conv.title,
        messages=[
            {"role": m.role, "content": m.content, "created_at": m.created_at.isoformat()}
            for m in conv.messages
        ],
    )


@router.delete("/conversations/{conv_id}", status_code=204)
def remove_conversation(
    conv_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """删除一条对话及其所有消息。"""
    delete_conversation(db, conv_id, user.id)


# 公开端点已移除——所有对话端点均需 JWT 认证


# ============================================================
# 流式辅助
# ============================================================

async def _stream_with_save(conv_id, user_msg, stream_generator):
    """流式输出收集器：逐 token 推流的同时缓存完整回复，最后存 DB。

    自己管理 DB session 生命周期——不用 Depends 注入的，因为路由函数返回
    StreamingResponse 后 FastAPI 会立刻关闭注入的 session，但生成器还在跑。
    """
    full_reply = ""
    sources = None

    async for event in stream_generator:
        yield event
        if event.startswith("data: [SOURCES]"):
            try:
                sources = json.loads(event[len("data: [SOURCES]"):])
            except json.JSONDecodeError:
                pass
        elif event.startswith("data: ") and not event.startswith("data: [DONE]"):
            payload = event[6:]
            if payload.startswith('{"token":'):
                try:
                    full_reply += json.loads(payload)["token"]
                except json.JSONDecodeError:
                    pass

    # 流结束后，用自己的 session 保存消息
    if full_reply or sources:
        db = SessionLocal()
        try:
            add_messages(db, conv_id, user_msg, full_reply, sources)
        finally:
            db.close()
