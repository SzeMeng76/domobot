<div align="right">

阅读其他语言版本: [English](./README.md)

</div>

<div align="center">

# DomoBot
*一个强大、多功能的Telegram机器人，支持价格查询、天气预报、电影电视信息、游戏价格比较等，使用Docker容器化以便于部署。*

## 🚀 立即试用: [@mengpricebot](https://t.me/mengpricebot)

**🎉 全部免费 - 可添加到任意群组！**

**所有用户和群组可用的公开功能:**
- 📺 **流媒体价格:** Netflix、Disney+、Spotify、HBO Max全球各地区订阅价格查询
- 👤 **用户信息:** Telegram注册日期、账号年龄和ID查询
- ⏰ **时间和时区:** 当前时间查询、时区转换和时区列表
- 📰 **新闻聚合:** 来自40+源的实时新闻，包括科技、社交、财经和综合新闻
- 🌐 **WHOIS查询:** 域名、IP地址、ASN和TLD信息查询，集成实时IANA数据和IP地理位置
- 🍳 **烹饪助手:** 菜谱搜索、分类浏览、智能膳食规划和每日菜单推荐
- 🆔 **快速命令:** `/nf`, `/ds`, `/sp`, `/max`, `/when`, `/id`, `/time`, `/timezone`, `/news`, `/newslist`, `/whois`, `/recipe`, `/what_to_eat`
- 👥 **群组友好:** 在任意 Telegram 群组中都可使用，无需白名单申请
- 🔧 **自助服务:** 如果新命令不在输入建议中显示，请使用 `/refresh` 刷新

*高级功能（加密货币、天气、Steam价格、电影电视等）需要白名单权限。*

</div>

<p align="center">
  <img src="https://github.com/SzeMeng76/domobot/actions/workflows/docker-publish.yml/badge.svg" alt="GitHub Actions Workflow Status" />
</p>

### 📝 项目概览

这是一款基于Python的、多功能的Telegram机器人，具备以下特性：

### ✨ 功能特性

-   📺 **公开流媒体价格:** 所有用户可用 - 查询Netflix、Disney+、Spotify、HBO Max等流媒体服务在全球各地区的订阅价格。
-   👤 **公开用户信息查询:** 所有用户可用 - 查询Telegram用户注册日期、账号年龄，以及获取用户/群组ID。
-   ⏰ **公开时间和时区查询:** 所有用户可用 - 查询任意时区的当前时间，时区间时间转换，以及查看支持的时区列表和IANA数据库集成。
-   📰 **公开新闻聚合:** 所有用户可用 - 接入40+新闻源的实时资讯，包括GitHub趋势、知乎热榜、微博热搜、科技新闻（IT之家、Hacker News）、财经新闻（金十数据、华尔街见闻）等，支持智能缓存和分类界面。
-   🌐 **公开WHOIS查询:** 所有用户可用 - 全面的域名、IP地址、ASN和TLD信息查询，集成实时IANA数据库和IP地理位置服务。支持智能查询类型检测，支持域名（.com、.io）、IP地址（IPv4/IPv6）、ASN号码（AS15169）和TLD信息（.com、.me）查询，提供详细的注册机构、WHOIS服务器、创建日期和管理组织数据。**新功能:** IP查询现在包含服务器实际地理位置信息，包括国家、地区、城市、坐标、ISP信息和时区数据，通过IP-API.com集成实现，清晰区分WHOIS注册数据和实际地理位置。
-   🍳 **公开烹饪助手:** 所有用户可用 - 基于HowToCook数据库的全面菜谱搜索和膳食规划系统，包含1000+中文菜谱。功能包括**智能菜谱搜索**（关键词匹配）、**分类浏览**（荤菜、素菜、主食、汤羹、水产、早餐、甜品等）、**智能膳食规划**（支持过敏原和忌口设置）、**每日菜单推荐**（人数选择）、**随机菜谱发现**和**Telegraph集成**（长菜谱显示完整食材和制作步骤）。所有菜谱包含难度评级、烹饪时间、份量和详细营养指导。
-   🎬 **电影和电视剧信息:** 查询电影/电视剧详情及海报、评分、演员、预告片、评价、推荐、观看平台和季集信息。支持**三平台数据整合**（TMDB + JustWatch + Trakt）及**JustWatch流媒体排行榜**，实时排名趋势、平台可用性、Telegraph长内容集成，热门趋势发现、人物搜索和增强的统计数据（观看数、社区数据）。*(需要白名单)*
-   🪙 **加密货币价格:** 查询实时加密货币价格，支持自定义数量和货币转换，并显示 24 小时和 7 天的价格变化率。*(需要白名单)*
-   💳 **BIN查询:** 查询信用卡BIN（银行识别号）信息，包括卡片品牌、类型、发卡银行和国家等详细信息。*(需要白名单)*
-   🌦️ **天气预报:** 提供详细、多格式的天气预报（实时、多日、每小时、分钟级降水和生活指数）。*(需要白名单)*
-   💱 **汇率转换:** 实时汇率查询，支持数学表达式计算（如 `/rate USD 1+2*3`）。*(需要白名单)*
-   🎮 **Steam 价格:** Steam 游戏、捆绑包多区域价格对比和综合搜索功能。*(需要白名单)*
-   📱 **应用商店:** 查询 App Store（详细内购项目定价）和 Google Play（内购价格范围）的应用价格和内购信息。*(需要白名单)*
-   🔐 **管理系统:** 完善的管理员权限系统和用户/群组白名单管理。
-   📊 **用户缓存与统计:** 缓存用户数据并进行命令使用统计。

