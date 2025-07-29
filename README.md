<div align="right">

Read this in other languages: [简体中文](./README.zh-CN.md)

</div>

<div align="center">

# DomoBot
*A powerful, multi-functional Telegram bot for price lookups, weather forecasts, and more, containerized with Docker for easy deployment.*

## 🚀 Try it now: [@mengpricebot](https://t.me/mengpricebot)

**🎉 Free for Everyone - Add to Any Group!**

**Public features available to all users and groups:**
- 📺 **Streaming Prices:** Netflix, Disney+, Spotify pricing across global regions
- 👤 **User Information:** Telegram registration dates, account age, and ID lookup
- 🆔 **Quick Commands:** `/nf`, `/ds`, `/sp`, `/when`, `/id`
- 👥 **Group Friendly:** Works in any Telegram group without requiring whitelist approval

*Advanced features (crypto, weather, Steam prices, etc.) require whitelist access.*

</div>

<p align="center">
  <img src="https://github.com/SzeMeng76/domobot/actions/workflows/docker-publish.yml/badge.svg" alt="GitHub Actions Workflow Status" />
</p>

### 📝 Project Overview

This is a Python-based, multi-functional Telegram bot with the following features:

### ✨ Features

-   📺 **Public Streaming Prices:** Available to all users - query subscription prices for Netflix, Disney+, and Spotify across global regions.
-   👤 **Public User Information:** Available to all users - check Telegram user registration dates, account age, and get user/group IDs.
-   🪙 **Crypto Prices:** Look up real-time cryptocurrency prices with support for custom amounts and currency conversion, including 24h and 7d percentage changes. *(Whitelist required)*
-   💳 **BIN Lookup:** Query credit card BIN (Bank Identification Number) information including card brand, type, issuing bank, and country details. *(Whitelist required)*
-   🌦️ **Weather Forecasts:** Detailed, multi-format weather forecasts (real-time, daily, hourly, minutely precipitation, and lifestyle indices). *(Whitelist required)*
-   💱 **Currency Conversion:** Real-time exchange rate lookups. *(Whitelist required)*
-   🎮 **Steam Prices:** Multi-region price comparison for Steam games. *(Whitelist required)*
-   📱 **App Stores:** Application price lookup for the App Store and Google Play. *(Whitelist required)*
-   🔐 **Admin System:** A comprehensive admin permission system with user/group whitelisting.
-   📊 **User Caching & Stats:** Caching user data and command usage statistics.

### 🚀 Getting Started

#### Basic Commands (Local Development)
```bash
# Install dependencies
pip install -r requirements.txt

# Run the bot
python main.py

# Manually clean up logs
python cleanup_logs.py
````

#### Docker Deployment (Recommended)

```bash
# Start all services using Docker Compose
docker-compose up -d

# View the logs for the bot container
docker-compose logs -f appbot

