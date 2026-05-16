# 孔夫子 AI 聊天助手 — 学习笔记

本文档按开发步骤组织，收录项目中涉及的每个技术概念的深入讲解。适合没有开发经验的初学者阅读，也适合面试前复习。

---

## 第①步：项目骨架

### 1. Web 框架 FastAPI

浏览器访问一个网址，向服务器发 HTTP 请求（"给我这个页面"），服务器收到后返回 HTML 或 JSON 数据。**Web 框架**就是帮你处理这些请求的工具——你定义"当用户访问 `/xxx` 时执行什么逻辑"，框架负责接收请求、解析参数、返回响应。

FastAPI 是 Python 里近几年最流行的 Web 框架，两个核心卖点：

- **快**：基于 Starlette（ASGI 框架）+ Pydantic（数据校验），性能接近 Go/Node.js
- **自动生成 API 文档**：你定义了 Pydantic 模型后，`/docs`（Swagger UI）和 `/redoc` 自动生成，不需要手写文档

**Python Web 框架简史**：

| 框架 | 时代 | 特点 |
|------|------|------|
| Django | 2005 | 全功能"电池已包含"：ORM、Admin、模板、表单全内置 |
| Flask | 2010 | 微框架，一个.py 文件就能跑，插件扩展 |
| FastAPI | 2019 | 异步原生 + 自动文档 + 类型校验，目前 GitHub Stars 增长最快的 Python 框架 |

### 2. ASGI 服务器 Uvicorn

FastAPI 写的代码不能直接对外服务，需要一个"服务器程序"来接收网络请求并转发给 FastAPI。

**类比**：FastAPI 是厨师（做菜），Uvicorn 是服务员（接待客人、传菜）。

**WSGI vs ASGI**：

| | WSGI (2003) | ASGI (2018) |
|------|------|------|
| 代表 | Gunicorn + Flask | Uvicorn + FastAPI |
| 并发模型 | 同步，一个请求一个线程 | 异步，一个线程处理多个请求 |
| WebSocket | 不支持 | 原生支持 |
| 性能 | 受线程数限制 | 事件循环，数千并发无压力 |

Uvicorn 内部用 `uvloop`（基于 libuv，Node.js 同款事件循环库），是 Python 生态最快的 ASGI 服务器。

### 3. 环境变量 & .env 文件

代码里有些值不能写死：
- DeepSeek API Key：写到 GitHub 上就泄露，被他人盗刷
- 数据库密码：开发环境和生产环境不同
- 密钥（JWT Secret）：每个部署实例应该不一样

这些值通过**环境变量**注入。`.env` 文件存项目本地（`.gitignore` 排除），格式是 `KEY=VALUE`。

```bash
# .env 示例
DEEPSEEK_API_KEY=sk-xxxx
DATABASE_URL=sqlite:///./data/kong.db
JWT_SECRET=random-string-here
```

**常见坑**：`.env` 文件一定要加进 `.gitignore`。哪怕你的仓库是私有的，也不要上传密钥到 Git——历史记录永远删不干净。参考：GitHub 每年检测到数百万个泄露的 API Key。

### 4. pydantic-settings

Pydantic 是 Python 的数据校验库。pydantic-settings 是其子项目，专门管理配置：

```
.env 文件 → python-dotenv 读到 os.environ → pydantic-settings 校验类型 → 注入到代码
```

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    deepseek_api_key: str          # 必填，没有就报错
    deepseek_base_url: str = "https://api.deepseek.com"  # 有默认值
    jwt_expire_minutes: int = 60 * 24 * 7

    class Config:
        env_file = ".env"          # 指定配置文件位置

settings = Settings()              # 读 .env → 校验 → 生成配置对象
```

好处：如果配置写错了（比如 `JWT_EXPIRE_MINUTES=abc` 填了字符串），pydantic 在应用启动时立刻报清晰错误，而不是运行到一半崩溃。

### 5. CORS 跨域资源共享

前端跑在 `localhost:5173`（Vite），后端跑在 `localhost:8000`（Uvicorn）。浏览器出于安全考虑，默认**不允许**不同源的访问——虽然都是你自己机器，但端口不同就是"跨域"。

**什么是"源"？** 协议 + 域名 + 端口三个都相同才算同源：

| 前端 | 后端 | 是否跨域？ |
|------|------|-----------|
| `localhost:5173` | `localhost:8000` | 是（端口不同） |
| `localhost:5173` | `localhost:5173/api` | 否（同端口） |
| `kong.com` | `api.kong.com` | 是（域名不同） |

CORS 配置就是后端声明："我允许 `localhost:5173` 来访问我"。浏览器收到后端返回的特殊 Header（`Access-Control-Allow-Origin`）后放行。

**为什么浏览器有同源策略？** 假设你登录了银行网站 `bank.com`，同时打开了恶意网站 `evil.com`。如果没有同源策略，`evil.com` 可以直接发 Ajax 请求到 `bank.com` 的转账接口，浏览器会自动带上你之前登录的 Cookie——你的钱就没了。同源策略从根本上阻止了这种"跨站请求伪造"。

### 6. Vite 构建工具

你把 React 写成 `.tsx` 文件，浏览器看不懂（TypeScript 标注、JSX 语法、ES Module import），需要"翻译"成浏览器能跑的 JS/CSS。

**Vite vs 传统工具（Webpack）**：

| | Webpack | Vite |
|------|------|------|
| 开发启动 | 打包全部模块，几十秒 | 按需编译，秒开 |
| 热更新 | 随着项目变大越来越慢 | 极快（ES Module HMR） |
| 生产构建 | 自己写的打包器 | 底层用 Rollup |
| 原理 | 打包一切 | 利用浏览器原生 ES Module |

Vite 快的原因：开发时不打包。直接利用浏览器原生支持的 ES Module——你 `import` 什么它就编译什么。传统 Webpack 要先把整个项目捆成一个 bundle 再启动开发服务器。

### 7. React 组件化

Facebook 出的前端 UI 库。页面由**组件**拼成——一个聊天框、一个输入框、一个侧边栏，每个是独立组件。

**核心概念**：

- **JSX**：在 JavaScript 里写 HTML，实际被编译成 `React.createElement()` 调用
- **Props**：父组件传数据给子组件（只读）
- **State**：组件内部的可变数据，变了就触发重新渲染
- **Hooks**：`useState` 管理状态、`useEffect` 处理副作用（网络请求、定时器等）

```tsx
function Counter() {
  const [count, setCount] = useState(0);    // State
  return <button onClick={() => setCount(count + 1)}>  // JSX + Event
    Clicked {count} times
  </button>;
}
```

React 帮你管理"数据变了 → 页面自动更新"。你只管改数据，不动 DOM。

### 8. TypeScript 类型系统

JavaScript 的超集，加了**类型标注**。

```typescript
function greet(name: string): string {
  return `你好，${name}`;
}
greet("孔子");     // OK
greet(42);         // 编辑器红线：类型"number"不能赋给类型"string"
greet(undefined);  // 编辑器红线
```

**类型 vs 无类型**：
- 无类型：`function add(a, b) { return a + b }` — a 和 b 是什么？调用者靠猜
- 有类型：`function add(a: number, b: number): number` — 一眼知道参数和返回值类型

好处：写代码时有自动补全、重构时类型检查防漏改、新人接手代码时类型是最佳文档。

**常见坑**：TypeScript 的类型只在编译时存在。编译后的 JS 文件里所有类型标注消失。所以你永远不能 100% 信任类型——运行时进来的数据（API 响应、用户输入）仍需校验。这也是为什么后端用 Pydantic 做运行时校验。

### 9. Tailwind CSS

传统 CSS 写法：写类名 → 打开 CSS 文件 → 写样式 → 来回切换。Tailwind 给你几万个原子类，直接在 HTML/JSX 标签上组合：

```html
<!-- 传统写法 -->
<div class="card"><h2 class="card-title">Hello</h2></div>
<!-- 另外三个文件里写 .card { display:flex; ... } .card-title { ... } -->

