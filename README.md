# 孔夫子 AI 聊天助手

以孔子风格回复的 AI 对话助手。基于 LangGraph + MCP 协议的 Agent 自主编排 6 个工具（混合检索、关键词匹配、联网搜索、长期记忆），结合《论语》全文 RAG 知识库，回答引经据典、有源可循。

## 架构

```
                         ┌─────────────────────┐
                         │     React 前端        │
                         └──────────┬──────────┘
                                    │ HTTP + SSE
                                    ▼
                         ┌─────────────────────┐
                         │   FastAPI 后端        │
                         │                      │
                         │  ┌─────────────────┐ │
                         │  │ LangGraph Agent  │ │
                         │  │ ReAct 循环        │ │
                         │  │ LLM 自主决策:     │ │
                         │  │ 闲聊→直接回复     │ │
                         │  │ 求教→调工具→查书  │ │
                         │  │ 记忆→remember/recall│
                         │  └────────┬────────┘ │
                         │           │           │
                         │  ┌────────┴────────┐  │
                         │  │   MCP 协议框架    │  │
                         │  │   3 Server/6 工具 │  │
                         │  └────────┬────────┘  │
                         │           │           │
                         │  ┌────────┴────────┐  │
                         │  │ RAG + 韧性 + 记忆 │  │
                         │  │ ChromaDB+SQLite  │  │
                         │  └─────────────────┘  │
                         └──────────┬──────────┘
                                    │ HTTPS
                                    ▼
                         ┌─────────────────────┐
                         │   DeepSeek API       │
                         └─────────────────────┘
```

## 核心特性

- **Agent 自主推理**：LangGraph StateGraph 构建 ReAct 循环，LLM 自主决定是否调工具、调哪个、调几次
- **MCP 协议框架**：手写 JSON-RPC 2.0 协议，3 个独立 Server 管理 6 个工具（混合检索、语义检索、关键词检索、联网搜索、记忆存储、记忆召回）
- **混合检索链路**：BGE 向量检索 + BM25 关键词检索 + RRF 融合 + Cross-Encoder Reranker 精排，两阶段检索（粗筛 Top-20 → 精排 Top-5）
- **工程韧性**：指数退避重试（含 jitter）+ 三态熔断器（CLOSED/OPEN/HALF_OPEN）+ L0→L1→L2 三层降级兜底
- **长期记忆**：Agent 工具型（remember/recall）+ 系统自动画像提取，记忆用向量语义检索，画像注入 System Prompt
- **Skill 系统**：3 种对话模式（夫子教诲/诗词赏析/经学辩论），每种独立配置 System Prompt 和工具权限
- **上下文管理**：滑动窗口 5 轮原文 + 超出自动 LLM 增量摘要
- **安全与限流**：提示词注入三层防御（输入过滤 + Prompt 分隔符加固 + 输出角色检测），三层限流漏斗（并发控制 + 分钟级 + 天级滑动窗口）
- **结构化日志**：structlog + trace_id 全链路追踪 + token 用量记录

## 技术栈

大模型层基于 OpenAI SDK 接入 DeepSeek API（Function Calling），封装 LangChain BaseChatModel 标准接口。Agent 编排用 LangGraph StateGraph，工具体系手写 MCP 协议（JSON-RPC 2.0）。RAG 链路 BGE Embedding (1024维) + BM25 + RRF 融合 + BGE-Reranker Cross-Encoder 精排。后端 FastAPI + SSE 流式，SQLite + SQLAlchemy ORM，JWT + bcrypt 鉴权。structlog 结构化日志 + trace_id 全链路追踪。pytest 150 用例覆盖单元/Mock/集成/E2E。Docker Compose + Nginx + GitHub Actions CI 部署。

## 快速开始

### 环境要求

- Python 3.12+
- Node.js 22+

### 本地开发

```bash
# 后端
cd backend
python -m venv .venv
source .venv/Scripts/activate   # Windows, 或 . .venv/bin/activate (Linux/Mac)
pip install -r requirements.txt
# 编辑 .env 填入 DEEPSEEK_API_KEY 和 TAVILY_API_KEY
python -m uvicorn app.main:app --reload

# 前端
cd frontend
npm install
npm run dev
```

浏览器打开 http://localhost:5173

### Docker

```bash
echo "DEEPSEEK_API_KEY=sk-xxxx" > .env
docker compose up -d
```

浏览器打开 http://localhost

## 项目结构