### 🚀 快速开始

#### 基础命令 (本地开发)
```bash
# 安装依赖
pip install -r requirements.txt

# 运行机器人
python main.py

# 手动清理日志
python cleanup_logs.py
````

#### Docker 部署 (推荐)

```bash
# 使用 Docker Compose 启动所有服务
docker-compose up -d

# 查看机器人容器的日志
docker-compose logs -f appbot

# 停止所有服务
docker-compose down
```

### ⚙️ 配置 (`.env`)

所有配置都通过 `.env` 文件进行管理。你必须将 `.env.example` 复制为 `.env` 并填写所需的变量。

| 变量                        | 描述                                                                        | 默认/示例               |
| --------------------------- | --------------------------------------------------------------------------- | ----------------------- |
| `BOT_TOKEN`                 | **（必需）** 来自 @BotFather 的 Telegram Bot Token。                         |                         |
| `SUPER_ADMIN_ID`            | **（必需）** 拥有所有权限的机器人主要所有者的用户ID。                       |                         |
| `CMC_API_KEY`               | **（可选）** CoinMarketCap的API Key，用于启用 `/crypto` 命令。                  |                         |
| `BIN_API_KEY`               | **（可选）** DY.AX的API Key，用于启用 `/bin` 命令。                         |                         |
| `TMDB_API_KEY`              | **（可选）** TMDB的API Key，用于启用 `/movie` 和 `/tv` 命令。               |                         |
| `TRAKT_API_KEY`             | **（可选）** Trakt的API Key，用于增强电影/电视剧统计和热门趋势数据。        |                         |
| `QWEATHER_API_KEY`          | **（可选）** 和风天气的API Key，用于启用 `/tq` 命令。                       |                         |
| `EXCHANGE_RATE_API_KEYS`    | **（可选）** openexchangerates.org的API Key，用于启用 `/rate` 命令。多个密钥用逗号分隔。 |                         |
| `ENABLE_USER_CACHE`         | **（可选）** 启用用户缓存系统 (`true`/`false`)。                            | `false`                 |
| `USER_CACHE_GROUP_IDS`      | **（可选）** 用逗号分隔的群组ID，用于监控用户缓存。**留空则监听所有**机器人加入的群组。 | (空 - 监听所有群组)    |
| `DB_HOST`                   | 数据库的主机名。**必须是 `mysql`**。                                        | `mysql`                 |
| `DB_PORT`                   | 数据库的内部端口。                                                          | `3306`                  |
| `DB_NAME`                   | 数据库的名称。必须与 `docker-compose.yml` 中的设置匹配。                    | `bot`                   |
| `DB_USER`                   | 数据库的用户名。必须与 `docker-compose.yml` 中的设置匹配。                  | `bot`                   |
| `DB_PASSWORD`               | **（必需）** 数据库的密码。必须与 `docker-compose.yml` 中的设置匹配。       | `your_mysql_password`   |
| `REDIS_HOST`                | 缓存服务的主机名。**必须是 `redis`**。                                      | `redis`                 |
| `REDIS_PORT`                | Redis 的内部端口。                                                          | `6379`                  |
| `DELETE_USER_COMMANDS`      | 设为 `true` 以启用自动删除用户命令的功能。                                  | `true`                  |
| `USER_COMMAND_DELETE_DELAY` | 删除用户命令前的延迟时间（秒）。使用 `0` 表示立即删除。                     | `5`                     |
| `LOG_LEVEL`                 | 设置日志级别 (`DEBUG`, `INFO`, `WARNING`, `ERROR`)。                        | `INFO`                  |
| `LOAD_CUSTOM_SCRIPTS`       | 设为 `true` 以启用从 `custom_scripts/` 目录加载脚本的功能。                 | `false`                 |

配置由 `utils/config_manager.py` 中的 `BotConfig` 类管理，该类支持设置缓存时长、自动删除开关、功能开关和性能参数。

#### 配置文件

配置由 `utils/config_manager.py` 中的 `BotConfig` 类管理，支持：

- 各项服务的缓存时长设置
- 消息自动删除设置
- 功能开关设置
- 性能参数设置

### 🎯 命令示例

#### 公开命令 (所有用户和群组可用)
```bash
# 流媒体服务价格
/nf          # Netflix全球价格
/ds US       # 美国Disney+价格
/sp          # Spotify全球价格
/max         # HBO Max全球价格

