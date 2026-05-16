import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Eye, EyeOff, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { login, register, setToken } from "@/lib/api";

function validate(username: string, password: string): string | null {
  if (username.length < 2) return "用户名至少2个字符";
  if (password.length < 6) return "密码至少6个字符";
  return null;
}

export default function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPwd, setShowPwd] = useState(false);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const navigate = useNavigate();

  const submit = async (mode: "login" | "register") => {
    const err = validate(username, password);
    if (err) { setError(err); return; }

    setError("");
    setIsLoading(true);
    try {
      if (mode === "register") {
        await register(username, password);
      }
      const token = await login(username, password);
      setToken(token);
      navigate("/");
    } catch (e: any) {
      setError(e.message || "操作失败");
    } finally {
      setIsLoading(false);
    }
  };

  const handleEnter = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") submit("login");
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-b from-stone-50 to-amber-50/30">
      <Card className="w-[380px] shadow-lg">
        <CardHeader className="text-center pb-2">
          <CardTitle className="text-2xl">孔夫子 AI 助手</CardTitle>
          <CardDescription>子曰：有朋自远方来，不亦乐乎？</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4 pt-4">
          <Input
            placeholder="用户名"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            onKeyDown={handleEnter}
            disabled={isLoading}
          />
          <div className="relative">
            <Input
              type={showPwd ? "text" : "password"}
              placeholder="密码（至少6位）"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={handleEnter}
              disabled={isLoading}
            />
            <button
              type="button"
              className="absolute right-3 top-1/2 -translate-y-1/2 text-stone-400 hover:text-stone-600"
              onClick={() => setShowPwd(!showPwd)}
              tabIndex={-1}
            >
              {showPwd ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
          {error && <p className="text-sm text-red-500 text-center">{error}</p>}
          <div className="flex gap-3 pt-2">
            <Button className="flex-1" onClick={() => submit("login")} disabled={isLoading}>
              {isLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              登录
            </Button>
            <Button variant="outline" className="flex-1" onClick={() => submit("register")} disabled={isLoading}>
              注册
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
