<div align="right">

Read this in other languages: [简体中文](./README.zh-CN.md)

</div>

<div align="center">

# DomoBot
*A powerful, multi-functional Telegram bot for price lookups, weather forecasts, and more, containerized with Docker for easy deployment.*

## 🚀 Try it now: [@mengpricebot](https://t.me/mengpricebot)

**🎉 Free for Everyone - Add to Any Group!**

**Public features available to all users and groups:**
- 📺 **Streaming Prices:** Netflix, Disney+, Spotify, HBO Max pricing across global regions
- 👤 **User Information:** Telegram registration dates, account age, and ID lookup
- ⏰ **Time & Timezone:** Current time queries, timezone conversion, and timezone lists
- 📰 **News Aggregation:** Real-time news from 40+ sources including tech, social, finance, and general news
- 🌐 **WHOIS & DNS Lookup:** Domain, IP, ASN, TLD information with DNS records and Telegraph integration
- 🍳 **Cooking Assistant:** Recipe search, categorized browsing, intelligent meal planning, and daily menu recommendations
- 🎭 **Memes & Entertainment:** Random meme fetching with AI-generated descriptions, custom quantities (1-20), smart retry for quality content, auto-deletion, and intelligent caching
- 📊 **Finance & Stocks:** Real-time stock prices, 15 ranking categories (gainers/losers, tech stocks, funds), analyst recommendations, financial statements, multi-market support (US/HK/CN/MY), intelligent search by symbol or company name
- 🆔 **Quick Commands:** `/nf`, `/ds`, `/sp`, `/max`, `/when`, `/id`, `/time`, `/timezone`, `/news`, `/newslist`, `/whois`, `/dns`, `/recipe`, `/meme`, `/finance`
- 👥 **Group Friendly:** Works in any Telegram group without requiring whitelist approval
- 🔧 **Self-Service:** Use `/refresh` if new commands don't appear in your input suggestions

*Advanced features (crypto, weather, Steam prices, movie/TV info, map services, etc.) require whitelist access.*

</div>

<p align="center">
  <img src="https://github.com/SzeMeng76/domobot/actions/workflows/docker-publish.yml/badge.svg" alt="GitHub Actions Workflow Status" />
</p>

### 📝 Project Overview

This is a Python-based, multi-functional Telegram bot with the following features:

### ✨ Features

