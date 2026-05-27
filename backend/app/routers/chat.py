import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.models.database import SessionLocal, User
from app.services.auth import get_current_user, get_db
from app.services.agent import run_agent
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
    skill: str | None = Field(default=None, description="Skill名称，如poetry/debate，不传则默认teaching")


class SourceRef(BaseModel):
    chapter: str
    text: str
    score: float


class ChatResponse(BaseModel):
    reply: str
    sources: list[SourceRef] = []
    conversation_id: int
    tool_calls: int = 0


# ============================================================
# 核心端点（JWT 认证 + 对话持久化）
# ============================================================


@router.post("", response_model=ChatResponse)
def chat(
    request: MessageRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """主对话入口（Agent 模式）——LLM 自主决定是否查书、查几次。"""
    from app.utils.rate_limit import check_rate_limit, release_concurrency_slot

    uid = str(user.id)
    check_rate_limit(uid)
    try:
        # 1. 获取或创建对话
        if request.conversation_id:
            conv = get_conversation(db, request.conversation_id, user.id)
        else:
            conv = create_conversation(db, user.id, request.message)

        # 2. 取历史 + 用户画像
        history = get_chat_history(db, conv.id)
        profile_text = _load_profile(user)

        # 3. Agent 循环
        result = run_agent(request.message, history, request.skill, profile_text)

        # 4. 保存消息
        add_messages(db, conv.id, request.message, result["reply"], result.get("sources"))

        # 5. 异步提取用户画像（后台线程，不阻塞响应）
        _extract_profile_async(user, request.message, result["reply"])

        return ChatResponse(
            reply=result["reply"],
            sources=[SourceRef(**s) for s in result.get("sources", [])],
            conversation_id=conv.id,
            tool_calls=result.get("tool_calls", 0),
        )
    finally:
        release_concurrency_slot(uid)


@router.post("/stream")
async def chat_stream(
    request: MessageRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """主对话入口（流式）——SSE 逐 token 推送。"""
    from app.utils.rate_limit import check_rate_limit, release_concurrency_slot

    uid = str(user.id)
    check_rate_limit(uid)
    # 流式端点的并发槽位在 SSE 流结束时释放（sse_with_conv_id 的 finally 中）

    if request.conversation_id:
        conv = get_conversation(db, request.conversation_id, user.id)
    else:
        conv = create_conversation(db, user.id, request.message)

    history = get_chat_history(db, conv.id)

    from app.llm.client import chat_stream
    from app.llm.prompts import get_agent_system_prompt
    from app.skills import get_skill_registry

    async def sse_with_conv_id():
        try:
            yield f"data: [CONV_ID]{conv.id}\n\n"
            registry = get_skill_registry()
            skill = registry.resolve(request.skill)
            sys_prompt = skill.system_prompt if skill else get_agent_system_prompt()
            msgs = [{"role": "system", "content": sys_prompt}]
            msgs.extend(history)
            msgs.append({"role": "user", "content": request.message})
            async for event in _stream_with_save(
                conv.id, request.message,
                _token_to_sse(chat_stream(msgs, temperature=0.8)),
            ):
                yield event
        finally:
            release_concurrency_slot(uid)

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


async def _token_to_sse(token_stream):
    """把 chat_stream 输出的原始 token 转成 SSE 格式"""
    from app.services.chat import _escape_sse as esc
    async for token in token_stream:
        yield f'data: {{"token":"{esc(token)}"}}\n\n'
    yield "data: [DONE]\n\n"


# ============================================================
# 用户画像辅助
# ============================================================

def _load_profile(user) -> str:
    """加载用户的画像并格式化为 Prompt 注入文本"""
    import json
    from app.services.profile import format_profile_for_prompt

    if not user.profile_json:
        return ""
    try:
        profile = json.loads(user.profile_json)
        return format_profile_for_prompt(profile)
    except (json.JSONDecodeError, TypeError):
        return ""


def _extract_profile_async(user, user_message: str, assistant_reply: str):
    """后台线程提取用户画像——不阻塞 HTTP 响应"""
    import json
    import threading

    from app.models.database import SessionLocal
    from app.services.profile import extract_profile, merge_profile

    def _run():
        db = SessionLocal()
        try:
            # 提取本轮对话的画像片段
            fragment = extract_profile(user_message, assistant_reply)
            if not _has_content(fragment):
                return  # 本轮无新信息，跳过

            # 加载现有画像，合并
            existing = None
            if user.profile_json:
                try:
                    existing = json.loads(user.profile_json)
                except (json.JSONDecodeError, TypeError):
                    pass

            merged = merge_profile(existing, fragment)

            # 写回数据库
            u = db.query(User).filter(User.id == user.id).first()
            if u:
                u.profile_json = json.dumps(merged, ensure_ascii=False)
                db.commit()
        except Exception:
            pass  # 画像提取是最低优先级的辅助功能，失败静默
        finally:
            db.close()

    t = threading.Thread(target=_run, daemon=True)
    t.start()


def _has_content(fragment: dict) -> bool:
    """检查画像片段是否有实际内容"""
    if fragment.get("identity", "").strip():
        return True
    if fragment.get("level", "").strip():
        return True
    if fragment.get("context", "").strip():
        return True
    if fragment.get("preferences"):
        return True
    return False