<!-- Tailwind 写法 -->
<div class="min-h-screen flex items-center justify-center bg-stone-50">
  <h1 class="text-3xl font-bold text-stone-800">Hello</h1>
</div>
```

**生产构建**：Tailwind 自动删除你用不到的类，最终 CSS 只有几 KB。

### 10. shadcn/ui

不是传统 npm 包，是"复制粘贴式"组件库——运行 `npx shadcn add button`，它把 Button 组件的**源代码**写到你的项目 `src/components/ui/button.tsx`，你可以随意修改。基于 Tailwind + Radix UI（处理无障碍访问等复杂逻辑）。

**vs Ant Design vs MUI**：

| | Ant Design | shadcn/ui |
|------|------|------|
| 引入方式 | `npm install` | 复制源码到你项目 |
| 定制 | 通过 ConfigProvider 主题 | 直接改代码 |
| bundle 大小 | 全量引入很大 | 只用你 copy 的几个组件 |
| 控制力 | 厂商决定 API | 你拥有全部代码 |

### 11. Python 虚拟环境

Python 全局安装的包是所有项目共享的。项目 A 要 `fastapi==0.100.0`，项目 B 要 `fastapi==0.115.0`——全局装一个，另一个项目就坏了。

**虚拟环境**每个项目独立隔离（`.venv/` 文件夹，不上传 Git）：

```bash
python -m venv .venv                    # 创建
source .venv/Scripts/activate           # 激活（Windows Git Bash）
pip install -r requirements.txt         # 安装
deactivate                              # 退出
```

**常见坑**：`.venv/` 别提交到 Git。`.venv/` 体积通常几百 MB（含编译好的二进制轮子），且路径绝对绑定你的机器，别人 clone 下来用不了。传 `requirements.txt` 即可，别人 `pip install -r requirements.txt` 自己装。

---

## 第②步：LLM 核心

### ②-a：DeepSeek API 客户端

#### 1. API Key 是什么

你用 DeepSeek 的模型，代码通过网络请求 DeepSeek 的 GPU 服务器。API Key 是一串密钥——每个请求都带上它，服务器验明身份、按 token 用量计费。

获取：platform.deepseek.com 注册 → 充值 → API Keys 页面创建 → 复制到 `.env`。

**安全注意事项**：
- API Key 永远不要硬编码在 Python 文件里
- 永远不要提交到 Git（包括私有仓库）
- 如果泄露，立即在 DeepSeek 后台吊销重建
- 充值 10 块钱够开发测试很久（DeepSeek 是目前最便宜的大模型，百万 token 几毛钱）

#### 2. OpenAI SDK 兼容

DeepSeek 的 HTTP API 格式完全兼容 OpenAI。这意味着你可以用 OpenAI 的 Python SDK，只改 `base_url` 指向 `https://api.deepseek.com`，就能调 DeepSeek。代码写法、参数、返回值格式和调 ChatGPT 一模一样。

```python
from openai import OpenAI

# 调 ChatGPT
client = OpenAI(api_key="sk-xxx")  # base_url 默认 api.openai.com

# 调 DeepSeek —— 只改 base_url
client = OpenAI(api_key="sk-xxx", base_url="https://api.deepseek.com")

# 下面的代码完全一样
response = client.chat.completions.create(
    model="deepseek-chat",  # DeepSeek 用 deepseek-chat
    messages=[{"role": "user", "content": "你好"}],
)
```

**好处**：换模型供应商只需改配置，不重写代码。而且 OpenAI SDK 是行业标准，学会了可以调任何兼容 API（通义千问、月之暗面、DeepSeek 都兼容）。

#### 3. Chat Completion 消息角色

大模型 API 的核心接口：**Chat Completion**（聊天补全）。你给一串消息列表，模型返回一条新消息。三种角色：

| 角色 | 含义 | 在对话中的作用 |
|------|------|------|
| `system` | 系统指令（设定性格、规则、边界） | 每条对话的开头一条 |
| `user` | 用户说的话 | 每条用户消息 |
| `assistant` | 模型之前的回复 | 每轮对话一条，构成历史 |

**核心理解**：模型没有内部记忆。每次请求你必须把**完整的对话历史**传过去。

示例——三轮对话的实际请求：

```python
# 第一轮
messages = [
    {"role": "system", "content": "你是孔子。"},
    {"role": "user", "content": "什么是仁？"},
]
# → assistant: "仁者，爱人也。"

# 第二轮（必须带上第一轮的上下文！）
messages = [
    {"role": "system", "content": "你是孔子。"},
    {"role": "user", "content": "什么是仁？"},
    {"role": "assistant", "content": "仁者，爱人也。"},  # ← 历史
    {"role": "user", "content": "能举个例子吗？"},
]
```

如果不带历史，模型不记得刚说过"仁者爱人"，会答非所问。这就是为什么后面要做对话持久化——把历史存数据库，每次请求时取出来拼进 messages。

---

### ②-b：System Prompt 设计

#### 1. System Prompt 的本质

写在对话最开头，告诉模型"你是谁、怎么说话、什么该说什么不该说"。类比：User Prompt 是用户当场说的话，System Prompt 是剧组开拍前递给演员的**角色卡**。

**为什么角色卡有用？** LLM 的训练数据里有大量"孔子"相关的文本（古籍、研究论文、教材），System Prompt 的作用是把这些知识"激活"——告诉模型从哪个角度、什么语气来组织回答。

