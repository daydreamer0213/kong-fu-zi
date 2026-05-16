const BASE_URL = "http://localhost:8000";

// ============================================================
// Token 管理（步骤⑩改为完整登录流程）
// ============================================================

export function getToken(): string | null {
  return localStorage.getItem("kong_token");
}

export function setToken(token: string) {
  localStorage.setItem("kong_token", token);
}

export function clearToken() {
  localStorage.removeItem("kong_token");
}

// ============================================================
// 类型定义
// ============================================================

export interface Source {
  chapter: string;
  text: string;
  score: number;
}

export interface ChatResponse {
  reply: string;
  sources: Source[];
  intent: string;
  conversation_id: number;
}

export interface Conversation {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface MessageDetail {
  role: string;
  content: string;
  created_at: string;
}

export interface ConversationDetail {
  id: number;
  title: string;
  messages: MessageDetail[];
}

// ============================================================
// 认证
// ============================================================

export async function login(username: string, password: string): Promise<string> {
  const res = await fetch(`${BASE_URL}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) throw new Error("登录失败");
  const data = await res.json();
  return data.access_token;
}

export async function register(username: string, password: string): Promise<void> {
  const res = await fetch(`${BASE_URL}/api/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "注册失败");
  }
}

// ============================================================
// 聊天
// ============================================================

async function authHeaders(): Promise<Record<string, string>> {
  const token = getToken();
  if (!token) throw new Error("未登录");
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`,
  };
}

export async function sendMessage(
  message: string,
  conversationId?: number
): Promise<ChatResponse> {
  const headers = await authHeaders();
  const res = await fetch(`${BASE_URL}/api/chat`, {
    method: "POST",
    headers,
    body: JSON.stringify({ message, conversation_id: conversationId || undefined }),
  });
  if (!res.ok) throw new Error("发送失败");
  return res.json();
}

/**
 * 流式发送消息，逐 token 回调 onToken，结束后回调 onDone。
 * 返回 abort 函数用于取消请求。
 */
export function sendMessageStream(
  message: string,
  conversationId: number | undefined,
  onToken: (token: string) => void,
  onSources: (sources: Source[]) => void,
  onDone: (conversationId: number) => void,
  onError: (err: Error) => void,
): () => void {
  const abortController = new AbortController();

  let timeoutId: ReturnType<typeof setInterval> | null = null;

  (async () => {
    try {
      const headers = await authHeaders();
      const res = await fetch(`${BASE_URL}/api/chat/stream`, {
        method: "POST",
        headers,
        body: JSON.stringify({ message, conversation_id: conversationId ?? undefined }),
        signal: abortController.signal,
      });
      if (!res.ok) throw new Error("请求失败");

      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let convId = conversationId ?? 0;

      // 60 秒无数据则超时
      const STREAM_TIMEOUT = 60_000;
      let lastChunkTime = Date.now();
      timeoutId = setInterval(() => {
        if (Date.now() - lastChunkTime > STREAM_TIMEOUT) {
          abortController.abort();
        }
      }, 5000);

      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          clearInterval(timeoutId);
          onDone(convId);
          break;
        }
        lastChunkTime = Date.now();
        buffer += decoder.decode(value, { stream: true });

        // SSE 规范兼容：\r\n, \r, \n 都作为行分隔
        const rawLines = buffer.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
        buffer = rawLines.pop() || "";

        for (const line of rawLines) {
          if (!line.startsWith("data: ")) continue;
          const payload = line.slice(6);

          if (payload === "[DONE]") {
            clearInterval(timeoutId);
            onDone(convId);
            return;
          }
          if (payload.startsWith("[CONV_ID]")) {
            convId = parseInt(payload.slice(9), 10);
            continue;
          }
          if (payload.startsWith("[SOURCES]")) {
            try {
              onSources(JSON.parse(payload.slice(9)));
            } catch { /* ignore */ }
            continue;
          }
          try {
            const { token } = JSON.parse(payload);
            onToken(token);
          } catch { /* ignore malformed JSON */ }
        }
      }
    } catch (err: any) {
      if (timeoutId) clearInterval(timeoutId);
      if (err.name !== "AbortError") {
        onError(err instanceof Error ? err : new Error(String(err)));
      }
    }
  })();

  return () => abortController.abort();
}

// ============================================================
// 对话管理
// ============================================================

export async function getConversations(): Promise<Conversation[]> {
  const headers = await authHeaders();
  const res = await fetch(`${BASE_URL}/api/chat/conversations`, { headers });
  if (!res.ok) throw new Error("获取对话列表失败");
  return res.json();
}

export async function getConversation(id: number): Promise<ConversationDetail> {
  const headers = await authHeaders();
  const res = await fetch(`${BASE_URL}/api/chat/conversations/${id}`, { headers });
  if (!res.ok) throw new Error("获取对话详情失败");
  return res.json();
}

export async function deleteConversation(id: number): Promise<void> {
  const headers = await authHeaders();
  const res = await fetch(`${BASE_URL}/api/chat/conversations/${id}`, {
    method: "DELETE",
    headers,
  });
  if (!res.ok) throw new Error("删除失败");
}
