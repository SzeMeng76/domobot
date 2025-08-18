"""
配置管理模块
"""

import logging
import os
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


class BotConfig:
    """机器人配置类"""

    def __init__(self):
        # 新增和风天气配置
        self.qweather_api_key: str = ""
        self.cmc_api_key: str = ""
        self.bin_api_key: str = ""
        
        # 电影信息API配置
        self.tmdb_api_key: str = ""
        self.trakt_api_key: str = ""
    
        # Webhook 配置
        self.webhook_url = ""
        self.webhook_listen = "0.0.0.0"
        self.webhook_port = 8443
        self.webhook_secret_token = ""
        self.webhook_key = ""
        self.webhook_cert = ""

        # 基础配置
        self.bot_token = ""
        self.super_admin_id = 0
        self.debug = False

        # 数据库配置（已统一使用 MySQL）

        # 缓存配置
        self.cache_dir = "cache"
        self.default_cache_duration = 3600
        self.rate_cache_duration = 3600

         # 各服务缓存配置
        self.app_store_cache_duration = 1209600  # 14天
        self.app_store_search_cache_duration = 1209600  # 14天
        self.apple_services_cache_duration = 86400  # 1天
        self.google_play_app_cache_duration = 21600  # 6小时
        self.google_play_search_cache_duration = 43200  # 12小时
        self.steam_cache_duration = 259200  # 3天
        self.netflix_cache_duration = 86400  # 24小时
        self.crypto_cache_duration = 60  # 1分钟
        self.spotify_cache_duration = 86400 * 8  # 8天，配合周日清理
        self.disney_cache_duration = 86400 * 8  # 8天，配合周日清理
        self.max_cache_duration = 86400 * 8  # 8天，配合周日清理
        self.movie_cache_duration = 7200   # 2小时，电影和电视剧缓存
        self.news_cache_duration = 86400  # 1天，新闻缓存
        self.whois_cache_duration = 3600 * 6  # 6小时，WHOIS查询缓存
        self.time_cache_duration = 86400  # 24小时，时区缓存
        self.cooking_cache_duration = 86400 * 7  # 7天，烹饪菜谱缓存
        self.memes_cache_duration = 600  # 10分钟，表情包缓存

        # 定时清理配置
        self.spotify_weekly_cleanup = True  # 默认启用
        self.disney_weekly_cleanup = True  # 默认启用
        self.max_weekly_cleanup = True  # 默认启用
        self.movie_weekly_cleanup = True  # 默认启用，电影和电视剧缓存
        self.news_weekly_cleanup = True  # 默认启用，新闻缓存
        self.whois_weekly_cleanup = True  # 默认启用，WHOIS缓存
        self.time_weekly_cleanup = True  # 默认启用，时区缓存
        self.cooking_weekly_cleanup = True  # 默认启用，烹饪菜谱缓存
        self.memes_weekly_cleanup = True  # 默认启用，表情包缓存

        # API配置
        self.exchange_rate_api_keys = []

        # 性能配置
        self.max_concurrent_requests = 10
        self.request_timeout = 30
        self.max_retries = 3

        # 速率限制配置
        self.rate_limit_enabled = True
        self.max_requests_per_minute = 30

        # 日志配置
        self.log_level = "INFO"
        self.log_file = ""  # 将在ConfigManager中动态生成
        self.log_max_size = 10 * 1024 * 1024  # 10MB
        self.log_backup_count = 5

        # 功能开关
        self.features = {
            "steam_enabled": True,
            "netflix_enabled": True,
            "spotify_enabled": True,
            "disney_enabled": True,
            "appstore_enabled": True,
            "googleplay_enabled": True,
            "apple_services_enabled": True,
            "rate_conversion_enabled": True,
        }

        # UI 配置
        self.folding_threshold = 15  # 消息折叠阈值（行数），超过此行数的消息将被折叠显示

        # 消息自动删除配置
        self.auto_delete_delay = 180  # 自动删除延迟时间（秒），默认3分钟
        self.delete_user_commands = True  # 是否删除用户命令消息
        self.user_command_delete_delay = 0  # 用户命令删除延迟时间（秒），默认立即删除

        # 用户缓存配置
        self.enable_user_cache = False
        self.user_cache_group_ids = []

        # 自定义脚本配置
        self.alerter_config = {}
        self.load_custom_scripts = False
        self.custom_scripts_dir = "custom_scripts"

        # 国家代码配置
        self.default_countries = {
            "steam": ["CN", "US", "TR", "RU", "AR"],
            "netflix": ["CN", "US", "TR", "NG", "IN"],
            "spotify": ["US", "NG", "TR", "IN", "MY"],
            "disney": ["US", "TR", "IN"],
            "appstore": ["CN", "US", "TR", "NG", "IN", "MY"],
            "googleplay": ["US", "NG", "TR"],
        }


        # Redis 配置
        self.redis_host = "localhost"
        self.redis_port = 6379
        self.redis_password = None
        self.redis_db = 0
        # Redis 连接池配置
        self.redis_max_connections = 50  # 最大连接数
        self.redis_health_check_interval = 30  # 健康检查间隔（秒）

        # MySQL 配置
        self.db_host = "localhost"
        self.db_port = 3306
        self.db_name = "bot"
        self.db_user = "bot"
        self.db_password = ""
        # MySQL 连接池配置
        self.db_min_connections = 5  # 最小连接数
        self.db_max_connections = 20  # 最大连接数