-   📺 **Public Streaming Prices:** Available to all users - query subscription prices for Netflix, Disney+, Spotify, and HBO Max across global regions.
-   👤 **Public User Information:** Available to all users - check Telegram user registration dates, account age, and get user/group IDs.
-   ⏰ **Public Time & Timezone:** Available to all users - query current time in any timezone, convert time between zones, and view supported timezone lists with IANA integration.
-   📰 **Public News Aggregation:** Available to all users - access real-time news from 40+ sources including GitHub trending, Zhihu hot topics, Weibo trending, tech news (IT Home, Hacker News), financial news (JinShi Data, Wallstreet CN), and general news sources with smart caching and categorized interface.
-   🌐 **Public WHOIS & DNS Lookup:** Available to all users - comprehensive domain, IP address, ASN, and TLD information lookup with real-time IANA data integration and IP geolocation services. Features intelligent query type detection, support for domains (.com, .io), IP addresses (IPv4/IPv6), ASN numbers (AS15169), and TLD information (.com, .me) with detailed registry, WHOIS server, creation dates, and management organization data. **NEW:** IP queries now include actual server location with country, region, city, coordinates, ISP information, and timezone data via IP-API.com integration, clearly distinguishing between WHOIS registration data and actual geographic location. **ENHANCED:** Domain WHOIS queries now automatically include comprehensive DNS records (A, AAAA, MX, NS, CNAME, TXT, SOA, PTR) with intelligent display formatting. Standalone `/dns` command available for DNS-only queries. Long query results automatically use Telegraph integration for complete information display with summary previews.
-   🍳 **Public Cooking Assistant:** Available to all users - comprehensive recipe search and meal planning system with 1000+ recipes from HowToCook database. Features include **smart recipe search** with keyword matching, **categorized browsing** (荤菜, 素菜, 主食, 汤羹, 水产, 早餐, 甜品, etc.), **intelligent meal planning** with dietary restrictions and allergy considerations, **daily menu recommendations** with people count selection, **random recipe discovery**, and **Telegraph integration** for long recipes with complete ingredients and step-by-step instructions. All recipes include difficulty ratings, cooking time, serving sizes, and detailed nutritional guidance.
-   🎭 **Public Memes:** Available to all users - fetch random memes from memes.bupt.site API with **AI-generated descriptions** for enhanced understanding. Features **smart retry mechanism** to ensure quality content when requesting single memes, custom quantities (1-20), intelligent caching system, auto-deletion scheduling (15 minutes), and fallback link display. Includes parameter validation, real-time status updates, and comprehensive error handling for reliable meme delivery. Description priority: manual review > AI description > none.
-   📊 **Public Finance & Stocks:** Available to all users - comprehensive financial market data powered by Yahoo Finance. Features **real-time stock prices** with market data and technical indicators, **15 ranking categories** including day gainers/losers, most actives, growth tech stocks, undervalued stocks, and mutual fund rankings, **intelligent stock search** supporting ticker symbols and company names across multiple markets (US, HK, CN, MY), **analyst recommendations** with buy/sell/hold ratings, **financial statements** (income, balance sheet, cash flow), categorized inline button interface, intelligent caching with different TTL for various data types, and comprehensive error handling with auto-deletion. Supports flexible search queries like "AAPL", "Apple", "Tesla", "6033.KL", "Maybank" with multilingual matching.
-   🗺️ **Map Services:** Intelligent location search and navigation system with **automatic language detection** - Google Maps API for English users and Amap (高德地图) API for Chinese users. Features **comprehensive location search** with detailed place information, ratings, and types, **nearby service recommendations** (restaurants, hospitals, banks, gas stations, supermarkets, schools, hotels), **route planning** with step-by-step directions and travel time estimates, **geocoding** for address-to-coordinates conversion, **reverse geocoding** for coordinates-to-address lookup, **interactive button interface** with single `/map` command, **session management** for multi-step operations, **Redis caching** with appropriate TTL for different data types, and **auto-deletion** for all messages. Supports text input, location sharing, and coordinate queries with comprehensive error handling. *(Whitelist required)*
-   ✈️ **Flight Services:** Intelligent flight search and booking information powered by Google Flights API. Features **multi-language airport recognition** (Chinese, English, IATA codes), **global airport coverage** (Asia, Europe, Americas, Oceania), **smart airport matching** with automatic selection of optimal airports, **real-time flight data** with price analysis and booking options, **intelligent route planning** with time zone calculations and flight distance information, **comprehensive airline coverage** with multiple booking channels, and **Telegraph integration** for detailed flight lists. Supports mixed-language input like `北京 New York` or `吉隆坡 Bangkok` with automatic conversion to optimal airport pairs (PEK↔JFK, KUL↔BKK). *(Whitelist required)*
-   🏨 **Hotel Services:** Intelligent hotel search and booking information powered by Google Hotels API. Features **multi-language location recognition** (Chinese, English, specific areas), **global hotel coverage** with support for major cities worldwide, **smart location matching** with automatic area selection, **real-time hotel data** with price analysis and booking options, **comprehensive accommodation information** including ratings, amenities, and descriptions, **flexible date handling** with automatic check-in/out date parsing, **interactive sorting and filtering** with price/rating options, **Telegraph integration** for detailed hotel lists, and **intelligent stay duration analysis**. Supports mixed-language input like `北京`, `Tokyo`, `Kepong`, `Times Square NYC` with automatic location resolution. *(Whitelist required)*
-   🎬 **Movie & TV Information:** Completely redesigned with **unified button interface system** for intuitive interaction. Features **triple-platform integration** (TMDB + JustWatch + Trakt) with comprehensive search capabilities, detailed movie/TV information with posters and ratings, **interactive season/episode browsing** with user-input selection, **one-click access** to recommendations, reviews, videos, related content, and streaming platforms. Enhanced with **Telegraph integration** for long content, **unified chart system** for trending/popular/upcoming content, **intelligent session management** for multi-step interactions, and **comprehensive caching** with automatic cleanup. All functionality accessed through simple `/movie`, `/tv`, `/person`, and `/chart` commands with no need to remember complex sub-commands. *(Whitelist required)*
-   🪙 **Crypto Prices:** Look up real-time cryptocurrency prices with support for custom amounts and currency conversion, including 24h and 7d percentage changes. **NEW:** Interactive ranking system with hot trending coins, top gainers/losers, market cap rankings, and trading volume charts - all powered by CoinGecko's free API (no API key required). Features include smart caching, refresh functionality, and unified menu interface. *(Whitelist required)*
-   💳 **BIN Lookup:** Query credit card BIN (Bank Identification Number) information including card brand, type, issuing bank, and country details. *(Whitelist required)*
-   🌦️ **Weather Forecasts:** Detailed, multi-format weather forecasts (real-time, daily, hourly, minutely precipitation, and lifestyle indices). *(Whitelist required)*
-   💱 **Currency Conversion:** Real-time exchange rate lookups with mathematical expression support (e.g., `/rate USD 1+2*3`). *(Whitelist required)*
-   🎮 **Steam Prices:** Multi-region price comparison for Steam games, bundles, and comprehensive search functionality. *(Whitelist required)*
-   📱 **App Stores:** Application and in-app purchase price lookup for the App Store (detailed IAP items with pricing) and Google Play (IAP price ranges). *(Whitelist required)*
-   🔐 **Admin System:** A comprehensive admin permission system with user/group whitelisting.
-   📊 **User Caching & Stats:** Caching user data and command usage statistics.
-   🛡️ **AI Anti-Spam:** Intelligent spam detection system powered by OpenAI GPT-4o-mini with **group-level configuration**, automatic user verification based on join time and activity, customizable spam score thresholds, comprehensive logging and statistics, **global statistics dashboard**, **Telegraph-integrated log viewing**, and automatic data cleanup. Features smart detection for new users while respecting verified members, detailed spam analysis with reasoning and mock text, ban/mute actions, and complete admin panel integration with per-group and cross-group analytics.

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
| `TMDB_API_KEY`              | **(Optional)** API Key from TMDB for the `/movie` and `/tv` commands.       |                         |
| `TRAKT_API_KEY`             | **(Optional)** API Key from Trakt for enhanced movie/TV statistics and trending data. |                         |
| `GOOGLE_MAPS_API_KEY`       | **(Optional)** API Key from Google Maps for the `/map` command (English users). |                         |
| `AMAP_API_KEY`              | **(Optional)** API Key from Amap (高德地图) for the `/map` command (Chinese users). |                         |
| `SERPAPI_KEY`               | **(Optional)** API Key from SerpAPI for the `/flight` and `/hotel` commands with Google Flights & Hotels integration. |                         |
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
| `OPENAI_API_KEY`            | **(Optional)** API Key from OpenAI for AI anti-spam detection feature. Feature is enabled by default if key is provided. After setting the key, enable anti-spam for specific groups via `/admin` panel. |                         |

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
/max         # HBO Max global pricing

