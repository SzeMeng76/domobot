"""
App Store 常量定义

包含平台映射、图标、URL、请求头等常量
"""

# App Store 网页基础 URL
APP_STORE_WEB_URL = "https://apps.apple.com/"

# 平台显示信息
PLATFORM_INFO = {
    "iphone": {"icon": "📱", "name": "iOS", "display": "iOS"},
    "ipad": {"icon": "📱", "name": "iPadOS", "display": "iPadOS"},
    "mac": {"icon": "💻", "name": "macOS", "display": "macOS"},
    "tv": {"icon": "📺", "name": "tvOS", "display": "tvOS"},
    "watch": {"icon": "⌚", "name": "watchOS", "display": "watchOS"},
    "vision": {"icon": "🥽", "name": "visionOS", "display": "visionOS"},
}

# 命令行参数标志 -> 平台类型
PLATFORM_FLAGS = {
    "-iphone": "iphone",
    "-ipad": "ipad",
    "-mac": "mac",
    "-tv": "tv",
    "-watch": "watch",
    "-vision": "vision",
}

# 默认搜索国家/地区
DEFAULT_COUNTRIES = ["CN", "NG", "TR", "IN", "MY", "US"]

# 完整的浏览器请求头（模拟真实浏览器，绕过地理位置限制）
MINIMAL_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Referer": "https://www.apple.com/",
    "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-site",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0",
}

# 分页配置
SEARCH_RESULTS_PER_PAGE = 5
MAX_PAGES = 10
WEB_SEARCH_LIMIT = 200  # 网页搜索单次最大结果数

# 缓存子目录
CACHE_SUBDIRECTORY = "app_store"

# CSS 选择器（适配 Apple 新的 Svelte 框架结构）
SELECTORS = {
    # 新选择器（当前 Apple 使用的 Svelte 组件）
    "in_app_items": "li.svelte-1a9curd",
    "in_app_container": "div.text-pair.svelte-1a9curd",
    # 旧选择器（已失效，保留作为参考）
    "in_app_items_legacy": "li.list-with-numbers__item",
    "in_app_name_legacy": "span.truncate-single-line.truncate-single-line--block",
    "in_app_price_legacy": "span.list-with-numbers__item__price.medium-show-tablecell",
}

# JSON-LD 脚本类型
JSON_LD_SCRIPT_TYPE = "application/ld+json"
JSON_LD_SOFTWARE_TYPE = "SoftwareApplication"