# 用户信息查询
/when 123456789           # 通过用户ID查询
/when @username           # 通过用户名查询
/when username            # 通过用户名查询（不带@）
/when                     # 回复用户消息后使用
/id                       # 获取用户/群组ID
/id                       # 回复消息后使用

# 时间和时区查询
/time                     # 显示时间命令帮助
/time 北京                # 北京当前时间
/time 日本                # 日本当前时间
/time 美国                # 美国当前时间
/convert_time 中国 14:30 美国    # 将下午2:30从中国时间转换为美国时间
/timezone                 # 查看支持的时区列表

# 新闻聚合
/news                     # 交互式新闻源选择界面
/newslist                 # 显示所有新闻源和分类
/newslist zhihu           # 获取知乎热榜（默认10条）
/newslist zhihu 5         # 获取知乎热榜前5条
/newslist github 15       # 获取GitHub趋势前15条
/hotnews                  # 快速获取多源热门新闻汇总

# WHOIS查询（增强IP地理位置功能）
/whois google.com         # 域名信息，包含注册商详细信息
/whois 8.8.8.8           # IP地址信息，包含WHOIS注册信息 + 实际地理位置
/whois AS15169            # ASN信息查询
/whois .com               # TLD信息，包含IANA数据
```

#### 白名单专享命令
```bash
# BIN查询
/bin 123456
/bin 12345678

# 加密货币价格
/crypto btc
/crypto eth 0.5 usd

# 汇率转换（支持数学表达式）
/rate USD 100
/rate EUR JPY 50
/rate USD 1+1*2          # 支持数学表达式计算

# 天气预报（支持多种格式）
/tq 北京                # 当前天气和预报
/tq 东京 7                # 7天天气预报
/tq 上海 24h             # 24小时逐时预报
/tq 广州 indices         # 生活指数查询

