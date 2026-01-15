"""
AI反垃圾数据库管理器
负责反垃圾功能的数据库操作
"""
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
import aiomysql

logger = logging.getLogger(__name__)


class AntiSpamManager:
    """反垃圾数据库管理器"""

    def __init__(self, db_pool: aiomysql.Pool):
        """
        初始化反垃圾管理器

        Args:
            db_pool: MySQL连接池
        """
        self.pool = db_pool
        logger.info("AntiSpamManager initialized")

    # ==================== 配置管理 ====================

    async def is_group_enabled(self, group_id: int) -> bool:
        """检查群组是否启用了反垃圾功能"""
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(
                    "SELECT enabled FROM anti_spam_config WHERE group_id = %s",
                    (group_id,)
                )
                result = await cursor.fetchone()
                return result['enabled'] if result else False

    async def get_group_config(self, group_id: int) -> Optional[Dict]:
        """获取群组的反垃圾配置"""
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(
                    "SELECT * FROM anti_spam_config WHERE group_id = %s",
                    (group_id,)
                )
                return await cursor.fetchone()

    async def enable_group(self, group_id: int) -> bool:
        """启用群组的反垃圾功能"""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """INSERT INTO anti_spam_config (group_id, enabled)
                           VALUES (%s, TRUE)
                           ON DUPLICATE KEY UPDATE enabled = TRUE""",
                        (group_id,)
                    )
                    await conn.commit()
                    logger.info(f"Enabled anti-spam for group {group_id}")
                    return True
        except Exception as e:
            logger.error(f"Failed to enable anti-spam for group {group_id}: {e}")
            return False

    async def disable_group(self, group_id: int) -> bool:
        """禁用群组的反垃圾功能"""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "UPDATE anti_spam_config SET enabled = FALSE WHERE group_id = %s",
                        (group_id,)
                    )
                    await conn.commit()
                    logger.info(f"Disabled anti-spam for group {group_id}")
                    return True
        except Exception as e:
            logger.error(f"Failed to disable anti-spam for group {group_id}: {e}")
            return False

    async def update_config(self, group_id: int, **kwargs) -> bool:
        """更新群组配置"""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    fields = [f"{k} = %s" for k in kwargs.keys()]
                    values = list(kwargs.values()) + [group_id]
                    await cursor.execute(
                        f"UPDATE anti_spam_config SET {', '.join(fields)} WHERE group_id = %s",
                        values
                    )
                    await conn.commit()
                    return True
        except Exception as e:
            logger.error(f"Failed to update config for group {group_id}: {e}")
            return False

    async def get_all_enabled_groups(self) -> List[int]:
        """获取所有启用反垃圾功能的群组ID"""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "SELECT group_id FROM anti_spam_config WHERE enabled = TRUE"
                )
                results = await cursor.fetchall()
                return [row[0] for row in results]

    # ==================== 用户信息管理 ====================

    async def get_or_create_user_info(self, user_id: int, group_id: int,
                                      username: str = None, first_name: str = None) -> Dict:
        """获取或创建用户信息"""
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(
                    "SELECT * FROM anti_spam_user_info WHERE user_id = %s AND group_id = %s",
                    (user_id, group_id)
                )
                result = await cursor.fetchone()

                if result:
                    return result

                # 创建新用户记录
                await cursor.execute(
                    """INSERT INTO anti_spam_user_info
                       (user_id, group_id, username, first_name, joined_time)
                       VALUES (%s, %s, %s, %s, NOW())""",
                    (user_id, group_id, username, first_name)
                )
                await conn.commit()

                # 返回新创建的记录
                await cursor.execute(
                    "SELECT * FROM anti_spam_user_info WHERE user_id = %s AND group_id = %s",
                    (user_id, group_id)
                )
                return await cursor.fetchone()

    async def increment_speech_count(self, user_id: int, group_id: int) -> bool:
        """增加用户发言次数"""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """UPDATE anti_spam_user_info
                           SET number_of_speeches = number_of_speeches + 1,
                               last_message_time = NOW()
                           WHERE user_id = %s AND group_id = %s""",
                        (user_id, group_id)
                    )
                    await conn.commit()
                    return True
        except Exception as e:
            logger.error(f"Failed to increment speech count: {e}")
            return False

    async def mark_user_verified(self, user_id: int, group_id: int) -> bool:
        """标记用户已通过验证"""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """UPDATE anti_spam_user_info
                           SET verification_times = verification_times + 1,
                               is_verified = TRUE
                           WHERE user_id = %s AND group_id = %s""",
                        (user_id, group_id)
                    )
                    await conn.commit()
                    return True
        except Exception as e:
            logger.error(f"Failed to mark user verified: {e}")
            return False

    async def should_check_user(self, user_info: Dict, config: Dict) -> bool:
        """判断是否需要对用户进行AI检测"""
        if user_info.get('is_verified'):
            return False

        joined_time = user_info.get('joined_time')
        if not joined_time:
            return True

        days_since_join = (datetime.now() - joined_time).days
        speech_count = user_info.get('number_of_speeches', 0)
        verification_times = user_info.get('verification_times', 0)

        # 根据配置判断是否需要检测
        if days_since_join < config.get('joined_time_threshold', 3):
            return True
        if speech_count < config.get('speech_count_threshold', 3):
            return True
        if verification_times < config.get('verification_times_threshold', 1):
            return True

        return False

    # ==================== 日志管理 ====================

    async def log_detection(self, user_id: int, group_id: int, username: str,
                           message_type: str, message_text: str, spam_score: int,
                           spam_reason: str, spam_mock_text: str, is_spam: bool,
                           is_banned: bool, detection_time_ms: int) -> bool:
        """记录检测日志"""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """INSERT INTO anti_spam_logs
                           (user_id, group_id, username, message_type, message_text,
                            spam_score, spam_reason, spam_mock_text, is_spam, is_banned,
                            detection_time_ms)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        (user_id, group_id, username, message_type, message_text,
                         spam_score, spam_reason, spam_mock_text, is_spam, is_banned,
                         detection_time_ms)
                    )
                    await conn.commit()
                    return True
        except Exception as e:
            logger.error(f"Failed to log detection: {e}")
            return False

    async def get_recent_logs(self, group_id: int, limit: int = 50) -> List[Dict]:
        """获取最近的检测日志"""
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(
                    """SELECT * FROM anti_spam_logs
                       WHERE group_id = %s
                       ORDER BY created_at DESC
                       LIMIT %s""",
                    (group_id, limit)
                )
                return await cursor.fetchall()

    # ==================== 统计管理 ====================

    async def update_stats(self, group_id: int, spam_detected: bool = False,
                          user_banned: bool = False) -> bool:
        """更新统计数据"""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    today = datetime.now().date()
                    await cursor.execute(
                        """INSERT INTO anti_spam_stats
                           (group_id, date, total_checks, spam_detected, users_banned)
                           VALUES (%s, %s, 1, %s, %s)
                           ON DUPLICATE KEY UPDATE
                           total_checks = total_checks + 1,
                           spam_detected = spam_detected + %s,
                           users_banned = users_banned + %s""",
                        (group_id, today, 1 if spam_detected else 0, 1 if user_banned else 0,
                         1 if spam_detected else 0, 1 if user_banned else 0)
                    )
                    await conn.commit()
                    return True
        except Exception as e:
            logger.error(f"Failed to update stats: {e}")
            return False

    async def get_group_stats(self, group_id: int, days: int = 7) -> List[Dict]:
        """获取群组统计数据"""
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                start_date = datetime.now().date() - timedelta(days=days)
                await cursor.execute(
                    """SELECT * FROM anti_spam_stats
                       WHERE group_id = %s AND date >= %s
                       ORDER BY date DESC""",
                    (group_id, start_date)
                )
                return await cursor.fetchall()