# User information lookup
/when 123456789           # Query by user ID
/when @username           # Query by username
/when username            # Query by username (without @)
/when                     # Reply to a user's message
/id                       # Get user/group IDs
/id                       # Reply to a message

# Time & timezone queries
/time                     # Show help for time commands
/time Beijing             # Current time in Beijing
/time Japan               # Current time in Japan
/time US                  # Current time in US
/convert_time China 14:30 US    # Convert 2:30 PM from China to US time
/timezone                 # View supported timezone list

# News aggregation
/news                     # Interactive news source selection
/newslist                 # Show all news sources with categories
/newslist zhihu           # Get Zhihu hot topics (default 10 items)
/newslist zhihu 5         # Get top 5 Zhihu hot topics
/newslist github 15       # Get top 15 GitHub trending items
/hotnews                  # Quick access to hot news from multiple sources

# WHOIS & DNS lookup (Enhanced with DNS Records & Telegraph Integration)
/whois google.com         # Domain WHOIS + DNS records (A, AAAA, MX, NS, CNAME, TXT, SOA, PTR)
/whois 8.8.8.8           # IP address with WHOIS registration + actual geographic location
/whois AS15169            # ASN information
/whois .com               # TLD information with IANA data
/dns github.com           # DNS records only (A, AAAA, MX, NS, CNAME, TXT, SOA, PTR)

