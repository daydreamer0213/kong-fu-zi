"""
MCP Server 基类 — 工具注册 + JSON-RPC 请求分发

每个 MCP Server 代表一个独立的能力域：
  - AnalectsServer: 论语知识检索
  - WebSearchServer: 联网搜索

Server 的职责：
  1. 注册工具（name + description + inputSchema + handler）
  2. 处理 initialize 握手（返回 capabilities）
  3. 处理 tools/list（返回已注册的工具列表）
  4. 处理 tools/call（找到工具 → 调 handler → 返回结果）

每个 Server 是独立无状态的（工具 handler 可能访问共享资源，但 Server 对象本身无状态）。
这为未来拆分为独立进程/服务留了空间：换 HTTP transport 时，每个 Server 可以独立部署。

设计原则：
  - 基类只定义框架（方法路由 + 错误处理），不写死任何工具
  - 子类在 __init__ 中注册自己的工具
  - handler 签名统一: (arguments: dict) -> str
  - 返回格式遵循 MCP 规范: {"content": [{"type":"text", "text":"..."}]}
"""

import logging
from abc import ABC

from app.mcp.protocol import (
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    METHOD_INITIALIZE,
    METHOD_TOOLS_CALL,
    METHOD_TOOLS_LIST,
    TOOL_EXECUTION_ERROR,
    TOOL_NOT_FOUND,
    InitializeResult,
    JsonRpcRequest,
    JsonRpcResponse,
    ServerInfo,
    ToolDefinition,
    make_error,
)

logger = logging.getLogger(__name__)

# MCP 协议版本
PROTOCOL_VERSION = "0.1.0"


class MCPServer(ABC):
    """MCP Server 抽象基类。

    子类使用方式：
        class AnalectsServer(MCPServer):
            def __init__(self):
                super().__init__(ServerInfo(name="analects-server", version="0.1.0"))
                self.register_tool(
                    ToolDefinition(
                        name="search_analects",
                        description="从《论语》中语义检索...",
                        inputSchema={...}
                    ),
                    handler=self._search_analects
                )

            def _search_analects(self, arguments: dict) -> str:
                ...

    生命周期：
      - __init__: 注册工具（子类在构造函数中调用 register_tool）
      - handle_request: 处理 JSON-RPC 请求（Agent 每次调工具时调用）

    为什么不用 async？
      - 当前 transport 是同进程函数调用，不需要 async
      - 换 HTTP transport 时，把 handler 方法改为 async 即可
        （MCP 协议的 transport 和 server 实现是正交的）
    """

    def __init__(self, server_info: ServerInfo):
        self.server_info = server_info
        # 工具注册表: {name: (ToolDefinition, handler)}
        self._tools: dict[str, tuple[ToolDefinition, callable]] = {}

    # ------------------------------------------------------------------
    # 工具注册
    # ------------------------------------------------------------------

    def register_tool(self, definition: ToolDefinition, handler: callable):
        """注册一个工具。

        Args:
            definition: 工具定义（name + description + inputSchema），会暴露给 LLM
            handler: 执行函数，签名 (arguments: dict) -> str
                     返回字符串会被包装成 MCP 标准的 content 格式

        handler 返回的字符串直接作为工具的文本输出传给 LLM。
        如果需要结构化输出（如混合检索结果），handler 内部格式化好文本即可——
        LLM 看到的是最终文本，不需要关心内部结构。
        """
        name = definition.name
        if name in self._tools:
            logger.warning("工具 %s 已注册，将被覆盖", name)
        self._tools[name] = (definition, handler)
        logger.debug("工具已注册: %s", name)

    def list_tools(self) -> list[ToolDefinition]:
        """返回已注册的工具定义列表（不含 handler）"""
        return [tdef for tdef, _ in self._tools.values()]

    # ------------------------------------------------------------------
    # JSON-RPC 请求分发（核心）
    # ------------------------------------------------------------------

    def handle_request(self, request: JsonRpcRequest) -> JsonRpcResponse:
        """处理 JSON-RPC 请求，分发给对应的 _handle_xxx 方法。

        这是 MCP Server 的唯一入口——Client 通过此方法发送所有请求。
        当前 transport 是同进程函数调用，未来可换成 HTTP endpoint 调此方法。

        方法路由：
          initialize  → _handle_initialize()  — Client↔Server 握手
          tools/list  → _handle_tools_list()   — 返回工具列表
          tools/call  → _handle_tools_call()   — 执行工具
          其他        → METHOD_NOT_FOUND 错误
        """
        method = request.method

        try:
            if method == METHOD_INITIALIZE:
                return self._handle_initialize(request)
            elif method == METHOD_TOOLS_LIST:
                return self._handle_tools_list(request)
            elif method == METHOD_TOOLS_CALL:
                return self._handle_tools_call(request)
            else:
                return JsonRpcResponse.error_response(
                    METHOD_NOT_FOUND,
                    f"Method not found: {method}",
                    request.id,
                )
        except Exception as e:
            logger.exception("处理请求时出错: method=%s", method)
            return JsonRpcResponse.error_response(
                TOOL_EXECUTION_ERROR,
                str(e),
                request.id,
            )

    # ------------------------------------------------------------------
    # 核心方法实现
    # ------------------------------------------------------------------

    def _handle_initialize(self, request: JsonRpcRequest) -> JsonRpcResponse:
        """握手：返回 Server 信息和能力声明。

        capabilities 字段声明了此 Server 支持哪些 MCP 功能。
        当前只有 "tools" 能力，未来可扩展 "resources"、"prompts" 等。

        面试时可对比：gRPC 的 service discovery、REST 的 HATEOAS——
        MCP 的 initialize 就是一个轻量的服务发现机制。
        """
        result = InitializeResult(
            protocol_version=PROTOCOL_VERSION,
            server_info=self.server_info,
            capabilities={
                "tools": {}  # {} 表示支持 tools 但不附加配置
            },
        )
        return JsonRpcResponse.success(result.to_dict(), request.id)

    def _handle_tools_list(self, request: JsonRpcRequest) -> JsonRpcResponse:
        """返回所有已注册工具的定义列表。

        返回格式（MCP 标准）：
          {
            "tools": [
              {"name": "...", "description": "...", "inputSchema": {...}},
              ...
            ]
          }
        """
        tools = [
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": t.inputSchema,
            }
            for t in self.list_tools()
        ]
        return JsonRpcResponse.success({"tools": tools}, request.id)

    def _handle_tools_call(self, request: JsonRpcRequest) -> JsonRpcResponse:
        """执行工具调用。

        请求 params 格式（MCP 标准）：
          {
            "name": "search_analects",
            "arguments": {"query": "什么是仁"}
          }

        返回格式（MCP 标准）：
          {
            "content": [
              {"type": "text", "text": "检索结果..."}
            ]
          }

        content 是一个数组，每个元素有 type 和 text/uri 等字段。
        这是 MCP 规范的设计——工具可以返回多类型内容（文本+图片+链接），
        但 LLM 目前只能消费文本，所以本项目只用 {"type":"text", "text":"..."}。
        """
        params = request.params
        if not isinstance(params, dict):
            return JsonRpcResponse.error_response(
                INVALID_PARAMS, "params must be a dict", request.id
            )

        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        if not tool_name:
            return JsonRpcResponse.error_response(
                INVALID_PARAMS, "Missing required field: name", request.id
            )

        # 查找工具
        entry = self._tools.get(tool_name)
        if entry is None:
            return JsonRpcResponse.error_response(
                TOOL_NOT_FOUND,
                f"Tool not found: {tool_name}",
                request.id,
            )

        _definition, handler = entry

        # 参数校验——防止 LLM 传错类型导致 handler 内部崩溃
        # MCP 的 inputSchema 是 JSON Schema，这里做轻量校验（不实现完整规范）
        # 只检查两件事：必填字段是否存在、字符串字段是否真的是字符串
        err = _validate_args(arguments, _definition.inputSchema)
        if err:
            return JsonRpcResponse.error_response(INVALID_PARAMS, err, request.id)

        # 执行工具 handler
        try:
            result_text = handler(arguments)
        except Exception as e:
            logger.exception("工具执行失败: tool=%s, args=%s", tool_name, arguments)
            return JsonRpcResponse.error_response(
                TOOL_EXECUTION_ERROR,
                f"Tool '{tool_name}' execution error: {e}",
                request.id,
            )

        # 包装为 MCP 标准的 content 格式
        return JsonRpcResponse.success(
            {"content": [{"type": "text", "text": result_text}]},
            request.id,
        )