#### 2. 角色 Prompt 设计四要素

| 要素 | 作用 | 本项目做法 |
|------|------|------|
| **身份** | 你是谁 | 孔子，春秋思想家，儒家创始人，弟子三千 |
| **语气风格** | 怎么说话 | 文白夹杂，简练有哲理，自称"吾"，称对方"子" |
| **知识边界** | 什么懂什么不懂 | 精通六经和春秋历史，不懂手机电脑等现代物 |
| **行为约束** | 红线 | 不碰色情暴力政治敏感，"非礼勿言" |

#### 3. 生成参数选择

**temperature（温度 0~2）**：

| 温度值 | 效果 | 适用场景 |
|--------|------|------|
| 0.0 | 完全确定，每次同样输入输出一样 | 分类、代码生成 |
| 0.7~1.0 | 适度随机 | 事实性问答 |
| 1.1~1.3 | 较有创造力 | 角色扮演、创意写作 |
| 1.5+ | 随机性高，可能胡扯 | 头脑风暴 |

孔夫子闲聊用 1.1（角色扮演需灵活），求教时降为 0.8（引用原文要更忠实）。

**max_tokens**：限制回复长度，孔子言简意赅 1024 足够。

---

### ②-c：文本对话 API

#### 1. Router → Service → Client 三层分离

很多初学者把所有逻辑写在一个路由函数里：解析请求 → 拼 Prompt → 调 API → 返回响应。**能跑，但有两个致命问题**：
- **不可测试**：想单独验证 Prompt 拼对了没，必须真发 HTTP 请求，甚至真调 DeepSeek（花钱）
- **不可复用**：另一个路由要调 LLM，得把同样的代码复制粘贴一遍

三层分离的核心理念——**依赖倒置**：

```
Router 层  →  只做 HTTP 的事（解析请求 body、返回 HTTP 响应）
  ↓ 调用
Service 层 →  只做业务逻辑（组装消息列表、决定调哪个 Prompt、拼装上下文）
  ↓ 调用
Client 层  →  只做和外部 API 通信（DeepSeek）
```

每一层不知道自己的上层。测试时可以 Mock 掉下层——Service 测试不用真调 API，Router 测试不用真连 Service。

**面试时怎么说**："采用分层架构实现关注点分离。Router 负责 HTTP 协议层面，Service 封装业务逻辑，Client 隔离外部 API 依赖。各层可独立单元测试，Client 可 Mock 替换。"

#### 2. Pydantic 模型 & JSON Schema

Pydantic 定义请求/响应体的"形状"：

```python
class ChatRequest(BaseModel):
    message: str
```

背后自动生成 JSON Schema——描述 JSON 数据应该长什么样：

```json
{
  "type": "object",
  "properties": {"message": {"type": "string"}},
  "required": ["message"]
}
```

FastAPI 在收到请求时，拿 Schema 和实际 body 对比：

| 输入 | 结果 |
|------|------|
| `{"message": "你好"}` | 通过 |
| `{"msg": "你好"}` | 422，提示 `message` 是必填 |
| `{"message": 123}` | 422，提示 `message` 必须是 string |
| `{"message": ""}` | 通过（空字符串也是 string，需业务逻辑判断） |

**关键**：JSON Schema 把"类型校验"从业务代码抽出来，请求到达时立刻校验。业务代码拿到 `request.message` 时已保证是 `str`，不必写 `if not isinstance(...)`。

#### 3. OpenAPI 规范 & Swagger

FastAPI 读取所有 Pydantic 模型 → 生成 OpenAPI JSON → Swagger UI（`/docs`）渲染成交互文档。不仅是文档，前端团队可用 `openapi-typescript` 从 OpenAPI JSON 自动生成 TypeScript 类型和 API 调用函数——后端改接口，前端自动发现类型不对。

#### 4. async/await 深入理解

Python 的 `async def` 不是"让函数更快"，而是**让函数主动让出 CPU**。

**同步的问题**：

```
函数A 发 HTTP 请求去 DeepSeek → 等 2 秒（CPU 空转，啥也不干） → 拿到结果 → 继续执行
                                 ↑ 这 2 秒的 CPU 全浪费了
```

**异步的解决方案**：

```
函数A 发 HTTP 请求 → await（"我先不等着，有事叫我"）
  → 事件循环发现 B 有请求进来 → 处理 B
  → B 也 await 了 → 处理 C
  → ... DeepSeek 返回 A 的结果 → 事件循环唤醒 A → A 从 await 处继续
```

**餐厅类比**：
- 同步：服务员站后厨门口等菜做好（什么都不干） → 端给客人 → 才去服务下一位
- 异步：服务员挂单后立刻回来服务下一位 → 哪个菜做好端哪个

**实际请求时间线**：

```
0ms   A 发请求 → 协程 A 挂起
1ms   B 发请求 → 协程 B 挂起
      ... DeepSeek 处理中 ...
800ms A 的结果回来 → 事件循环唤醒 A → 返回响应
850ms B 的结果回来 → 事件循环唤醒 B → 返回响应
```

一个进程，一个线程，同时服务多人。`await` 解决自己进程不阻塞，**不能**解决 DeepSeek 服务器本身的并发上限。

**常见坑**：在 `async def` 里调用同步阻塞函数（如 `time.sleep(5)`），会把整个事件循环卡住 5 秒——这期间所有其他请求全堵住。同步阻塞操作要用 `await asyncio.to_thread(func)` 扔到线程池。

---

## 第③步：SSE 流式输出

### 1. 为什么需要流式

LLM 是自回归的：预测一个 token → 拼到已有文本 → 预测下一个 → 直到结束。每个 token 都可以立刻发给前端。

```
非流式：用户点发送 → 等 2-3 秒（空白） → 整段回复一次性出现
流式：  用户点发送 → 立刻看到"学" → "而" → "不" → "思" → ... 逐字出现
```

用户的体感完全不同——"正在生成"比"空白等待"好一百倍。

### 2. SSE vs WebSocket

| | SSE | WebSocket |
|------|------|------|
| 通信方向 | 单向：服务器→客户端 | 双向：客户端↔服务器 |
| 协议层 | 普通 HTTP（`text/event-stream`） | 独立协议`ws://`（Upgrade 握手） |
| 浏览器 | `EventSource` API，自动重连 | 需要库（如 `ws`），自己写重连 |
| 防火墙 | 走 HTTP 端口，100% 兼容 | 部分企业防火墙拦截 |
| 复杂度 | 极简 | 需要管理连接状态、心跳 |

AI 流式输出场景只需服务端往客户端推 token，SSE 完美匹配。

**SSE 数据格式**：

```
Content-Type: text/event-stream

data: {"token":"学"}

data: {"token":"而"}

data: [DONE]
```

