"""
工程韧性 — 重试 / 熔断 / 降级

三个核心模式，都用装饰器或函数包装，和业务逻辑分离。

面试核心考点：
1. 指数退避 + jitter → 为什么不能固定间隔重试？
2. 熔断器三种状态 → CLOSED/OPEN/HALF_OPEN 各自做什么？
3. 降级兜底 → 和熔断器是什么关系？谁先谁后？

库对比（面试时可以说"原理一样，生产环境可以用现成库"）：
  - retry:   tenacity库（Python最流行）, Spring Retry（Java）
  - circuit: pybreaker库, resilience4j（Java）, Hystrix（Java，已停更）
  - 本项目手写三个都不到200行，但完整展示了三个模式的状态机和设计意图
"""

import asyncio
import functools
import logging
import random
import threading
import time
from enum import Enum
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

# ---------------------------------------------------------------------------
# 1. 指数退避重试 (Exponential Backoff with Jitter)
# ---------------------------------------------------------------------------


def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
    retryable_exceptions: tuple[type[BaseException], ...] = (Exception,),
):
    """指数退避重试装饰器。

    支持同步和异步函数。检测到 async def 自动走异步路径。

    参数：
      max_retries: 最多重试次数（不含首次调用）
      base_delay: 首次重试前的等待秒数
      max_delay: 单次等待的上限（防止重试间隔无限增长）
      backoff_factor: 每次重试后间隔乘以这个因子（通常 2.0）
      retryable_exceptions: 哪些异常触发重试。默认所有 Exception 都重试。
                            生产环境通常只重试网络异常（timeout、rate_limit、5xx）

    重试时间线示例（base=1s, factor=2, max_retries=3）：
      首次调用 → 失败
      等 1s + jitter → 重试1 → 失败
      等 2s + jitter → 重试2 → 失败
      等 4s + jitter → 重试3 → 失败
      → 抛出原始异常

    Jitter 是什么？
      随机抖动（±25%）。假设 4 个并发请求同时失败，如果都等恰好 1 秒后重试，
      它们会在同一毫秒同时打回来——可能再次压垮服务（惊群效应）。
      Jitter 让它们分散在 0.75s~1.25s 之间，削峰填谷。

    面试时可以和 tenacity 对比：
      from tenacity import retry, stop_after_attempt, wait_exponential
      @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1))
      def my_func(): ...

      原理一样，tenacity 封装的配置项更多（retry_on_result、before_sleep 回调等）。
      手写版优势：透明可控，面试时能讲清楚状态机。
    """

    def decorator(func: F) -> F:
        if asyncio.iscoroutinefunction(func):
            return _async_retry_wrapper(
                func, max_retries, base_delay, max_delay, backoff_factor, retryable_exceptions
            )
        else:
            return _sync_retry_wrapper(
                func, max_retries, base_delay, max_delay, backoff_factor, retryable_exceptions
            )

    return decorator


def _sync_retry_wrapper(func, max_retries, base_delay, max_delay, factor, retryable):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        last_exception = None
        for attempt in range(max_retries + 1):  # 0, 1, ..., max_retries
            try:
                return func(*args, **kwargs)
            except retryable as e:
                last_exception = e
                if attempt < max_retries:
                    delay = _calc_delay(base_delay, factor, attempt, max_delay)
                    logger.warning(
                        "%s 第 %d/%d 次失败，%0.1fs 后重试: %s",
                        func.__name__, attempt + 1, max_retries, delay, e,
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        "%s 重试 %d 次后仍失败: %s",
                        func.__name__, max_retries, e,
                    )
            except BaseException:
                # 非可重试异常（如 KeyboardInterrupt）直接抛出，不重试
                raise
        raise last_exception  # type: ignore[misc]

    return wrapper


def _async_retry_wrapper(func, max_retries, base_delay, max_delay, factor, retryable):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        last_exception = None
        for attempt in range(max_retries + 1):
            try:
                return await func(*args, **kwargs)
            except retryable as e:
                last_exception = e
                if attempt < max_retries:
                    delay = _calc_delay(base_delay, factor, attempt, max_delay)
                    logger.warning(
                        "%s 第 %d/%d 次失败，%0.1fs 后重试: %s",
                        func.__name__, attempt + 1, max_retries, delay, e,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "%s 重试 %d 次后仍失败: %s",
                        func.__name__, max_retries, e,
                    )
            except BaseException:
                raise
        raise last_exception  # type: ignore[misc]

    return wrapper


def _calc_delay(base: float, factor: float, attempt: int, max_delay: float) -> float:
    """计算第 attempt 次重试的等待时间，含 jitter。

    公式: delay = min(base * factor^attempt + jitter, max_delay)
    jitter = delay * random(-0.25, +0.25)  → ±25% 随机偏移
    """
    delay = base * (factor ** attempt)
    delay = min(delay, max_delay)
    jitter = delay * random.uniform(-0.25, 0.25)
    return max(0, delay + jitter)


# ---------------------------------------------------------------------------
# 2. 熔断器 (Circuit Breaker)
# ---------------------------------------------------------------------------