# Stop all services
docker-compose down
```

### ⚙️ Configuration (`.env`)

All configurations are managed via the `.env` file. You must copy `.env.example` to `.env` and fill in the required variables.

| Variable                    | Description                                                                 | Default/Example         |
| --------------------------- | --------------------------------------------------------------------------- | ----------------------- |
| `BOT_TOKEN`                 | **(Required)** Your Telegram Bot Token from @BotFather.                     |                         |
| `SUPER_ADMIN_ID`            | **(Required)** The User ID of the main bot owner with all permissions.      |                         |
| `CMC_API_KEY`               | **(Optional)** API Key from CoinMarketCap for the `/crypto` command.        |                         |
| `BIN_API_KEY`               | **(Optional)** API Key from DY.AX for the `/bin` command.                   |                         |
| `QWEATHER_API_KEY`          | **(Optional)** API Key from HeFeng Weather for the `/tq` command.           |                         |
| `EXCHANGE_RATE_API_KEYS`    | **(Optional)** API Keys from openexchangerates.org for the `/rate` command. Multiple keys separated by commas. |                         |
| `ENABLE_USER_CACHE`         | **(Optional)** Enable user caching system (`true`/`false`).                 | `false`                 |
| `USER_CACHE_GROUP_IDS`      | **(Optional)** Comma-separated group IDs to monitor for user caching. **Leave empty to monitor all groups** where the bot is added. | (empty - monitors all groups) |
| `DB_HOST`                   | Hostname for the database. **Must be `mysql`**.                             | `mysql`                 |
| `DB_PORT`                   | The internal port for the database.                                         | `3306`                  |
| `DB_NAME`                   | The name of the database. Must match `docker-compose.yml`.                  | `bot`                   |
| `DB_USER`                   | The username for the database. Must match `docker-compose.yml`.             | `bot`                   |
| `DB_PASSWORD`               | **(Required)** The password for the database. Must match `docker-compose.yml`.| `your_mysql_password`   |
| `REDIS_HOST`                | Hostname for the cache. **Must be `redis`**.                                | `redis`                 |
| `REDIS_PORT`                | The internal port for Redis.                                                | `6379`                  |
| `DELETE_USER_COMMANDS`      | Set to `true` to enable auto-deletion of user commands.                     | `true`                  |
| `USER_COMMAND_DELETE_DELAY` | Delay in seconds before deleting a user's command. Use `0` for immediate deletion. | `5`                     |
| `LOG_LEVEL`                 | Set the logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`).                | `INFO`                  |
| `LOAD_CUSTOM_SCRIPTS`       | Set to `true` to enable loading scripts from the `custom_scripts/` directory. | `false`                 |

The configuration is managed by the `BotConfig` class in `utils/config_manager.py`, which supports setting cache durations, auto-deletion toggles, feature flags, and performance parameters.

#### Configuration File

Configuration is managed by the `BotConfig` class in `utils/config_manager.py`, which supports:

- Cache duration settings for various services
- Message auto-deletion settings
- Feature flag settings
- Performance parameter settings

### 🎯 Command Examples

#### Public Commands (Available to All Users & Groups)
```bash
# Streaming service prices
/nf          # Netflix global pricing
/ds US       # Disney+ pricing in US
/sp          # Spotify global pricing

# User information lookup
/when 123456789           # Query by user ID
/when @username           # Query by username
/when username            # Query by username (without @)
/when                     # Reply to a user's message
/id                       # Get user/group IDs
/id                       # Reply to a message
```

#### Whitelist-Only Commands
```bash
# BIN lookup
/bin 123456
/bin 12345678

# Cryptocurrency prices
/crypto btc
/crypto eth 0.5 usd

# Currency conversion
/rate USD 100
/rate EUR JPY 50

# Weather forecasts
/tq Beijing
/tq Tokyo 7

# Steam game prices
/steam Cyberpunk
/steam "Red Dead" US

# App stores
/app WeChat
/gp WhatsApp

# Apple services
/aps iCloud
```

#### Admin Commands
```bash
# User cache management
/cache                    # View user cache status and statistics (shows user count, table size, etc.)
/cache username           # Check if specific user is cached
/cache @username          # Check if specific user is cached
/cache 123456789          # Check if specific user ID is cached
/cleanid                  # Clean all user ID cache
/cleanid 30               # Clean user cache older than 30 days

# Other cache management
/bin_cleancache
/crypto_cleancache
/rate_cleancache
# ... other cache management commands
```

<details>
<summary><b>📖 Click to expand for Full Architecture, Technical Details, and Best Practices</b></summary>

### 🛠️ Architecture Overview

#### Core Components

1.  **Main Application** (`main.py`): Handles async initialization, dependency injection, and lifecycle management.
2.  **Command Modules** (`commands/`): Each service has its own module, registered via a factory pattern with permission control.
3.  **Utility Modules** (`utils/`):
- `config_manager.py`: Configuration management.
- `cache_manager.py`, `redis_cache_manager.py`: Cache management.
- `mysql_user_manager.py`: Database operations for users and permissions.
- `task_scheduler.py`, `redis_task_scheduler.py`: Task scheduling.
- `permissions.py`: Permission system.
4.  **Data Storage:**
- **Redis:** Caching and message deletion scheduling.
- **MySQL:** User data and permission management.

#### Key Design Patterns

