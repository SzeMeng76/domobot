"""
配置管理模块
"""

import logging
import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


@dataclass
class BotConfig:
    """机器人配置类"""

    # 新增和风天气配置
    qweather_api_key: str = ""
    cmc_api_key: str = ""
    
    # Webhook 配置
    webhook_url: str = ""
    webhook_listen: str = "0.0.0.0"
    webhook_port: int = 8443
    webhook_secret_token: str = ""
    webhook_key: str = ""
    webhook_cert: str = ""

    # 基础配置
    bot_token: str = ""
    super_admin_id: int = 0
    debug: bool = False

    # 数据库配置
    db_path: str = "data/bot_data.db"
    whitelist_db_path: str = "data/permissions.db"
    admin_db_path: str = "data/permissions.db"

    # 缓存配置
    cache_dir: str = "cache"
    default_cache_duration: int = 3600
    rate_cache_duration: int = 3600

    # 各服务缓存配置
    app_store_cache_duration: int = 1209600  # 14天
    app_store_search_cache_duration: int = 1209600  # 14天
    apple_services_cache_duration: int = 86400  # 1天
    google_play_app_cache_duration: int = 21600  # 6小时
    google_play_search_cache_duration: int = 43200  # 12小时
    steam_cache_duration: int = 259200  # 3天
    netflix_cache_duration: int = 86400  # 24小时
    spotify_cache_duration: int = 86400 * 8  # 8天，配合周日清理
    disney_cache_duration: int = 86400 * 8  # 8天，配合周日清理

    # 定时清理配置
    spotify_weekly_cleanup: bool = True  # 默认启用
    disney_weekly_cleanup: bool = True  # 默认启用

    # API配置
    exchange_rate_api_keys: list[str] = field(default_factory=list)

    # 性能配置
    max_concurrent_requests: int = 10
    request_timeout: int = 30
    max_retries: int = 3

    # 速率限制配置
    rate_limit_enabled: bool = True
    max_requests_per_minute: int = 30

    # 日志配置
    log_level: str = "INFO"
    log_file: str = ""  # 将在ConfigManager中动态生成
    log_max_size: int = 10 * 1024 * 1024  # 10MB
    log_backup_count: int = 5

    # 功能开关
    features: dict[str, bool] = field(
        default_factory=lambda: {
            "steam_enabled": True,
            "netflix_enabled": True,
            "spotify_enabled": True,
            "disney_enabled": True,
            "appstore_enabled": True,
            "googleplay_enabled": True,
            "apple_services_enabled": True,
            "rate_conversion_enabled": True,
        }
    )

    # UI 配置
    folding_threshold: int = 15  # 消息折叠阈值（行数），超过此行数的消息将被折叠显示

    # 消息自动删除配置
    auto_delete_delay: int = 180  # 自动删除延迟时间（秒），默认3分钟
    delete_user_commands: bool = True  # 是否删除用户命令消息
    user_command_delete_delay: int = 0  # 用户命令删除延迟时间（秒），默认立即删除

    # 用户缓存配置
    enable_user_cache: bool = False
    user_cache_group_ids: list[int] = field(default_factory=list)

    # 自定义脚本配置
    alerter_config: dict = field(default_factory=dict)
    load_custom_scripts: bool = False
    custom_scripts_dir: str = "custom_scripts"

    # 国家代码配置
    default_countries: dict[str, list] = field(
        default_factory=lambda: {
            "steam": ["CN", "US", "TR", "RU", "AR"],
            "netflix": ["CN", "US", "TR", "NG", "IN"],
            "spotify": ["US", "NG", "TR", "IN", "MY"],
            "disney": ["US", "TR", "IN"],
            "appstore": ["CN", "US", "TR", "NG", "IN", "MY"],
            "googleplay": ["US", "NG", "TR"],
        }
    )

    # Redis 配置
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str | None = None
    redis_db: int = 0
    # Redis 连接池配置
    redis_max_connections: int = 50  # 最大连接数
    redis_health_check_interval: int = 30  # 健康检查间隔（秒）

    # MySQL 配置
    db_host: str = "localhost"
    db_port: int = 3306
    db_name: str = "bot"
    db_user: str = "bot"
    db_password: str = ""
    # MySQL 连接池配置
    db_min_connections: int = 5  # 最小连接数
    db_max_connections: int = 20  # 最大连接数


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
        # 基础配置
        self.config.bot_token = os.getenv("BOT_TOKEN", "")
        self.config.super_admin_id = int(os.getenv("SUPER_ADMIN_ID", "0"))
        self.config.debug = os.getenv("DEBUG", "False").lower() == "true"

        # 数据库配置
        self.config.db_path = os.getenv("DB_PATH", "data/bot_data.db")
        self.config.whitelist_db_path = os.getenv("WHITELIST_DB_PATH", "data/permissions.db")
        self.config.admin_db_path = os.getenv("ADMIN_DB_PATH", "data/permissions.db")

        # 缓存配置
        self.config.cache_dir = os.getenv("CACHE_DIR", "cache")
        self.config.default_cache_duration = int(os.getenv("DEFAULT_CACHE_DURATION", "3600"))
        self.config.rate_cache_duration = int(os.getenv("RATE_CACHE_DURATION", "3600"))

        # 各服务缓存配置
        self.config.app_store_cache_duration = int(os.getenv("APP_STORE_CACHE_DURATION", "1209600"))
        self.config.app_store_search_cache_duration = int(os.getenv("APP_STORE_SEARCH_CACHE_DURATION", "1209600"))
        self.config.apple_services_cache_duration = int(os.getenv("APPLE_SERVICES_CACHE_DURATION", "86400"))
        self.config.google_play_app_cache_duration = int(os.getenv("GOOGLE_PLAY_APP_CACHE_DURATION", "21600"))
        self.config.google_play_search_cache_duration = int(os.getenv("GOOGLE_PLAY_SEARCH_CACHE_DURATION", "43200"))
        self.config.steam_cache_duration = int(os.getenv("STEAM_CACHE_DURATION", "259200"))
        self.config.netflix_cache_duration = int(os.getenv("NETFLIX_CACHE_DURATION", "86400"))

        # 定时清理配置
        self.config.spotify_weekly_cleanup = os.getenv("SPOTIFY_WEEKLY_CLEANUP", "False").lower() == "true"
        self.config.disney_weekly_cleanup = os.getenv("DISNEY_WEEKLY_CLEANUP", "False").lower() == "true"

        # API配置
        keys_str = os.getenv("EXCHANGE_RATE_API_KEYS") or os.getenv("EXCHANGE_RATE_API_KEY", "")
        self.config.exchange_rate_api_keys = [key.strip() for key in keys_str.split(",") if key.strip()]

        # 性能配置
        self.config.max_concurrent_requests = int(os.getenv("MAX_CONCURRENT_REQUESTS", "10"))
        self.config.request_timeout = int(os.getenv("REQUEST_TIMEOUT", "30"))
        self.config.max_retries = int(os.getenv("MAX_RETRIES", "3"))

        # 速率限制配置
        self.config.rate_limit_enabled = os.getenv("RATE_LIMIT_ENABLED", "True").lower() == "true"
        self.config.max_requests_per_minute = int(os.getenv("MAX_REQUESTS_PER_MINUTE", "30"))

        # 日志配置
        self.config.log_level = os.getenv("LOG_LEVEL", "INFO")
        log_filename = f"bot-{datetime.now().strftime('%Y-%m-%d')}.log"
        self.config.log_file = os.getenv("LOG_FILE", f"logs/{log_filename}")
        self.config.log_max_size = int(os.getenv("LOG_MAX_SIZE", str(10 * 1024 * 1024)))
        self.config.log_backup_count = int(os.getenv("LOG_BACKUP_COUNT", "5"))

        # 功能开关
        for feature in self.config.features:
            env_key = f"{feature.upper()}"
            self.config.features[feature] = os.getenv(env_key, "True").lower() == "true"

        # UI 配置
        self.config.folding_threshold = int(os.getenv("FOLDING_THRESHOLD", "15"))  # 默认15行

        # 消息自动删除配置
        # 支持 DEFAULT_MESSAGE_DELETE_DELAY 作为 AUTO_DELETE_DELAY 的别名
        default_delay = os.getenv("DEFAULT_MESSAGE_DELETE_DELAY", os.getenv("AUTO_DELETE_DELAY", "180"))
        self.config.auto_delete_delay = int(default_delay)
        self.config.delete_user_commands = os.getenv("DELETE_USER_COMMANDS", "True").lower() == "true"
        self.config.user_command_delete_delay = int(os.getenv("USER_COMMAND_DELETE_DELAY", "0"))

        # 用户缓存配置
        self.config.enable_user_cache = os.getenv("ENABLE_USER_CACHE", "False").lower() == "true"
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
        self.config.load_custom_scripts = os.getenv("LOAD_CUSTOM_SCRIPTS", "False").lower() == "true"
        self.config.custom_scripts_dir = os.getenv("CUSTOM_SCRIPTS_DIR", "custom_scripts")

        # Redis 配置
        self.config.redis_host = os.getenv("REDIS_HOST", "localhost")
        self.config.redis_port = int(os.getenv("REDIS_PORT", "6379"))
        self.config.redis_password = os.getenv("REDIS_PASSWORD")
        self.config.redis_db = int(os.getenv("REDIS_DB", "0"))
        # Redis 连接池配置
        self.config.redis_max_connections = int(os.getenv("REDIS_MAX_CONNECTIONS", "50"))
        self.config.redis_health_check_interval = int(os.getenv("REDIS_HEALTH_CHECK_INTERVAL", "30"))
        # --- ✨✨✨ 2. 在这里加上读取天气配置的代码 ✨✨✨ ---
        # 和风天气 API 配置
        self.config.qweather_api_key = os.getenv("QWEATHER_API_KEY", "")
        self.config.cmc_api_key = os.getenv("CMC_API_KEY", "")
        # MySQL 配置
        self.config.db_host = os.getenv("DB_HOST", "localhost")
        self.config.db_port = int(os.getenv("DB_PORT", "3306"))
        self.config.db_name = os.getenv("DB_NAME", "bot")
        self.config.db_user = os.getenv("DB_USER", "bot")
        self.config.db_password = os.getenv("DB_PASSWORD", "")
        # MySQL 连接池配置
        self.config.db_min_connections = int(os.getenv("DB_MIN_CONNECTIONS", "5"))
        self.config.db_max_connections = int(os.getenv("DB_MAX_CONNECTIONS", "20"))

        # Webhook 配置
        self.config.webhook_url = os.getenv("WEBHOOK_URL", "")
        if self.config.webhook_url:
            self.config.webhook_listen = os.getenv("WEBHOOK_LISTEN", "0.0.0.0")
            self.config.webhook_port = int(os.getenv("WEBHOOK_PORT", "8443"))
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