每条 `data:` 后面跟一行数据，空行分隔事件。前端 `EventSource` 自动按 `message` 事件解析。

### 3. Python 异步生成器

普通函数 `return` → 执行完、返回一个值、结束。生成器 `yield` → 每 `yield` 一个值暂停一次，外面消费掉后从暂停处继续。

```python
# 普通函数
def get_reply():
    return "整段回复"   # 一次性返回

# 生成器
async def stream_reply():
    async for token in llm_stream:
        yield f"data: {token}\n\n"   # 每拿到一个 token 立刻推出去
    yield "data: [DONE]\n\n"
```

类比：普通函数是厨师做完一整道菜才端上桌；生成器是厨师做好一口立刻送到桌前，回去做下一口。

FastAPI 中，`StreamingResponse(generator, media_type="text/event-stream")` 创建 SSE 连接，框架持续从生成器取值并写入 HTTP 响应流。

### 4. Sync vs Async OpenAI 客户端

| | `OpenAI` | `AsyncOpenAI` |
|------|------|------|
| 调用方式 | `client.chat(...)` 同步阻塞 | `await client.chat(...)` 异步非阻塞 |
| 流式 | 同步迭代器 | 异步迭代器 `async for` |
| 适用 | CLI 脚本、非流式端点 | FastAPI 异步路由、流式端点 |

我们的 `client.py` 同时持有两个实例——`_client`（同步，闲聊用）和 `_async_client`（异步，流式用）。

### 5. 常见踩坑

**坑：SSE 中 JSON 特殊字符**。如果 LLM 生成的 token 里包含换行符、引号、反斜杠，直接拼到 SSE 消息中会破坏 JSON 结构：

```
// 错误：token 包含换行符
data: {"token":"第
二"}

// EventSource 解析失败，JSON 断掉了
```

解决：输出前对 token 做转义：

```python
token.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
```

前端拿到后用 `JSON.parse(event.data)` 自动解转义。

---

## 第④步：知识库构建（RAG 引擎）

### 1. RAG 是什么

**RAG = Retrieval-Augmented Generation = 检索增强生成**。

```
无 RAG：用户提问 → LLM 凭训练记忆回答（可能编造论语句子）
有 RAG：用户提问 → 搜知识库 → 原文+问题 → LLM 有据可依
```

类比：无 RAG 是闭卷考试（靠记忆，可能记错），有 RAG 是开卷考试（翻书查资料，准确度高）。

### 2. Embedding（向量化）原理

你怎么在 500 条论语句子里找到"最相关的 5 条"？文本搜索只能精确匹配。用户问"光学习不思考有什么坏处？"——没有"学而不思"四个字，零匹配。但语义上完全相关。

**Embedding 就是给文本拍"语义身份证"**——转成一串 1024 个数字（向量），语义相近的文本数字也相近：

```
"学而不思则罔"         → [0.12, -0.34, 0.78, ...]
"光学习不思考有什么坏处" → [0.15, -0.31, 0.75, ...]
                          ↑ 两个向量很接近
"今天天气很好"          → [0.89, 0.23, -0.45, ...]
                          ↑ 完全不一样
```

**BGE-large-zh**（BAAI General Embedding）是智源研究院训练的中文 Embedding 模型，开源、本地运行、专门为中文优化。1024 维向量，L2 归一化后适合余弦相似度检索。

### 3. 最近邻搜索原理

把每个 embedding 想成 1024 维空间里一个点。相似文本的点挨得近。检索就是找离查询点最近的 K 个邻居。

**暴力搜索 vs 近似搜索**：

| | 暴力搜索 (Brute Force) | ANN (HNSW) |
|------|------|------|
| 精度 | 100%，真正的最远邻 | ~95%，"够近"即可 |
| 速度 (500条) | < 1ms | < 0.1ms |
| 速度 (100万条) | 几秒，不可用 | < 10ms |
| 原理 | 每条算一次距离，排序 | 多层图索引，跳跃搜索 |

ChromaDB 默认用 **HNSW**（Hierarchical Navigable Small World）索引。HNSW 原理像"六度分隔"：

1. 先找"大 V"——高层跳跃节点，和谁都认识
2. 大 V 指路：你要找的人在 XX 圈子里
3. 进入该圈子的密集层，精确搜索
4. 返回最近邻居

面试时说得出 HNSW 的原理，够用了。

### 4. 余弦相似度（不推公式）

两个向量之间的"夹角"越小，语义越相近。

```
学而不思向量 →
                 ↘ 夹角小 = 相似
学而思向量    →
                  ↓
                  今天天气好向量 → 夹角接近 90° = 无关
```

用余弦而不是直接用点积的原因：余弦只看方向（语义），不看长度（文本长短）。一句话和一篇文章，只要说同一个话题，余弦相似度高。

### 5. 向量数据库 ChromaDB

传统数据库擅长 `WHERE name = '孔子'` 或 `WHERE age > 20`。但 `WHERE embedding SIMILAR TO user_query`——传统数据库没有"相似度搜索"能力。

向量数据库专门存向量，核心操作是相似度检索。

| 向量库 | 特点 | 适用 |
|--------|------|------|
| ChromaDB | Python 原生，轻量持久化 | 开发 + 小规模生产 |
| FAISS | Meta 出品，极快 | 大规模，需自管持久化 |
| pgvector | PostgreSQL 扩展 | 已有 PG 的项目 |
| Milvus | 分布式向量库 | 十亿级数据 |

本项目 500 条数据，ChromaDB 绰绰有余。比 FAISS 方便（自带持久化），比 pgvector 轻量（不需装 PG）。

### 6. 分块策略

把长文本切成 chunk，每条独立存。太大语义混杂，太小丢上下文。

《论语》天然适合按**章**分块——每章一句到一段，语义完整，边界清晰。`lunyu.json`：20 篇 → 512 章 = 512 个 chunk。

### 7. RAG 全流程

**离线索引（启动时）**：
```
lunyu.json → 按章分块 → BGE 向量化 → ChromaDB 存 data/chroma/
```

**在线检索（每次请求）**：
```
用户提问 → BGE 向量化 → ChromaDB.top_k(5) → 格式化为编号列表
 → 注入 Prompt → DeepSeek → 回复 + 引用来源
```

### 8. 为什么 RAG 抑制"幻觉"

LLM 本质是"续写"——根据训练数据里的模糊记忆预测下一个 token。记忆可能错、混、不确定。

RAG 把确切的原文直接放在 LLM 眼前——不需要回忆，直接读。从根源上减少编造。面试术语："通过可信外部知识源约束模型生成，降低事实性错误（hallucination）"。

### 9. 常见踩坑

