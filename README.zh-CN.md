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

这是一款强大的、多功能的 Telegram 机器人，提供一套完整的价格查询、管理等工具。整个技术栈通过 Docker、MySQL 和 Redis 进行容器化，可实现轻松、可靠的部署。派生自 [domoxiaojun/domobot](https://github.com/domoxiaojun/domobot) 的原始版本，并增加了大量新功能、错误修复和架构重构。

### ✨ 功能特性

-   **💱 汇率转换:** 实时汇率查询。
-   **🎮 Steam 价格:** 查询 Steam 游戏和捆绑包在不同地区的价格。
-   **📱 应用商店:** 通过关键词或 App ID 直接搜索 iOS、macOS 和 iPadOS 应用。
-   **📺 流媒体价格:** 查看 Netflix、Disney+、Spotify 等服务的订阅费用。
-   **🔐 管理系统:** 功能完善的、交互式的管理面板 (`/admin`)，用于管理用户/群组白名单和机器人管理员。
-   **🧹 自动清理:** 自动删除用户命令和机器人回复，以保持群聊整洁。
-   **⚙️ 容器化:** 整个应用（机器人、数据库、缓存）都由 Docker 和 Docker Compose 管理，只需一条命令即可启动。
-   **🚀 自动化设置:** 数据库表结构由程序在首次运行时自动创建，无需手动准备 `init.sql` 文件。

### 🛠️ 技术栈

-   **后端:** Python
-   **Telegram 框架:** `python-telegram-bot`
-   **数据库:** MySQL
-   **缓存:** Redis
-   **部署:** Docker & Docker Compose
-   **持续集成/部署:** GitHub Actions

### 🚀 快速开始

#### 环境要求
-   [Docker](https://docs.docker.com/get-docker/) 和 [Docker Compose](https://docs.docker.com/compose/install/)
-   一个从 [@BotFather](https://t.me/BotFather) 获取的 Telegram Bot Token。

#### 安装与设置
1.  **克隆仓库:**
    ```bash
    git clone [https://github.com/SzeMeng76/domobot.git](https://github.com/SzeMeng76/domobot.git)
    cd domobot
    ```

2.  **创建你的配置文件:**
    ```bash
    cp .env.example .env
    ```

3.  **编辑 `.env` 文件:**
    打开 `.env` 文件并填入你的信息，尤其是 `BOT_TOKEN`, `SUPER_ADMIN_ID`, 和 `DB_PASSWORD`。

4.  **运行机器人:**
    ```bash
    docker-compose up -d
    ```
    机器人将会启动，并在首次运行时自动在 MySQL 数据库中创建所需的表。

### ⚙️ 配置 (`.env`)

所有配置都通过 `.env` 文件管理。

| 变量                        | 描述                                                                    | 默认值/示例             |
| --------------------------- | ----------------------------------------------------------------------- | ----------------------- |
| `BOT_TOKEN`                 | **(必需)** 你的 Telegram Bot Token。                                    |                         |
| `SUPER_ADMIN_ID`            | **(必需)** 主要机器人所有者的用户ID，拥有所有权限。                     |                         |
| `DB_HOST`                   | 数据库的主机名。**必须为 `mysql`**。                                    | `mysql`                 |
| `DB_PASSWORD`               | **(必需)** 数据库密码。必须与 `docker-compose.yml` 中的设置一致。       | `your_mysql_password`   |
| `REDIS_HOST`                | 缓存的主机名。**必须为 `redis`**。                                        | `redis`                 |
| `DELETE_USER_COMMANDS`      | 设置为 `true` 以启用用户命令的自动删除。                                  | `true`                  |
| `USER_COMMAND_DELETE_DELAY` | 删除用户命令前的延迟（秒）。使用 `0` 表示立即删除。                 | `5`                     |
| `LOG_LEVEL`                 | 设置日志级别。`DEBUG` 用于故障排除, `INFO` 用于正常运行。                 | `INFO`                  |
| `LOAD_CUSTOM_SCRIPTS`       | 设置为 `true` 以加载 `custom_scripts/` 目录下的脚本。                     | `false`                 |

<details>
<summary><b>📖 点击展开查看架构与技术细节</b></summary>

### 🛠️ 架构概述

#### 核心组件
1.  **主程序** (`main.py`): 负责异步初始化、依赖注入和应用生命周期管理。
2.  **命令模块** (`commands/`): 每个服务都作为独立的模块，通过工厂模式进行统一注册和权限控制。
3.  **工具模块** (`utils/`):
    -   `config_manager.py`: 管理配置。
    -   `redis_cache_manager.py`: 使用 Redis 处理缓存。
    -   `mysql_user_manager.py`: 管理数据库交互。
    -   `task_scheduler.py`: 调度后台任务。
    -   `permissions.py`: 权限检查系统。
4.  **数据存储:**
    -   **Redis:** 用于缓存和调度消息删除。
    -   **MySQL:** 用于持久化存储用户数据和权限。

#### 数据库结构
该结构由程序自动初始化，你可以在 `database/init.sql` 中查看其定义。

#### 权限系统
1.  **超级管理员:** 由 `.env` 文件中的 `SUPER_ADMIN_ID` 定义。
2.  **管理员:** 存储在 MySQL 的 `admin_permissions` 表中。
3.  **白名单用户:** 私聊或群聊的使用权限。

### ⚡ 性能优化
-   **缓存策略:** 使用 Redis 缓存高频数据以减少 API 调用。
-   **任务调度:** 使用 Redis 处理消息删除等后台任务。
-   **连接池:** MySQL 和 Redis 都使用连接池高效管理连接。

</details>

### 🤝 贡献

欢迎提交贡献、问题和功能请求。请随时查看 [Issues 页面](https://github.com/SzeMeng76/domobot/issues)。

### 许可证
本项目采用 MIT 许可证。
