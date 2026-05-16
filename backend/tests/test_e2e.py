"""端到端流程测试 — 模拟真实用户操作链路

使用 TestClient 模拟完整用户旅程，从注册到多轮对话到历史查看
"""

from unittest.mock import patch

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


# ============================================================
# 用户生命周期
# ============================================================

def test_full_auth_lifecycle(client: TestClient):
    """完整认证生命周期：注册 → 登录 → 查看个人信息 → 错误密码"""
    # 注册
    r = client.post("/api/auth/register", json={
        "username": "lifecycle", "password": "pass1234",
    })
    assert r.status_code == 201
    assert r.json()["username"] == "lifecycle"

    # 登录
    r = client.post("/api/auth/login", json={
        "username": "lifecycle", "password": "pass1234",
    })
    assert r.status_code == 200
    token = r.json()["access_token"]
    assert token

    # 查看个人信息
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["username"] == "lifecycle"

    # 错误密码被拒
    r = client.post("/api/auth/login", json={
        "username": "lifecycle", "password": "wrongpass",
    })
    assert r.status_code == 401


# ============================================================
# 对话生命周期
# ============================================================

def test_conversation_lifecycle(client: TestClient):
    """对话 CRUD 完整链路"""
    token = register_and_login(client, "convuser")

    mock_reply = "论语有云：学而时习之..."
    mock_results = [
        {"chapter": "学而篇", "verse_index": 0, "text": "子曰：学而时习之", "score": 0.9},
    ]

    with (
        patch("app.services.chat.llm_chat", return_value=mock_reply),
        patch("app.services.chat.classify_intent", return_value="求教"),
        patch("app.services.chat.retrieve", return_value=mock_results),
    ):
        # 创建对话
        r = client.post("/api/chat", json={"message": "什么是学？"}, headers={
            "Authorization": f"Bearer {token}",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["conversation_id"] == 1
        assert "学" in data["reply"]
        assert data["intent"] == "求教"

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
    assert convs[0]["id"] == 1
    assert "学" in convs[0]["title"]

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
# 多用户隔离
# ============================================================

def test_multi_user_isolation(client: TestClient):
    """两个用户的对话互相隔离"""
    token_a = register_and_login(client, "user_a")
    token_b = register_and_login(client, "user_b")

    mock_reply = "善。"
    with (
        patch("app.services.chat.llm_chat", return_value=mock_reply),
        patch("app.services.chat.classify_intent", return_value="闲聊"),
    ):
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

    # B 不能访问 A 的对话
    r = client.get("/api/chat/conversations/1", headers={
        "Authorization": f"Bearer {token_b}",
    })
    assert r.status_code == 403

    # A 不能删除 B 的对话
    r = client.delete("/api/chat/conversations/2", headers={
        "Authorization": f"Bearer {token_a}",
    })
    assert r.status_code == 403

    # A 看到自己的对话
    r = client.get("/api/chat/conversations", headers={
        "Authorization": f"Bearer {token_a}",
    })
    assert len(r.json()) == 1


# ============================================================
# 意图路由 E2E
# ============================================================

def test_smart_routing_chat_to_rag(client: TestClient):
    """同一用户：闲聊→闲聊，求教→RAG"""
    token = register_and_login(client, "router_user")

    with patch("app.services.chat.llm_chat") as mock_llm:
        # 场景1：闲聊
        mock_llm.return_value = "闲聊回复"
        with patch("app.services.chat.classify_intent", return_value="闲聊"):
            r = client.post("/api/chat", json={"message": "你好孔子"}, headers={
                "Authorization": f"Bearer {token}",
            })
            assert r.json()["intent"] == "闲聊"
            assert len(r.json()["sources"]) == 0

        # 场景2：求教
        mock_llm.return_value = "引经据典回复"
        mock_results = [{"chapter": "学而篇", "verse_index": 0, "text": "...", "score": 0.9}]
        with (
            patch("app.services.chat.classify_intent", return_value="求教"),
            patch("app.services.chat.retrieve", return_value=mock_results),
        ):
            r = client.post("/api/chat", json={"message": "什么是仁？"}, headers={
                "Authorization": f"Bearer {token}",
            })
            assert r.json()["intent"] == "求教"
            assert len(r.json()["sources"]) == 1


# ============================================================
# 公开端点 vs 认证端点
# ============================================================

def test_all_endpoints_require_auth(client: TestClient):
    """全部对话端点需认证"""
    r = client.post("/api/chat", json={"message": "你好"})
    assert r.status_code == 403

    r = client.post("/api/chat/stream", json={"message": "你好"})
    assert r.status_code == 403

    r = client.get("/api/chat/conversations")
    assert r.status_code == 403

    # 对话列表需认证
    r = client.get("/api/chat/conversations")
    assert r.status_code == 403


# ============================================================
# 边界：对话归属校验
# ============================================================

def test_stream_endpoint_returns_sse(client: TestClient):
    """流式端点——返回 text/event-stream 且含逐 token 内容"""
    token = register_and_login(client, "streamuser")

    async def mock_stream(*args, **kwargs):
        for t in ["学", "而"]:
            yield t

    with (
        patch("app.services.chat.llm_chat_stream", side_effect=mock_stream),
        patch("app.services.chat.classify_intent", return_value="闲聊"),
    ):
        resp = client.post("/api/chat/stream", json={"message": "你好"}, headers={
            "Authorization": f"Bearer {token}",
        })
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")


def test_nonexistent_conversation(client: TestClient):
    """访问不存在的对话 → 404"""
    token = register_and_login(client, "nocnouser")
    r = client.get("/api/chat/conversations/9999", headers={
        "Authorization": f"Bearer {token}",
    })
    assert r.status_code == 404