# 电影和电视剧
/movie 复仇者联盟            # 搜索电影（按钮选择）
/movies 复仇者联盟           # 搜索电影（文本列表）
/movie_hot                 # 三平台热门电影（TMDB + JustWatch + Trakt）
/movie_hot tmdb            # 仅TMDB热门电影
/movie_hot justwatch       # 仅JustWatch流媒体排行榜
/movie_hot justwatch US    # JustWatch美国流媒体排行榜
/movie_detail 299536       # 电影详情（包含JustWatch排名信息）
/movie_videos 299536       # 电影预告片和相关视频
/movie_reviews 299536      # 用户评价（长内容自动生成Telegraph页面）
/movie_rec 299536          # 电影推荐
/movie_watch 299536        # 观看平台信息（包含JustWatch数据）
/movie_trending            # Trakt热门电影
/streaming_movie_ranking   # 综合流媒体电影热度排行榜
/streaming_movie_ranking US # 美国流媒体电影排行榜
/movie_related 299536      # Trakt相关电影推荐
/tv 权力的游戏              # 搜索电视剧（按钮选择）
/tvs 权力的游戏             # 搜索电视剧（文本列表）
/tv_hot                    # 三平台热门电视剧（TMDB + JustWatch + Trakt）
/tv_hot tmdb               # 仅TMDB热门电视剧
/tv_hot justwatch          # 仅JustWatch流媒体排行榜
/tv_hot justwatch CN       # JustWatch中国流媒体排行榜
/tv_detail 1399            # 电视剧详情（包含JustWatch排名信息）
/tv_season 1399 1          # 季详情
/tv_episode 1399 1 1       # 单集详情
/tv_videos 1399            # 电视剧预告片和相关视频
/tv_reviews 1399           # 用户评价（长内容自动生成Telegraph页面）
/tv_rec 1399               # 电视剧推荐
/tv_watch 1399             # 观看平台信息（包含JustWatch数据）
/tv_trending               # Trakt热门电视剧
/streaming_tv_ranking      # 综合流媒体电视剧热度排行榜
/streaming_tv_ranking CN   # 中国流媒体电视剧排行榜
/tv_related 1399           # Trakt相关电视剧推荐

# 热门趋势内容
/trending                  # 今日热门电影、电视剧和人物
/trending_week             # 本周热门内容
/now_playing               # 正在上映的电影
/upcoming                  # 即将上映的电影
/tv_airing                 # 今日播出的电视剧
/tv_on_air                 # 正在播出的电视剧

# 人物搜索
/person 汤姆·汉克斯          # 搜索演员、导演等（按钮选择）
/persons 汤姆·汉克斯         # 搜索演员、导演等（文本列表）
/person_detail 31          # 获取人物详情和履历

# Steam游戏价格和捆绑包
/steam 赛博朋克          # 游戏价格查询
/steam "荒野大镖客" US      # 多区域游戏价格
/steamb "Valve Complete"  # Steam捆绑包价格
/steams cyberpunk         # 综合搜索（游戏+捆绑包）

# 应用商店（含内购价格信息）
/app 微信                  # App Store: 详细内购项目和价格
/gp WeChat                # Google Play: 内购价格范围和CNY转换
# 注: Apple Store显示具体内购项目价格；Google Play显示价格范围（如"每件$0.99-$99.99"）

# Apple服务
/aps iCloud
```

#### 管理员命令
```bash
# 用户和群组管理
/add 123456789            # 添加用户到白名单（也可通过回复使用）
/addgroup                 # 添加当前群组到白名单
/admin                    # 打开管理员面板（交互式）

# 数据点管理
/listpoints [limit]       # 列出已知数据点（默认显示10个，含统计信息）
/addpoint <用户ID> <日期> [备注] # 添加新的数据点（格式：YYYY-MM-DD）
/removepoint <用户ID>     # 删除指定数据点

# 用户缓存管理
/cache                    # 查看用户缓存状态和统计信息
/cache username           # 检查特定用户是否已缓存
/cache @username          # 检查特定用户是否已缓存
/cache 123456789          # 检查特定用户ID是否已缓存
/cleanid                  # 清理所有用户ID缓存
/cleanid 30               # 清理30天前的用户缓存

# 服务缓存管理
/rate_cleancache          # 清理汇率缓存
/crypto_cleancache        # 清理加密货币缓存
/bin_cleancache           # 清理BIN查询缓存
/movie_cleancache         # 清理电影/电视缓存
/steamcc                  # 清理Steam缓存
/nf_cleancache           # 清理Netflix缓存
/ds_cleancache           # 清理Disney+缓存
/sp_cleancache           # 清理Spotify缓存
/max_cleancache          # 清理HBO Max缓存
/gp_cleancache           # 清理Google Play缓存
/app_cleancache          # 清理App Store缓存
/aps_cleancache          # 清理Apple服务缓存

