#!/usr/bin/env python3
"""
命令工厂模块
统一管理和注册命令，支持装饰器、权限检查、错误处理等功能
"""

import logging
from collections.abc import Callable
from typing import Any

from telegram.ext import Application, CallbackQueryHandler, CommandHandler

from utils.error_handling import RetryConfig, with_error_handling, with_rate_limit, with_retry
from utils.permissions import Permission, require_permission


logger = logging.getLogger(__name__)


class CommandFactory:
    """命令工厂类"""

    def __init__(self):
        self.commands: dict[str, dict[str, Any]] = {}
        self.callbacks: dict[str, dict[str, Any]] = {}

    def register_command(
        self,
        command: str,
        handler: Callable,
        permission: Permission = Permission.USER,
        description: str = "",
        use_retry: bool = True,
        use_rate_limit: bool = True,
        rate_limit_key: str | None = None,
    ):
        """
        注册命令

        Args:
            command: 命令名称
            handler: 命令处理函数
            permission: 所需权限等级
            description: 命令描述
            use_retry: 是否使用重试装饰器
            use_rate_limit: 是否使用速率限制
            rate_limit_key: 速率限制键名
        """
        decorated_handler = handler
        if handler is not None:
            # 应用错误处理装饰器
            decorated_handler = with_error_handling(decorated_handler)

            # 应用重试装饰器
            if use_retry:
                decorated_handler = with_retry(config=RetryConfig(max_retries=3))(decorated_handler)

            # 应用速率限制装饰器
            if use_rate_limit:
                key = rate_limit_key or f"command_{command}"
                decorated_handler = with_rate_limit(name=key)(decorated_handler)

            # 应用权限检查装饰器
            decorated_handler = require_permission(permission)(decorated_handler)

        self.commands[command] = {
            "handler": decorated_handler,
            "permission": permission,
            "description": description,
            "original_handler": handler,
        }

        logger.info(f"注册命令: /{command} (权限: {permission.name})")

    def register_callback(
        self, pattern: str, handler: Callable, permission: Permission = Permission.USER, description: str = ""
    ):
        """
        注册回调查询处理器

        Args:
            pattern: 匹配模式
            handler: 处理函数
            permission: 所需权限等级
            description: 描述
        """
        # 应用装饰器
        decorated_handler = with_error_handling(handler)
        decorated_handler = require_permission(permission)(decorated_handler)

        self.callbacks[pattern] = {
            "handler": decorated_handler,
            "permission": permission,
            "description": description,
            "original_handler": handler,
        }

        logger.info(f"注册回调: {pattern} (权限: {permission.name})")

    def setup_handlers(self, application: Application):
        """设置命令处理器到应用"""
        # 注册命令处理器
        for command, info in self.commands.items():
            if info["handler"] is not None:
                application.add_handler(CommandHandler(command.lstrip("/"), info["handler"]))
                logger.debug(f"添加命令处理器: /{command}")

        # 注册回调查询处理器
        for pattern, info in self.callbacks.items():
            if info["handler"] is not None:
                application.add_handler(CallbackQueryHandler(info["handler"], pattern=pattern))
                logger.debug(f"添加回调处理器: {pattern}")

        logger.info(f"已注册 {len(self.commands)} 个命令和 {len(self.callbacks)} 个回调处理器")

    def get_command_list(self, user_permission: Permission = Permission.USER) -> dict[str, str]:
        """
        获取用户可用的命令列表

        Args:
            user_permission: 用户权限等级

        Returns:
            可用命令及其描述的字典
        """
        available_commands = {}

        for command, info in self.commands.items():
            required_permission = info["permission"]

            # 检查权限等级
            if self._has_permission(user_permission, required_permission):
                available_commands[command] = info["description"]

        return available_commands

    def _has_permission(self, user_permission: Permission, required_permission: Permission) -> bool:
        """检查用户是否有足够权限"""
        permission_levels = {Permission.USER: 1, Permission.ADMIN: 2, Permission.SUPER_ADMIN: 3}

        user_level = permission_levels.get(user_permission, 0)
        required_level = permission_levels.get(required_permission, 1)

        return user_level >= required_level


# 全局命令工厂实例
command_factory = CommandFactory()
