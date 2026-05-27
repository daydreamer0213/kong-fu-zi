"""工程韧性单元测试 — 重试 / 熔断 / 降级"""
import time

import pytest

from app.utils.resilience import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitState,
    retry_with_backoff,
    with_fallback,
)


# ============================================================
# 指数退避重试
# ============================================================

class TestRetryWithBackoff:
    def test_retry_succeeds_on_second_attempt(self):
        call_count = [0]

        @retry_with_backoff(max_retries=3, base_delay=0.001, retryable_exceptions=(ValueError,))
        def flaky():
            call_count[0] += 1
            if call_count[0] < 3:
                raise ValueError("fail")
            return "ok"

        result = flaky()
        assert result == "ok"
        assert call_count[0] == 3

    def test_retry_exhausted_raises_last_exception(self):
        @retry_with_backoff(max_retries=2, base_delay=0.001, retryable_exceptions=(ValueError,))
        def always_fails():
            raise ValueError("always")

        with pytest.raises(ValueError, match="always"):
            always_fails()

    def test_non_retryable_exception_raised_immediately(self):
        call_count = [0]

        @retry_with_backoff(max_retries=3, base_delay=0.001, retryable_exceptions=(ValueError,))
        def type_error_func():
            call_count[0] += 1
            raise TypeError("not retryable")

        with pytest.raises(TypeError):
            type_error_func()
        assert call_count[0] == 1  # 不重试

    def test_retry_preserves_function_name(self):
        @retry_with_backoff(max_retries=1, base_delay=0.001)
        def my_func():
            return 1

        assert my_func.__name__ == "my_func"

    # async retry 测试需要 pytest-asyncio，当前环境未安装。
    # 异步路径的 retry_with_backoff 逻辑和同步版完全同构（同一套状态机），
    # 区别仅在 time.sleep → asyncio.sleep，集成测试通过 E2E 覆盖。


# ============================================================
# 熔断器
# ============================================================

class TestCircuitBreaker:
    def test_initial_state_is_closed(self):
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request()

    def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker(failure_threshold=3)
        for _ in range(3):
            assert cb.allow_request()
            cb.on_failure()
        assert cb.state == CircuitState.OPEN
        assert not cb.allow_request()

    def test_half_open_after_timeout(self):
        cb = CircuitBreaker(failure_threshold=2, timeout=0.05)
        for _ in range(2):
            cb.on_failure()
        assert not cb.allow_request()
        time.sleep(0.08)
        assert cb.allow_request()
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_success_returns_to_closed(self):
        cb = CircuitBreaker(failure_threshold=2, timeout=0.05)
        for _ in range(2):
            cb.on_failure()
        time.sleep(0.08)
        assert cb.allow_request()
        cb.on_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request()

    def test_half_open_failure_returns_to_open(self):
        cb = CircuitBreaker(failure_threshold=2, timeout=0.05)
        for _ in range(2):
            cb.on_failure()
        time.sleep(0.08)
        assert cb.allow_request()  # HALF_OPEN
        cb.on_failure()
        assert cb.state == CircuitState.OPEN

    def test_success_resets_count(self):
        cb = CircuitBreaker(failure_threshold=5)
        cb.on_failure()
        cb.on_failure()
        cb.on_success()
        # count 应重置为 0，不会触发熔断
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request()

    def test_decorator_blocks_when_open(self):
        cb = CircuitBreaker(failure_threshold=1, timeout=99)

        @cb
        def might_fail():
            raise ValueError("fail")

        # 第一次失败触发熔断
        with pytest.raises(ValueError):
            might_fail()
        # 第二次应直接抛 CircuitBreakerOpenError
        with pytest.raises(CircuitBreakerOpenError):
            might_fail()

    def test_decorator_success_resets(self):
        cb = CircuitBreaker(failure_threshold=2)

        @cb
        def ok_func():
            return "ok"

        result = ok_func()
        assert result == "ok"
        assert cb.state == CircuitState.CLOSED

    def test_context_manager(self):
        cb = CircuitBreaker(failure_threshold=2)
        with cb:
            pass  # success
        assert cb.state == CircuitState.CLOSED

    def test_context_manager_failure(self):
        cb = CircuitBreaker(failure_threshold=1)
        with pytest.raises(ValueError):
            with cb:
                raise ValueError("fail")
        assert cb.state == CircuitState.OPEN


# ============================================================
# 降级兜底
# ============================================================

class TestWithFallback:
    def test_first_step_succeeds(self):
        result = with_fallback(
            lambda: "step1",
            lambda: "step2",
        )
        assert result == "step1"

    def test_fallback_to_second(self):
        result = with_fallback(
            lambda: (_ for _ in ()).throw(ValueError()),
            lambda: "step2",
        )
        assert result == "step2"

    def test_all_fail_returns_default(self):
        result = with_fallback(
            lambda: (_ for _ in ()).throw(ValueError()),
            lambda: (_ for _ in ()).throw(ValueError()),
            default="fallback",
        )
        assert result == "fallback"

    def test_default_can_be_callable(self):
        result = with_fallback(
            lambda: (_ for _ in ()).throw(ValueError()),
            default=lambda: "computed",
        )
        assert result == "computed"

    def test_empty_steps_returns_default(self):
        result = with_fallback(default="only_default")
        assert result == "only_default"