# Cooking Assistant (Unified Recipe Interface)
/recipe                   # Interactive menu with all cooking features
/recipe 红烧肉             # Direct search for recipes by name or ingredients
# Menu includes: Recipe search, category browsing, random recommendations, daily menu planning, smart meal planning

# Memes & Entertainment
/meme 3                  # Get 3 random memes
/meme 5                  # Get 5 random memes (1-20 range)
/meme                    # Show help and usage guide

# Finance & Stock Market (Real-time data from Yahoo Finance)
/finance                 # Show finance main menu with categories
/finance AAPL            # Search Apple stock by symbol
/finance Tesla           # Search Tesla by company name
/finance 6033.KL         # Search Malaysian stock (PETRONAS Gas)
/finance Maybank         # Search by partial company name
# Interactive features: Stock rankings (15 categories), analyst recommendations, financial statements
```

#### Whitelist-Only Commands
```bash
# Intelligent Flight Search & Booking (Multi-language Airport Recognition)
/flight                        # Interactive flight service menu
/flight 北京 洛杉矶 2024-12-25     # Chinese cities (auto-converts PEK→LAX)
/flight 吉隆坡 普吉 2024-12-25 2024-12-30  # Round-trip flight (KUL→HKT)
/flight Shanghai Tokyo 2024-12-25  # Mixed language input (PVG→NRT)
/flight PEK LAX 2024-12-25     # Direct IATA codes
/flight Jakarta Bangkok 2024-12-25  # English cities (CGK→BKK)
# Interactive features: Price analysis, booking options, multi-city planning, airport info

# Intelligent Hotel Search & Booking (Multi-language Location Recognition)
/hotel                         # Interactive hotel service help
/hotel 北京                    # Chinese cities with area selection
/hotel 东京 2024-12-25          # Single date (auto check-out next day)
/hotel Tokyo 2024-12-25 2024-12-28  # Check-in and check-out dates
/hotel Kepong 25 28           # Current month dates (25th-28th)
/hotel "Times Square NYC" 2024-12-25  # Specific locations
/hotel Bangkok 01-20 01-25    # Month-day format (current year)
# Interactive features: Price sorting, rating sorting, detailed lists, map view

# BIN lookup
/bin 123456
/bin 12345678

# Cryptocurrency prices (Enhanced with Rankings)
/crypto                        # Interactive crypto menu with rankings
/crypto btc                    # Direct price query
/crypto eth 2 usd             # Custom amount and currency
# Interactive features: Hot trending coins, gainers/losers, market cap, volume rankings

# Currency conversion (supports mathematical expressions)
/rate USD 100
/rate EUR JPY 50
/rate USD 1+1*2          # Mathematical expressions supported

# Weather forecasts (supports multiple formats)
/tq Beijing                # Current weather and forecast
/tq Tokyo 7                # 7-day forecast
/tq Shanghai 24h           # 24-hour hourly forecast
/tq Guangzhou indices      # Lifestyle indices

# Movies and TV shows (Unified Button Interface)
/movie Avengers            # Search movies with interactive buttons
/tv Game of Thrones        # Search TV shows with interactive buttons  
/chart                     # Unified charts - trending, popular, upcoming content
/person Tom Hanks          # Search actors/directors with button interface

# Steam game prices and bundles
/steam Cyberpunk          # Game price lookup
/steam "Red Dead" US      # Multi-region game prices
/steamb "Valve Complete"  # Steam bundle prices
/steams cyberpunk         # Comprehensive search (games + bundles)

# App stores (with in-app purchase pricing)
/app WeChat                # App Store: detailed IAP items and pricing (iOS/iPadOS/macOS/tvOS/watchOS/visionOS)
/app -ipad Procreate       # iPad-specific search
/app -mac "Final Cut Pro"  # Mac-specific search
/gp WhatsApp              # Google Play: IAP price ranges
# Note: Apple Store shows individual IAP items with prices; Google Play shows ranges (e.g., "$0.99-$99.99 per item")
# Platform flags: -iphone, -ipad, -mac, -tv, -watch, -vision (default: -iphone)