**坑 1：HuggingFace 在国内被墙**。`sentence-transformers` 默认从 huggingface.co 下载模型，国内超时。解决：用 ModelScope（modelscope.cn，阿里国内服务器）作为下载源。

```python
from modelscope import snapshot_download
model_dir = snapshot_download("BAAI/bge-large-zh-v1.5", cache_dir="E:/ai-models")
```

**坑 2：BGE 模型 1.21GB 占 C 盘**。`sentence-transformers` 默认缓存到 `C:\Users\<user>\.cache\huggingface\`。解决：通过 `cache_folder` 参数指定到空间多的盘。

**坑 3：ChromaDB 检索返回欧氏距离而非相似度**。距离越小越相似，但给前端展示"距离=0.3"不够直观。解决：转成 `1 / (1 + distance)`，映射到 0~1 区间，越大越相关。

---

## 第⑤步：RAG 检索集成

### 1. 完整管道

```
用户提问
  → BGE 向量化（1024维）
  → ChromaDB 检索 Top-5
  → 格式化为编号列表："1. 《学而篇》第1章: 子曰：..."
  → 注入 RAG Prompt（System + Context + Question）
  → DeepSeek 生成回复（temperature=0.8，比闲聊低）
  → 返回 {"reply": "...", "sources": [...]}
```

### 2. Context 格式化

检索的 5 条结果（原文+篇名+序号）→ 编号列表 → 注入 Prompt。这样 LLM 可以精确引用来源。

### 3. 来源引用机制

非流式返回 JSON 的 `sources` 字段；流式在 token 推完后发 `[SOURCES]` 事件。

### 4. 温度差异

| 模式 | temperature | 原因 |
|------|-------------|------|
| 闲聊 | 1.1 | 语气更自然 |
| 求教 | 0.8 | 忠实原文，减少编造引用 |

温度低一点，模型更保守，更倾向于直接使用 Prompt 里提供的论语句子。

---

## 第⑥步：意图路由

### 1. 为什么需要意图路由

步骤⑤之后有 4 条端点（/send、/stream、/ask、/ask/stream）。用户需自己判断"我该调闲聊端点还是求教端点"——不合理。一个入口，系统自动分流。

### 2. 用 LLM 做二分类

极简 Classify Prompt，LLM 只输出一个字（"求教"或"闲聊"）。配置 `temperature=0.0, max_tokens=4`，一次 ~100 tokens，几乎免费。

### 3. 分类策略设计哲学

**核心原则**：分类不是"问知识 vs 不是问知识"，而是**"引用论语能否让回答更好？"**

```
能 → 走 RAG（求教）
不能 → 纯聊天（闲聊）
```

**宁愿多检索，不可漏检索**。即使检索结果不相关，LLM 也可忽略上下文直接用自己话回答，不会出大错。

### 4. Example-Driven Prompting

Classification Prompt 里放了 3 个 Few-Shot 示例：

```
用户消息：你好啊孔子
类别：闲聊

用户消息：学而时习之是什么意思
类别：求教

用户消息：面试失败了，好迷茫
类别：求教
```

第三个示例故意选了"面试失败"——它没有问号，没有"什么意思"这样的知识请求标记，但它入选"求教"是因为论语有"岁寒知松柏""君子坦荡荡"可引用。这个示例教 LLM 我们的分类边界偏宽泛。

### 5. 路由架构

```
POST /api/chat/smart
         │
         ▼
   classify_intent(message)
         │
    ┌────┴────┐
    ▼         ▼
  闲聊      求教
    │         │
    ▼         ▼
generate   generate
_reply     _rag_reply
```

### 6. 常见踩坑

**坑：分类 Prompt 太简单导致误判**。如果只写"求教=问论语，闲聊=聊天"，"面试失败了好迷茫"会被判为闲聊——因为它不是在问论语。解决方法：在 Prompt 的示例里放边界 case，用示例（Few-Shot）引导模型理解你想要的行为。

---

## 第⑦步：用户系统（JWT 认证）

### 1. 为什么不能存明文密码？

如果你把密码直接存数据库：

```
users 表
| username | password |
|----------|----------|
| 张三     | 123456   |
| 李四     | password |
```

**数据库一旦泄露，所有人的密码全部暴露。**而且大多数人多个网站用同一个密码——你泄露的不只是自己系统的安全，是用户整个数字身份的安全。

**哈希（Hash）**是单向函数——明文→哈希很容易，哈希→明文数学上不可能：

```
"123456"  →  bcrypt →  $2b$12$LJ3m4XNq9k...（一堆乱码）
"123456"  →  bcrypt →  $2b$12$Xk9qW7Pm3...（不同的乱码！）
```

用户登录时，把输入的密码用同一算法哈希一次，和数据库存的哈希值比对。数据库里永远没有明文。

**什么叫"加盐（SALT）"？** 同一个密码 "123456"，我和你哈希之后应该不一样——否则攻击者可以预先算好常见密码的哈希表（彩虹表），看到哈希值直接反查明文。加盐就是在每个密码后面随机拼接一段字符串再哈希，确保即使两个用户用了相同密码，哈希结果也完全不同。bcrypt 自动帮你加了盐，存进哈希值里。

### 2. 哈希函数选型：为什么是 bcrypt？

| 哈希函数 | 特点 | 适合密码？ |
|----------|------|-----------|
| MD5 | 极快，已被破解 | 绝不能用 |
| SHA-256 | 快，通用 | 不适合——太快了反而容易被暴力破解 |
| bcrypt | **故意慢**，内置加盐 | 专为密码设计 |
| argon2 | 最新，内存密集防 GPU 破解 | 更安全但依赖重 |

bcrypt 的核心优势：**刻意慢**。验证一个密码要 ~0.1 秒——用户登录多等 0.1 秒毫无感觉，但攻击者想暴力穷举 100 万个密码就要 27 个小时。通过 `cost factor`（工作因子）可以调整慢的程度。

### 3. JWT (JSON Web Token) 深入原理

HTTP 是**无状态协议**——每次请求互不关联。服务器收到第 1 次和第 2 次请求，不知道是不是同一个人发的。

传统方案是 Session：服务器存一份用户状态（内存或 Redis），发一个 Session ID Cookie 给浏览器。缺点：服务器要维护状态，分布式部署时要共享 Session，是"有状态"的。

JWT 方案：**把用户信息放在 Token 里，服务端不存任何东西**。任何拿到 Token 的服务节点都能独立验证。

**JWT 结构**（三个 Base64 字符串用 `.` 连接）：

```
eyJhbGciOiJIUzI1NiJ9  .  eyJzdWIiOiIxIiwiZXhwIjoxNzQ3...  .  SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c
      HEADER                        PAYLOAD                           SIGNATURE