# ---------------------------------------------------------------------------
# 参数校验 — JSON Schema 轻量实现
# ---------------------------------------------------------------------------
# 不实现完整 JSON Schema 规范（type/format/minLength/enum/...），
# 只做两道最常见的检查：required + string type coercion。
# LLM 传错参数的概率很低，但一旦传错（如 query=123 而非 "123"），
# 这里拦住比 handler 崩溃 → 靠 MCP 兜底 → LLM 重新调用 更省 token。


def _validate_args(arguments: dict, input_schema: dict) -> str | None:
    """校验工具参数，返回错误文本或 None（通过）。"""
    # 1. 检查必填字段
    required: list[str] = input_schema.get("required", [])
    for field in required:
        if field not in arguments or arguments[field] is None:
            return f"缺少必填参数: {field}"

    # 2. 字符串类型检查 + 自动转换
    props = input_schema.get("properties", {})
    for field, schema in props.items():
        if field not in arguments:
            continue
        val = arguments[field]
        expected_type = schema.get("type", "")

        if expected_type == "string" and not isinstance(val, str):
            # 尝试安全转换为字符串（数字、布尔等可转，list/dict 不可转）
            if isinstance(val, (int, float, bool)):
                arguments[field] = str(val)
            else:
                return f"参数 {field} 应为字符串，实际类型为 {type(val).__name__}"

        elif expected_type == "integer" and not isinstance(val, int):
            if isinstance(val, str) and val.isdigit():
                arguments[field] = int(val)
            elif isinstance(val, float) and val == int(val):
                arguments[field] = int(val)
            else:
                return f"参数 {field} 应为整数，实际值为 {val}"

    return None  # 校验通过
