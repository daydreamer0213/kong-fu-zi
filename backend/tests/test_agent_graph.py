"""Agent Graph 单元测试 — 节点逻辑 + 条件路由"""
from unittest.mock import MagicMock, patch


# ============================================================
# _agent_node — LLM 调用节点
# ============================================================

class TestAgentNode:
    def test_no_tool_calls(self):
        """LLM 直接回复（无 tool_calls）→ 返回的新消息列表只含 assistant 消息
        （LangGraph 的 reducer 负责把新消息追加到 state）"""
        from app.services.agent_graph import _agent_node

        msg = MagicMock()
        msg.content = "仁者爱人也"
        msg.tool_calls = None
        choice = MagicMock()
        choice.message = msg
        resp = MagicMock()
        resp.choices = [choice]

        with patch("app.services.agent_graph.chat_with_tools", return_value=resp):
            state = {"messages": [{"role": "user", "content": "什么是仁？"}], "tools": []}
            result = _agent_node(state)
            new_msgs = result["messages"]
            # 节点只返回新消息（reducer 负责追加），应包含 1 条 assistant 消息
            assert len(new_msgs) == 1
            assert new_msgs[0]["role"] == "assistant"
            assert new_msgs[0]["content"] == "仁者爱人也"
            assert "tool_calls" not in new_msgs[0]

    def test_with_tool_calls(self):
        """LLM 要求调工具 → assistant 消息应含 tool_calls"""
        from app.services.agent_graph import _agent_node

        tc = MagicMock()
        tc.id = "call_1"
        tc.function.name = "search_analects"
        tc.function.arguments = '{"query":"仁"}'

        msg = MagicMock()
        msg.content = None
        msg.tool_calls = [tc]
        choice = MagicMock()
        choice.message = msg
        resp = MagicMock()
        resp.choices = [choice]

        with patch("app.services.agent_graph.chat_with_tools", return_value=resp):
            state = {"messages": [{"role": "user", "content": "仁是什么"}], "tools": []}
            result = _agent_node(state)
            new_msgs = result["messages"]
            assert len(new_msgs) == 1
            assert new_msgs[0]["role"] == "assistant"
            assert "tool_calls" in new_msgs[0]
            assert new_msgs[0]["tool_calls"][0]["function"]["name"] == "search_analects"


# ============================================================
# _should_continue — 条件路由
# ============================================================

class TestShouldContinue:
    def test_with_tool_calls_returns_tools(self):
        from app.services.agent_graph import _should_continue
        import time
        state = {
            "messages": [{"role": "assistant", "tool_calls": [{"id": "1"}]}],
            "iteration": 0,
            "start_time": time.time(),
        }
        assert _should_continue(state) == "tools"

    def test_without_tool_calls_returns_end(self):
        from app.services.agent_graph import _should_continue
        import time
        state = {
            "messages": [{"role": "assistant", "content": "答案"}],
            "iteration": 0,
            "start_time": time.time(),
        }
        assert _should_continue(state) == "__end__"

    def test_max_iterations_reached(self):
        from app.services.agent_graph import _should_continue, MAX_ITERATIONS
        import time
        state = {
            "messages": [{"role": "assistant", "tool_calls": [{"id": "1"}]}],
            "iteration": MAX_ITERATIONS,
            "start_time": time.time(),
        }
        assert _should_continue(state) == "__end__"

    def test_timeout_exceeded(self):
        from app.services.agent_graph import _should_continue
        import time
        # 把 start_time 设到 3 小时前确保 time.time() - start > 120s
        state = {
            "messages": [{"role": "assistant", "tool_calls": [{"id": "1"}]}],
            "iteration": 0,
            "start_time": time.time() - 9999,
        }
        assert _should_continue(state) == "__end__"


# ============================================================
# _tools_node — 工具执行节点
# ============================================================

