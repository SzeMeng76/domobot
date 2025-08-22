#!/usr/bin/env python3
"""
多功能Telegram价格查询机器人
支持汇率查询、Steam游戏价格、流媒体订阅价格、应用商店价格查询等功能

功能特点:
- 汇率实时查询和转换
- Steam游戏价格多国对比
- Netflix、Disney+、Spotify等流媒体价格查询
- App Store、Google Play应用价格查询
- 管理员权限系统
- 用户和群组白名单管理
- 用户缓存管理
"""

import importlib
import logging
import logging.handlers
import os
import pkgutil

from telegram import BotCommand, Update
from telegram.ext import (
    Application,
    ContextTypes,
)


# 导入环境变量配置
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    print("⚠️ python-dotenv 未安装，直接使用环境变量")

# ========================================
# 配置日志系统
# ========================================
from utils.config_manager import get_config


config = get_config()

# 确保日志目录存在
os.makedirs(os.path.dirname(config.log_file), exist_ok=True)

# 配置日志系统（带轮换和压缩）
# 日志级别优先从环境变量 LOG_LEVEL 读取，默认为 INFO
log_level = os.getenv("LOG_LEVEL", config.log_level).upper()
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=getattr(logging, log_level, logging.INFO),
    handlers=[
        logging.handlers.RotatingFileHandler(
            config.log_file, maxBytes=config.log_max_size, backupCount=config.log_backup_count, encoding="utf-8"
        ),
        logging.StreamHandler(),
    ],
)

# 设置第三方库日志级别
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# 输出关键配置信息
logger.info("=" * 50)
logger.info(" Telegram Bot 启动")
logger.info("=" * 50)
logger.info(f" 自动删除延迟: {config.auto_delete_delay} 秒")
logger.info(f" 用户命令删除延迟: {config.user_command_delete_delay} 秒")
logger.info(f" 删除用户命令: {'启用' if config.delete_user_commands else '禁用'}")
logger.info(f" 日志级别: {config.log_level.upper()}")
logger.info("=" * 50)

# ========================================
# 导入核心模块
# ========================================
# ========================================
# 导入命令模块
# ========================================
from commands import (
    admin_commands,
    app_store,
    apple_services,
    bin,
    cache_manager_command,
    cooking,
    crypto,
    disney_plus,
    finance,
    google_play,
    help_command,
    map,
    max,
    memes,
    movie,
    netflix,
    news,
    spotify,
    steam,
    system_commands,
    time_command,
    weather,
    whois,
)
from commands.rate_command import set_rate_converter
from handlers.user_cache_handler import setup_user_cache_handler  # 新增：导入用户缓存处理器
from utils.command_factory import command_factory
from utils.error_handling import with_error_handling
from utils.log_manager import schedule_log_maintenance
from utils.mysql_user_manager import MySQLUserManager
from utils.permissions import Permission
from utils.rate_converter import RateConverter

# 导入 Redis 和 MySQL 管理器
from utils.redis_cache_manager import RedisCacheManager
from utils.redis_message_delete_scheduler import get_message_delete_scheduler
from utils.redis_stats_manager import RedisStatsManager
from utils.redis_task_scheduler import init_task_scheduler as redis_init_task_scheduler
from utils.script_loader import init_script_loader