class CircuitState(Enum):
    """熔断器三种状态。

    CLOSED   = 正常状态，请求放行，计数失败
    OPEN     = 熔断状态，直接拒绝所有请求（快速失败）
    HALF_OPEN = 半开状态，放行一个请求做探测

    状态转换：
      CLOSED ──连续失败>=threshold──→ OPEN
      OPEN   ──等待超时─────────────→ HALF_OPEN
      HALF_OPEN ──探测成功──────────→ CLOSED  (重置计数)
      HALF_OPEN ──探测失败──────────→ OPEN    (重新计时)
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """熔断器。

    为什么需要熔断器？
      假设 DeepSeek API 挂了。没有熔断器，每个用户请求都会尝试调 API →
      等到 30s 超时才返回错误。100 个并发请求 = 100 个线程/协程全卡在等超时。
      有熔断器：连续 5 次失败 → 熔断 30 秒 → 后续请求直接返回错误（毫秒级）
      → 保护了稀缺的线程资源和用户等待时间。

    线程安全：
      _lock 保护状态转换。对于 Web 服务（FastAPI），多个请求可能同时触发
      熔断状态变更，不加锁会导致计数不准或状态跳跃。

    使用方式：
      # 方式1: 装饰器工厂
      cb = CircuitBreaker(failure_threshold=5, timeout=30)

      @cb
      def my_func(): ...

      # 方式2: 手动调用
      if cb.allow_request():
          try:
              result = do_something()
              cb.on_success()
              return result
          except Exception:
              cb.on_failure()

      # 方式3: 上下文管理器
      with cb:
          result = do_something()
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        timeout: float = 30.0,
        half_open_max_requests: int = 1,
    ):
        """
        Args:
            failure_threshold: 连续失败多少次后熔断
            timeout: 熔断多少秒后进入半开状态
            half_open_max_requests: 半开状态下允许多少个探测请求（通常 1）
        """
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.half_open_max_requests = half_open_max_requests

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._half_open_count = 0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 核心方法
    # ------------------------------------------------------------------

    def allow_request(self) -> bool:
        """当前是否允许请求通过。

        CLOSED: 始终放行
        OPEN: 检查是否已过 timeout → 是则转 HALF_OPEN 并放行，否则拒绝
        HALF_OPEN: 仅放行 limited 个探测请求
        """
        with self._lock:
            if self._state == CircuitState.CLOSED:
                return True

            if self._state == CircuitState.OPEN:
                elapsed = time.monotonic() - self._last_failure_time
                if elapsed >= self.timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_count = 0
                    logger.info("熔断器进入 HALF_OPEN 状态，开始探测")
                    return True
                return False

            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_count < self.half_open_max_requests:
                    self._half_open_count += 1
                    return True
                return False

            return False

    def on_success(self):
        """请求成功——重置状态"""
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                logger.info("熔断器探测成功，恢复到 CLOSED")
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._half_open_count = 0

    def on_failure(self):
        """请求失败——递增计数，必要时触发熔断"""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if (
                self._state == CircuitState.HALF_OPEN
                or self._failure_count >= self.failure_threshold
            ):
                if self._state != CircuitState.OPEN:
                    logger.warning(
                        "熔断器触发 OPEN: 连续失败 %d 次, 熔断 %.0f 秒",
                        self._failure_count, self.timeout,
                    )
                self._state = CircuitState.OPEN
                self._half_open_count = 0

    # ------------------------------------------------------------------
    # 装饰器支持
    # ------------------------------------------------------------------

    def __call__(self, func: F) -> F:
        """作为装饰器使用: @circuit_breaker_instance"""
        cb = self

        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                if not cb.allow_request():
                    raise CircuitBreakerOpenError(
                        f"熔断器 OPEN: {func.__name__} 暂时不可用"
                    )
                try:
                    result = await func(*args, **kwargs)
                    cb.on_success()
                    return result
                except Exception:
                    cb.on_failure()
                    raise

            return async_wrapper  # type: ignore[return-value]
        else:
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                if not cb.allow_request():
                    raise CircuitBreakerOpenError(
                        f"熔断器 OPEN: {func.__name__} 暂时不可用"
                    )
                try:
                    result = func(*args, **kwargs)
                    cb.on_success()
                    return result
                except Exception:
                    cb.on_failure()
                    raise

            return sync_wrapper  # type: ignore[return-value]

    def __enter__(self):
        if not self.allow_request():
            raise CircuitBreakerOpenError("熔断器 OPEN")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.on_success()
        else:
            self.on_failure()
        return False  # 不吞异常

    @property
    def state(self) -> CircuitState:
        return self._state


class CircuitBreakerOpenError(Exception):
    """熔断器开启时抛出的异常——调用方可以据此走降级逻辑"""
    pass


# ---------------------------------------------------------------------------
# 3. 降级兜底 (Graceful Degradation)
# ---------------------------------------------------------------------------


def with_fallback(
    *steps: Callable[[], Any],
    default: Any = None,
):
    """降级链：依次尝试 steps，第一个成功的返回，全部失败返回 default。

    每次只尝试一个函数调用，失败后才尝试下一个。不是"都执行取最好的"——
    那是"重试"。这是"降级"——主方案失败换备用方案。

    使用示例：
        result = with_fallback(
            lambda: hybrid_search(query),    # 主方案：混合检索
            lambda: basic_search(query),     # 降级1：纯向量检索
            lambda: simple_reply(query),     # 降级2：纯 LLM 回复
            default="夫子暂时无法作答",       # 兜底：固定回复
        )

    和熔断器的协作关系：
      熔断器在前（快速失败），降级链在后（处理失败）。
      顺序：请求 → [熔断检查] → 主方案 → 失败 → 降级1 → 失败 → 降级2 → default
              ↑ 如果熔断直接跳到最后

    面试时可对比：
      - Netflix Hystrix 的 fallback 机制：每个命令都配降级逻辑
      - AWS 的"多 AZ 部署"本质上也是降级：主 AZ 挂了切备 AZ
    """
    for i, step in enumerate(steps):
        try:
            result = step()
            if i > 0:
                logger.info("降级链: 第 %d 个备选方案成功", i + 1)
            return result
        except Exception as e:
            logger.warning("降级链: 第 %d 步失败: %s", i + 1, e)
            continue

    logger.error("降级链: 全部 %d 步失败，返回兜底值", len(steps))
    return default() if callable(default) else default