# 天气缓存管理
/tq_cleancache           # 清理所有天气缓存
/tq_cleanlocation        # 清理天气位置缓存
/tq_cleanforecast        # 清理天气预报缓存
/tq_cleanrealtime        # 清理实时天气缓存

# 新闻缓存管理
/news_cleancache         # 清理所有新闻缓存

# WHOIS缓存管理  
/whois_cleancache        # 清理WHOIS查询缓存

# 命令列表管理
/refresh_all             # 管理员：刷新所有用户和群组的命令列表
/refresh                 # 用户：刷新自己的命令列表（修复新功能可见性问题）
```

<details>
<summary><b>📖 点击展开以查看完整的架构、技术细节和最佳实践</b></summary>

### 🛠️ 架构总览

#### 核心组件

1.  **主应用** (`main.py`): 处理异步初始化、依赖注入和生命周期管理。
2.  **命令模块** (`commands/`): 每个服务都有自己的模块，通过工厂模式注册并进行权限控制。
3.  **工具模块** (`utils/`):
    - `config_manager.py`: 配置管理。
    - `cache_manager.py`, `redis_cache_manager.py`: 缓存管理。
    - `mysql_user_manager.py`: 用户和权限的数据库操作。
    - `task_scheduler.py`, `redis_task_scheduler.py`: 任务调度。
    - `permissions.py`: 权限系统。
4.  **数据存储:**
    - **Redis:** 用于缓存和消息删除调度。
    - **MySQL:** 用于用户数据和权限管理。

#### 关键设计模式
- **命令工厂:** 用于统一的命令注册和权限处理。
- **依赖注入:** 核心组件通过 `bot_data` 传递。
- **异步编程:** 完全支持所有I/O操作的 `async/await`。
- **基于装饰器的错误处理:** 统一处理命令的错误。
- **直接异步权限检查:** 复杂的适配器层已被移除，MySQL操作现在是直接异步的。

### 🗄️ 数据库结构
- `users`: 用户基本信息
- `admin_permissions`: 管理员
- `super_admins`: 超级管理员
- `user_whitelist`: 用户白名单
- `group_whitelist`: 群组白名单
- `admin_logs`: 管理员操作日志
- `command_stats`: 命令使用统计

数据库结构定义在 `database/init.sql` 中，并在应用首次运行时自动创建。

### 🔐 权限系统

#### 架构优化

项目已从SQLite兼容性适配器完全迁移到统一的 MySQL + Redis 架构：
- **直接异步权限检查:** `utils/permissions.py` 直接从 `context.bot_data['user_cache_manager']` 获取MySQL管理器。
- **统一数据存储:** 所有权限数据都存储在MySQL中，防止不一致。
- **性能提升:** 移除了同步到异步的复杂性，提高了响应速度。

#### 权限级别

1.  **公开访问:** 所有用户和群组（不论是否在白名单中）都可以访问流媒体服务价格查询 (`/nf`, `/ds`, `/sp`) 和用户信息命令 (`/when`, `/id`)。只需将机器人添加到任意群组即可启用这些功能。
2.  **白名单访问:** 高级功能需要白名单权限，包括加密货币价格、汇率转换、天气预报、Steam价格、BIN查询、电影电视信息和应用商店查询。*联系获取白名单访问或未来服务计划。*
3.  **管理员:** 存储在MySQL的 `admin_permissions` 表中。
4.  **超级管理员:** 通过 `SUPER_ADMIN_ID` 环境变量配置。

### 🧩 扩展机器人

#### 自定义脚本

将Python脚本放置在 `custom_scripts/` 目录中，并设置 `LOAD_CUSTOM_SCRIPTS=true` 以自动加载它们。脚本可以访问：
- `application`: Telegram Application 实例。
- `cache_manager`: Redis 缓存管理器。
- `rate_converter`: 货币转换器。
- `user_cache_manager`: 用户缓存管理器。
- `stats_manager`: 统计管理器。

#### 新命令开发

1.  在 `commands/` 目录中创建一个新模块。
2.  使用 `command_factory.register_command()` 注册新命令。
3.  设置适当的权限级别。
4.  在 `main.py` 中注入任何必要的依赖。

### 📊 日志与监控

#### 日志管理
- **日志文件:** `logs/bot-YYYY-MM-DD.log`
- **日志轮转:** 10MB 大小限制，保留5个备份。
- **日志级别:** 支持 `DEBUG`, `INFO`, `WARNING`, `ERROR`。
- **定期清理:** 通过 `cleanup_logs.py` 或计划任务执行。

#### 监控功能
- 命令使用统计
- 用户活动监控
- 错误日志记录
- 性能指标收集

### ⚡ 性能优化

#### 缓存策略
- **Redis缓存:** 用于高频数据，如价格信息和天气位置查询。
- **统一缓存管理:** 通过 `redis_cache_manager.py` 管理。
- **智能缓存:** 不同服务的缓存时长可配置。
- **数学表达式缓存:** 汇率转换中数学表达式的安全评估和缓存。

#### 任务调度
- **Redis任务调度器:** 支持计划性、周期性任务。
- **消息删除:** 自动清理临时消息。
- **缓存清理:** 定期清除过期缓存。

#### 连接管理
- **连接池:** 用于MySQL和Redis。
- **异步客户端:** 使用 `httpx` 进行异步HTTP请求。
- **优雅关闭:** 优雅地清理资源并关闭连接。

### 💡 开发最佳实践

1.  **错误处理:** 使用 `@with_error_handling` 装饰器。
2.  **日志记录:** 使用适当的日志级别。
3.  **权限检查:** 使用 `@require_permission(...)` 装饰器。
4.  **异步权限:** 通过 `context.bot_data['user_cache_manager']` 获取用户管理器。
5.  **缓存:** 使用Redis缓存以避免重复请求。
6.  **异步代码:** 对所有I/O密集型操作使用 `async/await`。
7.  **配置:** 通过环境变量管理所有设置。
8.  **数据库查询:** 使用参数化查询以防止SQL注入。

### 🔍 故障排查

#### 常见问题
1.  **数据库连接失败:** 检查MySQL的配置和连接。
2.  **Redis连接失败:** 检查Redis服务的状态。
3.  **权限错误:** 确保用户在白名单或管理员列表中。
4.  **命令无响应:** 检查日志文件以查找错误。
5.  **天气命令失败:** 请确保在 `.env` 文件中正确设置了 `QWEATHER_API_KEY`，并且该密钥是有效的。
6.  **BIN查询失败:** 请确保在 `.env` 文件中正确设置了 `BIN_API_KEY`，并且你的API配额充足。

#### 调试技巧
1.  设置 `LOG_LEVEL=DEBUG` 以获取详细日志。
2.  使用 `docker-compose logs -f appbot` 查看实时日志。
3.  检查Redis缓存状态。
4.  验证数据库表结构和数据。

### 📜 架构迁移说明 (v2.0 - 最新)

**移除的组件:**
- `utils/compatibility_adapters.py` - SQLite 兼容性适配器
- `utils/redis_mysql_adapters.py` - 混合适配器
- `utils/unified_database.py` - 统一的SQLite数据库
- 其他SQLite相关文件

**架构优化:**
- 统一了基于 MySQL + Redis 的架构。
- 实现了直接的异步权限检查，移除了复杂的适配器层。
- 提升了性能和代码可维护性。
- 解决了一个白名单群组用户无法使用机器人的问题。

**迁移要点:**
- 所有权限数据现在都存储在MySQL中。
- Redis用于缓存和消息删除调度。
- MySQL和Redis的连接详情必须在 `.env` 文件中配置。

### 🆕 最新更新

#### 命令刷新系统 (最新功能)
- **智能命令列表管理:** 新增 `/refresh_all` 管理员命令，可刷新所有用户和群组的命令列表
- **用户自助服务:** `/refresh` 命令允许任何用户独立解决命令可见性问题
- **Telegram缓存解决方案:** 解决新功能添加时Telegram客户端命令缓存问题
- **全局+个人更新:** 同时更新全局默认命令和个人用户/群组命令列表
- **帮助集成:** 在帮助和开始命令中自动提供命令可见性问题的解决指导
- **新功能推送:** 简化Permission.NONE新功能向所有用户的部署流程
- **减轻管理员负担:** 用户可自行解决命令显示问题，无需联系管理员

#### 增强的WHOIS与IP地理位置功能
- **双信息系统:** WHOIS注册数据 + IP地址服务器实际地理位置
- **IP-API.com集成:** 实时IP地理位置服务，提供准确的服务器位置数据  
- **全面的位置详情:** 国家带国旗、地区、城市、邮政编码、坐标和时区
- **ISP和网络信息:** 来自地理位置服务的实际ISP、组织和AS号码
- **智能字段分类:** 注册信息与实际位置的独立显示部分
- **增强的国家显示:** 使用现有country_data集成显示国旗和中文国家名称
- **智能云服务检测:** 自动检测云服务提供商（微软、亚马逊、谷歌）并提供说明注释
- **错误处理与回退:** 地理位置服务不可用时的优雅降级
- **速率限制合规:** 遵守IP-API.com免费套餐45次/分钟的限制
- **缓存集成:** Redis缓存WHOIS和地理位置数据，支持可配置的TTL
- **用户友好的说明:** 清晰区分"📍 注册位置"和"🌍 实际位置"，便于理解

#### 时间和时区功能 (最新功能)
- **公开时间查询:** 所有用户可用 - 使用国家名称、代码、城市或IANA时区标识符查询任意时区的当前时间
- **时区转换:** 在不同时区间转换时间，智能解析各种时区格式
- **全面的时区支持:** 支持200+城市、190+国家，完整的IANA时区数据库集成
- **国家数据集成:** 利用现有的country_data.py实现一致的国旗显示和本地化国家名称
- **智能输入识别:** 接受中英文国家名称、ISO国家代码、主要城市名称和标准IANA时区标识符
- **交互式帮助系统:** 上下文感知帮助，提供完整的IANA时区文档链接
- **缓存系统:** Redis驱动的时区差异和位置查询缓存，优化性能
- **Markdown V2格式:** 完全符合Telegram格式要求，正确转义特殊字符

#### 数据点管理系统 (最新功能)
- **JSON存储架构:** 替换硬编码数据点，使用灵活的JSON文件存储系统
- **实时统计展示:** 显示总数、已验证和估算数据点的统计信息
- **动态管理功能:** 支持通过Telegram命令添加、删除和查看数据点
- **Docker卷持久化:** 确保数据在容器重启后保持完整
- **向后兼容性:** 与现有估算算法完全兼容，无需迁移

#### 基于角色的访问控制 (最新版本)
- **普遍公开访问:** 所有用户和群组都可以使用流媒体服务价格和用户信息查询功能，无任何限制
- **群组集成:** 将机器人添加到任意 Telegram 群组即可为所有成员启用公开功能
- **增强的帮助系统:** 根据用户权限级别显示不同的帮助内容
- **改进的用户体验:** 明确区分免费功能和高级功能
- **管理员管理工具:** 通过 `/add`、`/addgroup` 和交互式 `/admin` 面板提供全面的用户/群组白名单管理
- **白名单政策更新:** 申请目前暂不开放，未来考虑推出付费服务计划

#### 电影电视功能
- **3平台数据整合:** 结合TMDB、JustWatch和Trakt API提供全面的电影/电视剧信息
- **JustWatch流媒体排行榜:** 实时流媒体平台排名，支持趋势分析和成就统计
- **多源热门内容:** `/movie_hot` 和 `/tv_hot` 命令支持3个数据源（默认混合显示）
- **灵活的数据源选择:** 通过 `/movie_hot tmdb|justwatch|trakt [国家]` 选择特定平台
- **增强的排名显示:** 当前排名、趋势指标（📈📉➡️）、历史成就和排行榜统计
- **平台可用性:** 显示内容可观看的最多3个流媒体平台
- **趋势分析:** 上升/下降/稳定状态和排名变化指标
- **增强搜索:** 交互式按钮电影/电视剧选择
- **丰富详情:** 海报、评分、演员、剧组、预告片和观看平台，包含JustWatch排名信息
- **社区统计:** Trakt集成提供观看数、收藏统计和社区参与数据
- **用户评价:** 多源评价系统（TMDB + Trakt），长内容支持Telegraph集成
- **推荐系统:** 智能电影电视推荐，配合Trakt相关内容推荐
- **趋势发现:** 实时Trakt热门数据，每日刷新确保准确性
- **季集信息:** 详细的电视剧分集信息，智能内容截断
- **人物搜索:** 演员、导演和剧组信息及作品履历
- **数据源透明:** 所有显示中清晰标注数据来源（📊 TMDB、📺 JustWatch、🎯 Trakt）
- **多语言支持:** 中英文内容后备支持，提供更好覆盖
- **实时更新:** JustWatch数据包含时间戳和数据新鲜度指标

#### 用户信息查询功能
- **增强 `/when` 命令** 支持用户名查询的Telegram用户注册日期估算
- **多种查询方式** 支持直接ID输入、用户名查询（@username或username）和回复消息查询
- **智能ID算法** 使用线性插值结合真实数据点进行估算
- **用户分级系统** 根据账号年龄分类用户（新兵蛋子、不如老兵、老兵等）
- **Markdown安全特性** 包含特殊字符转义功能
- **精确年龄计算** 使用年月差值计算逻辑
- **增强 `/id` 命令** 用于获取用户和群组ID
- **用户缓存系统** 提升用户名到ID解析的性能

#### 用户缓存管理系统
- **全新用户缓存基础设施** 采用MySQL存储和Redis性能优化
- **灵活的群组监控** 通过 `ENABLE_USER_CACHE` 和 `USER_CACHE_GROUP_IDS` 设置 - **留空则监听所有群组**
- **管理员缓存调试** 使用 `/cache` 命令查看缓存统计、用户表大小和用户查询
- **灵活的缓存清理** 使用 `/cleanid` 命令支持基于时间和完全清理
- **自动用户数据收集** 从所有监控群组消息中自动收集用户名到ID的映射
- **增强的用户名支持** 在 `/when` 命令中利用缓存用户数据

#### Steam游戏功能
- **多格式游戏搜索:** `/steam` 查询单个游戏的多区域价格
- **捆绑包价格查询:** `/steamb` 查询Steam捆绑包价格和内容信息
- **综合搜索功能:** `/steams` 同时搜索游戏和捆绑包的综合结果
- **区域价格对比:** 多国价格对比，帮助找到更优惠的价格
- **智能缓存系统:** 智能缓存机制提升性能表现
- **管理员缓存管理:** 专用的 `/steamcc` 命令进行缓存控制

#### BIN查询功能
- **新增 `/bin` 命令** 用于信用卡BIN信息查询
- **全面的数据展示** 包括卡片品牌、类型、发卡银行和国家
- **智能缓存系统** 提升性能表现
- **管理员缓存管理** 通过 `/bin_cleancache` 命令
- **中文本地化支持** 卡片品牌和国家名称中文显示
- **环境变量配置** 通过 `BIN_API_KEY` 进行配置

</details>

### 📚 API依赖

- **CoinMarketCap API:** 用于加密货币价格数据
- **DY.AX BIN API:** 用于信用卡BIN信息查询
- **TMDB API:** 用于电影和电视剧信息查询，集成Telegraph支持
- **Trakt API:** 用于增强电影/电视剧统计、热门趋势数据和社区洞察
- **JustWatch API:** 用于流媒体平台排行榜、图表和平台可用性数据
- **和风天气API:** 用于天气预报数据
- **Steam API:** 用于游戏价格信息
- **IP-API.com:** 用于IP地理位置和实际服务器位置数据（免费服务）
- **各种流媒体服务API:** 用于订阅价格查询

### 🤝 贡献

欢迎提交贡献、问题和功能请求。请随时查看 [问题页面](https://github.com/SzeMeng76/domobot/issues)。

### 许可证

该项目根据 MIT 许可证授权。