# Apple services
/aps iCloud
```

#### Admin Commands
```bash
# User & Group Management
/add 123456789            # Add user to whitelist (also works with reply)
/addgroup                 # Add current group to whitelist
/admin                    # Open admin panel (interactive)

# AI Anti-Spam Management (via /admin panel)
# - Enable/disable anti-spam for specific groups
# - View per-group statistics (checks, spam detected, bans, false positives)
# - View global statistics across all groups (7-day and 30-day summaries)
# - View recent detection logs with Telegraph integration for long lists
# - Configure spam score thresholds and detection parameters
# - Automatic weekly data cleanup (logs: 30 days, stats: 90 days, inactive users: 60 days)

# Data Points Management
/listpoints [limit]       # List known data points (default 10, with statistics)
/addpoint <user_id> <date> [note] # Add new data point (format: YYYY-MM-DD)
/removepoint <user_id>    # Remove specified data point

# User cache management
/cache                    # View user cache status and statistics
/cache username           # Check if specific user is cached
/cache @username          # Check if specific user is cached
/cache 123456789          # Check if specific user ID is cached
/cleanid                  # Clean all user ID cache
/cleanid 30               # Clean user cache older than 30 days

# Unified Cache Management
/cleancache               # Interactive cache management menu
/cleancache all           # Clear all service caches
/cleancache memes         # Clear memes cache
/cleancache news          # Clear news cache
/cleancache crypto        # Clear cryptocurrency cache
/cleancache movie         # Clear movie/TV cache
/cleancache steam         # Clear Steam cache
/cleancache weather       # Clear weather cache (all types)
/cleancache cooking       # Clear cooking recipe cache
/cleancache whois         # Clear WHOIS query cache
/cleancache app           # Clear App Store cache
/cleancache netflix       # Clear Netflix cache
/cleancache spotify       # Clear Spotify cache
/cleancache disney        # Clear Disney+ cache
/cleancache max           # Clear HBO Max cache
/cleancache rate          # Clear exchange rate cache
/cleancache bin           # Clear BIN query cache
/cleancache google_play   # Clear Google Play cache
/cleancache apple_services # Clear Apple services cache
/cleancache finance       # Clear finance & stock data cache

# Command List Management
/refresh_all             # Admin: Refresh command lists for all users and groups
/refresh                 # User: Refresh your own command list (fixes new feature visibility)
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
- `anti_spam_config`: AI anti-spam group configuration
- `anti_spam_user_info`: User verification and activity tracking
- `anti_spam_logs`: Spam detection history and details
- `anti_spam_stats`: Daily statistics aggregation

The schema is defined in `database/init.sql` and is created automatically by the application on first run.

### 🔐 Permissions System

#### Architectural Optimizations

The project has been fully migrated away from SQLite compatibility adapters to a unified MySQL + Redis architecture:

- **Direct Asynchronous Permission Checks:** `utils/permissions.py` directly fetches the MySQL manager from `context.bot_data['user_cache_manager']`.
- **Unified Data Storage:** All permission data is stored in MySQL, preventing inconsistencies.
- **Performance Improvements:** The removal of synchronous-to-asynchronous complexities has increased response speed.

#### Permission Levels

1.  **Public Access:** All users and groups (whitelisted or not) can access streaming service pricing (`/nf`, `/ds`, `/sp`) and user information commands (`/when`, `/id`). Simply add the bot to any group to enable these features.
2.  **Whitelist Access:** Required for advanced features like crypto prices, currency conversion, weather forecasts, Steam prices, BIN lookup, movie/TV information, and app store queries. *Contact for whitelist access or future service plans.*
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
- **Mathematical Expression Caching:** Safe evaluation and caching of mathematical expressions in currency conversions.

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

