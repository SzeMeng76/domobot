"""
项目常量定义

本模块集中定义项目中使用的所有常量，避免魔法数字。
"""

# ============================================================================
# 时间常量（单位：秒）
# ============================================================================

# 基础时间单位
TIME_THIRTY_MINUTES = 1800  # 30 * 60
TIME_ONE_HOUR = 3600
TIME_FOUR_HOURS = 14400  # 4 * 3600
TIME_SIX_HOURS = 21600
TIME_TWELVE_HOURS = 43200
TIME_ONE_DAY = 86400
TIME_THREE_DAYS = 259200
TIME_SEVEN_DAYS = 604800
TIME_EIGHT_DAYS = 691200  # 86400 * 8
TIME_FOURTEEN_DAYS = 1209600
TIME_THIRTY_DAYS = 2592000  # 30 * 24 * 60 * 60

# 缓存时长别名（更语义化）
CACHE_DURATION_1HOUR = TIME_ONE_HOUR
CACHE_DURATION_6HOURS = TIME_SIX_HOURS
CACHE_DURATION_12HOURS = TIME_TWELVE_HOURS
CACHE_DURATION_1DAY = TIME_ONE_DAY
CACHE_DURATION_3DAYS = TIME_THREE_DAYS
CACHE_DURATION_7DAYS = TIME_SEVEN_DAYS
CACHE_DURATION_8DAYS = TIME_EIGHT_DAYS
CACHE_DURATION_14DAYS = TIME_FOURTEEN_DAYS

# ============================================================================
# 消息管理常量
# ============================================================================

# 消息自动删除配置
DEFAULT_MESSAGE_DELETE_DELAY = 180  # 默认消息删除延迟（秒）
INFO_MESSAGE_DELETE_DELAY = 3  # 提示信息删除延迟（秒）
ERROR_MESSAGE_DELETE_DELAY = 5  # 错误消息删除延迟（秒）
WARNING_MESSAGE_DELETE_DELAY = 10  # 警告消息删除延迟（秒）
USER_COMMAND_DELETE_DELAY = 0  # 用户命令删除延迟（立即删除）

# UI 配置
FOLDING_THRESHOLD = 15  # 消息折叠阈值（行数）

# ============================================================================
# 分页常量
# ============================================================================

# App Store 分页
APP_STORE_RESULTS_PER_PAGE = 5
APP_STORE_MAX_PAGES = 10
APP_STORE_SEARCH_LIMIT = 200
DEFAULT_APP_STORE_PLATFORM = "iphone"  # 默认平台

# Google Play 配置
GOOGLE_PLAY_DEFAULT_COUNTRIES = ["US", "NG", "TR"]  # 默认搜索国家
GOOGLE_PLAY_SEARCH_LIMIT = 5  # 搜索结果限制
DEFAULT_LANGUAGE_CODE = "zh-cn"  # 默认语言代码

# ============================================================================
# 网络和性能配置
# ============================================================================

# HTTP 超时配置（秒）
HTTP_TIMEOUT_SHORT = 5  # 快速请求
HTTP_TIMEOUT_DEFAULT = 10  # 默认超时
HTTP_TIMEOUT_MEDIUM = 15  # 中等超时
HTTP_TIMEOUT_LONG = 30  # 长超时

# HTTP 请求配置
DEFAULT_REQUEST_TIMEOUT = 30  # 默认请求超时（秒）
DEFAULT_MAX_RETRIES = 3  # 默认最大重试次数
DEFAULT_MAX_CONCURRENT_REQUESTS = 10  # 默认最大并发请求数

# 速率限制配置
DEFAULT_MAX_REQUESTS_PER_MINUTE = 30  # 默认每分钟最大请求数
RATE_LIMIT_WINDOW = TIME_ONE_HOUR  # 速率限制时间窗口
CIRCUIT_BREAKER_TIMEOUT = 60  # 断路器超时（秒）
CIRCUIT_BREAKER_FAILURE_THRESHOLD = 5  # 失败阈值

