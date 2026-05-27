"""
限流 — 并发控制 + 频率限制

两层保护（面试可讲）：
  1. 并发控制：同一用户同时只允许 1 个请求
     - Agent 循环是有状态的（messages 列表在内存中累加）
     - 同一用户两个并发请求会互相覆盖对话历史 → 脏数据
  2. 频率限制：同一用户每分钟最多 15 次
     - 保护 DeepSeek API 费用（每次对话 ~0.7分，滥用成本不可控）
     - 返回 429 + Retry-After 头，让客户端自愿等待

为什么用内存字典而不是 Redis？
  - 单进程 demo 够用，生产换 Redis 只需改存储层（接口不变）
  - 面试时讲清楚"当前方案适合什么规模，什么规模后该换什么"比直接用 Redis 更重要

算法选择：
  - 并发控制：信号量字典 {user_id: bool}，请求前 acquire，请求后 release
  - 频率限制：滑动窗口 {user_id: [timestamp, ...]}，每次请求清理过期记录
"""

import time
import threading
from fastapi import HTTPException, Request

# 并发控制 — {user_id: is_busy}
_user_locks: dict[str, bool] = {}
_lock = threading.Lock()

# 频率限制 — {user_id: [timestamp, timestamp, ...]}
_user_windows: dict[str, list[float]] = {}

# 配置
MAX_CONCURRENT_PER_USER = 1   # 同一用户同时最多 1 个请求
MAX_REQUESTS_PER_MINUTE = 15   # 同一用户每分钟最多 15 次
WINDOW_SECONDS = 60            # 滑动窗口大小


def check_rate_limit(user_id: str):
    """FastAPI 依赖：检查并发和频率限制，通过则放行，不通过抛 429。

    用法（在路由函数参数里）：
        user_id: str = Depends(get_current_user_id_str)
        check_rate_limit(user_id)
    """
    # ---- 1. 并发控制 ----
    _acquire_concurrency_slot(user_id)

    # ---- 2. 频率限制 ----
    _check_frequency(user_id)


def release_concurrency_slot(user_id: str):
    """释放并发槽位——请求处理完时调用"""
    with _lock:
        _user_locks.pop(user_id, None)


# ---------------------------------------------------------------------------
# 并发控制
# ---------------------------------------------------------------------------

def _acquire_concurrency_slot(user_id: str):
    """获取并发槽位，同一用户已有请求在处理中则拒绝"""
    with _lock:
        if _user_locks.get(user_id):
            raise HTTPException(
                status_code=429,
                detail="子勿急躁，前问未答，稍后再问。",
                headers={"Retry-After": "3"},
            )
        _user_locks[user_id] = True


# ---------------------------------------------------------------------------
# 频率限制 — 滑动窗口
# ---------------------------------------------------------------------------

def _check_frequency(user_id: str):
    """检查滑动窗口内的请求次数"""
    now = time.time()
    window_start = now - WINDOW_SECONDS

    if user_id not in _user_windows:
        _user_windows[user_id] = []

    # 清理过期记录
    timestamps = _user_windows[user_id]
    timestamps[:] = [t for t in timestamps if t > window_start]

    if len(timestamps) >= MAX_REQUESTS_PER_MINUTE:
        # 计算最早一条记录什么时候过期
        earliest = min(timestamps)
        retry_after = int(earliest + WINDOW_SECONDS - now) + 1
        raise HTTPException(
            status_code=429,
            detail=f"子问之勤，夫子应接不暇。请 {retry_after} 秒后再问。",
            headers={"Retry-After": str(retry_after)},
        )

    timestamps.append(now)


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def get_remaining_quota(user_id: str) -> int:
    """查询剩余请求次数（给 /health 或 debug 接口用）"""
    now = time.time()
    window_start = now - WINDOW_SECONDS
    timestamps = _user_windows.get(user_id, [])
    active = [t for t in timestamps if t > window_start]
    return max(0, MAX_REQUESTS_PER_MINUTE - len(active))
