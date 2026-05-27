"""MCP 框架单元测试 — protocol + server + client"""
import pytest

from app.mcp.protocol import (
    METHOD_INITIALIZE,
    METHOD_TOOLS_CALL,
    METHOD_TOOLS_LIST,
    TOOL_NOT_FOUND,
    JsonRpcRequest,
    JsonRpcResponse,
    ServerInfo,
    ToolDefinition,
    make_error,
)
from app.mcp.server import MCPServer


# ============================================================
# protocol — JSON-RPC 消息格式
# ============================================================

class TestJsonRpcProtocol:
    def test_request_to_dict(self):
        req = JsonRpcRequest(method="tools/list", params={}, id=1)
        d = req.to_dict()
        assert d["jsonrpc"] == "2.0"
        assert d["method"] == "tools/list"
        assert d["id"] == 1

    def test_request_from_dict(self):
        req = JsonRpcRequest.from_dict({"method": "tools/call", "params": {"name": "x"}, "id": 3})
        assert req.method == "tools/call"
        assert req.params == {"name": "x"}
        assert req.id == 3

    def test_response_success(self):
        resp = JsonRpcResponse.success({"tools": []}, req_id=2)
        assert not resp.is_error
        assert resp.result == {"tools": []}

    def test_response_error(self):
        resp = JsonRpcResponse.error_response(-32601, "Not found", req_id=1)
        assert resp.is_error
        assert resp.error["code"] == -32601

    def test_response_to_dict_success(self):
        resp = JsonRpcResponse.success({"ok": True}, req_id=5)
        d = resp.to_dict()
        assert "result" in d
        assert "error" not in d

    def test_response_to_dict_error(self):
        resp = JsonRpcResponse.error_response(-32600, "Bad", req_id=5)
        d = resp.to_dict()
        assert "error" in d
        assert "result" not in d

    def test_make_error(self):
        err = make_error(-32601)
        assert err["code"] == -32601

    def test_tool_definition(self):
        td = ToolDefinition(
            name="test_tool",
            description="A test tool",
            inputSchema={"type": "object", "properties": {"q": {"type": "string"}}},
        )
        assert td.name == "test_tool"
        assert "q" in td.inputSchema["properties"]


# ============================================================
# server — MCPServer 基类
# ============================================================