#### Cryptocurrency Rankings Enhancement (Latest)
- **CoinGecko Integration:** Migrated ranking features to CoinGecko's free API, removing API key requirements for ranking functionality
- **Interactive Menu System:** New unified interface similar to finance module with button navigation and real-time data
- **Multiple Ranking Categories:** Hot trending coins, 24h gainers/losers, market cap rankings, and trading volume charts
- **Smart Dual API Strategy:** CoinGecko for rankings (free), CoinMarketCap for individual price queries (premium)
- **Enhanced Data Display:** Comprehensive coin information with prices, changes, market cap ranks, and real-time timestamps
- **Caching Integration:** Intelligent caching system with separate TTL for different data types and unified cache management
- **User Experience:** Clean markdown formatting, refresh functionality, and auto-deletion for chat cleanliness
- **No Setup Required:** Ranking features work out-of-the-box without API configuration
- **New `/finance` Command:** Comprehensive financial market data powered by Yahoo Finance API with real-time stock prices
- **15 Ranking Categories:** Complete stock and fund rankings including day gainers/losers, most actives, growth tech stocks, undervalued stocks, and 6 mutual fund categories
- **Multi-Market Support:** US, Hong Kong (HK), China (CN), Malaysia (MY) stocks with flexible ticker format support
- **Intelligent Stock Search:** Support for ticker symbols (AAPL, 6033.KL) and company names (Apple, Tesla, Maybank) with multilingual matching
- **Advanced Financial Data:** Analyst recommendations with buy/sell/hold ratings, financial statements (income, balance sheet, cash flow)
- **Categorized Interface:** Separate stock rankings (9 types) and fund rankings (6 types) with interactive button navigation
- **Smart Caching System:** Intelligent Redis caching with different TTL for stock info (5min), rankings (3min), and search results (10min)
- **Auto-deletion Management:** All user commands and bot messages automatically deleted to maintain clean chat interface
- **Real-time Market Data:** Current prices, daily changes, volume, market cap, P/E ratio, and exchange information
- **Technical Integration:** yfinance library integration with pandas DataFrame processing and comprehensive error handling

#### Memes Feature Integration
- **New `/meme` Command:** Fetch random memes from memes.bupt.site API with support for 1-20 memes per request
- **Parameter Validation:** Smart input validation with clear error messages and usage guidance
- **Auto-deletion System:** Meme images automatically delete after 15 minutes to keep chats clean
- **Intelligent Caching:** Redis-powered caching system for improved performance with configurable TTL
- **Fallback Support:** Link-based fallback display when direct image sending fails
- **Unified Cache Management:** Integrated with `/cleancache` system for easy cache administration
- **Error Handling:** Comprehensive error handling with loading indicators and user feedback
- **Pydantic Validation:** Type-safe API response parsing using Pydantic models
- **Weekly Cleanup:** Configurable weekly cache cleanup via `memes_weekly_cleanup` setting

#### Unified Cache Management System (Latest)
- **Single Command Interface:** Replaced 20+ individual `*_cleancache` commands with unified `/cleancache` system
- **Interactive Menu:** Button-based service selection with clear categorization and status feedback
- **Command-line Support:** Direct cache clearing via `/cleancache [service]` for power users
- **Special Handling:** Complex cache structures (weather with 7 prefixes) handled automatically
- **Comprehensive Coverage:** All services included - memes, news, crypto, movie, steam, weather, cooking, whois, app stores, streaming services, rate, and BIN
- **Admin Permission:** Secure admin-only access with proper error handling and logging
- **Real-time Feedback:** Immediate status updates during cache clearing operations
- **Service Mapping:** Clear service name mappings for better user experience

#### Command Refresh System (Previous Feature)
- **Smart Command List Management:** New `/refresh_all` admin command refreshes command lists for all users and groups
- **User Self-Service:** `/refresh` command allows any user to fix command visibility issues independently
- **Telegram Cache Solution:** Resolves Telegram client-side command caching when new features are added
- **Global + Personal Updates:** Updates both global default commands and individual user/group command lists
- **Help Integration:** Automatic guidance in help and start commands for troubleshooting command visibility
- **New Feature Rollout:** Streamlines deployment of new Permission.NONE features to all users
- **Reduces Admin Burden:** Users can resolve command display issues without contacting administrators

