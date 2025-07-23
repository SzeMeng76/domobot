<div align="right">

Read this in other languages: [简体中文](./README.zh-CN.md)

</div>

<div align="center">

# DomoAppBot
*A powerful, multi-functional Telegram bot for price lookups and more, containerized with Docker for easy deployment.*

</div>

<p align="center">
  <img src="https://github.com/SzeMeng76/domoappbot/actions/workflows/docker-publish.yml/badge.svg" alt="GitHub Actions Workflow Status" />
</p>

This is a powerful, multi-functional Telegram bot featuring a comprehensive suite of tools for price lookups, administration, and more. The entire stack is containerized with Docker, MySQL, and Redis for easy, reliable deployment.

### ✨ Features

-   **💱 Real-time Currency Conversion:** Fetches and converts between 160+ world currencies.
-   **🎮 Multi-Region Game Prices:** Queries prices for Steam games and bundles.
-   **📺 Streaming Subscriptions:** Looks up prices for Netflix, Disney+, Spotify, and more.
-   **📱 App Stores:** Searches the Apple App Store (iOS/macOS/iPadOS) and Google Play Store by keyword or App ID.
-   **🔐 Robust Admin System:** An interactive admin panel (`/admin`) to manage user/group whitelists and bot administrators via a MySQL backend.
-   **🚀 High Performance:** Utilizes Redis for caching API responses and managing asynchronous tasks like message deletion.
-   **🧹 Auto-Cleanup:** Automatically deletes user commands and bot replies to keep chats tidy.
-   **🧩 Extensible:** Supports loading custom Python scripts to add new functionalities.
-   **📈 Analytics:** Includes a statistics module to log command usage and admin actions.
-   **⚙️ Automated Setup:** The database schema is created automatically by the application on its first run.

### 🚀 Getting Started

#### Prerequisites
-   [Docker](https://docs.docker.com/get-docker/) & [Docker Compose](https://docs.docker.com/compose/install/)
-   A Telegram Bot Token from [@BotFather](https://t.me/BotFather)

#### Installation & Setup
1.  **Clone the repository:**
    ```bash
    git clone [https://github.com/SzeMeng76/domoappbot.git](https://github.com/SzeMeng76/domoappbot.git)
    cd domoappbot
    ```

2.  **Create your configuration file:**
    ```bash
    cp .env.example .env
    ```

3.  **Edit the `.env` file:**
    Open the `.env` file with a text editor. You must fill in `BOT_TOKEN`, `SUPER_ADMIN_ID`, and `DB_PASSWORD`. See the Configuration section for more details.

4.  **Run the bot:**
    ```bash
    docker-compose up -d
    ```
    The application will start, connect to the database, and automatically create the required tables on the first launch.

### ⚙️ Configuration (`.env`)

All configurations are managed via the `.env` file.

| Variable                    | Description                                                                 | Default/Example         |
| --------------------------- | --------------------------------------------------------------------------- | ----------------------- |
| `BOT_TOKEN`                 | **(Required)** Your Telegram Bot Token.                                     |                         |
| `SUPER_ADMIN_ID`            | **(Required)** The User ID of the main bot owner with all permissions.      |                         |
| `DB_HOST`                   | Hostname for the database. **Must be `mysql`**.                             | `mysql`                 |
| `DB_PASSWORD`               | **(Required)** Password for the database. Must match `docker-compose.yml`.  | `your_mysql_password`   |
| `REDIS_HOST`                | Hostname for the cache. **Must be `redis`**.                                | `redis`                 |
| `DELETE_USER_COMMANDS`      | Set to `true` to enable auto-deletion of user commands.                     | `true`                  |
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
-   `users`: Basic user information.
-   `admin_permissions`: Bot administrators.
-   `super_admins`: Super administrators.
-   `user_whitelist`: Whitelisted users.
-   `group_whitelist`: Whitelisted groups.
-   `admin_logs`: Log of administrator actions.
-   `command_stats`: Command usage statistics.

The schema is defined and initialized automatically from the application code, but you can see the structure in `database/init.sql`.

#### Permissions System
The project uses a tiered permission system, now managed directly via asynchronous MySQL queries for better performance and consistency.
1.  **Super Admin:** Defined by `SUPER_ADMIN_ID` in the `.env` file. Has all permissions.
2.  **Admin:** Stored in the `admin_permissions` table in MySQL.
3.  **Whitelisted User:** Required for private chats (stored in `user_whitelist`) or group chats (group ID stored in `group_whitelist`).

### ⚡ Performance Optimizations
-   **Caching:** Redis is used for high-frequency data to reduce API calls. Different services have configurable cache durations.
-   **Task Scheduling:** Background tasks like message deletion and cache cleanup are handled by a Redis-based scheduler.
-   **Connection Pooling:** Both MySQL and Redis connections use pooling to efficiently manage database connections.

</details>

### 🧩 Extending the Bot
#### Custom Scripts
Place custom Python scripts in the `custom_scripts/` directory and set `LOAD_CUSTOM_SCRIPTS=true` in your `.env` file to automatically load them. Scripts have access to core bot components like `application`, `cache_manager`, and more.

#### Developing New Commands
1.  Create a new module in the `commands/` directory.
2.  Use `command_factory.register_command()` to register your command functions.
3.  Set the appropriate permission level (`USER`, `ADMIN`, or `SUPER_ADMIN`).
4.  Inject necessary dependencies (like `rate_converter`) in `main.py`.

### 🤝 Contributing
Contributions, issues, and feature requests are welcome. Feel free to check the [issues page](https://github.com/SzeMeng76/domoappbot/issues).

### License
This project is licensed under the MIT License.
