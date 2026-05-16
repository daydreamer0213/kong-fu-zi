import { useState, useEffect, useRef, useCallback } from "react";
import { Send, Plus, Trash2, MessageCircle, LogOut } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Separator } from "@/components/ui/separator";
import {
  type Conversation,
  type Source,
  getToken,
  clearToken,
  sendMessageStream,
  getConversations,
  getConversation,
  deleteConversation,
} from "@/lib/api";

export default function Chat() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [currentConvId, setCurrentConvId] = useState<number | null>(null);
  const [messages, setMessages] = useState<MessageVM[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingToken, setStreamingToken] = useState("");
  const [sources, setSources] = useState<Source[]>([]);
  const [errorTip, setErrorTip] = useState("");
  const [loadingConvs, setLoadingConvs] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<(() => void) | null>(null);

  const token = getToken();

  // ---- 助函数 ----

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  const loadConversations = async () => {
    setLoadingConvs(true);
    try {
      setConversations(await getConversations());
    } catch { setErrorTip("加载对话列表失败"); }
    finally { setLoadingConvs(false); }
  };

  const loadConversation = async (id: number) => {
    try {
      const detail = await getConversation(id);
      setMessages(detail.messages.map((m) => ({
        role: m.role,
        content: m.content,
      })));
      setCurrentConvId(id);
      setSources([]);
    } catch { setErrorTip("加载对话失败"); }
  };

  const handleNewChat = () => {
    setCurrentConvId(null);
    setMessages([]);
    setSources([]);
  };

  const handleDelete = async (id: number) => {
    if (!window.confirm("确定删除此对话？")) return;
    try {
      await deleteConversation(id);
      if (currentConvId === id) handleNewChat();
      await loadConversations();
    } catch { setErrorTip("删除对话失败"); }
  };

  const handleLogout = () => {
    clearToken();
    window.location.reload();
  };

  // ---- 发送消息 ----

  const handleSend = useCallback(() => {
    const text = input.trim();
    if (!text || isStreaming) return;

    // 添加用户消息到界面
    const userMsg: MessageVM = { role: "user", content: text };
    const updated = [...messages, userMsg];
    setMessages(updated);
    setInput("");
    setStreamingToken("");
    setSources([]);
    setIsStreaming(true);

    // 发送流式请求
    cancelRef.current = sendMessageStream(
      text,
      currentConvId ?? undefined,
      (token) => setStreamingToken((prev) => prev + token),          // onToken
      (srcs) => setSources(srcs),                                     // onSources
      (convId) => {                                                   // onDone
        setIsStreaming(false);
        // 不要在这里清 streamingToken！useEffect 需要它来存助手消息
        if (!currentConvId) {
          setCurrentConvId(convId);
          loadConversations();
        }
      },
      (err) => {                                                      // onError
        setIsStreaming(false);
        setStreamingToken("");
        setErrorTip(err.message || "发送失败，请稍后重试");
      },
    );

    scrollToBottom();
  }, [input, isStreaming, messages, currentConvId]);

  // 完成流式后，将流式内容转为正式 assistant 消息
  useEffect(() => {
    if (!isStreaming && streamingToken) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: streamingToken, sources },
      ]);
      setStreamingToken("");
    }
  }, [isStreaming]);

  // 自动滚动
  useEffect(() => {
    scrollToBottom();
  }, [messages, streamingToken]);

  // 组件卸载时取消流式请求
  useEffect(() => {
    return () => {
      cancelRef.current?.();
    };
  }, []);

  // 加载对话列表
  useEffect(() => {
    if (token) loadConversations();
  }, [token]);

  // ---- 渲染 ----

  const displayMessages = [...messages];
  if (isStreaming && streamingToken) {
    displayMessages.push({ role: "assistant", content: streamingToken, sources });
  }

  return (
    <div className="flex h-screen bg-stone-50">
      {/* 错误提示横幅 */}
      {errorTip && (
        <div className="absolute top-4 left-1/2 -translate-x-1/2 z-50 bg-red-50 border border-red-200 text-red-700 px-6 py-3 rounded-lg shadow-lg flex items-center gap-3">
          <span className="text-sm">{errorTip}</span>
          <button className="text-red-400 hover:text-red-600 font-bold" onClick={() => setErrorTip("")}>x</button>
        </div>
      )}
      {/* ---- 侧边栏 ---- */}
      <aside className="w-64 flex flex-col bg-white border-r border-stone-200">
        <div className="p-4">
          <Button className="w-full" onClick={handleNewChat} disabled={isStreaming}>
            <Plus className="mr-2 h-4 w-4" />
            新对话
          </Button>
        </div>
        <Separator />
        <ScrollArea className="flex-1">
          <div className="p-2 space-y-1">
            {conversations.map((c) => (
              <div
                key={c.id}
                className={`group flex items-center rounded-lg px-3 py-2 text-sm cursor-pointer transition-colors
                  ${c.id === currentConvId
                    ? "bg-stone-100 text-stone-900"
                    : "text-stone-600 hover:bg-stone-50 hover:text-stone-800"
                  }`}
                onClick={() => loadConversation(c.id)}
              >
                <MessageCircle className="mr-2 h-4 w-4 shrink-0" />
                <span className="truncate flex-1">{c.title}</span>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 opacity-0 group-hover:opacity-100 shrink-0"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleDelete(c.id);
                  }}
                >
                  <Trash2 className="h-3 w-3 text-stone-400" />
                </Button>
              </div>
            ))}
            {loadingConvs && (
              <p className="text-xs text-stone-400 text-center py-4">加载中...</p>
            )}
            {!loadingConvs && conversations.length === 0 && (
              <p className="text-xs text-stone-400 text-center py-4">暂无对话</p>
            )}
          </div>
        </ScrollArea>
        <Separator />
        <div className="p-4">
          <Button variant="ghost" className="w-full justify-start text-stone-500" onClick={handleLogout}>
            <LogOut className="mr-2 h-4 w-4" />
            退出登录
          </Button>
        </div>
      </aside>

      {/* ---- 主聊天区 ---- */}
      <main className="flex-1 flex flex-col">
        {/* 消息列表 */}
        <ScrollArea className="flex-1 px-4">
          <div className="max-w-2xl mx-auto py-6 space-y-6">
            {displayMessages.length === 0 && (
              <div className="text-center py-20 text-stone-400">
                <p className="text-lg">子曰：有朋自远方来，不亦乐乎？</p>
                <p className="text-sm mt-2">有何疑问，但说无妨</p>
              </div>
            )}
            {displayMessages.map((m, i) => (
              <div key={i} className={`flex gap-3 ${m.role === "user" ? "flex-row-reverse" : ""}`}>
                <Avatar className="h-8 w-8 shrink-0">
                  <AvatarFallback className={m.role === "user" ? "bg-stone-400 text-white" : "bg-amber-700 text-white"}>
                    {m.role === "user" ? "子" : "孔"}
                  </AvatarFallback>
                </Avatar>
                <div className={`rounded-xl px-4 py-3 max-w-[80%] text-sm leading-relaxed
                  ${m.role === "user"
                    ? "bg-stone-800 text-white"
                    : "bg-white border border-stone-200 text-stone-700"
                  }`}
                >
                  <p className="whitespace-pre-wrap">{m.content}</p>
                  {/* 引用来源 */}
                  {m.role === "assistant" && m.sources && m.sources.length > 0 && (
                    <div className="mt-2 pt-2 border-t border-stone-200">
                      <p className="text-xs text-stone-400 mb-1">参考论语原文：</p>
                      {m.sources.map((s, j) => (
                        <p key={j} className="text-xs text-stone-400 truncate">
                          《{s.chapter}》：{s.text.slice(0, 50)}...
                        </p>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>
        </ScrollArea>

        {/* 输入区 */}
        <div className="border-t border-stone-200 bg-white p-4">
          <div className="max-w-2xl mx-auto flex gap-3">
            <Input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="向夫子请教..."
              className="flex-1"
              disabled={isStreaming}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
            />
            <Button onClick={handleSend} disabled={isStreaming || !input.trim()}>
              <Send className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </main>
    </div>
  );
}

interface MessageVM {
  role: string;
  content: string;
  sources?: Source[];
}
