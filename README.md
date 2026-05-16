# 孔夫子 AI 聊天助手

以孔子（Confucius）风格回复的智能聊天助手。接入了《论语》全文知识库（RAG），闲聊时以儒家语气回应，求教时引用论语原文作答。

## 技术栈

| 层 | 技术 |
|----|------|
| 大模型 | DeepSeek API (OpenAI SDK 兼容) |
| Embedding | BGE-large-zh 本地运行 |
| 向量库 | ChromaDB |
| 后端 | FastAPI + SSE 流式 |
| 前端 | React 18 + TypeScript + shadcn/ui + Tailwind CSS |
| 数据库 | SQLite (SQLAlchemy) |
| 用户系统 | JWT 轻量认证 |
| 部署 | Docker Compose |

## 快速开始

### 环境要求

- Python 3.13+
- Node.js 22+
- Docker（可选）

### 方式一：本地开发

```bash
# 后端
cd backend
python -m venv .venv
source .venv/Scripts/activate   # Windows
pip install -r requirements.txt
cp .env.example .env            # 编辑填入 DEEPSEEK_API_KEY
python -m uvicorn app.main:app --reload

# 前端
cd frontend
npm install
npm run dev
```

浏览器打开 http://localhost:5173

### 方式二：Docker 部署

```bash
# 根目录下创建 .env 填入 API Key
echo "DEEPSEEK_API_KEY=sk-xxxx" > .env
docker compose up -d
```

浏览器打开 http://localhost

## 项目结构

```
kong/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI 入口
│   │   ├── config.py        # 配置管理
│   │   ├── routers/         # API 路由
│   │   ├── services/        # 业务逻辑
│   │   ├── models/          # 数据库 ORM
│   │   ├── rag/             # RAG 引擎（自研）
│   │   └── llm/             # LLM 客户端
│   └── tests/
├── frontend/
│   └── src/
│       ├── pages/           # Chat, Login
│       ├── components/      # UI 组件
│       └── lib/             # API 客户端
├── docker-compose.yml
└── README.md
```

## API 概览

| 端点 | 说明 |
|------|------|
| POST /api/auth/register | 注册 |
| POST /api/auth/login | 登录 |
| GET /api/auth/me | 当前用户 |
| POST /api/chat | 智能对话（JWT） |
| POST /api/chat/stream | 流式对话（JWT） |
| GET /api/chat/conversations | 对话列表 |
| DELETE /api/chat/conversations/:id | 删除对话 |

## 学习笔记

项目开发过程中的所有技术知识点已整理到 [Learning-Notes.md](Learning-Notes.md)，适合初学者阅读，也适合面试前复习。