@with_error_handling
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理错误"""
    logger.error("Exception while handling an update:", exc_info=context.error)

    # 尝试向用户发送错误信息
    if isinstance(update, Update) and update.effective_message:
        try:
            from utils.config_manager import get_config
            from utils.message_manager import send_and_auto_delete

            config = get_config()

            # 使用自动删除功能发送错误消息
            await send_and_auto_delete(
                context=context,
                chat_id=update.effective_chat.id,
                text="❌ 处理请求时发生错误，请稍后重试。\n如果问题持续存在，请联系管理员。",
                delay=config.auto_delete_delay,
                command_message_id=update.effective_message.message_id
                if hasattr(update.effective_message, "message_id")
                else None,
            )
        except Exception as e:
            logger.error(f"发送错误消息失败: {e}")  # 记录失败原因而不是静默忽略


def load_commands():
    """动态加载并注册所有命令"""
    commands_dir = "commands"
    for _, name, _ in pkgutil.iter_modules([commands_dir]):
        try:
            importlib.import_module(f"{commands_dir}.{name}")
            logger.info(f"成功加载命令模块: {name}")
        except Exception as e:
            logger.error(f"加载命令模块 {name} 失败: {e}")


def setup_handlers(application: Application):
    """设置命令处理器"""

    # 动态加载所有命令
    load_commands()

    # 使用命令工厂设置处理器
    command_factory.setup_handlers(application)

    # 手动添加管理员对话处理器
    from commands.admin_commands import admin_panel_handler

    application.add_handler(admin_panel_handler.get_conversation_handler())

    # 错误处理器
    application.add_error_handler(error_handler)

    logger.info("所有命令处理器已设置完成")


async def setup_application(application: Application, config) -> None:
    """异步设置应用"""
    logger.info(" 开始初始化机器人应用...")

    # ========================================
    # 第零步：检查并初始化数据库
    # ========================================
    logger.info("🔍 检查数据库...")
    from utils.database_init import check_and_init_database

    db_initialized = await check_and_init_database(config)
    if not db_initialized:
        logger.error("❌ 数据库初始化失败，无法继续")
        raise RuntimeError("数据库初始化失败")

    # ========================================
    # 第一步：初始化核心组件
    # ========================================
    logger.info(" 初始化核心组件...")

    # 初始化 Redis 缓存管理器
    cache_manager = RedisCacheManager(
        host=config.redis_host, port=config.redis_port, password=config.redis_password, db=config.redis_db
    )
    await cache_manager.connect()

    # 初始化 MySQL 用户管理器
    user_cache_manager = MySQLUserManager(
        host=config.db_host,
        port=config.db_port,
        database=config.db_name,
        user=config.db_user,
        password=config.db_password,
    )
    await user_cache_manager.connect()

    # 初始化 Redis 统计管理器
    stats_manager = RedisStatsManager(cache_manager.redis_client)

    # 初始化汇率转换器
    rate_converter = RateConverter(config.exchange_rate_api_keys, cache_manager)

    # 初始化优化的 HTTP 客户端
    from utils.http_client import get_http_client

    httpx_client = get_http_client()

    # 将核心组件存储到 bot_data 中
    application.bot_data["cache_manager"] = cache_manager
    application.bot_data["rate_converter"] = rate_converter
    application.bot_data["httpx_client"] = httpx_client
    application.bot_data["user_cache_manager"] = user_cache_manager
    application.bot_data["stats_manager"] = stats_manager
    logger.info("✅ 核心组件初始化完成")

    # ========================================
    # 第二步：为命令模块注入依赖
    # ========================================
    logger.info(" 注入命令模块依赖...")
    set_rate_converter(rate_converter)
    steam.set_rate_converter(rate_converter)
    steam.set_cache_manager(cache_manager)
    steam.set_steam_checker(cache_manager, rate_converter)
    netflix.set_dependencies(cache_manager, rate_converter)
    disney_plus.set_dependencies(cache_manager, rate_converter)
    spotify.set_dependencies(cache_manager, rate_converter)
    max.set_dependencies(cache_manager, rate_converter)
    app_store.set_rate_converter(rate_converter)
    app_store.set_cache_manager(cache_manager)
    google_play.set_rate_converter(rate_converter)
    google_play.set_cache_manager(cache_manager)
    apple_services.set_rate_converter(rate_converter)
    weather.set_dependencies(cache_manager, httpx_client)
    crypto.set_dependencies(cache_manager, httpx_client)
    bin.set_dependencies(cache_manager, httpx_client)
    movie.set_dependencies(cache_manager, httpx_client)
    movie.init_movie_service()
    time_command.set_dependencies(cache_manager)
    news.set_dependencies(cache_manager)
    whois.set_dependencies(cache_manager)
    cooking.set_dependencies(cache_manager, httpx_client)
    memes.set_dependencies(cache_manager, httpx_client)
    finance.set_dependencies(cache_manager, httpx_client)
    map.set_dependencies(cache_manager, httpx_client)

    # 新增：为需要用户缓存的模块注入依赖
    # 这里可以根据实际需要为特定命令模块注入用户缓存管理器
    # 例如：system_commands.set_user_cache_manager(user_cache_manager)

    logger.info("✅ 命令模块依赖注入完成")

    # ========================================
    # 第三步：初始化任务管理系统
    # ========================================
    logger.info("⚙️ 初始化任务管理系统...")

    # 初始化任务管理器
    from utils.task_manager import get_task_manager

    task_manager = get_task_manager()
    logger.info(f" 任务管理器已初始化，最大任务数: {task_manager.max_tasks}")

    # 初始化 Redis 定时任务调度器
    task_scheduler = redis_init_task_scheduler(cache_manager, cache_manager.redis_client)
    task_scheduler.set_rate_converter(rate_converter)  # 设置汇率转换器
    application.bot_data["task_scheduler"] = task_scheduler

    # 根据配置添加定时清理任务
    cleanup_tasks_added = 0
    if config.spotify_weekly_cleanup:
        await task_scheduler.add_weekly_cache_cleanup("spotify", "spotify", weekday=6, hour=5, minute=0)
        logger.info(" 已配置 Spotify 每周日UTC 5:00 定时清理")
        cleanup_tasks_added += 1

    if config.disney_weekly_cleanup:
        await task_scheduler.add_weekly_cache_cleanup("disney_plus", "disney_plus", weekday=6, hour=5, minute=0)
        logger.info(" 已配置 Disney+ 每周日UTC 5:00 定时清理")
        cleanup_tasks_added += 1

    if config.max_weekly_cleanup:
        await task_scheduler.add_weekly_cache_cleanup("max", "max", weekday=6, hour=5, minute=0)
        logger.info(" 已配置 HBO Max 每周日UTC 5:00 定时清理")
        cleanup_tasks_added += 1

    if config.movie_weekly_cleanup:
        await task_scheduler.add_weekly_cache_cleanup("movie", "movie", weekday=6, hour=5, minute=0)
        logger.info(" 已配置 电影和电视剧 每周日UTC 5:00 定时清理")
        cleanup_tasks_added += 1

    if config.news_weekly_cleanup:
        await task_scheduler.add_weekly_cache_cleanup("news", "news", weekday=6, hour=5, minute=0)
        logger.info(" 已配置 新闻缓存 每周日UTC 5:00 定时清理")
        cleanup_tasks_added += 1

    if config.whois_weekly_cleanup:
        await task_scheduler.add_weekly_cache_cleanup("whois", "whois", weekday=6, hour=5, minute=0)
        logger.info(" 已配置 WHOIS缓存 每周日UTC 5:00 定时清理")
        cleanup_tasks_added += 1

    if config.time_weekly_cleanup:
        await task_scheduler.add_weekly_cache_cleanup("time", "time", weekday=6, hour=5, minute=0)
        logger.info(" 已配置 时区缓存 每周日UTC 5:00 定时清理")
        cleanup_tasks_added += 1

    if config.cooking_weekly_cleanup:
        await task_scheduler.add_weekly_cache_cleanup("cooking", "cooking", weekday=6, hour=5, minute=0)
        logger.info(" 已配置 烹饪菜谱缓存 每周日UTC 5:00 定时清理")
        cleanup_tasks_added += 1

    if config.memes_weekly_cleanup:
        await task_scheduler.add_weekly_cache_cleanup("memes", "memes", weekday=6, hour=5, minute=0)
        logger.info(" 已配置 表情包缓存 每周日UTC 5:00 定时清理")
        cleanup_tasks_added += 1

    if config.finance_weekly_cleanup:
        await task_scheduler.add_weekly_cache_cleanup("finance", "finance", weekday=6, hour=5, minute=0)
        logger.info(" 已配置 金融数据缓存 每周日UTC 5:00 定时清理")
        cleanup_tasks_added += 1

    if config.map_weekly_cleanup:
        await task_scheduler.add_weekly_cache_cleanup("map", "map", weekday=6, hour=5, minute=0)
        logger.info(" 已配置 地图服务缓存 每周日UTC 5:00 定时清理")
        cleanup_tasks_added += 1

    # 启动任务调度器（包含汇率刷新任务）
    task_scheduler.start()
    if cleanup_tasks_added > 0:
        logger.info(f" 定时任务调度器已启动，活动任务: {cleanup_tasks_added + 1} 个（含汇率刷新）")
    else:
        logger.info(" 定时任务调度器已启动，仅汇率刷新任务")

    # 初始化并启动 Redis 消息删除调度器
    message_delete_scheduler = get_message_delete_scheduler(cache_manager.redis_client)
    message_delete_scheduler.start(application.bot)
    application.bot_data["message_delete_scheduler"] = message_delete_scheduler
    logger.info("️ 消息删除调度器已启动")

    # 调度日志维护任务
    schedule_log_maintenance()
    logger.info(" 日志维护任务已调度")

    logger.info("✅ 任务管理系统初始化完成")

    # ========================================
    # 第四步：预加载数据
    # ========================================
    logger.info(" 预加载数据...")
    try:
        await rate_converter.get_rates()
        logger.info("✅ 汇率数据预加载完成")
    except Exception as e:
        logger.warning(f"⚠️ 汇率数据预加载失败: {e}")

    # ========================================
    # 第五步：设置命令处理器
    # ========================================
    logger.info("🔧 设置命令处理器...")
    setup_handlers(application)
    logger.info("✅ 命令处理器设置完成")

    # ========================================
    # 第五步半：设置用户缓存处理器
    # ========================================
    logger.info("🔧 设置用户缓存处理器...")
    setup_user_cache_handler(application)
    logger.info("✅ 用户缓存处理器设置完成")

    # ========================================
    # 第六步：设置机器人命令菜单（分权限显示）
    # ========================================
    logger.info("📱 设置机器人命令菜单...")

    # 获取不同权限级别的命令
    none_commands = command_factory.get_command_list(Permission.NONE)
    user_commands = command_factory.get_command_list(Permission.USER)
    admin_commands = command_factory.get_command_list(Permission.ADMIN)
    super_admin_commands = command_factory.get_command_list(Permission.SUPER_ADMIN)

    try:
        # 默认命令菜单（给非白名单用户显示基础命令）
        basic_commands = {}
        basic_commands.update(none_commands)
        basic_bot_commands = [BotCommand(command, description) for command, description in basic_commands.items()]
        await application.bot.set_my_commands(basic_bot_commands)
        
        # 准备白名单用户命令菜单（基础命令 + 用户命令）
        user_level_commands = {}
        user_level_commands.update(none_commands)
        user_level_commands.update(user_commands)
        user_bot_commands = [BotCommand(command, description) for command, description in user_level_commands.items()]
        
        # 准备管理员完整命令菜单
        all_commands = {}
        all_commands.update(none_commands)
        all_commands.update(user_commands)
        all_commands.update(admin_commands)
        all_commands.update(super_admin_commands)
        # 手动添加由ConversationHandler处理的admin命令
        all_commands["admin"] = "打开管理员面板"
        
        full_bot_commands = [BotCommand(command, description) for command, description in all_commands.items()]
        
        from telegram import BotCommandScopeChat
        
        user_manager = application.bot_data.get("user_cache_manager")
        if user_manager:
            try:
                # 为白名单用户设置用户级命令菜单
                whitelist_users = await user_manager.get_whitelisted_users()
                for user_id in whitelist_users:
                    if user_id != config.super_admin_id:  # 超级管理员后面单独设置
                        await application.bot.set_my_commands(
                            user_bot_commands,
                            scope=BotCommandScopeChat(chat_id=user_id)
                        )
                
                # 为管理员设置完整命令菜单
                admin_list = await user_manager.get_all_admins()
                for admin_id in admin_list:
                    await application.bot.set_my_commands(
                        full_bot_commands,
                        scope=BotCommandScopeChat(chat_id=admin_id)
                    )
                
                # 为超级管理员设置完整命令菜单
                if config.super_admin_id:
                    await application.bot.set_my_commands(
                        full_bot_commands,
                        scope=BotCommandScopeChat(chat_id=config.super_admin_id)
                    )
                
                # 为白名单群组设置群组级命令菜单
                whitelist_groups = await user_manager.get_whitelisted_groups()
                for group in whitelist_groups:
                    group_id = group['group_id']
                    await application.bot.set_my_commands(
                        user_bot_commands,  # 群组显示用户级命令（不包含管理员命令）
                        scope=BotCommandScopeChat(chat_id=group_id)
                    )
                
                logger.info(f"👥 已为 {len(whitelist_users)} 位白名单用户设置用户级命令菜单")
                logger.info(f"👥 已为 {len(whitelist_groups)} 个白名单群组设置群组级命令菜单")
                logger.info(f"🔧 已为 {len(admin_list) + (1 if config.super_admin_id else 0)} 位管理员设置完整命令菜单")
                
            except Exception as e:
                logger.warning(f"⚠️ 为用户设置命令菜单时出错: {e}")
        
        logger.info("✅ 命令菜单设置完成:")
        logger.info(f"🌐 默认显示基础命令: {len(basic_commands)} 条")
        logger.info(f"👥 白名单用户显示: {len(user_level_commands)} 条")
        logger.info(f"🔧 管理员显示全部命令: {len(all_commands)} 条")
        logger.info("ℹ️ 用户权限在运行时检查")
        
    except Exception as e:
        logger.error(f"❌ 设置机器人命令菜单失败: {e}")

    # ========================================
    # 第七步：加载自定义脚本（可选）
    # ========================================
    if config.load_custom_scripts:
        logger.info(" 加载自定义脚本...")
        script_loader = init_script_loader(config.custom_scripts_dir)

        # 准备机器人上下文供脚本使用
        bot_context = {
            "application": application,
            "cache_manager": cache_manager,
            "rate_converter": rate_converter,
            "task_scheduler": task_scheduler,
            "user_cache_manager": user_cache_manager,  # 新增：为脚本提供用户缓存管理器
            "stats_manager": stats_manager,  # 新增：统计管理器
            "config": config,
            "logger": logger,
        }

        # 加载脚本
        success = script_loader.load_scripts(bot_context)
        if success:
            logger.info("✅ 自定义脚本加载完成")
        else:
            logger.warning("⚠️ 部分自定义脚本加载失败")

        # 将脚本加载器存储到bot_data中
        application.bot_data["script_loader"] = script_loader
    else:
        logger.info(" 自定义脚本加载已禁用")

    logger.info(" 机器人应用初始化完成！")


async def cleanup_application(application: Application) -> None:
    """清理应用资源"""
    logger.info(" 开始清理应用资源...")

    try:
        # ========================================
        # 第一步：关闭网络连接
        # ========================================
        from utils.http_client import close_global_client

        await close_global_client()
        logger.info("✅ httpx客户端已关闭")

        # ========================================
        # 第二步：停止调度器
        # ========================================
        if "task_scheduler" in application.bot_data:
            application.bot_data["task_scheduler"].stop()
            logger.info("✅ 定时任务调度器已停止")

        if "message_delete_scheduler" in application.bot_data:
            application.bot_data["message_delete_scheduler"].stop()
            logger.info("✅ 消息删除调度器已停止")

        # ========================================
        # 第三步：关闭任务管理器
        # ========================================
        from utils.task_manager import shutdown_task_manager

        await shutdown_task_manager()
        logger.info("✅ 任务管理器已关闭")

        # ========================================
        # 第四步：关闭数据库连接
        # ========================================
        if "cache_manager" in application.bot_data:
            await application.bot_data["cache_manager"].close()
            logger.info("✅ Redis 连接已关闭")

        if "user_cache_manager" in application.bot_data:
            await application.bot_data["user_cache_manager"].close()
            logger.info("✅ MySQL 连接已关闭")

        logger.info(" 应用资源清理完成")

    except Exception as e:
        logger.error(f"❌ 清理资源时出错: {e}")


def main() -> None:
    """主函数"""
    # ========================================
    # 第一步：验证环境配置
    # ========================================
    logger.info(" 验证环境配置...")
    config = get_config()

    # 验证 Bot Token
    bot_token = config.bot_token
    if not bot_token:
        logger.error("❌ 未设置 BOT_TOKEN 环境变量")
        return

    # 验证超级管理员ID
    super_admin_id = config.super_admin_id
    if not super_admin_id:
        logger.error("❌ 未设置 SUPER_ADMIN_ID 环境变量")
        return

    try:
        int(super_admin_id)
        logger.info(f"✅ 超级管理员ID: {super_admin_id}")
    except ValueError:
        logger.error("❌ SUPER_ADMIN_ID 必须是数字")
        return

    # 验证数据库配置
    if not config.db_host or not config.db_user or not config.db_name:
        logger.error("❌ 数据库配置不完整，请检查 DB_HOST, DB_USER, DB_NAME")
        return

    logger.info(f"✅ 数据库配置: {config.db_user}@{config.db_host}:{config.db_port}/{config.db_name}")

    # 验证 Redis 配置
    logger.info(f"✅ Redis 配置: {config.redis_host}:{config.redis_port}")

    # ========================================
    # 第二步：创建并配置应用
    # ========================================
    logger.info(" 创建 Telegram Bot 应用...")
    application = Application.builder().token(bot_token).build()

    # 设置异步初始化和清理回调
    async def init_and_run(app):
        await setup_application(app, config)
        logger.info("✅ 机器人启动完成，开始服务...")

    application.post_init = init_and_run
    application.post_shutdown = cleanup_application

    # ========================================
    # 第三步：启动机器人
    # ========================================
    try:
        if config.webhook_url:
            # Webhook 模式
            url_path = f"/telegram/{config.bot_token}/webhook"
            webhook_url = f"{config.webhook_url.rstrip('/')}{url_path}"

            logger.info(" Webhook 模式启动")
            logger.info(f" Webhook URL: {webhook_url}")
            logger.info(f" 本地监听: {config.webhook_listen}:{config.webhook_port}")

            application.run_webhook(
                listen=config.webhook_listen,
                port=config.webhook_port,
                url_path=url_path,
                secret_token=config.webhook_secret_token,
                webhook_url=webhook_url,
            )
        else:
            # Polling 模式
            logger.info(" Polling 模式启动")
            application.run_polling(allowed_updates=Update.ALL_TYPES)

    except KeyboardInterrupt:
        logger.info("⏹️ 接收到停止信号，正在关闭机器人...")
    except Exception as e:
        logger.error(f"❌ 机器人运行时出错: {e}")
    finally:
        logger.info(" 机器人已停止")


if __name__ == "__main__":
    main()