class ConfigManager:
    """配置管理器"""

    def __init__(self, config_file: str | None = None):
        self.config_file = config_file or ".env"
        self.config = BotConfig()
        self._load_config()

    def _load_config(self):
        """加载配置"""
        try:
            # 尝试加载.env文件
            if os.path.exists(self.config_file):
                self._load_from_env_file()

            # 加载环境变量
            self._load_from_environment()
            # 验证配置
            self._validate_config()

            logger.info("Configuration loaded successfully")

        except Exception as e:
            logger.error(f"Error loading configuration: {e}")
            raise

    def _load_from_env_file(self):
        """从.env文件加载配置"""
        try:
            from dotenv import load_dotenv

            load_dotenv(self.config_file)
            logger.info(f"Loaded configuration from {self.config_file}")
        except ImportError:
            logger.warning("python-dotenv not installed, skipping .env file loading")

    def _load_from_environment(self):
        """从环境变量加载配置"""
        
        # 辅助方法：读取布尔值环境变量
        def get_bool_env(key: str, default: str = "False") -> bool:
            return os.getenv(key, default).lower() == "true"
            
        # 辅助方法：读取整数环境变量
        def get_int_env(key: str, default: str) -> int:
            return int(os.getenv(key, default))
                
        # 基础配置
        self.config.bot_token = os.getenv("BOT_TOKEN", "")
        self.config.super_admin_id = get_int_env("SUPER_ADMIN_ID", "0")
        self.config.debug = get_bool_env("DEBUG")

        # 缓存配置
        self.config.cache_dir = os.getenv("CACHE_DIR", "cache")
        self.config.default_cache_duration = get_int_env("DEFAULT_CACHE_DURATION", "3600")
        self.config.rate_cache_duration = get_int_env("RATE_CACHE_DURATION", "3600")

        # 各服务缓存配置
        self.config.app_store_cache_duration = get_int_env("APP_STORE_CACHE_DURATION", "1209600")
        self.config.app_store_search_cache_duration = get_int_env("APP_STORE_SEARCH_CACHE_DURATION", "1209600")
        self.config.apple_services_cache_duration = get_int_env("APPLE_SERVICES_CACHE_DURATION", "86400")
        self.config.google_play_app_cache_duration = get_int_env("GOOGLE_PLAY_APP_CACHE_DURATION", "21600")
        self.config.google_play_search_cache_duration = get_int_env("GOOGLE_PLAY_SEARCH_CACHE_DURATION", "43200")
        self.config.steam_cache_duration = get_int_env("STEAM_CACHE_DURATION", "259200")
        self.config.netflix_cache_duration = get_int_env("NETFLIX_CACHE_DURATION", "86400")
        self.config.crypto_cache_duration = get_int_env("CRYPTO_CACHE_DURATION", "60")
        self.config.movie_cache_duration = get_int_env("MOVIE_CACHE_DURATION", "7200")
        self.config.news_cache_duration = get_int_env("NEWS_CACHE_DURATION", "86400")
        self.config.whois_cache_duration = get_int_env("WHOIS_CACHE_DURATION", str(3600 * 6))
        self.config.time_cache_duration = get_int_env("TIME_CACHE_DURATION", "86400")
        self.config.memes_cache_duration = get_int_env("MEMES_CACHE_DURATION", "600")

        # 定时清理配置
        self.config.spotify_weekly_cleanup = get_bool_env("SPOTIFY_WEEKLY_CLEANUP")
        self.config.disney_weekly_cleanup = get_bool_env("DISNEY_WEEKLY_CLEANUP")
        self.config.movie_weekly_cleanup = get_bool_env("MOVIE_WEEKLY_CLEANUP", "True")
        self.config.news_weekly_cleanup = get_bool_env("NEWS_WEEKLY_CLEANUP", "True")
        self.config.whois_weekly_cleanup = get_bool_env("WHOIS_WEEKLY_CLEANUP", "True")
        self.config.time_weekly_cleanup = get_bool_env("TIME_WEEKLY_CLEANUP", "True")

        # API配置
        keys_str = os.getenv("EXCHANGE_RATE_API_KEYS") or os.getenv("EXCHANGE_RATE_API_KEY", "")
        self.config.exchange_rate_api_keys = [key.strip() for key in keys_str.split(",") if key.strip()]

        # 性能配置
        self.config.max_concurrent_requests = get_int_env("MAX_CONCURRENT_REQUESTS", "10")
        self.config.request_timeout = get_int_env("REQUEST_TIMEOUT", "30")
        self.config.max_retries = get_int_env("MAX_RETRIES", "3")

        # 速率限制配置
        self.config.rate_limit_enabled = get_bool_env("RATE_LIMIT_ENABLED", "True")
        self.config.max_requests_per_minute = get_int_env("MAX_REQUESTS_PER_MINUTE", "30")

        # 日志配置
        self.config.log_level = os.getenv("LOG_LEVEL", "INFO")
        log_filename = f"bot-{datetime.now().strftime('%Y-%m-%d')}.log"
        self.config.log_file = os.getenv("LOG_FILE", f"logs/{log_filename}")
        self.config.log_max_size = get_int_env("LOG_MAX_SIZE", str(10 * 1024 * 1024))
        self.config.log_backup_count = get_int_env("LOG_BACKUP_COUNT", "5")

        # 功能开关
        for feature in self.config.features:
            env_key = f"{feature.upper()}"
            self.config.features[feature] = get_bool_env(env_key, "True")

        # UI 配置
        self.config.folding_threshold = get_int_env("FOLDING_THRESHOLD", "15")  # 默认15行

        # 消息自动删除配置
        # 支持 DEFAULT_MESSAGE_DELETE_DELAY 作为 AUTO_DELETE_DELAY 的别名
        default_delay = os.getenv("DEFAULT_MESSAGE_DELETE_DELAY", os.getenv("AUTO_DELETE_DELAY", "180"))
        self.config.auto_delete_delay = int(default_delay)
        self.config.delete_user_commands = get_bool_env("DELETE_USER_COMMANDS", "True")
        self.config.user_command_delete_delay = get_int_env("USER_COMMAND_DELETE_DELAY", "0")

        # 用户缓存配置
        self.config.enable_user_cache = get_bool_env("ENABLE_USER_CACHE")
        cache_group_ids_str = os.getenv("USER_CACHE_GROUP_IDS", "")
        if cache_group_ids_str:
            self.config.user_cache_group_ids = [
                int(gid.strip()) for gid in cache_group_ids_str.split(",") if gid.strip()
            ]

        # 自定义脚本配置
        alerter_config_str = os.getenv("ALERTER_CONFIG", "{}")
        try:
            import json

            self.config.alerter_config = json.loads(alerter_config_str)
        except json.JSONDecodeError:
            logger.error("Failed to parse ALERTER_CONFIG JSON string. Using empty config.")
            self.config.alerter_config = {}
        self.config.load_custom_scripts = get_bool_env("LOAD_CUSTOM_SCRIPTS")
        self.config.custom_scripts_dir = os.getenv("CUSTOM_SCRIPTS_DIR", "custom_scripts")

        # Redis 配置
        self.config.redis_host = os.getenv("REDIS_HOST", "localhost")
        self.config.redis_port = get_int_env("REDIS_PORT", "6379")
        self.config.redis_password = os.getenv("REDIS_PASSWORD")
        self.config.redis_db = get_int_env("REDIS_DB", "0")
        # Redis 连接池配置
        self.config.redis_max_connections = get_int_env("REDIS_MAX_CONNECTIONS", "50")
        self.config.redis_health_check_interval = get_int_env("REDIS_HEALTH_CHECK_INTERVAL", "30")

        # 和风天气 API 配置
        self.config.qweather_api_key = os.getenv("QWEATHER_API_KEY", "")
        self.config.cmc_api_key = os.getenv("CMC_API_KEY", "")
        self.config.bin_api_key = os.getenv("BIN_API_KEY", "")
        
        # 电影信息 API 配置
        self.config.tmdb_api_key = os.getenv("TMDB_API_KEY", "")
        self.config.trakt_api_key = os.getenv("TRAKT_API_KEY", "")

        # MySQL 配置
        self.config.db_host = os.getenv("DB_HOST", "localhost")
        self.config.db_port = get_int_env("DB_PORT", "3306")
        self.config.db_name = os.getenv("DB_NAME", "bot")
        self.config.db_user = os.getenv("DB_USER", "bot")
        self.config.db_password = os.getenv("DB_PASSWORD", "")
        # MySQL 连接池配置
        self.config.db_min_connections = get_int_env("DB_MIN_CONNECTIONS", "5")
        self.config.db_max_connections = get_int_env("DB_MAX_CONNECTIONS", "20")

        # Webhook 配置
        self.config.webhook_url = os.getenv("WEBHOOK_URL", "")
        if self.config.webhook_url:
            self.config.webhook_listen = os.getenv("WEBHOOK_LISTEN", "0.0.0.0")
            self.config.webhook_port = get_int_env("WEBHOOK_PORT", "8443")
            self.config.webhook_secret_token = os.getenv("WEBHOOK_SECRET_TOKEN") or secrets.token_hex(32)

    def _validate_config(self):
        """验证配置"""
        if not self.config.bot_token:
            raise ValueError("BOT_TOKEN is required")

        if self.config.super_admin_id <= 0:
            raise ValueError("SUPER_ADMIN_ID must be a valid positive integer")

        # 创建必要的目录
        Path(self.config.cache_dir).mkdir(parents=True, exist_ok=True)
        Path("logs").mkdir(exist_ok=True)

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值"""
        return getattr(self.config, key, default)

    def is_feature_enabled(self, feature: str) -> bool:
        """检查功能是否启用"""
        return self.config.features.get(feature, False)

    def get_default_countries(self, service: str) -> list:
        """获取服务的默认国家列表"""
        return self.config.default_countries.get(service, ["US"])

    def update_config(self, **kwargs):
        """更新配置"""
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
                logger.info(f"Configuration updated: {key} = {value}")

    def reload(self):
        """重新加载配置"""
        self._load_config()


# 全局配置管理器实例
config_manager = ConfigManager()


def get_config() -> BotConfig:
    """获取全局配置"""
    return config_manager.config


def is_feature_enabled(feature: str) -> bool:
    """检查功能是否启用"""
    return config_manager.is_feature_enabled(feature)