#### Enhanced WHOIS with IP Geolocation
- **Dual Information System:** WHOIS registration data + actual server geolocation for IP addresses
- **IP-API.com Integration:** Real-time IP geolocation service providing accurate server location data  
- **Comprehensive Location Details:** Country with flags, region, city, postal code, coordinates, and timezone
- **ISP & Network Information:** Actual ISP, organization, and AS number from geolocation service
- **Smart Field Categorization:** Separate display sections for registration info vs. actual location
- **Enhanced Country Display:** Country flags and Chinese names using existing country_data integration
- **Intelligent Cloud Detection:** Automatic detection of cloud providers (Microsoft, Amazon, Google) with explanatory notes
- **Error Handling & Fallback:** Graceful degradation when geolocation service is unavailable
- **Rate Limit Compliance:** Respects IP-API.com's 45 requests/minute free tier limitations
- **Cache Integration:** Redis caching for both WHOIS and geolocation data with configurable TTL
- **User-Friendly Explanations:** Clear distinction between "📍 注册位置" and "🌍 实际位置" for better understanding

#### Time & Timezone Features
- **Public Time Queries:** Available to all users - query current time in any timezone using country names, codes, cities, or IANA timezone identifiers
- **Timezone Conversion:** Convert time between different timezones with intelligent parsing of various timezone formats
- **Comprehensive Timezone Support:** Supports 200+ cities, 190+ countries with full IANA timezone database integration
- **Country Data Integration:** Leverages existing country_data.py for consistent flag display and localized country names
- **Smart Input Recognition:** Accepts Chinese/English country names, ISO country codes, major city names, and standard IANA timezone identifiers
- **Interactive Help System:** Context-aware help with complete IANA timezone documentation links
- **Caching System:** Redis-powered caching for timezone differences and location lookups for optimal performance
- **Markdown V2 Formatting:** Full compliance with Telegram's formatting requirements with proper character escaping

#### Data Points Management System (Latest Feature)
- **JSON Storage Architecture:** Replaced hardcoded data points with flexible JSON file storage system
- **Real-time Statistics Display:** Shows statistics for total, verified, and estimated data points
- **Dynamic Management Features:** Support for adding, removing, and viewing data points via Telegram commands
- **Docker Volume Persistence:** Ensures data integrity across container restarts
- **Backward Compatibility:** Fully compatible with existing estimation algorithms, no migration required

#### Role-Based Access Control (Latest)
- **Universal Public Access:** All users and groups can use streaming service pricing and user information commands without any restrictions
- **Group Integration:** Add the bot to any Telegram group to enable public features for all members
- **Enhanced Help System:** Different help content displayed based on user permission level
- **Improved User Experience:** Clear distinction between free and premium features
- **Admin Management Tools:** Comprehensive user/group whitelist management via `/add`, `/addgroup`, and interactive `/admin` panel
- **Whitelist Policy Update:** Applications currently closed, future paid service plans under consideration

#### Movie & TV Features  
- **Unified Button Interface System:** Complete redesign with interactive buttons for intuitive navigation
- **3-Platform Data Integration:** Combines TMDB, JustWatch, and Trakt APIs for comprehensive movie/TV information
- **JustWatch Streaming Charts:** Real-time streaming platform rankings integrated into unified `/chart` system
- **Interactive Content Access:** One-click access to recommendations, reviews, videos, platforms via button interface
- **Smart Session Management:** Multi-step interactions for season/episode selection with user input
- **Enhanced Search:** Intelligent movie/TV/person search with comprehensive result display
- **Rich Details:** Posters, ratings, cast, crew, trailers, and viewing platforms with full integration
- **Community Statistics:** Trakt integration provides watch counts, collector stats, and community engagement data
- **Telegraph Integration:** Seamless long content display for reviews, cast lists, and detailed information
- **Unified Chart System:** All trending, popular, and upcoming content consolidated in `/chart` command
- **Simplified Commands:** Just 4 main commands (`/movie`, `/tv`, `/person`, `/chart`) replace 25+ old commands
- **Season/Episode Navigation:** Interactive season and episode browsing with contextual information
- **Platform Availability:** Shows streaming platforms with intelligent geographic relevance
- **Source Transparency:** Clear indicators showing data sources (📊 TMDB, 📺 JustWatch, 🎯 Trakt) in all displays
- **Multilingual Support:** Chinese/English content fallback for better coverage
- **Real-time Updates:** JustWatch data includes timestamps and data freshness indicators