- **Command Factory:** For unified command registration and permission handling.
- **Dependency Injection:** Core components are passed via `bot_data`.
- **Asynchronous Programming:** Fully supports `async/await` for all I/O operations.
- **Decorator-based Error Handling:** Unified error handling for commands.
- **Direct Async Permission Checks:** The complex adapter layer has been removed, and MySQL operations are now directly asynchronous.

### 🗄️ Database Schema

- `users`: Basic user information
- `admin_permissions`: Administrators
- `super_admins`: Super administrators
- `user_whitelist`: Whitelisted users
- `group_whitelist`: Whitelisted groups
- `admin_logs`: Administrator action logs
- `command_stats`: Command usage statistics

The schema is defined in `database/init.sql` and is created automatically by the application on first run.

### 🔐 Permissions System

#### Architectural Optimizations

The project has been fully migrated away from SQLite compatibility adapters to a unified MySQL + Redis architecture:

- **Direct Asynchronous Permission Checks:** `utils/permissions.py` directly fetches the MySQL manager from `context.bot_data['user_cache_manager']`.
- **Unified Data Storage:** All permission data is stored in MySQL, preventing inconsistencies.
- **Performance Improvements:** The removal of synchronous-to-asynchronous complexities has increased response speed.

#### Permission Levels

1.  **Public Access:** All users and groups (whitelisted or not) can access streaming service pricing (`/nf`, `/ds`, `/sp`) and user information commands (`/when`, `/id`). Simply add the bot to any group to enable these features.
2.  **Whitelist Access:** Required for advanced features like crypto prices, currency conversion, weather forecasts, Steam prices, BIN lookup, and app store queries. *Whitelist applications are currently closed - future paid service plans may be available.*
3.  **Admin:** Stored in the MySQL `admin_permissions` table.
4.  **Super Admin:** Configured via the `SUPER_ADMIN_ID` environment variable.

### 🧩 Extending the Bot

#### Custom Scripts

Place Python scripts in the `custom_scripts/` directory and set `LOAD_CUSTOM_SCRIPTS=true` to load them automatically. Scripts get access to:

- `application`: The Telegram Application instance.
- `cache_manager`: The Redis cache manager.
- `rate_converter`: The currency converter.
- `user_cache_manager`: The user cache manager.
- `stats_manager`: The statistics manager.

#### New Command Development

1.  Create a new module in the `commands/` directory.
2.  Use `command_factory.register_command()` to register the new command.
3.  Set the appropriate permission level.
4.  Inject any necessary dependencies in `main.py`.

### 📊 Logging & Monitoring

#### Log Management

- **Log File:** `logs/bot-YYYY-MM-DD.log`
- **Log Rotation:** 10MB size limit with 5 backups.
- **Log Levels:** Supports `DEBUG`, `INFO`, `WARNING`, `ERROR`.
- **Periodic Cleanup:** Via `cleanup_logs.py` or a scheduled task.

#### Monitoring Features

- Command usage statistics
- User activity monitoring
- Error logging
- Performance metric collection

### ⚡ Performance Optimizations

#### Caching Strategy

- **Redis Cache:** Used for high-frequency data like price information and weather location lookups.
- **Unified Cache Management:** Managed via `redis_cache_manager.py`.
- **Smart Caching:** Different services have configurable cache durations.

#### Task Scheduling

- **Redis Task Scheduler:** Supports scheduled, recurring tasks.
- **Message Deletion:** Automatically cleans up temporary messages.
- **Cache Cleanup:** Periodically purges expired cache.

#### Connection Management

- **Connection Pooling:** Used for both MySQL and Redis.
- **Asynchronous Client:** Uses `httpx` for async HTTP requests.
- **Graceful Shutdown:** Cleans up resources and closes connections gracefully.

### 💡 Development Best Practices

1.  **Error Handling:** Use the `@with_error_handling` decorator.
2.  **Logging:** Use appropriate log levels.
3.  **Permission Checks:** Use the `@require_permission(...)` decorator.
4.  **Async Permissions:** Fetch the user manager via `context.bot_data['user_cache_manager']`.
5.  **Caching:** Use Redis caching to avoid duplicate requests.
6.  **Async Code:** Use `async/await` for all I/O-bound operations.
7.  **Configuration:** Manage all settings via environment variables.
8.  **Database Queries:** Use parameterized queries to prevent SQL injection.

