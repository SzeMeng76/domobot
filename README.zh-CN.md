<div align="right">

阅读其他语言版本: [English](./README.md)

</div>

<div align="center">

# DomoBot
*一个强大、多功能、支持价格查询、天气预报等的Telegram机器人，使用Docker容器化以便于部署。*

</div>

<p align="center">
  <img src="https://github.com/SzeMeng76/domobot/actions/workflows/docker-publish.yml/badge.svg" alt="GitHub Actions Workflow Status" />
</p>

### 📝 项目概览

这是一款基于Python的、多功能的Telegram机器人，具备以下特性：

### ✨ 功能特性

-   🪙 **加密货币价格:** 查询实时加密货币价格，支持自定义数量和货币转换，并显示 24 小时和 7 天的价格变化率。
-   💳 **BIN查询:** 查询信用卡BIN（银行识别号）信息，包括卡片品牌、类型、发卡银行和国家等详细信息。
-   🌦️ **天气预报:** 提供详细、多格式的天气预报（实时、多日、每小时、分钟级降水和生活指数）。
-   💱 **汇率转换:** 实时汇率查询。
-   🎮 **Steam 价格:** Steam 游戏多区域价格对比。
-   📺 **流媒体价格:** 查询 Netflix、Disney+、Spotify 等流媒体服务的订阅价格。
-   📱 **应用商店价格:** 查询 App Store 和 Google Play 的应用价格。
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
| `QWEATHER_API_KEY`          | **（可选）** 和风天气的API Key，用于启用 `/tq` 命令。                       |                         |
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

#### BIN查询命令
```bash
# 基础BIN查询
/bin 123456

# 查询较长的BIN
/bin 12345678

# 管理员缓存管理
/bin_cleancache
```

#### 其他热门命令
```bash
# 加密货币价格
/crypto btc
/crypto eth 0.5 usd

# 汇率转换
/rate USD 100
/rate EUR JPY 50

# 天气预报
/tq 北京
/tq 东京 7

# Steam游戏价格
/steam 赛博朋克
/steam "荒野大镖客" US

# 流媒体服务价格
/nf
/ds US
/sp

# 应用商店
/app 微信
/gp WeChat

# Apple服务
/aps iCloud
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

1.  **超级管理员:** 通过 `SUPER_ADMIN_ID` 环境变量配置。
2.  **管理员:** 存储在MySQL的 `admin_permissions` 表中。
3.  **白名单用户:** 在私聊 (`user_whitelist`) 或群聊 (`group_whitelist`) 中需要。

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

#### BIN查询功能 (最新版本)
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
- **和风天气API:** 用于天气预报数据
- **Steam API:** 用于游戏价格信息
- **各种流媒体服务API:** 用于订阅价格查询

### 🤝 贡献

欢迎提交贡献、问题和功能请求。请随时查看 [问题页面](https://github.com/SzeMeng76/domobot/issues)。

### 许可证

该项目根据 MIT 许可证授权。