#### User Cache Management System
- **New user caching infrastructure** with MySQL storage and Redis performance optimization
- **Flexible group monitoring** via `ENABLE_USER_CACHE` and `USER_CACHE_GROUP_IDS` settings - **leave empty to monitor all groups**
- **Admin cache debugging** with `/cache` command for viewing cache statistics, user table size, and user lookup
- **Flexible cache cleanup** with `/cleanid` command supporting time-based and complete cleanup
- **Automatic user data collection** from all monitored group messages for username-to-ID mapping
- **Enhanced username support** in `/when` command leveraging cached user data

#### Steam Gaming Features
- **Multi-format Game Search:** `/steam` for individual games with multi-region pricing
- **Bundle Price Lookup:** `/steamb` for Steam bundle pricing and content information
- **Comprehensive Search:** `/steams` for combined games and bundles search results
- **Region Comparison:** Multi-country price comparison for better deals
- **Smart Caching:** Intelligent caching system for improved performance
- **Unified Cache Management:** Integrated with `/cleancache steam` command for cache control

#### BIN Lookup Feature
- **New `/bin` command** for credit card BIN information lookup
- **Comprehensive data display** including card brand, type, issuing bank, and country
- **Smart caching system** for improved performance
- **Unified cache management** via `/cleancache bin` command
- **Chinese localization support** for card brands and countries
- **Environment variable configuration** via `BIN_API_KEY`

</details>

### 📚 API Dependencies

- **OpenAI API:** For AI-powered spam detection with GPT-4o-mini model
- **CoinMarketCap API:** For cryptocurrency price data
- **CoinGecko API:** For cryptocurrency rankings, trending coins, and market data (free tier, no API key required)
- **DY.AX BIN API:** For credit card BIN information lookup
- **TMDB API:** For movie and TV show information with Telegraph integration
- **Trakt API:** For enhanced movie/TV statistics, trending data, and community insights
- **JustWatch API:** For streaming platform rankings, charts, and platform availability data
- **HeFeng Weather API:** For weather forecast data
- **Steam API:** For game pricing information
- **Google Maps API:** For location search, nearby places, route planning, and geocoding services (English users)
- **Amap (高德地图) API:** For location search, nearby places, route planning, and geocoding services (Chinese users)
- **SerpAPI:** For flight search and booking information via Google Flights integration with multi-language airport recognition, and hotel search with multi-language location recognition via Google Hotels integration
- **IP-API.com:** For IP geolocation and actual server location data (free service)
- **Yahoo Finance API:** For real-time stock prices, market data, rankings, analyst recommendations, and financial statements
- **Various streaming service APIs:** For subscription pricing

### 📊 Data Sources

This project leverages several open source projects for data collection and processing:

- **News Sources:** [newsnow](https://github.com/SzeMeng76/newsnow) - News aggregation and trending content
- **TLD Information:** [iana_tld_list](https://github.com/SzeMeng76/iana_tld_list) - IANA top-level domain data
- **Cooking Recipes:** [HowToCook](https://github.com/SzeMeng76/HowToCook) - Recipe database and meal planning
- **Netflix Pricing:** [netflix-pricing-scraper](https://github.com/SzeMeng76/netflix-pricing-scraper) - Global Netflix subscription prices
- **Disney+ Pricing:** [disneyplus-prices](https://github.com/SzeMeng76/disneyplus-prices) - Disney+ subscription pricing data
- **Spotify Pricing:** [spotify-prices](https://github.com/SzeMeng76/spotify-prices) - Spotify subscription pricing information
- **HBO Max Pricing:** [hbo-max-global-prices](https://github.com/SzeMeng76/hbo-max-global-prices) - HBO Max global pricing data

### 🤝 Contributing

Contributions, issues, and feature requests are welcome. Feel free to check the [issues page](https://github.com/SzeMeng76/domobot/issues).

### License

This project is licensed under the MIT License.
