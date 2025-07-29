#!/usr/bin/env python3
"""
用户缓存处理器
自动缓存所有消息发送者的用户信息
"""

import logging

from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters

from utils.config_manager import get_config


logger = logging.getLogger(__name__)


async def cache_user_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    自动缓存用户信息的处理器
    """
    logger.debug("[UserCache] 处理器被触发")

    # 获取用户缓存管理器
    user_cache_manager = context.bot_data.get("user_cache_manager")
    if not user_cache_manager:
        logger.error("[UserCache] 无法获取用户缓存管理器")
        return

    # 获取消息和用户信息
    message = update.message
    if not message or not message.from_user:
        logger.debug("[UserCache] 消息或用户信息为空")
        return

    user = message.from_user
    chat_id = message.chat.id

    logger.debug(f"[UserCache] 处理消息: 用户={user.id}(@{user.username}), 群组={chat_id}")

    # 修改：缓存所有用户，不仅仅是有用户名的用户
    try:
        await user_cache_manager.update_user_cache(
            user_id=user.id, username=user.username, first_name=user.first_name, last_name=user.last_name
        )
        # 日志记录已移至 user_cache_manager 内部，此处不再重复记录
    except Exception as e:
        logger.error(f"[UserCache] 缓存用户信息失败: {e}")


def setup_user_cache_handler(application):
    """
    设置用户缓存处理器
    """
    config = get_config()

    # 检查是否启用用户缓存
    if not config.enable_user_cache:
        logger.info("用户缓存功能已禁用，跳过设置用户缓存处理器")
        return

    # 检查是否配置了监听群组
    if config.user_cache_group_ids:
        # 如果配置了群组，只监听指定群组
        group_filter = filters.Chat(config.user_cache_group_ids)
        handler = MessageHandler((filters.ChatType.SUPERGROUP | filters.ChatType.GROUP) & group_filter, cache_user_info)
        logger.info(
            f"✅ 用户缓存处理器已设置，监听指定 {len(config.user_cache_group_ids)} 个群组: {config.user_cache_group_ids}"
        )
    else:
        # 如果未配置群组，监听所有群组
        handler = MessageHandler(filters.ChatType.SUPERGROUP | filters.ChatType.GROUP, cache_user_info)
        logger.info("✅ 用户缓存处理器已设置，监听所有群组（未配置指定群组）")

    # 添加到应用程序，使用较高的优先级（group=1）以确保先执行
    # group 数字越小，优先级越高
    application.add_handler(handler, group=1)
