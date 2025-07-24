<div align="right">

用其他语言阅读: [English](./README.md)

</div>

<div align="center">

# DomoBot
*一款强大的、多功能的 Telegram 机器人，用于价格查询等功能，并使用 Docker 容器化以便轻松部署。*

</div>

<p align="center">
  <img src="https://github.com/SzeMeng76/domobot/actions/workflows/docker-publish.yml/badge.svg" alt="GitHub Actions Workflow Status" />
</p>

### 📝 项目概述

这是一个基于 Python 的多功能 Telegram 价格查询机器人，支持以下功能：
-   汇率实时查询和转换
-   Steam 游戏价格多国对比
-   Netflix、Disney+、Spotify 等流媒体订阅价格查询
-   App Store、Google Play 应用价格查询
-   管理员权限系统和用户白名单管理
-   用户缓存管理和统计功能

### 🚀 开发环境设置

#### 基础命令
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
# 使用 Docker Compose 启动
docker-compose up -d

# 查看日志
docker-compose logs -f appbot

# 停止服务
docker-compose down
```

### ⚙️ 配置管理

#### 环境变量

必需的环境变量：

  - `BOT_TOKEN`: Telegram Bot Token
  - `SUPER_ADMIN_ID`: 超级管理员 ID
  - `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`: MySQL 数据库配置
  - `REDIS_HOST`, `REDIS_PORT`: Redis 配置

可选配置：

  - `LOG_LEVEL`: 日志级别 (默认 INFO)
  - `WEBHOOK_URL`: Webhook 模式 URL
  - `LOAD_CUSTOM_SCRIPTS`: 启用自定义脚本

#### 配置文件

配置通过 `utils/config_manager.py` 的 `BotConfig` 类管理，支持：

  - 各服务缓存时长配置
  - 消息自动删除配置
  - 功能开关配置
  - 性能参数配置

<details>
<summary><b>📖 点击展开查看架构、技术细节与最佳实践\</b></summary>

### 🛠️ 架构概述

#### 核心组件

1.  **主程序** (`main.py`): 负责异步初始化、依赖注入和应用生命周期管理。
2.  **命令模块** (`commands/`): 每个服务都作为独立的模块，通过工厂模式进行统一注册和权限控制。
3.  **工具模块** (`utils/`):
      - `config_manager.py`: 管理配置。
      - `redis_cache_manager.py`: 使用 Redis 处理缓存。
      - `mysql_user_manager.py`: 管理数据库交互。
      - `task_scheduler.py`: 调度后台任务。
      - `permissions.py`: 权限检查系统。
4.  **数据存储:**
      - **Redis:** 用于缓存和调度消息删除。
      - **MySQL:** 用于持久化存储用户数据和权限。

#### 关键设计模式

  - **命令工厂模式**: 统一命令注册和权限管理
  - **依赖注入**: 核心组件通过 `bot_data` 传递
  - **异步编程**: 全面支持异步操作
  - **错误处理**: 使用装饰器统一错误处理
  - **直接异步权限检查**: 移除了复杂的适配器层，直接使用 MySQL 异步操作

### 🗄️ 数据库结构

  - `users`: 用户基本信息
  - `admin_permissions`: 管理员权限
  - `super_admins`: 超级管理员
  - `user_whitelist`: 用户白名单
  - `group_whitelist`: 群组白名单
  - `admin_logs`: 管理员操作日志
  - `command_stats`: 命令使用统计

初始化脚本: `database/init.sql`

### 🔐 权限系统

#### 架构优化

项目已经完全移除了 SQLite 兼容性适配器，统一使用 MySQL + Redis 架构：

  - **直接异步权限检查**: `utils/permissions.py` 直接通过 `context.bot_data['user_cache_manager']` 获取 MySQL 管理器
  - **统一数据存储**: 所有权限数据存储在 MySQL 中，避免了数据不一致问题
  - **性能优化**: 移除了同步转异步的复杂性，提升了响应速度

#### 权限级别

1.  **超级管理员**: 通过环境变量 `SUPER_ADMIN_ID` 配置
2.  **普通管理员**: 存储在 MySQL `admin_permissions` 表中
3.  **白名单用户**: 私聊需要在 `user_whitelist` 表中，群聊需要群组在 `group_whitelist` 表中

### 🧩 扩展功能

#### 自定义脚本

在 `custom_scripts/` 目录放置 Python 脚本，设置 `LOAD_CUSTOM_SCRIPTS=true` 后自动加载。
脚本可以访问：

  - `application`: Telegram 应用实例
  - `cache_manager`: Redis 缓存管理器
  - `rate_converter`: 汇率转换器
  - `user_cache_manager`: 用户缓存管理器
  - `stats_manager`: 统计管理器

#### 命令开发

1.  在 `commands/` 目录创建新模块
2.  使用 `command_factory.register_command()` 注册命令
3.  设置适当的权限级别
4.  在 `main.py` 中注入必要的依赖

### 📊 日志和监控

#### 日志管理

  - **日志文件：** `logs/bot-YYYY-MM-DD.log`
  - **自动轮换：** 10MB 大小限制，保留 5 个备份
  - **日志级别：** 支持 DEBUG、INFO、WARNING、ERROR
  - **定期清理：** 通过 `cleanup_logs.py` 或定时任务

#### 监控功能

  - 命令使用统计
  - 用户活跃度监控
  - 错误日志记录
  - 性能指标收集

### ⚡ 性能优化

#### 缓存策略

  - **Redis 缓存：** 用于高频访问数据和价格信息
  - **统一缓存管理：** 通过 `redis_cache_manager.py` 统一管理
  - **智能缓存：** 不同服务有不同的缓存时长配置

#### 任务调度

  - **Redis 任务调度器：** 支持定时任务
  - **消息删除调度：** 自动清理临时消息
  - **缓存清理任务：** 定期清理过期缓存

#### 连接管理

  - **连接池：** MySQL 和 Redis 连接池
  - **异步客户端：** httpx 异步 HTTP 客户端
  - **资源清理：** 优雅关闭连接

### 💡 开发最佳实践

1.  **错误处理**: 使用 `@with_error_handling` 装饰器
2.  **日志记录**: 使用适当的日志级别
3.  **权限检查**: 使用 `@require_permission(Permission.USER/ADMIN/SUPER_ADMIN)` 装饰器
4.  **异步权限操作**: 通过 `context.bot_data['user_cache_manager']` 获取用户管理器
5.  **缓存使用**: 合理使用 Redis 缓存避免重复请求
6.  **异步编程**: 使用 `async/await` 处理所有 I/O 操作
7.  **配置管理**: 通过环境变量管理配置
8.  **数据库操作**: 使用参数化查询防止 SQL 注入

### 🔍 故障排除

#### 常见问题

1.  **数据库连接失败**: 检查 MySQL 配置和连接
2.  **Redis 连接失败**: 检查 Redis 服务状态
3.  **权限错误**: 确认用户在白名单或管理员列表中
4.  **命令不响应**: 检查日志文件中的错误信息

#### 调试技巧

1.  设置 `LOG_LEVEL=DEBUG` 获取详细日志
2.  使用 `docker-compose logs -f appbot` 查看实时日志
3.  检查 Redis 缓存状态
4.  验证数据库表结构和数据

### 📜 架构迁移记录

#### v2.0 架构统一 (最新)

**已移除的组件:**

  - `utils/compatibility_adapters.py` - SQLite 兼容性适配器
  - `utils/redis_mysql_adapters.py` - 混合适配器
  - `utils/unified_database.py` - SQLite 统一数据库
  - `utils/deletion_task_manager.py` - 未使用的删除任务管理器
  - 其他 SQLite 相关文件

**架构优化:**

  - 统一使用 MySQL + Redis 架构
  - 直接异步权限检查，移除了复杂的适配器层
  - 提升了性能和代码可维护性
  - 解决了群组白名单用户无法使用机器人的问题

**迁移要点:**

  - 所有权限数据现在存储在 MySQL 中
  - Redis 用于缓存和消息删除调度
  - 环境变量中必须配置 MySQL 和 Redis 连接信息

</details>

### 🤝 贡献

欢迎提交贡献、问题和功能请求。请随时查看 [Issues 页面](https://www.google.com/search?q=https://github.com/SzeMeng76/domobot/issues)。

### 许可证

本项目采用 MIT 许可证。

```
```