```

- **HEADER**：`{"alg":"HS256","typ":"JWT"}` — 签名算法
- **PAYLOAD**：`{"sub":"1","exp":1747000000}` — 用户 ID、过期时间等（不加密！）
- **SIGNATURE**：用密钥算出来的签名 = `HMAC-SHA256(header + "." + payload, SECRET)`

**关键理解："签名"不是"加密"**。

Payload 是 Base64 编码，任何人都可以解码看到内容（去 jwt.io 试一下）。但 Signature 是用密钥算出来的——如果你改了 Payload 里的 user_id，签名就对不上了，服务器立即拒收。

**所以**：JWT 防**篡改**，不防**偷看**。Payload 里绝不能放密码、银行卡号等敏感数据。

### 4. JWT 完整登录流程

以本项目为例，走一遍完整链路：

```
=== 注册 ===
用户 → POST /api/auth/register {"username":"kongzi","password":"lunyu123"}
  → bcrypt.hashpw("lunyu123") → "$2b$12$..."
  → INSERT INTO users(username, password_hash) VALUES('kongzi','$2b$12$...')
  → 返回 {"id":1,"username":"kongzi"}    (201 Created)

=== 登录 ===
用户 → POST /api/auth/login {"username":"kongzi","password":"lunyu123"}
  → SELECT FROM users WHERE username='kongzi'
  → bcrypt.checkpw("lunyu123", "$2b$12$...") → True  ✓
  → 签发 JWT：payload={"sub":"1","exp":1748000000}，用 SECRET 算签名
  → 返回 {"access_token":"eyJhbGci...","token_type":"bearer"}

=== 后续请求 ===
用户 → GET /api/auth/me
  → 请求头带：Authorization: Bearer eyJhbGci...
  → 服务端解析：jwt.decode(token, SECRET)
  → 签名校验通过，exp 未过期
  → 取 payload.sub = "1" → SELECT FROM users WHERE id=1
  → 返回 {"id":1,"username":"kongzi"}
```

### 5. 常见踩坑记录

**坑 1：passlib 与 bcrypt 5.x 不兼容**

passlib 1.7.4 是 2020 年的老版本，调用 `bcrypt.__about__.__version__` 这个属性。但 bcrypt 5.x 删掉了 `__about__` 模块，导致 `AttributeError`。解决方案：不用 passlib，直接用 `bcrypt.hashpw()` / `bcrypt.checkpw()`。

```python
# 不用 passlib
hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
check = bcrypt.checkpw(password.encode(), hash.encode())
```

**坑 2：PyJWT 密钥太短**

HS256 算法要求密钥 ≥32 字节（256 位）。`"change-me-in-production"` 只有 23 个字符，PyJWT 发出 `InsecureKeyLengthWarning`，且可能在解码时拒绝。解决方法：用至少 32 字符的随机密钥，生产环境更要用 `secrets.token_hex(32)` 生成。

**坑 3：Windows 时钟偏差导致 JWT iat 失败**

JWT 的 `iat`（Issued At）表示签发时间。如果服务器时钟比签发时慢（哪怕几秒），`iat` 看起来在未来，PyJWT 拒绝验证，报 `"The token is not yet valid (iat)"`。这在 Windows 虚拟机/云主机上尤其常见。

解决方法：不要放 `iat` 字段。`exp`（过期时间）才是安全关键——即使有轻微时钟偏差，只要过期时间设置足够远（7天），就不会误判。如果确实需要 iat，加 `leeway` 参数容忍偏差：

```python
jwt.decode(token, secret, leeway=60)  # 容忍60秒偏差
```

### 6. FastAPI 依赖注入做鉴权

传统的鉴权方式：每个路由函数里复制粘贴"取 token → 解析 → 查用户"的代码。FastAPI 的 `Depends` 机制把鉴权抽象成独立函数：

```python
def get_current_user(token = Depends(bearer_scheme), db = Depends(get_db)) -> User:
    user_id = decode_token(token.credentials)
    return db.query(User).filter(User.id == user_id).first()

# 受保护的路由：鉴权干净的，只写业务逻辑
@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {"id": user.id, "username": user.username}
    # 到这里时 token 已校验通过，user 已从数据库取出
    # 任何鉴权失败（过期/伪造/用户不存在）已在 Depends 里抛出 401
```

**类比**：`Depends` 是大楼门禁。路由函数上装了门禁，FastAPI 执行业务逻辑前先过门禁——token 不合法？直接 401，根本进不了业务代码。

### 7. SQLite 的线程安全注意事项

SQLite 默认不支持多线程并发写。FastAPI 的同步路由（`def` 而非 `async def`）会被放进线程池运行，可能多线程同时访问 SQLite。

解决：连接时加 `check_same_thread=False`：

```python
engine = create_engine("sqlite:///./data/kong.db", connect_args={"check_same_thread": False})
```

这只对 SQLite 需要。如果后面迁移到 PostgreSQL，去掉这个参数即可。

---

## 第⑨步：前端聊天界面

### 1. 浏览器 SSE 接收方案

第③步后端实现了 SSE 流式输出（`text/event-stream`）。浏览器有原生 `EventSource` API：

```typescript
const es = new EventSource("/api/some/stream");
es.onmessage = (event) => console.log(event.data);
```

**问题**：`EventSource` 只支持 GET，不能传 request body。而我们的流式端点 `POST /api/chat/stream` 需要传 `{"message":"你好","conversation_id":null}`，所以 EventSource 不可用。

**解决方案：fetch + ReadableStream 手动解析 SSE**：

```typescript
const response = await fetch("/api/chat/stream", {
  method: "POST",
  headers: { "Content-Type": "application/json", Authorization: "Bearer ..." },
  body: JSON.stringify({ message: "你好" }),
});

const reader = response.body!.getReader();
const decoder = new TextDecoder();

while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  const text = decoder.decode(value);
  // 手动解析 SSE 格式：
  for (const line of text.split("\n")) {
    if (line.startsWith("data: ")) {
      const payload = line.slice(6);
      if (payload === "[DONE]") { /* 结束 */ }
      else if (payload.startsWith("[SOURCES]")) { /* 引用 */ }
      else {
        const { token } = JSON.parse(payload);
        // 追加到消息末尾
      }
    }
  }
}
```

这就是 ChatGPT、Claude 前端的底层机制——不是 WebSocket，不是 EventSource，而是 **fetch + ReadableStream + 逐行解析 SSE 事件**。

### 2. React 聊天页面的状态设计

四种核心状态：

| 状态 | 类型 | 说明 |
|------|------|------|
| `messages` | `MessageVM[]` | 完整消息列表（用户 + 助手，渲染用） |
| `input` | `string` | 输入框当前内容 |
| `isStreaming` | `boolean` | 是否正在流式生成中 |
| `streamingToken` | `string` | 当前流式生成中的内容（逐字累加） |

**流式渲染的特殊处理**：LLM 逐字生成时，assistant 回复还不完整。在消息列表底部放一条"构建中"的消息，token 不断追加：

```
初始：[user: "什么是仁？", assistant: ""]
      [user: "什么是仁？", assistant: "仁"]
      [user: "什么是仁？", assistant: "仁者"]
      [user: "什么是仁？", assistant: "仁者，爱人"]
