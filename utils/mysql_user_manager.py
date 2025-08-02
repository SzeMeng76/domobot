"""
MySQL 用户管理器
保持与现有 UserCacheManager 相同的接口，底层改用 MySQL
"""

import logging
from contextlib import asynccontextmanager

from aiomysql import DictCursor, create_pool


logger = logging.getLogger(__name__)


class MySQLUserManager:
    """MySQL 用户管理器"""

    def __init__(self, host: str, port: int, database: str, user: str, password: str):
        """初始化 MySQL 连接参数"""
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.pool = None
        self._connected = False

    async def connect(self):
        """创建连接池"""
        try:
            # 获取连接池配置
            from utils.config_manager import get_config

            config = get_config()

            self.pool = await create_pool(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                db=self.database,
                charset="utf8mb4",
                autocommit=True,
                minsize=config.db_min_connections,
                maxsize=config.db_max_connections,
                echo=False,
                cursorclass=DictCursor,
            )
            self._connected = True
            logger.info("✅ MySQL 连接池创建成功")

            # 初始化超级管理员（如果配置了）
            await self._init_super_admin()

        except Exception as e:
            logger.error(f"❌ MySQL 连接失败: {e}")
            raise

    async def close(self):
        """关闭连接池"""
        if self.pool:
            self.pool.close()
            await self.pool.wait_closed()
            self._connected = False
            logger.info("MySQL 连接池已关闭")

    @asynccontextmanager
    async def get_cursor(self):
        """获取数据库游标的上下文管理器"""
        async with self.pool.acquire() as conn, conn.cursor(DictCursor) as cursor:
            yield cursor

    async def _init_super_admin(self):
        """初始化超级管理员"""
        from utils.config_manager import get_config

        config = get_config()

        if config.super_admin_id:
            try:
                async with self.get_cursor() as cursor:
                    # 先确保用户存在
                    await cursor.execute("INSERT IGNORE INTO users (user_id) VALUES (%s)", (config.super_admin_id,))

                    # 添加到超级管理员表
                    await cursor.execute(
                        "INSERT IGNORE INTO super_admins (user_id) VALUES (%s)", (config.super_admin_id,)
                    )

                logger.info(f"超级管理员已初始化: {config.super_admin_id}")
            except Exception as e:
                logger.error(f"初始化超级管理员失败: {e}")

    async def update_user_cache(
        self, user_id: int, username: str | None = None, first_name: str | None = None, last_name: str | None = None
    ):
        """更新用户缓存，保持与原接口相同"""
        if not self._connected:
            logger.warning("MySQL 未连接")
            return

        try:
            async with self.get_cursor() as cursor:
                # 优化: 使用INSERT ... ON DUPLICATE KEY UPDATE避免重复查询
                await cursor.execute(
                    """
                    INSERT INTO users (user_id, username, first_name, last_name, last_seen, created_at)
                    VALUES (%s, %s, %s, %s, NOW(), NOW()) AS new_user
                    ON DUPLICATE KEY UPDATE
                        username = new_user.username,
                        first_name = new_user.first_name,
                        last_name = new_user.last_name,
                        last_seen = NOW()
                """,
                    (user_id, username, first_name, last_name),
                )

            logger.debug(f"用户缓存已更新: {user_id}")

        except Exception as e:
            logger.error(f"更新用户缓存失败: {e}")

    async def get_user_from_cache(self, user_id: int) -> dict | None:
        """从缓存获取用户信息"""
        if not self._connected:
            return None

        try:
            async with self.get_cursor() as cursor:
                await cursor.execute(
                    "SELECT user_id, username, first_name, last_name FROM users WHERE user_id = %s", (user_id,)
                )
                result = await cursor.fetchone()
                return result

        except Exception as e:
            logger.error(f"获取用户缓存失败: {e}")
            return None

    async def get_user_by_username(self, username: str) -> dict | None:
        """通过用户名获取用户信息"""
        if not self._connected:
            return None

        try:
            async with self.get_cursor() as cursor:
                await cursor.execute(
                    "SELECT user_id, username, first_name, last_name FROM users WHERE username = %s", (username,)
                )
                result = await cursor.fetchone()
                return result

        except Exception as e:
            logger.error(f"通过用户名获取用户失败: {e}")
            return None

    # 管理员相关方法
    async def is_admin(self, user_id: int) -> bool:
        """检查是否为管理员"""
        if not self._connected:
            return False

        try:
            async with self.get_cursor() as cursor:
                # 检查是否为超级管理员
                await cursor.execute("SELECT 1 FROM super_admins WHERE user_id = %s", (user_id,))
                if await cursor.fetchone():
                    return True

                # 检查是否为普通管理员
                await cursor.execute("SELECT 1 FROM admin_permissions WHERE user_id = %s", (user_id,))
                return await cursor.fetchone() is not None

        except Exception as e:
            logger.error(f"检查管理员权限失败: {e}")
            return False

    async def is_super_admin(self, user_id: int) -> bool:
        """检查是否为超级管理员"""
        if not self._connected:
            return False

        try:
            async with self.get_cursor() as cursor:
                await cursor.execute("SELECT 1 FROM super_admins WHERE user_id = %s", (user_id,))
                return await cursor.fetchone() is not None

        except Exception as e:
            logger.error(f"检查超级管理员权限失败: {e}")
            return False

    async def get_all_admins(self) -> list[int]:
        """获取所有管理员ID列表"""
        if not self._connected:
            return []

        try:
            async with self.get_cursor() as cursor:
                # 获取所有管理员（包括超级管理员）
                await cursor.execute("""
                    SELECT user_id FROM admin_permissions
                    UNION
                    SELECT user_id FROM super_admins
                """)
                results = await cursor.fetchall()
                return [row["user_id"] for row in results]

        except Exception as e:
            logger.error(f"获取管理员列表失败: {e}")
            return []

    async def add_admin(self, user_id: int, granted_by: int) -> bool:
        """添加管理员"""
        if not self._connected:
            return False

        try:
            async with self.get_cursor() as cursor:
                # 确保用户存在
                await cursor.execute("INSERT IGNORE INTO users (user_id) VALUES (%s)", (user_id,))

                # 添加管理员权限
                await cursor.execute(
                    "INSERT IGNORE INTO admin_permissions (user_id, granted_by) VALUES (%s, %s)", (user_id, granted_by)
                )

            logger.info(f"管理员已添加: {user_id}")
            return True

        except Exception as e:
            logger.error(f"添加管理员失败: {e}")
            return False

    async def remove_admin(self, user_id: int) -> bool:
        """移除管理员"""
        if not self._connected:
            return False

        try:
            async with self.get_cursor() as cursor:
                await cursor.execute("DELETE FROM admin_permissions WHERE user_id = %s", (user_id,))

            logger.info(f"管理员已移除: {user_id}")
            return True

        except Exception as e:
            logger.error(f"移除管理员失败: {e}")
            return False

    # 白名单相关方法
    async def is_whitelisted(self, user_id: int) -> bool:
        """检查用户是否在白名单中"""
        if not self._connected:
            return False

        try:
            async with self.get_cursor() as cursor:
                await cursor.execute("SELECT 1 FROM user_whitelist WHERE user_id = %s", (user_id,))
                return await cursor.fetchone() is not None

        except Exception as e:
            logger.error(f"检查用户白名单失败: {e}")
            return False

    async def is_group_whitelisted(self, group_id: int) -> bool:
        """检查群组是否在白名单中"""
        if not self._connected:
            return False

        try:
            async with self.get_cursor() as cursor:
                await cursor.execute("SELECT 1 FROM group_whitelist WHERE group_id = %s", (group_id,))
                return await cursor.fetchone() is not None

        except Exception as e:
            logger.error(f"检查群组白名单失败: {e}")
            return False

    async def add_to_whitelist(self, user_id: int, added_by: int) -> bool:
        """添加用户到白名单"""
        if not self._connected:
            return False

        try:
            async with self.get_cursor() as cursor:
                # 确保用户存在
                await cursor.execute("INSERT IGNORE INTO users (user_id) VALUES (%s)", (user_id,))

                # 添加到白名单
                await cursor.execute(
                    "INSERT IGNORE INTO user_whitelist (user_id, added_by) VALUES (%s, %s)", (user_id, added_by)
                )

            logger.info(f"用户已添加到白名单: {user_id}")
            return True

        except Exception as e:
            logger.error(f"添加到白名单失败: {e}")
            return False

    async def remove_from_whitelist(self, user_id: int) -> bool:
        """从白名单移除用户"""
        if not self._connected:
            return False

        try:
            async with self.get_cursor() as cursor:
                await cursor.execute("DELETE FROM user_whitelist WHERE user_id = %s", (user_id,))

            logger.info(f"用户已从白名单移除: {user_id}")
            return True

        except Exception as e:
            logger.error(f"从白名单移除失败: {e}")
            return False

    async def add_group_to_whitelist(self, group_id: int, group_name: str | None, added_by: int) -> bool:
        """添加群组到白名单"""
        if not self._connected:
            return False

        try:
            async with self.get_cursor() as cursor:
                await cursor.execute(
                    "INSERT INTO group_whitelist (group_id, group_name, added_by) VALUES (%s, %s, %s) AS new_group "
                    "ON DUPLICATE KEY UPDATE group_name = new_group.group_name",
                    (group_id, group_name, added_by),
                )

            logger.info(f"群组已添加到白名单: {group_id}")
            return True

        except Exception as e:
            logger.error(f"添加群组到白名单失败: {e}")
            return False

    async def remove_group_from_whitelist(self, group_id: int) -> bool:
        """从白名单移除群组"""
        if not self._connected:
            return False

        try:
            async with self.get_cursor() as cursor:
                await cursor.execute("DELETE FROM group_whitelist WHERE group_id = %s", (group_id,))

            logger.info(f"群组已从白名单移除: {group_id}")
            return True

        except Exception as e:
            logger.error(f"从白名单移除群组失败: {e}")
            return False

    async def get_whitelisted_users(self) -> list[int]:
        """获取白名单用户列表"""
        if not self._connected:
            return []

        try:
            async with self.get_cursor() as cursor:
                await cursor.execute("SELECT user_id FROM user_whitelist")
                results = await cursor.fetchall()
                return [row["user_id"] for row in results]

        except Exception as e:
            logger.error(f"获取白名单用户失败: {e}")
            return []

    async def get_whitelisted_groups(self) -> list[dict]:
        """获取白名单群组列表"""
        if not self._connected:
            return []

        try:
            async with self.get_cursor() as cursor:
                await cursor.execute("SELECT group_id, group_name FROM group_whitelist")
                results = await cursor.fetchall()
                return results

        except Exception as e:
            logger.error(f"获取白名单群组失败: {e}")
            return []

    # 统计相关方法
    async def log_command(self, command: str, user_id: int, chat_id: int, chat_type: str):
        """记录命令使用情况"""
        if not self._connected:
            return

        try:
            async with self.get_cursor() as cursor:
                await cursor.execute(
                    "INSERT INTO command_stats (command, user_id, chat_id, chat_type) VALUES (%s, %s, %s, %s)",
                    (command, user_id, chat_id, chat_type),
                )

        except Exception as e:
            logger.error(f"记录命令失败: {e}")

    async def log_admin_action(
        self,
        admin_id: int,
        action: str,
        target_type: str | None = None,
        target_id: int | None = None,
        details: str | None = None,
    ):
        """记录管理员操作"""
        if not self._connected:
            return

        try:
            async with self.get_cursor() as cursor:
                await cursor.execute(
                    "INSERT INTO admin_logs (admin_id, action, target_type, target_id, details) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (admin_id, action, target_type, target_id, details),
                )

        except Exception as e:
            logger.error(f"记录管理员操作失败: {e}")
