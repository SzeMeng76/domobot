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
    electricity,
    finance,
    flight,
    fuel,
    google_play,
    help_command,
    hotel,
    map as map_command,
    max as max_command,
    memes,
    movie,
    music,
    netflix,
    ytmusic,
    news,
    scan_command,
    spotify,
    steam,
    system_commands,
    time_command,
    weather,
    whois,
    xbox,
)
from commands.rate_command import set_rate_converter
from handlers.user_cache_handler import setup_user_cache_handler  # 新增：导入用户缓存处理器
from utils.command_factory import command_factory
from utils.unified_text_handler import unified_text_handler  # 导入统一文本处理器
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
            from utils.message_manager import send_error

            # 使用自动删除功能发送错误消息
            await send_error(
                context=context,
                chat_id=update.effective_chat.id,
                text="处理请求时发生错误，请稍后重试。\n如果问题持续存在，请联系管理员。",
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

    # 重要：ConversationHandler 必须在 UnifiedTextHandler 之前注册
    # 否则 UnifiedTextHandler 会拦截所有文本消息，导致 ConversationHandler 收不到用户输入
    from commands.admin_commands import admin_panel_handler
    application.add_handler(admin_panel_handler.get_conversation_handler())

    # 注册 AI 反垃圾处理器（必须在 UnifiedTextHandler 之前）
    anti_spam_handler = application.bot_data.get("anti_spam_handler")
    if anti_spam_handler:
        from telegram.ext import MessageHandler, CallbackQueryHandler, filters

        # 注册新成员加入处理器
        application.add_handler(MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS,
            anti_spam_handler.handle_new_member
        ))

        # 注册群组消息处理器（文本和图片）
        application.add_handler(MessageHandler(
            filters.ChatType.GROUPS & (filters.TEXT | filters.PHOTO) & ~filters.COMMAND,
            anti_spam_handler.handle_message
        ))

        # 注册解禁回调处理器
        application.add_handler(CallbackQueryHandler(
            anti_spam_handler.handle_unban_callback,
            pattern="^antispam_unban:"
        ))

        logger.info("✅ AI反垃圾处理器已注册")

    # 注册社交媒体自动解析处理器（必须在 UnifiedTextHandler 之前）
    from handlers.auto_parse_handler import setup_auto_parse_handler
    setup_auto_parse_handler(application)

    # 注册网易云音乐自动识别处理器
    from handlers.auto_music_handler import setup_auto_music_handler
    setup_auto_music_handler(application)

    # 注册AI总结callback handler
    from handlers.ai_summary_callback_handler import get_ai_summary_handler, set_adapter
    from commands.social_parser import _adapter as parser_adapter
    set_adapter(parser_adapter)
    application.add_handler(get_ai_summary_handler())
    logger.info("✅ AI总结callback处理器已注册")

    # 注册 Reddit AI 总结 callback handler（如果已配置）
    if config.reddit_client_id and config.reddit_client_secret and config.enable_ai_summary:
        from handlers.reddit_ai_summary_callback_handler import get_reddit_ai_summary_handler
        application.add_handler(get_reddit_ai_summary_handler())
        logger.info("✅ Reddit AI总结callback处理器已注册")

    # 注册Weather AI日报callback handler
    from handlers.weather_ai_callback_handler import get_handler as get_weather_ai_handler
    application.add_handler(get_weather_ai_handler())
    logger.info("✅ Weather AI日报callback处理器已注册")

    # 注册 Parse Lazy callback handler (TikTok/Douyin延迟加载)
    from telegram.ext import CallbackQueryHandler as CQHandler
    from handlers.inline_parse_handler import handle_lazy_parse_callback
    application.add_handler(CQHandler(handle_lazy_parse_callback, pattern="^parse_lazy_"))
    logger.info("✅ Parse Lazy callback处理器已注册")

    # 注册 Map Nearby callback handler
    from handlers.map_nearby_callback_handler import get_map_nearby_handler
    application.add_handler(get_map_nearby_handler())
    logger.info("✅ Map Nearby callback处理器已注册")

    # 注册 Google Play callback handler
    from telegram.ext import CallbackQueryHandler as CQHandler
    from commands.google_play import googleplay_callback_handler
    application.add_handler(CQHandler(googleplay_callback_handler, pattern="^gp_"))
    logger.info("✅ Google Play callback处理器已注册")

    # 使用命令工厂设置处理器（包括 UnifiedTextHandler）
    command_factory.setup_handlers(application)

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

    # 初始化价格历史管理器（MySQL 持久化层）
    from utils.price_history_manager import PriceHistoryManager

    price_history_manager = PriceHistoryManager(
        host=config.db_host,
        port=config.db_port,
        database=config.db_name,
        user=config.db_user,
        password=config.db_password,
    )
    await price_history_manager.connect()
    logger.info("✅ 价格历史管理器初始化完成")

    # 初始化智能缓存管理器（Redis + MySQL 分层缓存）
    from utils.smart_cache_manager import SmartCacheManager

    smart_cache_manager = SmartCacheManager(
        redis_cache_manager=cache_manager,
        price_history_manager=price_history_manager,
    )
    logger.info("✅ 智能缓存管理器初始化完成")

    # 初始化优化的 HTTP 客户端
    from utils.http_client import get_http_client

    httpx_client = get_http_client()

    # 初始化 Pyrogram Helper（用于获取 DC ID）
    pyrogram_helper = None
    if config.telegram_api_id and config.telegram_api_hash:
        logger.info("🌐 初始化Pyrogram客户端（用于DC ID检测）...")
        try:
            from utils.pyrogram_client import PyrogramHelper

            pyrogram_helper = PyrogramHelper(
                api_id=config.telegram_api_id,
                api_hash=config.telegram_api_hash,
                bot_token=config.bot_token
            )
            await pyrogram_helper.start()
            logger.info("✅ Pyrogram客户端初始化完成")
        except ImportError:
            logger.warning("⚠️ Pyrogram未安装，DC ID检测功能将不可用。安装方法: pip install pyrogram tgcrypto")
        except Exception as e:
            logger.warning(f"⚠️ Pyrogram客户端初始化失败: {e}")
    else:
        logger.info("ℹ️ 未配置TELEGRAM_API_ID和TELEGRAM_API_HASH，DC ID检测功能将不可用")

    # 初始化 AI 反垃圾组件（如果启用）
    anti_spam_manager = None
    anti_spam_detector = None
    anti_spam_handler = None
    if config.anti_spam_enabled and config.openai_api_key:
        logger.info("🛡️ 初始化AI反垃圾功能...")
        from utils.anti_spam_manager import AntiSpamManager
        from utils.anti_spam_detector import AntiSpamDetector
        from handlers.anti_spam_handler import AntiSpamHandler

        anti_spam_manager = AntiSpamManager(user_cache_manager.pool)
        anti_spam_detector = AntiSpamDetector(
            api_key=config.openai_api_key,
            model=config.openai_model,
            base_url=config.openai_base_url if config.openai_base_url else None
        )
        anti_spam_handler = AntiSpamHandler(
            anti_spam_manager,
            anti_spam_detector,
            pyrogram_helper=pyrogram_helper  # 传入 Pyrogram helper
        )
        logger.info("✅ AI反垃圾功能初始化完成")
    elif config.anti_spam_enabled:
        logger.warning("⚠️ AI反垃圾功能已启用但缺少OPENAI_API_KEY，功能将不可用")

    # 将核心组件存储到 bot_data 中
    # 初始化社交媒体解析适配器（使用 WARP 代理）
    from utils.parse_hub_adapter import ParseHubAdapter, set_parse_adapter
    parse_adapter = ParseHubAdapter(
        cache_manager,
        user_cache_manager,
        config,
        pyrogram_helper,
        proxy="socks5://warp:1080"  # 使用 WARP 代理解析小红书等平台
    )

    # 设置全局 ParseHub 适配器实例
    set_parse_adapter(parse_adapter)

    application.bot_data["cache_manager"] = cache_manager
    application.bot_data["rate_converter"] = rate_converter
    application.bot_data["httpx_client"] = httpx_client
    application.bot_data["user_cache_manager"] = user_cache_manager
    application.bot_data["stats_manager"] = stats_manager
    application.bot_data["price_history_manager"] = price_history_manager
    application.bot_data["smart_cache_manager"] = smart_cache_manager
    application.bot_data["anti_spam_handler"] = anti_spam_handler  # 存储反垃圾处理器
    application.bot_data["parse_adapter"] = parse_adapter  # 存储社交解析适配器
    application.bot_data["pyrogram_helper"] = pyrogram_helper  # 存储Pyrogram helper（用于DC ID查询）
    logger.info("✅ 核心组件初始化完成")

    # ========================================
    # 第二步：为命令模块注入依赖
    # ========================================
    logger.info("📦 注入命令模块依赖...")

    # 初始化 App Store 价格查询机器人（使用新的模块化架构）
    try:
        from commands.app_store_modules import init_app_store_bot
        init_app_store_bot(
            application=application,
            cache_manager=cache_manager,
            rate_converter=rate_converter,
            smart_cache_manager=smart_cache_manager,
        )
    except Exception as e:
        logger.error(f"❌ App Store 机器人初始化失败: {e}")

    # 初始化 Netflix 价格查询机器人（使用新的模块化架构）
    try:
        from commands.netflix_modules import init_netflix_bot
        init_netflix_bot(
            application=application,
            cache_manager=cache_manager,
            rate_converter=rate_converter,
            smart_cache_manager=smart_cache_manager,
        )
    except Exception as e:
        logger.error(f"❌ Netflix 机器人初始化失败: {e}")

    # 初始化 Spotify 价格查询机器人（使用新的模块化架构）
    try:
        from commands.spotify_modules import init_spotify_bot
        init_spotify_bot(
            application=application,
            cache_manager=cache_manager,
            rate_converter=rate_converter,
            smart_cache_manager=smart_cache_manager,
        )
    except Exception as e:
        logger.error(f"❌ Spotify 机器人初始化失败: {e}")

    # 初始化 Google Play 查询机器人（使用新的模块化架构）
    try:
        from commands.google_play_modules import init_google_play_bot
        init_google_play_bot(
            application=application,
            cache_manager=cache_manager,
            rate_converter=rate_converter,
            smart_cache_manager=smart_cache_manager,
        )
    except Exception as e:
        logger.error(f"❌ Google Play 机器人初始化失败: {e}")

    # 初始化 Steam 价格查询机器人（使用新的模块化架构）
    try:
        from commands.steam import init_steam_bot
        init_steam_bot(
            application=application,
            cache_manager=cache_manager,
            rate_converter=rate_converter,
            smart_cache_manager=smart_cache_manager,
        )
    except Exception as e:
        logger.error(f"❌ Steam 机器人初始化失败: {e}")

    # 初始化 Disney+ 价格查询机器人（使用新的模块化架构）
    try:
        from commands.disney_modules import init_disney_bot
        init_disney_bot(
            application=application,
            cache_manager=cache_manager,
            rate_converter=rate_converter,
            smart_cache_manager=smart_cache_manager,
        )
    except Exception as e:
        logger.error(f"❌ Disney+ 机器人初始化失败: {e}")

    # 初始化 Xbox Game Pass 价格查询机器人（使用新的模块化架构）
    try:
        from commands.xbox_modules import init_xbox_bot
        init_xbox_bot(
            application=application,
            cache_manager=cache_manager,
            rate_converter=rate_converter,
            smart_cache_manager=smart_cache_manager,
        )
    except Exception as e:
        logger.error(f"❌ Xbox Game Pass 机器人初始化失败: {e}")

    # 初始化 Max 价格查询机器人（使用新的模块化架构）
    try:
        from commands.max_modules import init_max_bot
        init_max_bot(
            application=application,
            cache_manager=cache_manager,
            rate_converter=rate_converter,
            smart_cache_manager=smart_cache_manager,
        )
    except Exception as e:
        logger.error(f"❌ Max 机器人初始化失败: {e}")

    try:
        from commands.apple_services_modules import init_apple_services_bot
        init_apple_services_bot(
            application=application,
            cache_manager=cache_manager,
            rate_converter=rate_converter,
            smart_cache_manager=smart_cache_manager,
        )
    except Exception as e:
        logger.error(f"❌ Apple Services 机器人初始化失败: {e}")

    # 为其他命令模块注入依赖（旧方式，逐步迁移）
    set_rate_converter(rate_converter)
    # steam.set_rate_converter(rate_converter)  # 已改用 init_steam_bot
    # steam.set_cache_manager(cache_manager)    # 已改用 init_steam_bot
    # steam.set_steam_checker(cache_manager, rate_converter)  # 已改用 init_steam_bot
    # netflix.set_dependencies(cache_manager, rate_converter)  # 已改用 init_netflix_bot
    # spotify.set_dependencies(cache_manager, rate_converter)  # 已改用 init_spotify_bot
    # disney_plus.set_dependencies(cache_manager, rate_converter)  # 已改用 init_disney_bot
    # max_command.set_dependencies(cache_manager, rate_converter)  # 已改用 init_max_bot
    # app_store.set_rate_converter(rate_converter)  # 已改用 init_app_store_bot
    # app_store.set_cache_manager(cache_manager)    # 已改用 init_app_store_bot
    # google_play.set_rate_converter(rate_converter)  # 已改用 init_google_play_bot
    # google_play.set_cache_manager(cache_manager)    # 已改用 init_google_play_bot
    # apple_services.set_rate_converter(rate_converter)  # 已改用 init_apple_services_bot
    weather.set_dependencies(cache_manager, httpx_client)
    crypto.set_dependencies(cache_manager, httpx_client)
    bin.set_dependencies(cache_manager, httpx_client)
    scan_command.set_dependencies(cache_manager, httpx_client)
    movie.set_dependencies(cache_manager, httpx_client)
    movie.init_movie_service()
    time_command.set_dependencies(cache_manager)
    news.set_dependencies(cache_manager)
    whois.set_dependencies(cache_manager)
    cooking.set_dependencies(cache_manager, httpx_client)
    memes.set_dependencies(cache_manager, httpx_client)
    finance.set_dependencies(cache_manager, httpx_client)
    map_command.set_dependencies(cache_manager, httpx_client)
    system_commands.set_dependencies(cache_manager)

    # 设置 Map Nearby callback handler 依赖
    from handlers import map_nearby_callback_handler
    from utils.map_services import MapServiceManager
    from utils.telegraph_helper import TelegraphPublisher
    map_service_manager = MapServiceManager(
        google_api_key=config.google_maps_api_key,
        amap_api_key=config.amap_api_key
    )
    telegraph_publisher = TelegraphPublisher()
    map_nearby_callback_handler.set_map_service(map_service_manager)
    map_nearby_callback_handler.set_telegraph_service(telegraph_publisher)

    flight.set_dependencies(cache_manager, httpx_client)
    hotel.set_dependencies(cache_manager, httpx_client)
    fuel.set_dependencies(cache_manager, httpx_client)
    electricity.set_dependencies(cache_manager, httpx_client)

    # 注入社交媒体解析依赖
    from commands import social_parser
    from handlers import auto_parse_handler
    social_parser.set_adapter(parse_adapter)
    auto_parse_handler.set_adapter(parse_adapter)

    # 初始化 Reddit 客户端
    # 支持 OAuth 和 JSON 两种模式，通过环境变量 REDDIT_API_MODE 控制
    # REDDIT_API_MODE=oauth (默认) 或 json
    reddit_client = None
    reddit_api_mode = os.getenv("REDDIT_API_MODE", "oauth").lower()

    if reddit_api_mode == "json":
        # JSON 模式：使用 curl_cffi 伪装 TLS 指纹 + WARP 代理
        try:
            from utils.reddit_json_client import RedditJsonClient
            user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            reddit_client = RedditJsonClient(
                user_agent=user_agent,
                proxy="socks5://warp:1080",  # WARP SOCKS5 代理（Docker 服务名）
                rotate_browser=True  # 启用浏览器轮询
            )
            logger.info(f"✅ Reddit JSON 客户端已初始化 (TLS 指纹伪装 + WARP 代理 + 浏览器轮询)")
        except Exception as e:
            logger.error(f"❌ Reddit JSON 客户端初始化失败: {e}")
            logger.info("⚠️ 尝试回退到 OAuth 模式...")
            reddit_api_mode = "oauth"

    if reddit_api_mode == "oauth" and config.reddit_client_id and config.reddit_client_secret:
        # OAuth 模式：需要 API key，通过 WARP 代理
        try:
            from utils.reddit_client import RedditClient
            user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            reddit_client = RedditClient(
                client_id=config.reddit_client_id,
                client_secret=config.reddit_client_secret,
                user_agent=user_agent,
                proxy="socks5://warp:1080"  # WARP SOCKS5 代理（默认端口 1080）
            )
            logger.info(f"✅ Reddit OAuth 客户端已初始化 (通过 WARP 代理)")
        except Exception as e:
            logger.error(f"❌ Reddit OAuth 客户端初始化失败: {e}")
            reddit_client = None

    if not reddit_client:
        logger.warning("⚠️ Reddit 客户端未配置或初始化失败")

    if reddit_client:
        from commands import reddit_command
        from handlers import auto_parse_handler
        reddit_command.set_reddit_client(reddit_client)
        reddit_command.set_cache_manager(cache_manager)
        reddit_command.set_pyrogram_helper(pyrogram_helper)
        auto_parse_handler.set_reddit_client(reddit_client)  # 设置到 auto parse handler

        # 如果启用了 AI 总结，设置 AI 总结器
        if config.enable_ai_summary and config.openai_api_key:
            from utils.ai_summary import AISummarizer
            ai_summarizer = AISummarizer(
                api_key=config.openai_api_key,
                base_url=config.openai_base_url or None,
                model=config.ai_summary_model or "gpt-5-mini"
            )
            reddit_command.set_ai_summarizer(ai_summarizer)
            logger.info("✅ Reddit AI 总结已启用")

            # 注册 Reddit AI 总结 callback handler
            from handlers import reddit_ai_summary_callback_handler
            reddit_ai_summary_callback_handler.set_reddit_client(reddit_client)
            reddit_ai_summary_callback_handler.set_cache_manager(cache_manager)
            reddit_ai_summary_callback_handler.set_ai_summarizer(ai_summarizer)
            logger.info("✅ Reddit AI 总结 callback handler 已配置")
    else:
        logger.info("⚠️ Reddit 功能未配置（缺少 REDDIT_CLIENT_ID 或 REDDIT_CLIENT_SECRET）")

    # 注入网易云音乐依赖
    music.set_dependencies(cache_manager, httpx_client, pyrogram_helper)
    from handlers import auto_music_handler
    auto_music_handler.set_dependencies(cache_manager, httpx_client, pyrogram_helper)

    # 注入 YouTube Music 依赖
    ytmusic.set_dependencies(cache_manager, httpx_client, pyrogram_helper)

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

    if config.xbox_weekly_cleanup:
        await task_scheduler.add_weekly_cache_cleanup("xbox", "xbox", weekday=6, hour=5, minute=0)
        logger.info(" 已配置 Xbox Game Pass 每周日UTC 5:00 定时清理")
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

    if config.flight_weekly_cleanup:
        await task_scheduler.add_weekly_cache_cleanup("flights", "flights", weekday=6, hour=5, minute=0)
        logger.info(" 已配置 航班服务缓存 每周日UTC 5:00 定时清理")
        cleanup_tasks_added += 1

    if config.hotel_weekly_cleanup:
        await task_scheduler.add_weekly_cache_cleanup("hotels", "hotels", weekday=6, hour=5, minute=0)
        logger.info(" 已配置 酒店服务缓存 每周日UTC 5:00 定时清理")
        cleanup_tasks_added += 1

    if config.reddit_weekly_cleanup:
        await task_scheduler.add_weekly_cache_cleanup("reddit", "reddit", weekday=6, hour=5, minute=0)
        logger.info(" 已配置 Reddit 缓存 每周日UTC 5:00 定时清理")
        cleanup_tasks_added += 1

    # 注册 AI 反垃圾数据库清理任务
    anti_spam_handler = application.bot_data.get("anti_spam_handler")
    if anti_spam_handler and config.anti_spam_enabled:
        # 注册 anti_spam 清理处理器
        async def handle_antispam_cleanup(task_id: str, data: dict):
            """处理 AI 反垃圾数据清理"""
            try:
                anti_spam_manager = anti_spam_handler.manager
                logs_days = data.get("logs_days", 30)
                stats_days = data.get("stats_days", 90)
                inactive_users_days = data.get("inactive_users_days", 60)

                result = await anti_spam_manager.cleanup_old_data(
                    logs_days=logs_days,
                    stats_days=stats_days,
                    inactive_users_days=inactive_users_days
                )
                logger.info(f"🗑️ AI反垃圾数据清理完成: {result}")
            except Exception as e:
                logger.error(f"AI反垃圾数据清理失败: {e}")

        # 注册处理器
        task_scheduler.register_handler("antispam_cleanup", handle_antispam_cleanup)

        # 添加每周清理任务（周日 UTC 6:00）
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        weekday = 6  # 周日
        hour = 6
        minute = 0

        days_ahead = weekday - now.weekday()
        if days_ahead <= 0:
            days_ahead += 7

        next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        next_run = next_run + datetime.timedelta(days=days_ahead)

        await task_scheduler.schedule_task(
            task_id="antispam_weekly_cleanup",
            task_type="antispam_cleanup",
            execute_at=next_run.timestamp(),
            data={"logs_days": 30, "stats_days": 90, "inactive_users_days": 60, "weekday": weekday, "hour": hour, "minute": minute}
        )
        logger.info(f"🗑️ 已配置 AI反垃圾数据 每周日UTC 6:00 定时清理（保留：日志30天，统计90天，用户60天）")
        cleanup_tasks_added += 1

    # 添加临时文件清理任务（每天UTC 4:00清理24小时前的文件）
    if "parse_adapter" in application.bot_data:
        async def handle_temp_files_cleanup(task_id: str, data: dict):
            """处理临时文件清理"""
            try:
                parse_adapter = application.bot_data.get("parse_adapter")
                if parse_adapter:
                    await parse_adapter.cleanup_temp_files(older_than_hours=24)
                    logger.info("✅ 临时文件清理完成")
            except Exception as e:
                logger.error(f"临时文件清理失败: {e}")

        # 注册处理器
        task_scheduler.register_handler("temp_files_cleanup", handle_temp_files_cleanup)

        # 计算下次执行时间（明天UTC 4:00）
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        hour, minute = 4, 0  # UTC 4:00

        # 如果当前时间已过今天的清理时间，则安排到明天
        days_ahead = 1 if now.hour >= hour else 0
        next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        next_run = next_run + datetime.timedelta(days=days_ahead)

        await task_scheduler.schedule_task(
            task_id="temp_files_daily_cleanup",
            task_type="temp_files_cleanup",
            execute_at=next_run.timestamp(),
            data={"repeat_interval": 86400}  # 每24小时重复
        )

        logger.info(f"🗑️ 已配置 临时文件 每天UTC 4:00 定时清理（保留：24小时）")
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
    # 第五步又半：设置 Inline Query 处理器
    # ========================================
    logger.info("🔧 设置 Inline Query 处理器...")
    from handlers.inline_query_handler import setup_inline_query_handler
    await setup_inline_query_handler(application)
    logger.info("✅ Inline Query 处理器设置完成")

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
                    if user_id not in config.super_admin_ids:  # 超级管理员后面单独设置
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
                for super_admin_id in config.super_admin_ids:
                    await application.bot.set_my_commands(
                        full_bot_commands,
                        scope=BotCommandScopeChat(chat_id=super_admin_id)
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
                logger.info(f"🔧 已为 {len(admin_list) + len(config.super_admin_ids)} 位管理员设置完整命令菜单")
                
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

    # ========================================
    # 启动后台任务
    # ========================================
    logger.info("🚀 启动后台任务...")

    # 启动 inline parse 缓存清理任务
    from handlers.inline_parse_handler import start_cache_cleanup_task
    start_cache_cleanup_task()
    logger.info("✅ Inline parse 缓存清理任务已启动")

    # 启动天气订阅定时任务
    from datetime import time
    from zoneinfo import ZoneInfo
    from commands.weather import send_daily_weather_brief

    job_queue = application.job_queue
    if job_queue:
        # 每天早上 8:00 发送天气简报（使用马来西亚时区 UTC+8）
        malaysia_tz = ZoneInfo("Asia/Kuala_Lumpur")
        job_queue.run_daily(send_daily_weather_brief, time=time(8, 0, tzinfo=malaysia_tz))
        logger.info("✅ 天气订阅定时任务已启动（每天 8:00 马来西亚时间）")
    else:
        logger.warning("⚠️ JobQueue 不可用，天气订阅定时任务未启动")

    logger.info("✅ 机器人应用初始化完成！")


async def cleanup_application(application: Application) -> None:
    """清理应用资源"""
    logger.info(" 开始清理应用资源...")

    try:
        # ========================================
        # 第零步：停止后台任务
        # ========================================
        from handlers.inline_parse_handler import stop_cache_cleanup_task
        stop_cache_cleanup_task()
        logger.info("✅ Inline parse 缓存清理任务已停止")

        # ========================================
        # 第一步：关闭 Pyrogram 客户端
        # ========================================
        if "pyrogram_helper" in application.bot_data and application.bot_data["pyrogram_helper"]:
            await application.bot_data["pyrogram_helper"].stop()
            logger.info("✅ Pyrogram客户端已关闭")

        # ========================================
        # 第二步：关闭网络连接
        # ========================================
        from utils.http_client import close_global_client

        await close_global_client()
        logger.info("✅ httpx客户端已关闭")

        # ========================================
        # 第三步：停止调度器
        # ========================================
        if "task_scheduler" in application.bot_data:
            application.bot_data["task_scheduler"].stop()
            logger.info("✅ 定时任务调度器已停止")

        if "message_delete_scheduler" in application.bot_data:
            application.bot_data["message_delete_scheduler"].stop()
            logger.info("✅ 消息删除调度器已停止")

        # ========================================
        # 第四步：关闭任务管理器
        # ========================================
        from utils.task_manager import shutdown_task_manager

        await shutdown_task_manager()
        logger.info("✅ 任务管理器已关闭")

        # ========================================
        # 第五步：关闭数据库连接
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
    super_admin_ids = config.super_admin_ids
    if not super_admin_ids:
        logger.error("❌ 未设置 SUPER_ADMIN_ID 环境变量")
        logger.error("   支持多个ID（逗号分隔）: SUPER_ADMIN_ID=123456,789012")
        return

    logger.info(f"✅ 超级管理员ID: {', '.join(map(str, super_admin_ids))}")

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
    logger.info("📱 创建 Telegram Bot 应用...")

    # 确保 data 目录存在
    import os
    os.makedirs("data", exist_ok=True)

    application = (
        Application.builder()
        .token(bot_token)
        .read_timeout(60)  # 增加读取超时到60秒（发送大图片/视频时需要）
        .write_timeout(60)  # 增加写入超时到60秒
        .media_write_timeout(120)  # 上传媒体文件（视频/图片）的写入超时120秒
        .concurrent_updates(True)  # 允许并发处理update，上传大文件时不阻塞其他命令
        .build()
    )

    # 设置异步初始化和清理回调
    async def init_and_run(app):
        # 启动bot应用
        await setup_application(app, config)
        logger.info("✅ 机器人启动完成，开始服务...")

    application.post_init = init_and_run
    application.post_shutdown = cleanup_application

    # ========================================
    # 第四步：启动机器人
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



