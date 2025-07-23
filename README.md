<div align="right">

Read this in other languages: [简体中文](./README.zh-CN.md)

</div>

<div align="center">

# DomoBot
*A powerful, multi-functional Telegram bot for price lookups and more, containerized with Docker for easy deployment.*

</div>

<p align="center">
  <img src="https://github.com/SzeMeng76/domobot/actions/workflows/docker-publish.yml/badge.svg" alt="GitHub Actions Workflow Status" />
</p>

This is a powerful, multi-functional Telegram bot featuring a comprehensive suite of tools for price lookups, administration, and more. The entire stack is containerized with Docker, MySQL, and Redis for easy, reliable deployment. Forked from the original [domoxiaojun/domoappbot](https://github.com/domoxiaojun/domoappbot) with significant feature enhancements, bug fixes, and a refactored architecture using MySQL and Redis.

### ✨ Features

-   **💱 Currency Conversion:** Real-time exchange rate lookups.
-   **🎮 Steam Prices:** Query prices for Steam games and bundles across different regions.
-   **📱 App Stores:** Search for iOS, macOS, and iPadOS applications by keyword or directly by App ID.
-   **📺 Streaming Prices:** Check subscription costs for services like Netflix, Disney+, and Spotify.
-   **🔐 Admin System:** A comprehensive, interactive admin panel (`/admin`) to manage user/group whitelists and bot administrators via a MySQL backend.
-   **🧹 Auto-Cleanup:** Automatically deletes commands and bot replies to keep group chats tidy.
-   **⚙️ Containerized:** The entire application stack (bot, database, cache) is managed with Docker and Docker Compose for a simple, one-command startup.
-   **🚀 Automated Setup:** The database schema is created automatically by the application on its first run, no manual `init.sql` needed.

### 🛠️ Tech Stack

-   **Backend:** Python
-   **Telegram Framework:** `python-telegram-bot`
-   **Database:** MySQL
-   **Cache:** Redis
-   **Deployment:** Docker & Docker Compose
-   **CI/CD:** GitHub Actions

### 🚀 Getting Started

Follow these steps to get the bot up and running.

#### Prerequisites

-   [Docker](https://docs.docker.com/get-docker/) & [Docker Compose](https://docs.docker.com/compose/install/)
-   A Telegram Bot Token from [@BotFather](https://t.me/BotFather)

#### Installation & Setup

1.  **Clone the repository:**
    ```bash
    git clone [https://github.com/SzeMeng76/domobot.git](https://github.com/SzeMeng76/domobot.git)
    cd domobot
    ```

2.  **Create your configuration file:**
    ```bash
    cp .env.example .env
    ```

3.  **Edit the `.env` file:**
    Open the `.env` file with a text editor and fill in the required values. See the configuration section below for details.

4.  **Run the bot:**
    ```bash
    docker-compose up -d
    ```
    The application will start, connect to the database, and automatically create the required tables on the first launch.

### ⚙️ Configuration (`.env`)

All configurations are managed via the `.env` file.

| Variable                    | Description                                                                 | Default/Example         |
| --------------------------- | --------------------------------------------------------------------------- | ----------------------- |
| `BOT_TOKEN`                 | **(Required)** Your Telegram Bot Token from @BotFather.                     |                         |
| `SUPER_ADMIN_ID`            | **(Required)** The User ID of the main bot owner with all permissions.      |                         |
| `DB_HOST`                   | Hostname for the database. **Must be `mysql`**.                             | `mysql`                 |
| `DB_PASSWORD`               | **(Required)** Password for the database. Must match `docker-compose.yml`.  | `your_mysql_password`   |
| `REDIS_HOST`                | Hostname for the cache. **Must be `redis`**.                                | `redis`                 |
| `DELETE_USER_COMMANDS`      | Set to `true` to enable auto-deletion of user commands.                       | `true`                  |
| `USER_COMMAND_DELETE_DELAY` | Delay in seconds before deleting a user's command. Use `0` for immediate deletion. | `5`                     |
| `LOG_LEVEL`                 | Set the logging level. `DEBUG` for troubleshooting, `INFO` for normal operation. | `INFO`                  |
| `LOAD_CUSTOM_SCRIPTS`       | Set to `true` to enable loading scripts from the `custom_scripts/` directory. | `false`                 |

<details>
<summary><b>📖 Click to expand for Architecture & Technical Details</b></summary>

### 🛠️ Architecture Overview

#### Core Components
1.  **Main Application** (`main.py`): Handles async initialization, dependency injection, and lifecycle management.
2.  **Command Modules** (`commands/`): Each service (Steam, App Store, etc.) has its own module. Commands are registered via a factory pattern with permission control.
3.  **Utility Modules** (`utils/`):
    -   `config_manager.py`: Manages configuration from the `.env` file and `BotConfig` class.
    -   `redis_cache_manager.py`: Handles all caching operations with Redis.
    -   `mysql_user_manager.py`: Manages all database interactions for users and permissions.
    -   `task_scheduler.py`: Schedules recurring background tasks.
    -   `permissions.py`: Decorator-based permission checking system.
4.  **Data Storage:**
    -   **Redis:** Caching of API responses and scheduling of message deletion tasks.
    -   **MySQL:** Persistent storage for user data, permissions, and whitelists.

#### Database Schema
The schema is defined and initialized automatically from the application code. You can see the structure in `database/init.sql`.

#### Permissions System
1.  **Super Admin:** Defined by `SUPER_ADMIN_ID` in the `.env` file. Has all permissions.
2.  **Admin:** Stored in the `admin_permissions` table in MySQL.
3.  **Whitelisted User:** Required for private chats or group chats.

### ⚡ Performance Optimizations
-   **Caching:** Redis is used for high-frequency data to reduce API calls.
-   **Task Scheduling:** Background tasks like message deletion are handled by a Redis-based scheduler.
-   **Connection Pooling:** Both MySQL and Redis connections use pooling to efficiently manage connections.

</details>

### 🤝 Contributing

Contributions, issues, and feature requests are welcome. Feel free to check the [issues page](https://github.com/SzeMeng76/domobot/issues).

### License
This project is licensed under the MIT License.