结束： 将 streamingToken 转为正式 assistant 消息，加入 sources
```

**实现方式**：`streamingToken` 作为独立 state，不在 messages 数组里。`displayMessages` 计算属性在渲染时把 streamingToken 追加到末尾。流式结束后（`isStreaming` → `false`），正式加入 messages。

### 3. 自动滚动到底部

每次有新消息（或 streamingToken 变化）时自动滚：

```tsx
const messagesEndRef = useRef<HTMLDivElement>(null);
const scrollToBottom = () => {
  messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
};

useEffect(() => {
  scrollToBottom();
}, [messages, streamingToken]);

// JSX 底部放一个空 div 作为滚动锚点
<div ref={messagesEndRef} />
```

核心：`useRef` 指向消息列表底部的一个不可见 `<div>`，内容变化时自动 `scrollIntoView`。

### 4. 流式请求的取消（AbortController）

用户如果等不及，在回复生成中又发了新消息——必须取消上一个请求：

```typescript
const abortRef = useRef<AbortController | null>(null);

function sendMessage(text: string) {
  abortRef.current?.abort();  // 取消旧的
  const controller = new AbortController();
  abortRef.current = controller;

  fetch("/api/chat/stream", {
    method: "POST",
    body: JSON.stringify({ message: text }),
    signal: controller.signal,  // ← 绑定
  });
}
```

`AbortController` 的 `signal` 传给 `fetch`，调 `abort()` 时浏览器立即断开连接，`ReadableStream` 抛出 `AbortError`。

### 5. 组件结构

```
App.tsx (路由)
├── /login → Login.tsx   登录/注册页
└── /      → Chat.tsx    主聊天页
                ├── 侧边栏
                │   ├── "新对话"按钮
                │   └── 对话列表（点切换、hover删）
                ├── 消息列表
                │   └── 消息气泡 × N
                │       ├── 头像（子/孔）
                │       ├── 内容（markdown风格）
                │       └── 引用来源
                └── 输入区
                    ├── Input 输入框（Enter发送）
                    └── Button 发送按钮
```

### 6. 常见踩坑

**坑 1：shadcn v4 依赖 `@base-ui/react`**

shadcn v4 的组件底层从 Radix UI 迁移到了 `@base-ui/react`。用 `npx shadcn add` 生成组件后，必须手动 `npm install @base-ui/react`、`class-variance-authority` 等底层依赖，否则构建报 `Failed to resolve import`。

**坑 2：shadcn `@` 路径别名在 Windows 上变成字面目录**

`npx shadcn add` 在 Windows 上把文件写到 `@\components\ui\` 而非 `src\components\ui\`。原因：shadcn CLI 未正确解析 tsconfig 的 paths 别名。每次用 `shadcn add` 后，手动 `mv` 文件到正确位置。

**坑 3：流式结束后的 state 更新时序**

流式结束（`onDone` 回调）时，`streamingToken` 还存着最后几个 token，直接加入 messages 可能不完整。需要：`onDone` → 设 `isStreaming=false` → `useEffect` 检测变化 → 将 streamingToken 转为正式消息。靠 effect 确保所有 token 都已被累加。

**坑 4：`useCallback` 闭包陷阱**

`handleSend` 用 `useCallback`，但依赖 `input`、`messages`、`isStreaming`——任何一个变化都会重建函数。如果依赖不全，`handleSend` 里读到的可能是过期值。依赖数组必须包含 `[input, isStreaming, messages, currentConvId]`。

---

## 第⑧步：对话持久化

### 1. 为什么需要对话持久化

第②-b 讲过：LLM 没有内部记忆，每次请求必须把完整对话历史传过去。如果不存历史：

```
用户："什么是仁？"   → 孔子回答
用户："举个例子"     → 孔子："举个例子"指什么？不懂你的意思
```

因为模型不知道上一轮说了"仁"。

**解决**：每次对话存数据库，下次请求时查历史，拼进 messages 传给 LLM。

### 2. 数据关系设计

两级一对多关系：User → Conversations → Messages：

```sql
-- 一个用户可以有多个对话
users 1 ──── N conversations

-- 一个对话可以有多条消息
conversations 1 ──── N messages
```

实际表结构：

```
users: id | username | password_hash | created_at

conversations: id | user_id(FK) | title | created_at | updated_at

messages: id | conversation_id(FK) | role | content | sources(JSON) | created_at
```

### 3. SQLAlchemy ORM 关系（Relationship）

ORM 不是简单存外键，还能定义对象之间的导航关系：

```python
class User(Base):
    conversations = relationship("Conversation", back_populates="user")
    # user.conversations → 直接拿到用户所有对话（Python 列表）

class Conversation(Base):
    user_id = Column(ForeignKey("users.id"))
    user = relationship("User", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation",
                            cascade="all,delete",          # 删对话自动删消息
                            order_by="Message.created_at") # 消息按时间排序
    # conversation.user → 对话所属用户
    # conversation.messages → 对话的所有消息

class Message(Base):
    conversation_id = Column(ForeignKey("conversations.id"))
    conversation = relationship("Conversation", back_populates="messages")
```

**`cascade="all,delete"` 的含义**：当你 `db.delete(conversation)` 时，SQLAlchemy 自动删除该对话的所有消息。如果没有这个，删对话后消息变成"孤儿数据"（`conversation_id` 指向一个不存在的对话），数据库完整性被破坏。

**`order_by="Message.created_at"`**：访问 `conversation.messages` 时自动按时间排序，不需要每次手动 `.order_by()`。

### 4. 对话生命周期

| 操作 | 触发 | 做什么 |
|------|------|------|
| **创建** | 用户首次发消息（不传 conversation_id） | `create_conversation()` → 新建 Conversation 行 |
| **追加** | 同一对话继续发 | `add_messages()` → 存 user + assistant 消息，更新 updated_at |
| **列表** | 前端加载侧栏 | 查当前用户所有对话，按 updated_at 降序 |
| **详情** | 用户点进对话 | 查全部消息 + 拼成 LLM messages 格式 |
| **删除** | 用户点删除 | `db.delete(conv)` → cascade 删所有消息 |

### 5. 上下文窗口管理

约定保留最近 **10 轮（20 条消息）**。具体实现：

```python
MAX_HISTORY_MESSAGES = 20  # 10轮 × 2条/轮

