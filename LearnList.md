# AI 应用开发学习路线

> 基于本项目（孔夫子 AI 聊天助手）从初级到中级，AI 核心 → 后端 → 运维，循序渐进。

---

## 阶段一：LLM 基础（初级）

- [x] **1.1 Token 是什么** — 为什么中文一个字可能2-3个token？tokenizer 是怎么切词的？
- [x] **1.2 Chat Completion 原理** — system/user/assistant 三种角色、消息列表不是"记忆"
- [x] **1.3 API 调用全链路** — 前端发请求到拿到回复，经过了哪些层？
- [x] **1.4 temperature & top_p 调优** — 什么时候高/低？对角色扮演的影响？

## 阶段二：Prompt Engineering

- [x] **2.1 System Prompt 设计方法论** — 四要素（身份/语气/边界/约束）、Few-shot 示范
- [x] **2.2 Prompt 注入风险** — 什么叫提示词注入？用户输入花括号怎么崩的？
- [x] **2.3 成本优化** — token 怎么计费？DeepSeek vs OpenAI 价格对比

## 阶段三：RAG 核心（重点，最深度）

- [x] **3.1 Embedding 原理** — 文本→向量的数学直观、为什么相似文本向量接近？
- [x] **3.2 BGE 模型选型** — 为什么选 BGE 而不是直接用 DeepSeek Embedding？local vs API
- [x] **3.3 向量检索流程** — 从 query 到 Top-K 结果每一步发生了什么
- [x] **3.4 余弦相似度** — 不看长度只看方向、和欧氏距离的区别
- [x] **3.5 分块策略** — chunk size 怎么定？overlap 做什么用？论语为什么天然适合按章分块？
- [x] **3.6 向量数据库选型** — ChromaDB vs FAISS vs pgvector vs Milvus 对比
- [x] **3.7 HNSW 索引原理** — 六度分隔类比、跳跃层+密集层
- [x] **3.8 RAG 评估与调优** — 怎么知道自己检索质量好不好？Hit Rate、MRR 是什么？
- [x] **3.9 实践：改 Top-K、改温度、对比效果**
- [x] **3.10 Transformer 与注意力机制** — QKV 是什么？多头注意力怎么"读懂"上下文？Pooling 到底做了什么？

## 阶段四：Agent（核心概念）

- [x] **4.1 Agent 是什么** — Chatbot vs Agent 的区别、Tool Calling 原理
- [x] **4.2 ReAct 模式** — Reasoning + Acting 循环、观察-思考-行动
- [x] **4.3 你的项目算 Agent 吗？** — 不算。为什么？差了什么？
- [x] **4.4 Agent 实战构想** — 如果要给孔夫子加"翻译工具""发邮件工具"怎么做？

## 阶段五：模型微调

- [x] **5.1 什么时候该微调？** — Prompt 搞不定了才微调，不是第一步
- [x] **5.2 LoRA / QLoRA 原理** — 只训练一小部分参数、显存友好
- [x] **5.3 数据标注** — 需要什么样的训练数据？孔夫子 QA 对怎么收集？
- [x] **5.4 SFT vs RLHF** — 监督微调 vs 人类反馈强化学习有什么区别？

## 阶段六：后端开发基础

- [x] **6.1 HTTP 协议基础** — GET/POST、请求头请求体、状态码（200/400/401/403/500）
- [x] **6.2 FastAPI 路由与分层** — Router → Service → Client 为什么三层分离？
- [x] **6.3 数据库 ORM** — SQLAlchemy 是什么？一对多关系怎么建？cascade 删除原理
- [x] **6.4 JWT 鉴权深入** — 签名 vs 加密、为什么`iat`会出问题？HS256 vs RS256
- [x] **6.5 密码安全** — bcrypt 为什么故意慢？加盐原理、哈希不可逆
- [x] **6.6 异步编程入门** — async/await、事件循环、阻塞 vs 非阻塞
- [x] **6.7 SSE 流式原理** — 为什么不用 WebSocket？EventSource vs fetch+ReadableStream

## 阶段七：测试与工程化

- [x] **7.1 测试金字塔** — 单元测试 vs 集成测试 vs E2E、Mock 怎么用？
- [x] **7.2 pytest 入门** — fixture、conftest、parametrize
- [x] **7.3 Docker 基础** — 镜像 vs 容器、Dockerfile 怎么写、docker-compose 做什么
- [x] **7.4 CI/CD** — GitHub Actions 做什么？为什么 push 以后自动跑测试？

## 阶段八：运维与部署

- [x] **8.1 nginx 反向代理** — 前端请求怎么转发到后端？为什么生产环境要 nginx？
- [x] **8.2 环境变量管理** — .env 文件、为什么不提交到 Git
- [x] **8.3 日志与监控** — 怎么看日志排查问题？health check 该查什么？

---

## 进度

| 阶段 | 完成 | 进度 |
|------|------|------|
| 一：LLM 基础 | 4/4 | 100% |
| 二：Prompt Engineering | 3/3 | 100% |
| 三：RAG 核心 | 10/10 | 100% |
| 四：Agent | 4/4 | 100% |
| 五：模型微调 | 4/4 | 100% |
| 六：后端基础 | 7/7 | 100% |
| 七：测试工程化 | 4/4 | 100% |
| 八：运维部署 | 3/3 | 100% |

---

> 每个知识点的学习流程：讲解 → 看代码 → 加注释 → 改一个东西 → 记笔记