```
kong/
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI 入口
│   │   ├── config.py                # 配置管理
│   │   ├── routers/
│   │   │   ├── auth.py              # 认证 (注册/登录/JWT)
│   │   │   └── chat.py              # 对话 (Agent + 流式 + 画像提取)
│   │   ├── services/
│   │   │   ├── agent.py             # Agent 入口 (降级链 + Skill 集成)
│   │   │   ├── agent_graph.py       # LangGraph StateGraph Agent 循环
│   │   │   ├── chat.py              # 基础对话函数 (已废弃,保留参考)
│   │   │   ├── tools.py             # 旧工具注册表 (已废弃)
│   │   │   ├── auth.py              # 认证逻辑
│   │   │   ├── conversation.py      # 对话持久化 + 窗口管理
│   │   │   ├── summarizer.py        # 滑动窗口摘要生成
│   │   │   └── profile.py           # 用户画像提取
│   │   ├── mcp/
│   │   │   ├── protocol.py          # JSON-RPC 2.0 消息格式
│   │   │   ├── server.py            # MCPServer 基类
│   │   │   ├── client.py            # MCPClient 聚合层
│   │   │   └── servers/
│   │   │       ├── analects_server.py   # 论语检索 (3工具)
│   │   │       ├── web_search_server.py # 联网搜索 (Tavily)
│   │   │       └── memory_server.py     # 长期记忆 (2工具)
│   │   ├── rag/
│   │   │   ├── chunker.py           # 文本分块 (按论语篇章)
│   │   │   ├── embedder.py          # BGE 向量化
│   │   │   ├── retriever.py         # ChromaDB 语义检索
│   │   │   ├── keyword_search.py    # BM25 关键词检索
│   │   │   ├── fusion.py            # RRF 混合融合
│   │   │   ├── reranker.py          # Cross-Encoder 精排
│   │   │   └── builder.py           # 知识库构建
│   │   ├── llm/
│   │   │   ├── client.py            # DeepSeek API (含重试+熔断)
│   │   │   ├── prompts.py           # 角色 + Agent Prompt 模板
│   │   │   └── langchain_adapter.py # LangChain ChatModel 适配
│   │   ├── skills/
│   │   │   ├── base.py              # Skill 数据类
│   │   │   ├── registry.py          # Skill 注册表
│   │   │   └── builtin.py           # 3 个内置 Skill
│   │   ├── models/
│   │   │   ├── database.py          # ORM (User/Conv/Message/MemoryFact)
│   │   │   └── memory.py            # 记忆存储 + 向量检索
│   │   └── utils/
│   │       ├── resilience.py        # 重试/熔断/降级
│   │       ├── logging.py           # structlog 配置 + 请求中间件
│   │       ├── rate_limit.py        # 限流 (并发+分钟+天级)
│   │       └── security.py          # 提示词注入防御
│   ├── prompts/
│   │   ├── summary.yaml             # 摘要生成 Prompt (v2)
│   │   └── profile.yaml             # 画像提取 Prompt (v1)
│   ├── data/
│   │   └── lunyu.json               # 论语全文 (20篇512章)
│   └── tests/
│       ├── conftest.py
│       ├── test_auth.py
│       ├── test_e2e.py
│       ├── test_edge_cases.py
│       ├── test_llm_mock.py
│       ├── test_rag.py
│       ├── test_mcp.py              # MCP 协议层测试
│       ├── test_skills.py           # Skill 注册表测试
│       ├── test_resilience.py       # 韧性机制测试
│       ├── test_rag_extensions.py   # RAG 扩展测试
│       └── test_agent_graph.py      # Agent 图测试
├── frontend/
│   └── src/
│       ├── pages/                   # Chat, Login
│       ├── components/              # UI 组件
│       └── lib/                     # API 客户端 + SSE 解析
├── docker-compose.yml
├── LearnList.md                     # 学习路线 (38 知识点)
├── LearnTalk.md                     # 学习对话笔记
└── README.md
```

## 核心设计决策

| 决策 | 选择 | 原因 |
|------|------|------|
| Agent 编排 | LangGraph StateGraph | Agent 天然带环，声明式图比手写 while 易扩展、可并行、支持 checkpointing |
| MCP 协议 | JSON-RPC 2.0 同进程 | 标准化工具发现与调用，transport 层可替换为 HTTP，工具即插即用 |
| 混合检索 | 向量 + BM25 + RRF + Reranker | 语义理解 + 精确匹配互补，RRF 用排名不用分数（两路评分尺度不同） |
| 韧性 | 重试(jitter) + 熔断(三态) + 降级(三层) | 瞬时/持续/彻底故障分层应对，API 故障时用户仍可获取回复 |
| 记忆系统 | Agent 工具型 + 自动画像提取 | 记忆管"事"需向量检索，画像管"人"一份摘要直接注入，不同访问模式不同方案 |
| 上下文 | 滑动窗口 5 轮原文 + 增量摘要 | 近期细节 + 远期脉络兼顾，token 预算可控 |
| Prompt 管理 | 任务类集中(YAML)，Skill/MCP 就近 | 判断标准：改 Prompt 要否同步改代码 → 决定集中或嵌入 |
| 限流 | 三层漏斗（并发+分钟滑动窗口+天滑动窗口） | 每层保护不同维度：并发防状态覆盖，分钟防脚本攻击，天防长期挂机 |
| 提示词安全 | 输入过滤 + Prompt 加固 + 输出检测 | 纵深防御，聊天应用低风险场景输出端仅告警不截断 |
| Embedding | BGE-large-zh 本地 | 中文 SOTA，零 API 成本，和 Cross-Encoder 同家族 |
| 向量库 | ChromaDB (论语) + SQLite JSON (记忆) | 数据量决定索引策略：512 条用 HNSW，<50 条 Python 循环 |
| 数据库 | SQLite → 可迁移 PG | SQLAlchemy ORM 全表统一，切换数据库仅改连接串 |

## API

| 端点 | 说明 |
|------|------|
| POST /api/auth/register | 注册 |
| POST /api/auth/login | 登录 → JWT |
| GET /api/auth/me | 当前用户 |
| POST /api/chat | Agent 对话 (支持 `skill` 参数切换对话模式) |
| POST /api/chat/stream | 流式对话 |
| GET /api/chat/conversations | 对话列表 |
| GET /api/chat/conversations/:id | 对话详情 |
| DELETE /api/chat/conversations/:id | 删除对话 |

## 测试

```bash
cd backend
python -m pytest tests/ -v
```

150 用例，覆盖单元 / Mock / 集成 / E2E 四层。

## License

MIT
