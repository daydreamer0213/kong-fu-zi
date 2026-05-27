"""端到端流程测试 — Agent 模式"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def register_and_login(client: TestClient, username: str = "e2euser") -> str:
    """辅助：注册并登录，返回 token"""
    client.post("/api/auth/register", json={
        "username": username, "password": "testpass123",
    })
    resp = client.post("/api/auth/login", json={
        "username": username, "password": "testpass123",
    })
    return resp.json()["access_token"]


def _fake_response(content: str, tool_calls=None):
    """构造 OpenAI SDK 风格的响应对象"""
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls  # None 表示"不调工具，直接回答"
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


# ============================================================
# 用户生命周期
# ============================================================

def test_full_auth_lifecycle(client: TestClient):
    """完整认证生命周期：注册 → 登录 → 查看个人信息 → 错误密码"""
    r = client.post("/api/auth/register", json={
        "username": "lifecycle", "password": "pass1234",
    })
    assert r.status_code == 201
    assert r.json()["username"] == "lifecycle"

    r = client.post("/api/auth/login", json={
        "username": "lifecycle", "password": "pass1234",
    })
    assert r.status_code == 200
    token = r.json()["access_token"]
    assert token

    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["username"] == "lifecycle"

    r = client.post("/api/auth/login", json={
        "username": "lifecycle", "password": "wrongpass",
    })
    assert r.status_code == 401


# ============================================================
# 对话生命周期（Agent 模式）
# ============================================================

def test_conversation_lifecycle(client: TestClient):
    """对话 CRUD 完整链路 — Agent 模式"""
    token = register_and_login(client, "convuser")

    mock_reply = "论语有云：学而时习之..."
    mock_results = [
        {"chapter": "学而篇", "verse_index": 0, "text": "子曰：学而时习之", "score": 0.9},
    ]

    with (
        patch("app.services.agent_graph.chat_with_tools",
              return_value=_fake_response(mock_reply, tool_calls=None)),
        patch("app.services.agent_graph.retrieve", return_value=mock_results),
    ):
        # 创建对话
        r = client.post("/api/chat", json={"message": "什么是学？"}, headers={
            "Authorization": f"Bearer {token}",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["conversation_id"] == 1
        assert "学" in data["reply"]
        assert data["tool_calls"] == 0  # 无工具调用，直接回答

        # 追加到同一对话
        r = client.post("/api/chat", json={
            "message": "举个例子",
            "conversation_id": 1,
        }, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json()["conversation_id"] == 1

    # 对话列表
    r = client.get("/api/chat/conversations", headers={
        "Authorization": f"Bearer {token}",
    })
    assert r.status_code == 200
    convs = r.json()
    assert len(convs) == 1

    # 对话详情——应有 4 条消息
    r = client.get("/api/chat/conversations/1", headers={
        "Authorization": f"Bearer {token}",
    })
    assert r.status_code == 200
    detail = r.json()
    assert len(detail["messages"]) == 4
    roles = [m["role"] for m in detail["messages"]]
    assert roles == ["user", "assistant", "user", "assistant"]

    # 删除对话
    r = client.delete("/api/chat/conversations/1", headers={
        "Authorization": f"Bearer {token}",
    })
    assert r.status_code == 204

    # 确认已删除
    r = client.get("/api/chat/conversations", headers={
        "Authorization": f"Bearer {token}",
    })
    assert len(r.json()) == 0


# ============================================================
# Agent 专用测试
# ============================================================

def test_agent_calls_tool_for_knowledge_query(client: TestClient):
    """求教场景——Agent 调了 search_analects"""
    token = register_and_login(client, "agentuser1")

    # 模拟：LLM 第一次调用返回 tool_calls
    tool_call = MagicMock()
    tool_call.id = "call_001"
    tool_call.function.name = "search_analects"
    tool_call.function.arguments = '{"query":"仁"}'

    fake_tool_resp = _fake_response(None, tool_calls=[tool_call])

    # 模拟：LLM 第二次调用（看到工具结果后）直接回复
    fake_final = _fake_response("仁者，爱人也。", tool_calls=None)

    mock_results = [
        {"chapter": "雍也篇", "text": "夫仁者，己欲立而立人...", "score": 0.56},
    ]

    with (
        patch("app.services.agent_graph.chat_with_tools",
              side_effect=[fake_tool_resp, fake_final]) as mock_llm,
        patch("app.services.agent_graph.retrieve", return_value=mock_results),
        patch("app.services.tools.retrieve", return_value=mock_results),
    ):
        r = client.post("/api/chat", json={"message": "什么是仁？"}, headers={
            "Authorization": f"Bearer {token}",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["tool_calls"] >= 1
        assert len(data["sources"]) == 1

        # 验证 LLM 被调了两次（tool_call + final）
        assert mock_llm.call_count == 2


def test_agent_skips_tool_for_casual_chat(client: TestClient):
    """闲聊场景——Agent 不调工具，直接回复"""
    token = register_and_login(client, "agentuser2")

    fake_resp = _fake_response("善哉！来者皆是客。", tool_calls=None)

    with patch("app.services.agent_graph.chat_with_tools", return_value=fake_resp) as mock_llm:
        r = client.post("/api/chat", json={"message": "你好孔子"}, headers={
            "Authorization": f"Bearer {token}",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["tool_calls"] == 0
        assert len(data["sources"]) == 0

        # 只调了一次 LLM（直接回复，无工具循环）
        assert mock_llm.call_count == 1


# ============================================================
# 多用户隔离
# ============================================================

def test_multi_user_isolation(client: TestClient):
    """两个用户的对话互相隔离"""
    token_a = register_and_login(client, "user_a")
    token_b = register_and_login(client, "user_b")

    with patch("app.services.agent_graph.chat_with_tools",
               return_value=_fake_response("善。", tool_calls=None)):
        # A 创建对话
        r = client.post("/api/chat", json={"message": "A 的对话"}, headers={
            "Authorization": f"Bearer {token_a}",
        })
        assert r.json()["conversation_id"] == 1

        # B 创建对话
        r = client.post("/api/chat", json={"message": "B 的对话"}, headers={
            "Authorization": f"Bearer {token_b}",
        })
        assert r.json()["conversation_id"] == 2

    r = client.get("/api/chat/conversations/1", headers={
        "Authorization": f"Bearer {token_b}",
    })
    assert r.status_code == 403

    r = client.delete("/api/chat/conversations/2", headers={
        "Authorization": f"Bearer {token_a}",
    })
    assert r.status_code == 403

    r = client.get("/api/chat/conversations", headers={
        "Authorization": f"Bearer {token_a}",
    })
    assert len(r.json()) == 1


# ============================================================
# 认证
# ============================================================

def test_all_endpoints_require_auth(client: TestClient):
    """全部对话端点需认证"""
    for method, path, body in [
        ("post", "/api/chat", {"message": "你好"}),
        ("post", "/api/chat/stream", {"message": "你好"}),
        ("get", "/api/chat/conversations", None),
    ]:
        if method == "post":
            r = client.post(path, json=body)
        else:
            r = client.get(path)
        assert r.status_code in (401, 403), f"{method} {path} should require auth"


def test_nonexistent_conversation(client: TestClient):
    """访问不存在的对话 → 404"""
    token = register_and_login(client, "nocnouser")
    r = client.get("/api/chat/conversations/9999", headers={
        "Authorization": f"Bearer {token}",
    })
    assert r.status_code == 404
