"""
统一的会话管理器
用于替代全局字典，防止内存泄漏
"""

import logging
import threading
import time
from typing import Any


logger = logging.getLogger(__name__)


class SessionData:
    """会话数据"""

    def __init__(self, data: dict[str, Any], created_at: float, last_accessed: float, session_type: str = "default"):
        self.data = data
        self.created_at = created_at
        self.last_accessed = last_accessed
        self.session_type = session_type


class SessionManager:
    """
    统一的会话管理器
    自动过期清理，防止内存泄漏
    """

    def __init__(self, name: str, max_age: int = 3600, max_sessions: int = 1000):
        """
        初始化会话管理器

        Args:
            name: 管理器名称，用于日志
            max_age: 会话最大存活时间（秒），默认1小时
            max_sessions: 最大会话数量，防止无限增长
        """
        self.name = name
        self.sessions: dict[int, SessionData] = {}
        self.max_age = max_age
        self.max_sessions = max_sessions
        self._lock = threading.RLock()
        self._last_cleanup = time.time()
        self._cleanup_interval = 300  # 5分钟清理一次

    def set_session(self, user_id: int, data: dict[str, Any], session_type: str = "default") -> None:
        """
        设置用户会话

        Args:
            user_id: 用户ID
            data: 会话数据
            session_type: 会话类型，用于统计
        """
        with self._lock:
            now = time.time()
            self.sessions[user_id] = SessionData(
                data=data.copy(),  # 防止外部修改
                created_at=now,
                last_accessed=now,
                session_type=session_type,
            )

            # 定期清理
            if now - self._last_cleanup > self._cleanup_interval:
                self._cleanup_expired()
                self._last_cleanup = now

            # 强制执行数量限制
            self._enforce_session_limit()

            logger.debug(f"{self.name}: 设置用户 {user_id} 的会话 (类型: {session_type})")

    def get_session(self, user_id: int) -> dict[str, Any] | None:
        """
        获取用户会话

        Args:
            user_id: 用户ID

        Returns:
            会话数据，如果不存在或已过期则返回None
        """
        with self._lock:
            if user_id not in self.sessions:
                return None

            session = self.sessions[user_id]
            now = time.time()

            # 检查是否过期
            if now - session.created_at > self.max_age:
                del self.sessions[user_id]
                logger.debug(f"{self.name}: 用户 {user_id} 的会话已过期并被删除")
                return None

            # 更新访问时间
            session.last_accessed = now
            return session.data.copy()  # 返回副本防止外部修改

    def remove_session(self, user_id: int) -> bool:
        """
        移除用户会话

        Args:
            user_id: 用户ID

        Returns:
            是否成功移除
        """
        with self._lock:
            if user_id in self.sessions:
                session_type = self.sessions[user_id].session_type
                del self.sessions[user_id]
                logger.debug(f"{self.name}: 移除用户 {user_id} 的会话 (类型: {session_type})")
                return True
            return False

    def has_session(self, user_id: int) -> bool:
        """检查用户是否有活跃会话"""
        return self.get_session(user_id) is not None

    def _cleanup_expired(self) -> None:
        """清理过期会话"""
        now = time.time()
        expired_users = []

        for user_id, session in self.sessions.items():
            if now - session.created_at > self.max_age:
                expired_users.append(user_id)

        for user_id in expired_users:
            del self.sessions[user_id]

        if expired_users:
            logger.info(f"{self.name}: 清理了 {len(expired_users)} 个过期会话")

    def _enforce_session_limit(self) -> None:
        """强制执行会话数量限制"""
        if len(self.sessions) <= self.max_sessions:
            return

        # 按最后访问时间排序，移除最旧的会话
        sorted_sessions = sorted(self.sessions.items(), key=lambda x: x[1].last_accessed)

        # 移除多余的会话（保留一些余量）
        to_remove = len(self.sessions) - self.max_sessions + 50
        removed_count = 0

        for user_id, _session in sorted_sessions[:to_remove]:
            del self.sessions[user_id]
            removed_count += 1

        if removed_count > 0:
            logger.warning(f"{self.name}: 达到会话数量限制，移除了 {removed_count} 个最旧的会话")

    def force_cleanup(self) -> dict[str, int]:
        """强制清理所有过期会话和统计信息"""
        with self._lock:
            initial_count = len(self.sessions)
            self._cleanup_expired()
            final_count = len(self.sessions)

            return {
                "initial_count": initial_count,
                "final_count": final_count,
                "removed_count": initial_count - final_count,
            }

    def get_stats(self) -> dict[str, Any]:
        """获取会话统计信息"""
        with self._lock:
            now = time.time()
            session_ages = []
            session_types = {}

            for session in self.sessions.values():
                age = now - session.created_at
                session_ages.append(age)

                session_type = session.session_type
                session_types[session_type] = session_types.get(session_type, 0) + 1

            return {
                "name": self.name,
                "total_sessions": len(self.sessions),
                "max_sessions_limit": self.max_sessions,
                "max_age_limit": self.max_age,
                "avg_age_seconds": sum(session_ages) / len(session_ages) if session_ages else 0,
                "oldest_session_age": max(session_ages) if session_ages else 0,
                "session_types": session_types,
                "memory_usage_estimate_kb": len(self.sessions) * 2,  # 粗略估计
            }

    def clear_all(self) -> int:
        """清除所有会话"""
        with self._lock:
            count = len(self.sessions)
            self.sessions.clear()
            logger.info(f"{self.name}: 清除了所有 {count} 个会话")
            return count


# 创建全局会话管理器实例
app_search_session_manager = SessionManager("AppSearch", max_age=3600, max_sessions=500)
steam_search_session_manager = SessionManager("SteamSearch", max_age=3600, max_sessions=500)
steam_bundle_session_manager = SessionManager("SteamBundle", max_age=3600, max_sessions=300)


# 为了向后兼容，提供字典式接口的包装器
class CompatibleSessionDict:
    """向后兼容的字典式接口"""

    def __init__(self, session_manager: SessionManager, session_type: str = "default"):
        self.manager = session_manager
        self.session_type = session_type

    def __getitem__(self, user_id: int) -> dict[str, Any]:
        session = self.manager.get_session(user_id)
        if session is None:
            raise KeyError(user_id)
        return session

    def __setitem__(self, user_id: int, data: dict[str, Any]) -> None:
        self.manager.set_session(user_id, data, self.session_type)

    def __delitem__(self, user_id: int) -> None:
        if not self.manager.remove_session(user_id):
            raise KeyError(user_id)

    def __contains__(self, user_id: int) -> bool:
        return self.manager.has_session(user_id)

    def get(self, user_id: int, default=None):
        session = self.manager.get_session(user_id)
        return session if session is not None else default

    def pop(self, user_id: int, default=None):
        session = self.manager.get_session(user_id)
        if session is not None:
            self.manager.remove_session(user_id)
            return session
        return default

    def clear(self):
        self.manager.clear_all()

    def get_stats(self):
        """获取会话统计信息"""
        return self.manager.get_stats()

    def __len__(self):
        return self.manager.get_stats()["total_sessions"]


# 创建兼容性接口
app_search_sessions = CompatibleSessionDict(app_search_session_manager, "app_search")
steam_search_sessions = CompatibleSessionDict(steam_search_session_manager, "steam_search")
steam_bundle_sessions = CompatibleSessionDict(steam_bundle_session_manager, "steam_bundle")