### 🔍 Troubleshooting

#### Common Issues

1.  **Database Connection Failure:** Check MySQL configuration and connection.
2.  **Redis Connection Failure:** Check Redis service status.
3.  **Permission Errors:** Ensure the user is in the whitelist or admin list.
4.  **Commands Not Responding:** Check the log file for errors.
5.  **Weather Command Fails:** Ensure the `QWEATHER_API_KEY` is set correctly in your `.env` file and that it's a valid key.
6.  **BIN Lookup Fails:** Ensure the `BIN_API_KEY` is set correctly in your `.env` file and that you have sufficient API quota.

#### Debugging Tips

1.  Set `LOG_LEVEL=DEBUG` for detailed logs.
2.  Use `docker-compose logs -f appbot` to view real-time logs.
3.  Check Redis cache status.
4.  Verify database table structure and data.

### 📜 Architecture Migration Notes (v2.0 - Latest)

**Removed Components:**

- `utils/compatibility_adapters.py` - SQLite compatibility adapter
- `utils/redis_mysql_adapters.py` - Hybrid adapter
- `utils/unified_database.py` - Unified SQLite database
- Other SQLite-related files

**Architectural Optimizations:**

- Unified the architecture on MySQL + Redis.
- Implemented direct asynchronous permission checks, removing the complex adapter layer.
- Improved performance and code maintainability.
- Resolved an issue where whitelisted group users could not use the bot.

**Migration Essentials:**

- All permission data is now stored in MySQL.
- Redis is used for caching and message deletion scheduling.
- MySQL and Redis connection details must be configured in the `.env` file.

### 🆕 Recent Updates

#### Role-Based Access Control (Latest)
- **Universal Public Access:** All users and groups can use streaming service pricing and user information commands without any restrictions
- **Group Integration:** Add the bot to any Telegram group to enable public features for all members
- **Enhanced Help System:** Different help content displayed based on user permission level
- **Improved User Experience:** Clear distinction between free and premium features
- **Whitelist Policy Update:** Applications currently closed, future paid service plans under consideration

#### User Information Lookup Feature
- **Enhanced `/when` command** with username support for Telegram user registration date estimation
- **Multiple query methods** supporting direct ID input, username lookup (@username or username), and reply-to-message
- **Intelligent ID-based algorithm** using linear interpolation with real-world data points
- **User classification system** categorizing users by account age (新兵蛋子, 不如老兵, 老兵, etc.)
- **Markdown safety features** with proper special character escaping
- **Accurate age calculation** using year/month difference logic
- **Enhanced `/id` command** for getting user and group IDs
- **User caching system** for improved username-to-ID resolution performance

#### User Cache Management System
- **New user caching infrastructure** with MySQL storage and Redis performance optimization
- **Flexible group monitoring** via `ENABLE_USER_CACHE` and `USER_CACHE_GROUP_IDS` settings - **leave empty to monitor all groups**
- **Admin cache debugging** with `/cache` command for viewing cache statistics, user table size, and user lookup
- **Flexible cache cleanup** with `/cleanid` command supporting time-based and complete cleanup
- **Automatic user data collection** from all monitored group messages for username-to-ID mapping
- **Enhanced username support** in `/when` command leveraging cached user data

#### BIN Lookup Feature
- **New `/bin` command** for credit card BIN information lookup
- **Comprehensive data display** including card brand, type, issuing bank, and country
- **Smart caching system** for improved performance
- **Admin cache management** with `/bin_cleancache` command
- **Chinese localization support** for card brands and countries
- **Environment variable configuration** via `BIN_API_KEY`

</details>

### 📚 API Dependencies

- **CoinMarketCap API:** For cryptocurrency price data
- **DY.AX BIN API:** For credit card BIN information lookup
- **HeFeng Weather API:** For weather forecast data
- **Steam API:** For game pricing information
- **Various streaming service APIs:** For subscription pricing

### 🤝 Contributing

Contributions, issues, and feature requests are welcome. Feel free to check the [issues page](https://github.com/SzeMeng76/domobot/issues).

### License

This project is licensed under the MIT License.
