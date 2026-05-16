"""Mock 测试——patch service 层的 LLM 函数引用"""

import asyncio
from unittest.mock import patch


def test_classify_intent_qiujiao():
    with patch("app.services.chat.llm_chat", return_value="求教"):
        from app.services.chat import classify_intent
        assert classify_intent("什么是仁？") == "求教"


def test_classify_intent_chat():
    with patch("app.services.chat.llm_chat", return_value="闲聊"):
        from app.services.chat import classify_intent
        assert classify_intent("你好啊") == "闲聊"


def test_generate_reply_mocked():
    with patch("app.services.chat.llm_chat") as mock:
        mock.return_value = "善哉！子来问吾。"

        from app.services.chat import generate_reply
        reply = generate_reply("你好")
        assert reply == "善哉！子来问吾。"

        messages = mock.call_args[0][0]
        assert messages[0]["role"] == "system"
        assert "孔子" in messages[0]["content"]
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "你好"


def test_generate_reply_with_history():
    with patch("app.services.chat.llm_chat") as mock:
        mock.return_value = "然也。"

        history = [
            {"role": "user", "content": "什么是仁？"},
            {"role": "assistant", "content": "仁者，爱人也。"},
        ]

        from app.services.chat import generate_reply
        reply = generate_reply("能举例吗？", history=history)
        assert reply == "然也。"

        messages = mock.call_args[0][0]
        assert len(messages) == 4


def test_generate_rag_reply_no_results():
    with (
        patch("app.services.chat.llm_chat", return_value="闲聊回复"),
        patch("app.services.chat.retrieve", return_value=[]),
    ):
        from app.services.chat import generate_rag_reply
        result = generate_rag_reply("你好")
        assert result["reply"] == "闲聊回复"
        assert result["sources"] == []


def test_generate_rag_reply_with_sources():
    fake_results = [
        {"chapter": "学而篇", "verse_index": 0, "text": "子曰：学而时习之", "score": 0.8},
        {"chapter": "为政篇", "verse_index": 14, "text": "子曰：学而不思则罔", "score": 0.7},
    ]

    with (
        patch("app.services.chat.llm_chat") as mock,
        patch("app.services.chat.retrieve", return_value=fake_results),
    ):
        mock.return_value = "引用论语的回复"

        from app.services.chat import generate_rag_reply
        result = generate_rag_reply("学而时习之")
        assert len(result["sources"]) == 2

        messages = mock.call_args[0][0]
        last_msg = messages[-1]["content"]
        assert "学而时习之" in last_msg
        assert "学而不思则罔" in last_msg


def test_stream_returns_tokens():
    async def mock_stream(*args, **kwargs):
        for t in ["学", "而", "不", "思"]:
            yield t

    with patch("app.llm.client.chat_stream", side_effect=mock_stream):
        from app.llm.client import chat_stream

        async def collect():
            return [t async for t in chat_stream([{"role": "user", "content": "test"}])]

        tokens = asyncio.run(collect())
        assert tokens == ["学", "而", "不", "思"]


def test_config_loads():
    from app.config import settings
    assert settings.deepseek_base_url == "https://api.deepseek.com"
    assert settings.jwt_expire_minutes > 0


def test_smart_reply_routes_to_chat():
    with (
        patch("app.services.chat.llm_chat", return_value="闲聊"),
        patch("app.services.chat.classify_intent", return_value="闲聊"),
    ):
        from app.services.chat import generate_smart_reply
        result = generate_smart_reply("你好")
        assert result["intent"] == "闲聊"
        assert result["reply"] == "闲聊"


def test_smart_reply_routes_to_rag():
    fake_results = [{"chapter": "学而篇", "verse_index": 0, "text": "...", "score": 0.9}]

    with (
        patch("app.services.chat.llm_chat", return_value="引用论语的回复"),
        patch("app.services.chat.retrieve", return_value=fake_results),
        patch("app.services.chat.classify_intent", return_value="求教"),
    ):
        from app.services.chat import generate_smart_reply
        result = generate_smart_reply("什么是仁？")
        assert result["intent"] == "求教"
        assert len(result["sources"]) == 1