def get_chat_history(db, conversation_id):
    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())  # 倒序
        .limit(MAX_HISTORY_MESSAGES)          # 只取最近20条
        .all()
    )
    messages.reverse()  # 再正序回来
    return [{"role": m.role, "content": m.content} for m in messages]
```

**为什么取倒序再 reverse？** SQL 的 `LIMIT` 截取前 N 条。如果正序取前 20 条，拿的是最早的消息，最近的反被裁掉。倒序取最新 20 条，再 reverse 成正序——保证拿到的是最新 20 条。

**为什么数据库不删旧消息？**旧消息只是不传给 LLM，数据库中保留完整历史。用户翻看历史对话时能看到全部内容。

### 6. RAG Prompt 拆分重构

原来的 RAG Prompt 模板把 System Prompt 嵌在用户消息里。引入历史消息后，消息结构统一为：

```
[
  {"role": "system", "content": "你是孔子..."},        ← System Prompt
  {"role": "user", "content": "什么是仁？"},            ← 历史
  {"role": "assistant", "content": "仁者，爱人也..."},   ← 历史
  {"role": "user", "content": "## 参考知识\n...(检索结果)\n用户问题：举个例子"},  ← 当前
]
```

System Prompt 必须是独立的第一条消息——LLM 从第一条 system 消息中读取角色指令，后续 user/assistant 交替构成对话历史。拆开后结构清晰，每层职责分明。

### 7. 常见踩坑

**坑 1：首条消息重复保存**。`create_conversation()` 创建对话时如果也插入首条消息，后续 `add_messages()` 又存一遍，导致数据库里两条相同的 user 消息。

**正确做法**：创建对话只建 Conversation 行（标题取首条消息前 30 字），消息统一由 `add_messages()` 存。

**坑 2：依赖注入时 db session 生命周期**。FastAPI 的 `Depends(get_db)` 在每个请求结束时自动关闭 session。如果你把 `db` 对象传到后台任务（比如流式结束后存消息），session 可能已关闭。

**本项目处理**：流式端点用 `_stream_with_save()` 包装——在流全部结束后（async for 循环完成）再调 `add_messages()`。此时请求还没结束，session 仍然有效。

**坑 3：对话归属校验**。两个用户 A 和 B 都登录了，A 不能访问 B 的对话。必须在每个对话查询中验证 `conv.user_id == current_user.id`，否则是越权漏洞。

---

## 第⑩步：前端登录增强

### 1. 路由守卫

用户没登录时，受保护页面不应显示"请先登录"按钮，而是自动跳转到 `/login`。

```tsx
function ProtectedRoute({ children }: { children: React.ReactNode }) {
  if (!getToken()) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}
```

`<Navigate>` 是 React Router 的声明式跳转组件，渲染时立刻导航。`replace` 参数表示替换当前历史记录（用户不能"返回"到受保护页面）。

原理：守卫组件本身不渲染任何 UI，只做判断——有 token = 渲染子组件，无 token = 跳转。

### 2. 表单状态机

登录表单不只是"成功/失败"：

```
初始 → 提交中(loading) → 成功 → 跳转首页
                      → 失败 → 显示红色错误 → 用户重试 → 回到初始
```

实现：一个 `isLoading` state 控制全局：
- `isLoading=true` → 按钮显示 spinner + "登录中..."，输入框禁用
- `isLoading=false` + `error` → 显示错误提示

### 3. 客户端校验

发请求前检查输入合法性，减少不必要的网络往返：

```typescript
function validate(username: string, password: string): string | null {
  if (username.length < 2) return "用户名至少2个字符";
  if (password.length < 6) return "密码至少6个字符";
  return null;
}
```

客户端校验是体验优化，不是安全措施——后端仍然有完整校验。好处：用户不用等网络往返才知道"密码太短"。

---

## 第⑪步：工程化收尾

### 1. Docker 核心概念

**问题**：项目在你电脑能跑。换别人电脑——Python 版本不同、Node 不同、没装依赖——大概率崩。

**Docker 解决**：把代码 + 依赖 + 运行环境打包成标准镜像，任何装了 Docker 的机器上一条命令跑起来。

三大概念：

| 概念 | 类比 | 本项目 |
|------|------|------|
| **Dockerfile** | 菜谱 | 用 Python 3.13 做基底，装依赖，启动 uvicorn |
| **镜像** | 做好的菜的照片 | 用 Dockerfile build 出来的只读包 |
| **容器** | 端上桌的菜 | 镜像跑起来的实例，可读写分离 |

### 2. docker-compose

项目有后端和前端两个独立服务。docker-compose 一条命令启动全部：

```yaml
services:
  backend:
    build: ./backend
    ports: ["8000:8000"]
    volumes: [kong_data:/app/data]  # 持久化数据，不随容器删除而消失
  frontend:
    build: ./frontend
    ports: ["80:80"]
    depends_on: [backend]  # 等后端先启动
```

`docker compose up -d` → 两个容器同时启动，前端 80 端口暴露。

### 3. 前端 nginx 托管

开发时 Vite dev server。生产环境用 nginx 托管静态文件 + 代理 API 请求：

```
浏览器 → http://localhost/       → nginx → /usr/share/nginx/html/index.html
浏览器 → http://localhost/api/chat → nginx → proxy_pass http://backend:8000
```

nginx.conf 关键配置：
- `try_files $uri /index.html` — SPA 路由回退，所有路径交给 React Router
- `proxy_buffering off` — SSE 流式支持，禁用缓冲
- `location /api/` — 所有 `/api/*` 请求代理到后端

### 4. Docker Compose 一键启动

```bash
echo "DEEPSEEK_API_KEY=sk-xxxx" > .env   # 只需配一次
docker compose up -d                      # 启动
docker compose down                       # 停止
```

浏览器打开 `http://localhost`，前端 80 端口对外。

### 5. Docker 常见踩坑

**坑 1：Windows 路径语法**。docker-compose 的 volumes 使用 Linux 路径格式（`/app/data`），即使是 Windows 宿主，容器内部是 Linux 文件系统，所有路径用 `/`。

**坑 2：BGE 模型在 Docker 中的位置**。本地开发 BGE 模型缓存在 `E:/ai-models`。Docker 容器内路径为 `/app/models_cache`（通过 volume 挂载）。需要在 `docker-compose.yml` 中通过环境变量 `MODEL_CACHE_DIR=/app/models_cache` 覆盖。

**坑 3：首次启动时知识库初始化**。Docker 容器启动时 `data/` 目录为空，需要先运行一次知识库构建。下次可以把 `data/` 挂载为 volume 保持持久化。

---

> 本文档随项目开发持续更新
