"""
MCP 协议层 — JSON-RPC 2.0 消息格式 + 工具定义

MCP (Model Context Protocol) 是 Anthropic 提出的 LLM 与外部工具/数据源之间的
标准化通信协议。它的核心设计：

1. JSON-RPC 2.0 作为消息编码格式
   - 请求: {"jsonrpc":"2.0", "method":"...", "params":{...}, "id":N}
   - 响应: {"jsonrpc":"2.0", "result":{...}, "id":N}
   - 错误: {"jsonrpc":"2.0", "error":{"code":N, "message":"..."}, "id":N}

2. 核心方法（本项目涉及的）：
   - initialize:    Client↔Server 握手，协商协议版本和能力
   - tools/list:    Client 查询 Server 提供了哪些工具
   - tools/call:    Client 调用 Server 的某个工具

3. 工具定义格式：
   - name:         工具唯一标识（如 "search_analects"）
   - description:  给 LLM 看的自然语言描述（LLM 据此决定何时调工具）
   - inputSchema:  JSON Schema 格式的参数定义（和 OpenAI Function Calling 兼容）

当前实现：
  - transport 层用纯函数调用（in-process），不走 HTTP
  - JSON-RPC 消息格式完整保留，方便未来换成真正的 HTTP transport
  - 面试时可说："transport 层可替换，换 HTTP+SSE 就是标准 MCP，协议层不动"

参考：
  - MCP Spec: https://spec.modelcontextprotocol.io/
  - JSON-RPC 2.0: https://www.jsonrpc.org/specification
"""

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# JSON-RPC 2.0 标准方法名
# ---------------------------------------------------------------------------

# MCP 协议方法
METHOD_INITIALIZE = "initialize"
METHOD_TOOLS_LIST = "tools/list"
METHOD_TOOLS_CALL = "tools/call"

# JSON-RPC 通知（无需响应）
METHOD_NOTIFICATION_INITIALIZED = "notifications/initialized"

# ---------------------------------------------------------------------------
# JSON-RPC 2.0 标准错误码
# ---------------------------------------------------------------------------

# 标准 JSON-RPC 错误码
PARSE_ERROR = -32700       # JSON 解析失败
INVALID_REQUEST = -32600    # 请求格式不对（缺 jsonrpc/method 等）
METHOD_NOT_FOUND = -32601   # 调了不存在的 method
INVALID_PARAMS = -32602     # params 不符合预期
INTERNAL_ERROR = -32603     # Server 内部错误

# MCP 自定义错误码（-32000 ~ -32099 是 JSON-RPC reserved range）
TOOL_NOT_FOUND = -32001     # 工具不存在
TOOL_EXECUTION_ERROR = -32002  # 工具执行时出错

# 人类可读的错误消息
ERROR_MESSAGES = {
    PARSE_ERROR: "Parse error",
    INVALID_REQUEST: "Invalid Request",
    METHOD_NOT_FOUND: "Method not found",
    INVALID_PARAMS: "Invalid params",
    INTERNAL_ERROR: "Internal error",
    TOOL_NOT_FOUND: "Tool not found",
    TOOL_EXECUTION_ERROR: "Tool execution error",
}


def make_error(code: int, message: str | None = None) -> dict:
    """构造 JSON-RPC 错误对象"""
    return {
        "code": code,
        "message": message or ERROR_MESSAGES.get(code, "Unknown error"),
    }


# ---------------------------------------------------------------------------
# MCP 元信息
# ---------------------------------------------------------------------------


@dataclass
class ServerInfo:
    """MCP Server 的身份信息"""
    name: str           # 如 "analects-server"
    version: str = "0.1.0"


@dataclass
class ClientInfo:
    """MCP Client 的身份信息"""
    name: str = "kong-agent"
    version: str = "0.1.0"


# ---------------------------------------------------------------------------
# 工具定义
# ---------------------------------------------------------------------------


@dataclass
class ToolDefinition:
    """MCP 标准工具描述。

    MCP 规范中工具的 inputSchema 是 JSON Schema 格式。
    这和 OpenAI Function Calling 的 parameters 字段格式完全兼容——
    两者都遵循 JSON Schema Draft 7，所以转换时直接复用，无需映射。

    示例：
        ToolDefinition(
            name="search_analects",
            description="从《论语》知识库中语义检索相关章句。当用户询问...",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "检索关键词或问题"
                    }
                },
                "required": ["query"]
            }
        )

    对比 OpenAI Function Calling 格式：
        {
            "type": "function",
            "function": {
                "name": "...",         ← 和 ToolDefinition.name 一致
                "description": "...",  ← 和 ToolDefinition.description 一致
                "parameters": {...}    ← 和 ToolDefinition.inputSchema 一致
            }
        }
    """

    name: str               # 工具唯一标识
    description: str         # 给 LLM 看的自然语言说明
    inputSchema: dict        # JSON Schema 参数定义


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 消息
# ---------------------------------------------------------------------------


@dataclass
class JsonRpcRequest:
    """JSON-RPC 2.0 请求。

    示例（tools/list）：
        JsonRpcRequest(method="tools/list", params={}, id=1)

    示例（tools/call）：
        JsonRpcRequest(
            method="tools/call",
            params={"name": "search_analects", "arguments": {"query": "仁"}},
            id=3
        )
    """

    method: str
    params: dict = field(default_factory=dict)
    jsonrpc: str = "2.0"
    id: int = 0

    def to_dict(self) -> dict:
        """序列化为 JSON-RPC 请求 dict"""
        return {
            "jsonrpc": self.jsonrpc,
            "method": self.method,
            "params": self.params,
            "id": self.id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "JsonRpcRequest":
        """从 JSON-RPC 请求 dict 反序列化"""
        return cls(
            jsonrpc=data.get("jsonrpc", "2.0"),
            method=data.get("method", ""),
            params=data.get("params", {}),
            id=data.get("id", 0),
        )


@dataclass
class JsonRpcResponse:
    """JSON-RPC 2.0 响应。

    成功响应：
        JsonRpcResponse(
            result={"tools": [...]},
            id=2
        )

    错误响应：
        JsonRpcResponse(
            error={"code": -32601, "message": "Method not found"},
            id=1
        )
    """

    result: Any = None
    error: dict | None = None
    jsonrpc: str = "2.0"
    id: int = 0

    @property
    def is_error(self) -> bool:
        return self.error is not None

    def to_dict(self) -> dict:
        d: dict = {"jsonrpc": self.jsonrpc, "id": self.id}
        if self.error:
            d["error"] = self.error
        else:
            d["result"] = self.result
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "JsonRpcResponse":
        return cls(
            jsonrpc=data.get("jsonrpc", "2.0"),
            result=data.get("result"),
            error=data.get("error"),
            id=data.get("id", 0),
        )

    @classmethod
    def success(cls, result: Any, req_id: int = 0) -> "JsonRpcResponse":
        """快捷构造成功响应"""
        return cls(result=result, id=req_id)

    @classmethod
    def error_response(cls, code: int, message: str | None = None, req_id: int = 0) -> "JsonRpcResponse":
        """快捷构造错误响应"""
        return cls(error=make_error(code, message), id=req_id)


# ---------------------------------------------------------------------------
# MCP 握手结果
# ---------------------------------------------------------------------------


@dataclass
class InitializeResult:
    """initialize 方法的返回结果"""
    protocol_version: str
    server_info: ServerInfo
    capabilities: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "protocolVersion": self.protocol_version,
            "serverInfo": {
                "name": self.server_info.name,
                "version": self.server_info.version,
            },
            "capabilities": self.capabilities,
        }
