"""
MCP Client — 聚合多 Server，提供统一接口给 Agent

MCPClient 是 Agent 和所有 MCP Server 之间的唯一桥梁：

  Agent                        MCPClient                    MCPServer(s)
  ─────                        ─────────                    ────────────
  tools = discover_tools() ──→ 遍历所有 Server
                               各调 tools/list   ──────→  返回 ToolDefinition[]
                               合并 + 转 OpenAI 格式
                             ←─ 返回 tools[] 列表

  result = call_tool()     ──→ 找到拥有该工具的 Server
                               调 tools/call      ──────→  执行 handler → 返回结果
                             ←─ 返回结果文本

设计要点：
  1. 单例模式 — 全局一个 MCPClient 实例，启动时注册所有 Server
  2. 工具发现 — 每次 Agent 循环开始时调 discover_tools() 可获取最新工具列表
                （当前工具列表不变，但未来热加载新 Server 时有用）
  3. 格式转换 — OpenAI Function Calling 的 tools 参数和 MCP ToolDefinition
                底层都是 JSON Schema，直接映射
  4. 协议透明 — Agent 不感知 MCP 协议，只看到 OpenAI 格式的 tools 列表
"""

import logging

from app.mcp.protocol import (
    METHOD_TOOLS_CALL,
    METHOD_TOOLS_LIST,
    ClientInfo,
    JsonRpcRequest,
    JsonRpcResponse,
    ToolDefinition,
)
from app.mcp.server import MCPServer

logger = logging.getLogger(__name__)