class _TestServer(MCPServer):
    """用于测试的 Server 子类，注册一个虚拟工具"""

    def __init__(self):
        super().__init__(ServerInfo(name="test-server", version="0.1.0"))
        self.register_tool(
            ToolDefinition(
                name="echo",
                description="Echo back the input",
                inputSchema={
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            ),
            handler=self._echo,
        )
        self.register_tool(
            ToolDefinition(
                name="fail_tool",
                description="Always fails",
                inputSchema={"type": "object", "properties": {}},
            ),
            handler=self._fail,
        )

    def _echo(self, args):
        return f"echo: {args.get('text', '')}"

    def _fail(self, args):
        raise RuntimeError("intentional failure")


@pytest.fixture
def test_server():
    return _TestServer()


class TestMCPServer:
    def test_list_tools(self, test_server):
        tools = test_server.list_tools()
        assert len(tools) == 2
        names = [t.name for t in tools]
        assert "echo" in names
        assert "fail_tool" in names

    def test_handle_initialize(self, test_server):
        req = JsonRpcRequest(method=METHOD_INITIALIZE, params={}, id=1)
        resp = test_server.handle_request(req)
        assert not resp.is_error
        result = resp.result
        assert result["serverInfo"]["name"] == "test-server"
        assert "capabilities" in result
        assert "tools" in result["capabilities"]

    def test_handle_tools_list(self, test_server):
        req = JsonRpcRequest(method=METHOD_TOOLS_LIST, params={}, id=2)
        resp = test_server.handle_request(req)
        assert not resp.is_error
        tools = resp.result["tools"]
        assert len(tools) == 2

    def test_handle_tools_call_success(self, test_server):
        req = JsonRpcRequest(
            method=METHOD_TOOLS_CALL,
            params={"name": "echo", "arguments": {"text": "hello"}},
            id=3,
        )
        resp = test_server.handle_request(req)
        assert not resp.is_error
        content = resp.result["content"]
        assert len(content) == 1
        assert "echo: hello" in content[0]["text"]

    def test_handle_tools_call_not_found(self, test_server):
        req = JsonRpcRequest(
            method=METHOD_TOOLS_CALL,
            params={"name": "nonexistent", "arguments": {}},
            id=4,
        )
        resp = test_server.handle_request(req)
        assert resp.is_error
        assert resp.error["code"] == TOOL_NOT_FOUND

    def test_handle_tools_call_missing_name(self, test_server):
        req = JsonRpcRequest(
            method=METHOD_TOOLS_CALL,
            params={"arguments": {}},
            id=5,
        )
        resp = test_server.handle_request(req)
        assert resp.is_error

    def test_handle_tools_call_handler_raises(self, test_server):
        req = JsonRpcRequest(
            method=METHOD_TOOLS_CALL,
            params={"name": "fail_tool", "arguments": {}},
            id=6,
        )
        resp = test_server.handle_request(req)
        assert resp.is_error
        assert "intentional failure" in resp.error["message"]

    def test_handle_unknown_method(self, test_server):
        req = JsonRpcRequest(method="nonexistent/method", params={}, id=7)
        resp = test_server.handle_request(req)
        assert resp.is_error
        assert resp.error["code"] == -32601  # METHOD_NOT_FOUND

    def test_handle_request_exception_logs(self, test_server, caplog):
        """异常不应导致 handle_request 本身崩溃，而是返回错误响应"""
        req = JsonRpcRequest(
            method=METHOD_TOOLS_CALL,
            params={"name": "fail_tool", "arguments": {}},
            id=6,
        )
        resp = test_server.handle_request(req)
        assert resp.is_error
        # 验证没有未捕获的异常
        assert resp.error["code"] != -32603  # INTERNAL_ERROR 也不应该（handler 抛了但被 catch 了）


# ============================================================
# client — MCPClient
# ============================================================

from app.mcp.client import MCPClient


@pytest.fixture
def mcp_client():
    client = MCPClient()
    client.register(_TestServer())
    return client


class TestMCPClient:
    def test_register_duplicate_is_idempotent(self, mcp_client):
        """同名 Server 重复注册不应添加重复项"""
        initial_count = len(mcp_client._servers)
        mcp_client.register(_TestServer())  # 同名
        assert len(mcp_client._servers) == initial_count

    def test_initialize(self, mcp_client):
        """initialize 不应抛异常"""
        mcp_client.initialize()
        assert mcp_client._initialized

    def test_discover_tools_format(self, mcp_client):
        tools = mcp_client.discover_tools()
        assert len(tools) == 2  # echo + fail_tool
        for t in tools:
            assert t["type"] == "function"
            f = t["function"]
            assert "name" in f
            assert "description" in f
            assert "parameters" in f

    def test_call_tool_success(self, mcp_client):
        result = mcp_client.call_tool("echo", {"text": "hello"})
        assert "echo: hello" in result

    def test_call_tool_not_found_returns_error_text(self, mcp_client):
        """工具不存在时应返回错误文本，而非抛异常"""
        result = mcp_client.call_tool("nonexistent", {})
        assert "工具不存在" in result or "未找到工具" in result

    def test_call_tool_failure_returns_error_text(self, mcp_client):
        """工具 handler 抛异常时应返回错误文本"""
        result = mcp_client.call_tool("fail_tool", {})
        assert "工具" in result  # "工具调用失败" or "工具调用异常"

    def test_list_tools_returns_definitions(self, mcp_client):
        tools = mcp_client.list_tools()
        assert len(tools) == 2
        assert isinstance(tools[0], ToolDefinition)

    def test_to_openai_format(self):
        """内部格式转换验证"""
        mcp_tool = {
            "name": "test",
            "description": "desc",
            "inputSchema": {"type": "object", "properties": {}},
        }
        result = MCPClient._to_openai_format(mcp_tool)
        assert result["type"] == "function"
        assert result["function"]["name"] == "test"