class TestToolsNode:
    def test_executes_tool_and_updates_state(self):
        from app.services.agent_graph import _tools_node
        from app.mcp import get_mcp_client
        from app.mcp.servers import AnalectsServer

        mcp = get_mcp_client()
        mcp.register(AnalectsServer())

        state = {
            "messages": [
                {"role": "user", "content": "test"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "search_analects",
                                "arguments": '{"query":"仁"}',
                            },
                        }
                    ],
                },
            ],
            "iteration": 0,
            "tool_call_count": 0,
            "sources": [],
        }

        result = _tools_node(state)
        # 节点返回新 tool 消息（reducer 负责追加到 state）
        new_msgs = result["messages"]
        assert len(new_msgs) >= 1
        assert new_msgs[-1]["role"] == "tool"
        assert new_msgs[-1]["tool_call_id"] == "call_1"
        # 计数递增
        assert result["tool_call_count"] >= 1
        assert result["iteration"] == 1

    def test_increments_existing_count(self):
        from app.services.agent_graph import _tools_node
        from app.mcp import get_mcp_client
        from app.mcp.servers import AnalectsServer

        mcp = get_mcp_client()
        mcp.register(AnalectsServer())

        state = {
            "messages": [
                {"role": "user", "content": "test"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_2",
                            "type": "function",
                            "function": {
                                "name": "search_analects",
                                "arguments": '{"query":"学"}',
                            },
                        }
                    ],
                },
            ],
            "iteration": 0,
            "tool_call_count": 3,
            "sources": [],
        }

        result = _tools_node(state)
        assert result["tool_call_count"] == 4


# ============================================================
# 图编译
# ============================================================

class TestGraphBuild:
    def test_graph_compiles(self):
        from app.services.agent_graph import _build_graph
        graph = _build_graph()
        assert graph is not None

    def test_graph_is_cached(self):
        from app.services.agent_graph import _build_graph
        g1 = _build_graph()
        g2 = _build_graph()
        assert g1 is g2  # 同一个对象（缓存生效）


# ============================================================
# run_agent_graph — 端到端（mock LLM）
# ============================================================

class TestRunAgentGraph:
    def test_direct_reply_no_tools(self):
        from app.services.agent_graph import run_agent_graph

        msg = MagicMock()
        msg.content = "善哉！"
        msg.tool_calls = None
        choice = MagicMock()
        choice.message = msg
        resp = MagicMock()
        resp.choices = [choice]

        with patch("app.services.agent_graph.chat_with_tools", return_value=resp):
            result = run_agent_graph(
                system_prompt="你是孔子",
                tools=[],
                user_message="你好",
            )
            assert result["reply"] == "善哉！"
            assert result["tool_calls"] == 0

    def test_agent_with_tool_call_single_turn(self):
        from app.services.agent_graph import run_agent_graph
        from app.mcp import get_mcp_client
        from app.mcp.servers import AnalectsServer

        # 注册 MCP Server
        mcp = get_mcp_client()
        mcp.register(AnalectsServer())

        # 第一次调用: tool_calls
        tc = MagicMock()
        tc.id = "call_1"
        tc.function.name = "search_analects"
        tc.function.arguments = '{"query":"仁"}'

        msg1 = MagicMock()
        msg1.content = None
        msg1.tool_calls = [tc]
        c1 = MagicMock()
        c1.message = msg1
        r1 = MagicMock()
        r1.choices = [c1]

        # 第二次调用: 直接回复
        msg2 = MagicMock()
        msg2.content = "仁者爱人也"
        msg2.tool_calls = None
        c2 = MagicMock()
        c2.message = msg2
        r2 = MagicMock()
        r2.choices = [c2]

        with patch("app.services.agent_graph.chat_with_tools",
                   side_effect=[r1, r2]):
            result = run_agent_graph(
                system_prompt="你是孔子",
                tools=[{"type": "function", "function": {
                    "name": "search_analects",
                    "description": "检索论语",
                    "parameters": {"type": "object", "properties": {}},
                }}],
                user_message="什么是仁",
            )
            assert result["reply"] == "仁者爱人也"
            assert result["tool_calls"] >= 1