class MCPClient:
    """MCP Client — 管理多个 MCP Server，提供工具发现和调用。

    使用方式：
        client = MCPClient()
        client.register(AnalectsServer())
        client.register(WebSearchServer())
        client.initialize()  # 握手，验证所有 Server 可用

        # Agent 循环中
        tools = client.discover_tools()  # → OpenAI format
        result = client.call_tool("search_analects", {"query": "仁"})  # → str
    """

    def __init__(self):
        self._servers: list[MCPServer] = []
        self._initialized = False

    # ------------------------------------------------------------------
    # Server 管理
    # ------------------------------------------------------------------

    def register(self, server: MCPServer):
        """注册一个 MCP Server（幂等——同名 Server 只注册一次）。

        注册顺序不影响工具优先级。
        如果两个 Server 注册了同名工具，后注册的生效（和 MCP 标准一致）。
        """
        # 检查是否已注册同名 Server（防止 lifespan 重复执行时重复注册）
        for existing in self._servers:
            if existing.server_info.name == server.server_info.name:
                logger.debug(
                    "MCP Server '%s' 已注册，跳过",
                    server.server_info.name,
                )
                return

        self._servers.append(server)
        logger.info(
            "MCP Server 已注册: %s (v%s), %d 个工具",
            server.server_info.name,
            server.server_info.version,
            len(server.list_tools()),
        )

    def initialize(self, client_info: ClientInfo | None = None):
        """和所有已注册的 Server 进行握手。

        调用每个 Server 的 initialize 方法：
          - 验证 Server 可达（当前进程内总是成功）
          - 协商协议版本
          - 获取 capabilities 声明

        初始化后 Server 进入就绪状态，可以处理 tools/list 和 tools/call。
        失败会记录但不会阻止其他 Server 初始化（优雅降级）。
        """
        for server in self._servers:
            try:
                request = JsonRpcRequest(
                    method="initialize",
                    params={
                        "protocolVersion": "0.1.0",
                        "clientInfo": (
                            {"name": client_info.name, "version": client_info.version}
                            if client_info
                            else {}
                        ),
                    },
                    id=0,
                )
                response = server.handle_request(request)
                if response.is_error:
                    logger.error(
                        "Server %s 初始化失败: %s",
                        server.server_info.name,
                        response.error,
                    )
                else:
                    logger.info(
                        "Server %s 初始化成功，能力: %s",
                        server.server_info.name,
                        response.result.get("capabilities", {}),
                    )
            except Exception as e:
                logger.exception("Server %s 初始化异常: %s", server.server_info.name, e)

        self._initialized = True

    # ------------------------------------------------------------------
    # 工具发现（Agent 入口）
    # ------------------------------------------------------------------

    def discover_tools(self) -> list[dict]:
        """收集所有 Server 的工具列表，转为 OpenAI Function Calling 格式。

        这是 Agent 获取可用工具的入口。调用链：
          MCPClient.discover_tools()
            → Server.handle_request(JsonRpcRequest(method="tools/list"))
              → Server._handle_tools_list()
                → 返回 {"tools": [ToolDefinition, ...]}
            → _to_openai_format() 转换为 OpenAI tools 参数的格式

        OpenAI Function Calling 格式：
          [
            {
              "type": "function",
              "function": {
                "name": "search_analects",
                "description": "从《论语》...",
                "parameters": {
                  "type": "object",
                  "properties": {
                    "query": {"type": "string", "description": "..."}
                  },
                  "required": ["query"]
                }
              }
            }
          ]

        注意：MCP 的 inputSchema 和 OpenAI 的 parameters 都是 JSON Schema ，
        格式完全兼容，可以直接复用——这是 MCP 刻意设计的兼容性。
        """
        all_tools: list[dict] = []

        for server in self._servers:
            try:
                request = JsonRpcRequest(method=METHOD_TOOLS_LIST, params={}, id=0)
                response = server.handle_request(request)

                if response.is_error:
                    logger.error(
                        "Server %s tools/list 失败: %s",
                        server.server_info.name,
                        response.error,
                    )
                    continue

                # response.result = {"tools": [{"name":..., "description":..., "inputSchema":...}, ...]}
                mcp_tools = response.result.get("tools", [])

                for tool in mcp_tools:
                    all_tools.append(self._to_openai_format(tool))

            except Exception as e:
                logger.exception(
                    "Server %s tools/list 异常: %s",
                    server.server_info.name,
                    e,
                )
                continue

        logger.debug("工具发现完成: %d 个 Server 共 %d 个工具", len(self._servers), len(all_tools))
        return all_tools

    def list_tools(self) -> list[ToolDefinition]:
        """返回所有 Server 的工具定义列表（MCP 原生格式，不含 handler）。

        用于动态生成 Agent System Prompt 中的工具描述——
        这样加新工具时 Prompt 自动更新，不用手动改。
        """
        result: list[ToolDefinition] = []
        for server in self._servers:
            result.extend(server.list_tools())
        return result

    # ------------------------------------------------------------------
    # 工具调用（Agent 入口）
    # ------------------------------------------------------------------

    def call_tool(self, name: str, arguments: dict) -> str:
        """调用指定工具。

        遍历所有 Server，找到注册了该工具的 Server，调 tools/call，
        返回 MCP content 数组中第一段文本。

        Agent 不感知哪个 Server 提供了该工具——这是位置透明的设计。

        Args:
            name: 工具名（如 "search_analects"）
            arguments: 工具参数（如 {"query": "什么是仁"}）

        Returns:
            工具执行结果文本。如果调用失败，返回错误信息的文本表示
            （不抛异常，让 LLM 根据错误信息决定下一步）。

        为什么失败返回文本而不是抛异常？
          → 这是 Agent 的韧性设计。如果某工具失败，LLM 看到错误文本后
            可以换一个工具、换参数重试、或直接告诉用户"这个我查不到"。
            抛异常会终止整个 Agent 循环，用户什么也看不到。
        """
        for server in self._servers:
            # 检查此 Server 是否有该工具
            if not self._server_has_tool(server, name):
                continue

            try:
                request = JsonRpcRequest(
                    method=METHOD_TOOLS_CALL,
                    params={"name": name, "arguments": arguments},
                    id=0,
                )
                response = server.handle_request(request)

                if response.is_error:
                    err = response.error
                    logger.warning(
                        "工具调用失败: tool=%s, server=%s, error=%s",
                        name,
                        server.server_info.name,
                        err,
                    )
                    return f"[工具调用失败] {err.get('message', '未知错误')}"

                # 从 MCP content 数组中提取文本
                # content = [{"type":"text", "text":"..."}, ...]
                content = response.result.get("content", [])
                text_parts = [
                    item.get("text", "")
                    for item in content
                    if item.get("type") == "text"
                ]
                return "\n".join(text_parts)

            except Exception as e:
                logger.exception(
                    "工具调用异常: tool=%s, server=%s",
                    name,
                    server.server_info.name,
                )
                return f"[工具调用异常] {e}"

        # 走完所有 Server 都没找到该工具
        return f"[工具不存在] 未找到工具: {name}"

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _server_has_tool(self, server: MCPServer, tool_name: str) -> bool:
        """检查 Server 是否注册了某个工具"""
        return any(t.name == tool_name for t in server.list_tools())

    @staticmethod
    def _to_openai_format(mcp_tool: dict) -> dict:
        """将一个 MCP 工具定义转为 OpenAI Function Calling 格式。

        MCP tools/list 返回的格式:
          {"name": "...", "description": "...", "inputSchema": {...}}

        OpenAI tools 参数需要的格式:
          {"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}

        inputSchema → parameters 是直接复用——两者都遵循 JSON Schema。
        这是 MCP 协议设计时的刻意兼容：MCP 的工具描述和 OpenAI 的 Function
        Calling 共享同一套 schema 底层，减少了协议转换的摩擦。
        """
        return {
            "type": "function",
            "function": {
                "name": mcp_tool["name"],
                "description": mcp_tool["description"],
                "parameters": mcp_tool["inputSchema"],
            },
        }


# ---------------------------------------------------------------------------
# 全局单例 — 启动时注册所有 Server，Agent 循环复用
# ---------------------------------------------------------------------------

_global_client: MCPClient | None = None


def get_mcp_client() -> MCPClient:
    """获取全局 MCPClient 单例。

    第一个调用方（通常在 main.py 的 lifespan 中）负责：
      1. get_mcp_client()
      2. client.register(analects_server)
      3. client.register(web_search_server)
      4. client.initialize()
    """
    global _global_client
    if _global_client is None:
        _global_client = MCPClient()
    return _global_client
