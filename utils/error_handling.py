"""
错误处理和重试机制
"""

import asyncio
import logging
import time
from collections.abc import Callable
from functools import wraps
from typing import Any

import httpx

from utils.message_manager import delete_user_command, send_error


logger = logging.getLogger(__name__)


def with_telegram_retry(max_retries: int = 5):
    """
    Telegram API 重试装饰器，专门处理 RetryAfter 异常

    Args:
        max_retries: 最大重试次数（默认5次）
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            from telegram.error import RetryAfter, TimedOut, NetworkError

            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except RetryAfter as e:
                    last_exception = e
                    if attempt < max_retries:
                        wait_time = e.retry_after + 1  # 额外等待1秒
                        logger.warning(
                            f"Telegram RetryAfter in {func.__name__}: wait {wait_time}s "
                            f"(attempt {attempt + 1}/{max_retries + 1})"
                        )
                        await asyncio.sleep(wait_time)
                    else:
                        logger.error(f"All retry attempts failed for {func.__name__}: {e}")
                except (TimedOut, NetworkError) as e:
                    last_exception = e
                    if attempt < max_retries:
                        wait_time = 2 ** attempt  # 指数退避：1s, 2s, 4s, 8s, 16s
                        logger.warning(
                            f"Telegram {type(e).__name__} in {func.__name__}: wait {wait_time}s "
                            f"(attempt {attempt + 1}/{max_retries + 1})"
                        )
                        await asyncio.sleep(wait_time)
                    else:
                        logger.error(f"All retry attempts failed for {func.__name__}: {e}")

            raise last_exception

        return wrapper

    return decorator


def with_error_handling(func):
    """
    通用错误处理装饰器

    Args:
        func: 要装饰的函数
    """

    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error in {func.__name__}: {e}", exc_info=True)
            # 如果是Telegram更新，尝试发送错误消息
            if len(args) >= 2 and hasattr(args[0], "effective_chat") and hasattr(args[1], "bot"):
                try:
                    update, context = args[0], args[1]

                    # 使用新的消息管理API发送错误消息
                    await send_error(
                        context=context,
                        chat_id=update.effective_chat.id,
                        text="处理请求时发生错误，请稍后重试。\n如果问题持续存在，请联系管理员。"
                    )

                    # 删除用户命令消息
                    if (
                        hasattr(update, "effective_message")
                        and getattr(update.effective_message, "message_id", None)
                    ):
                        await delete_user_command(
                            context=context,
                            chat_id=update.effective_chat.id,
                            message_id=update.effective_message.message_id
                        )
                except Exception:
                    pass
            raise

    return wrapper


class RetryConfig:
    """重试配置"""

    def __init__(self, max_retries: int = 3, delay: float = 1.0, backoff: float = 2.0):
        self.max_retries = max_retries
        self.delay = delay
        self.backoff = backoff


def with_retry(config: RetryConfig = None, exceptions: tuple = (Exception,)):
    """
    重试装饰器

    Args:
        config: 重试配置
        exceptions: 需要重试的异常类型
    """
    if config is None:
        config = RetryConfig()

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            delay = config.delay

            for attempt in range(config.max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < config.max_retries:
                        logger.warning(
                            f"Attempt {attempt + 1}/{config.max_retries + 1} failed for {func.__name__}: {e}"
                        )
                        await asyncio.sleep(delay)
                        delay *= config.backoff
                    else:
                        logger.error(f"All retry attempts failed for {func.__name__}: {e}")

            raise last_exception

        return wrapper

    return decorator


class CircuitBreaker:
    """熔断器模式实现"""

    def __init__(self, failure_threshold: int = 5, timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """执行函数调用，应用熔断器逻辑"""

        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.timeout:
                self.state = "HALF_OPEN"
                logger.info(f"Circuit breaker for {func.__name__} is now HALF_OPEN")
            else:
                raise Exception(f"Circuit breaker is OPEN for {func.__name__}")

        try:
            result = await func(*args, **kwargs)

            if self.state == "HALF_OPEN":
                self.state = "CLOSED"
                self.failure_count = 0
                logger.info(f"Circuit breaker for {func.__name__} is now CLOSED")

            return result

        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.failure_count >= self.failure_threshold:
                self.state = "OPEN"
                logger.warning(f"Circuit breaker for {func.__name__} is now OPEN")

            raise e


class CircuitBreakerManager:
    """熔断器管理器，自动清理不活跃的熔断器"""

    def __init__(self, cleanup_interval: int = 3600):  # 1小时清理一次
        self.circuit_breakers: dict[str, CircuitBreaker] = {}
        self.last_cleanup = time.time()
        self.cleanup_interval = cleanup_interval

    def get_circuit_breaker(self, name: str, failure_threshold: int = 5, timeout: int = 60) -> CircuitBreaker:
        """获取或创建熔断器"""
        now = time.time()

        # 定期清理
        if now - self.last_cleanup > self.cleanup_interval:
            self._cleanup_inactive_breakers()
            self.last_cleanup = now

        if name not in self.circuit_breakers:
            self.circuit_breakers[name] = CircuitBreaker(failure_threshold, timeout)

        return self.circuit_breakers[name]

    def _cleanup_inactive_breakers(self):
        """清理长时间未使用的熔断器"""
        now = time.time()
        inactive_names = []

        for name, breaker in self.circuit_breakers.items():
            # 如果熔断器超过24小时未失败，且处于关闭状态，则清理
            if now - breaker.last_failure_time > 86400 and breaker.state == "CLOSED" and breaker.failure_count == 0:
                inactive_names.append(name)

        for name in inactive_names:
            del self.circuit_breakers[name]
            logger.debug(f"清理不活跃的熔断器: {name}")


class RateLimiter:
    """速率限制器"""

    def __init__(self, max_calls: int, time_window: int):
        self.max_calls = max_calls
        self.time_window = time_window
        self.calls = []

    async def acquire(self, user_id: int) -> bool:
        """获取执行许可"""
        now = time.time()

        # 清理过期的调用记录
        self.calls = [call_time for call_time in self.calls if now - call_time < self.time_window]

        if len(self.calls) >= self.max_calls:
            return False

        self.calls.append(now)
        return True


class RateLimiterManager:
    """速率限制器管理器，自动清理过期的限制器"""

    def __init__(self, cleanup_interval: int = 1800):  # 30分钟清理一次
        self.rate_limiters: dict[str, RateLimiter] = {}
        self.last_cleanup = time.time()
        self.cleanup_interval = cleanup_interval

    def get_rate_limiter(self, name: str, max_calls: int = 10, time_window: int = 60) -> RateLimiter:
        """获取或创建速率限制器"""
        now = time.time()

        # 定期清理
        if now - self.last_cleanup > self.cleanup_interval:
            self._cleanup_inactive_limiters()
            self.last_cleanup = now

        if name not in self.rate_limiters:
            self.rate_limiters[name] = RateLimiter(max_calls, time_window)

        return self.rate_limiters[name]

    def _cleanup_inactive_limiters(self):
        """清理长时间未使用的限制器"""
        now = time.time()
        inactive_names = []

        for name, limiter in self.rate_limiters.items():
            # 如果限制器超过1小时无调用记录，则清理
            if not limiter.calls or (now - max(limiter.calls) > 3600):
                inactive_names.append(name)

        for name in inactive_names:
            del self.rate_limiters[name]
            logger.debug(f"清理不活跃的速率限制器: {name}")


# 创建全局管理器实例
circuit_breaker_manager = CircuitBreakerManager()
rate_limiter_manager = RateLimiterManager()

# 为了向后兼容，保留原有接口
circuit_breakers = circuit_breaker_manager.circuit_breakers
rate_limiters = rate_limiter_manager.rate_limiters


def with_rate_limit(name: str | None = None, max_calls: int = 10, time_window: int = 60):
    """速率限制装饰器"""

    def decorator(func):
        limiter_name = name or func.__name__

        @wraps(func)
        async def wrapper(update, context, *args, **kwargs):
            user_id = update.effective_user.id if update.effective_user else 0
            rate_limiter = rate_limiter_manager.get_rate_limiter(limiter_name, max_calls, time_window)

            if await rate_limiter.acquire(user_id):
                return await func(update, context, *args, **kwargs)
            else:
                # 使用新的消息管理API发送频率限制错误消息
                await send_error(
                    context=context,
                    chat_id=update.effective_chat.id,
                    text="⚠️ 请求频率过高，请稍后重试。"
                )

                # 删除用户命令消息
                if (
                    hasattr(update, "effective_message")
                    and getattr(update.effective_message, "message_id", None)
                ):
                    await delete_user_command(
                        context=context,
                        chat_id=update.effective_chat.id,
                        message_id=update.effective_message.message_id
                    )

        return wrapper

    return decorator


class ErrorAnalyzer:
    """错误分析器"""

    @staticmethod
    def analyze_http_error(error: Exception) -> dict:
        """分析HTTP错误"""
        error_info = {
            "type": "unknown",
            "message": str(error),
            "retry_after": None,
            "user_message": "❌ 网络请求失败，请稍后重试。",
        }

        if isinstance(error, httpx.TimeoutException):
            error_info.update({"type": "timeout", "user_message": "⏱️ 请求超时，请稍后重试。"})
        elif isinstance(error, httpx.ConnectError):
            error_info.update({"type": "connection", "user_message": "🌐 网络连接失败，请检查网络状态。"})
        elif isinstance(error, httpx.HTTPStatusError):
            status_code = error.response.status_code
            if status_code == 429:
                # 尝试解析Retry-After头
                retry_after = error.response.headers.get("Retry-After")
                error_info.update(
                    {
                        "type": "rate_limit",
                        "retry_after": int(retry_after) if retry_after else 60,
                        "user_message": f"⚠️ 请求频率过高，请{retry_after or 60}秒后重试。",
                    }
                )
            elif status_code >= 500:
                error_info.update({"type": "server_error", "user_message": "🔧 服务器暂时不可用，请稍后重试。"})
            elif status_code == 404:
                error_info.update({"type": "not_found", "user_message": "❓ 请求的资源不存在。"})

        return error_info


def handle_api_errors(func):
    """API错误处理装饰器"""

    @wraps(func)
    async def wrapper(update, context, *args, **kwargs):
        try:
            return await func(update, context, *args, **kwargs)
        except Exception as e:
            error_info = ErrorAnalyzer.analyze_http_error(e)
            logger.error(f"API error in {func.__name__}: {error_info}")

            # 使用新的消息管理API发送错误消息
            await send_error(
                context=context,
                chat_id=update.effective_chat.id,
                text=error_info["user_message"]
            )

            # 删除用户命令消息
            if (
                hasattr(update, "effective_message")
                and getattr(update.effective_message, "message_id", None)
            ):
                await delete_user_command(
                    context=context,
                    chat_id=update.effective_chat.id,
                    message_id=update.effective_message.message_id
                )

    return wrapper