# 会话管理配置
SESSION_MAX_AGE = TIME_ONE_HOUR  # 会话最大存活时间（秒）
SESSION_CLEANUP_INTERVAL = 300  # 5分钟清理一次（秒）

# 清理间隔配置
CLEANUP_INTERVAL_FAST = 60  # 1分钟（快速清理）
CLEANUP_INTERVAL_NORMAL = 1800  # 30分钟（正常清理）
CLEANUP_INTERVAL_SLOW = 3600  # 1小时（慢速清理）

# ============================================================================
# 数据库和 Redis 配置
# ============================================================================

# Redis 连接池配置
REDIS_MAX_CONNECTIONS = 50  # Redis 最大连接数
REDIS_HEALTH_CHECK_INTERVAL = 30  # Redis 健康检查间隔（秒）
DEFAULT_REDIS_PORT = 6379  # Redis 默认端口
DEFAULT_REDIS_DB = 0  # Redis 默认数据库编号

# MySQL 连接池配置
MYSQL_MIN_CONNECTIONS = 5  # MySQL 最小连接数
MYSQL_MAX_CONNECTIONS = 100  # MySQL 最大连接数
DEFAULT_MYSQL_PORT = 3306  # MySQL 默认端口

# 数据保留配置
PRICE_HISTORY_RETENTION_DAYS = 90  # 价格历史保留天数

# ============================================================================
# 日志配置
# ============================================================================

# 日志文件配置
LOG_MAX_SIZE = 10 * 1024 * 1024  # 日志文件最大大小（10MB）
LOG_BACKUP_COUNT = 5  # 日志备份数量

# ============================================================================
# Webhook 配置
# ============================================================================

DEFAULT_WEBHOOK_PORT = 8443  # Webhook 默认端口
DEFAULT_WEBHOOK_LISTEN = "0.0.0.0"  # Webhook 监听地址

# ============================================================================
# 服务缓存配置（默认值）
# ============================================================================

# App Store 缓存配置
DEFAULT_APP_STORE_REDIS_CACHE = TIME_SIX_HOURS
DEFAULT_APP_STORE_DB_FRESHNESS = TIME_ONE_DAY

# Apple Services 缓存配置
DEFAULT_APPLE_SERVICES_CACHE_DURATION = TIME_ONE_DAY

# Google Play 缓存配置
DEFAULT_GOOGLE_PLAY_REDIS_CACHE = TIME_SIX_HOURS
DEFAULT_GOOGLE_PLAY_DB_FRESHNESS = TIME_ONE_DAY

# Steam 缓存配置
DEFAULT_STEAM_REDIS_CACHE = TIME_ONE_DAY
DEFAULT_STEAM_DB_FRESHNESS = TIME_ONE_DAY

# Netflix 缓存配置
DEFAULT_NETFLIX_REDIS_CACHE = TIME_SEVEN_DAYS
DEFAULT_NETFLIX_DB_FRESHNESS = TIME_SEVEN_DAYS

# Spotify 缓存配置
DEFAULT_SPOTIFY_REDIS_CACHE = TIME_SEVEN_DAYS
DEFAULT_SPOTIFY_DB_FRESHNESS = TIME_SEVEN_DAYS

# Disney+ 缓存配置
DEFAULT_DISNEY_REDIS_CACHE = TIME_SEVEN_DAYS
DEFAULT_DISNEY_DB_FRESHNESS = TIME_SEVEN_DAYS

# Max 缓存配置
DEFAULT_MAX_REDIS_CACHE = TIME_SEVEN_DAYS
DEFAULT_MAX_DB_FRESHNESS = TIME_SEVEN_DAYS

# Xbox Game Pass 缓存配置
DEFAULT_XBOX_REDIS_CACHE = TIME_SEVEN_DAYS

# 汇率缓存配置
DEFAULT_RATE_CACHE_DURATION = TIME_ONE_HOUR

# 通用缓存配置
DEFAULT_CACHE_DURATION = TIME_ONE_HOUR
