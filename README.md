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
- 🌐 **WHOIS Lookup:** Domain, IP, ASN, and TLD information with real-time IANA data and IP geolocation
- 🍳 **Cooking Assistant:** Recipe search, categorized browsing, intelligent meal planning, and daily menu recommendations
- 🆔 **Quick Commands:** `/nf`, `/ds`, `/sp`, `/max`, `/when`, `/id`, `/time`, `/timezone`, `/news`, `/newslist`, `/whois`, `/recipe`, `/what_to_eat`
- 👥 **Group Friendly:** Works in any Telegram group without requiring whitelist approval
- 🔧 **Self-Service:** Use `/refresh` if new commands don't appear in your input suggestions

*Advanced features (crypto, weather, Steam prices, movie/TV info, etc.) require whitelist access.*

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
-   🌐 **Public WHOIS Lookup:** Available to all users - comprehensive domain, IP address, ASN, and TLD information lookup with real-time IANA data integration and IP geolocation services. Features intelligent query type detection, support for domains (.com, .io), IP addresses (IPv4/IPv6), ASN numbers (AS15169), and TLD information (.com, .me) with detailed registry, WHOIS server, creation dates, and management organization data. **NEW:** IP queries now include actual server location with country, region, city, coordinates, ISP information, and timezone data via IP-API.com integration, clearly distinguishing between WHOIS registration data and actual geographic location.
-   🍳 **Public Cooking Assistant:** Available to all users - comprehensive recipe search and meal planning system with 1000+ recipes from HowToCook database. Features include **smart recipe search** with keyword matching, **categorized browsing** (荤菜, 素菜, 主食, 汤羹, 水产, 早餐, 甜品, etc.), **intelligent meal planning** with dietary restrictions and allergy considerations, **daily menu recommendations** with people count selection, **random recipe discovery**, and **Telegraph integration** for long recipes with complete ingredients and step-by-step instructions. All recipes include difficulty ratings, cooking time, serving sizes, and detailed nutritional guidance.
-   🎬 **Movie & TV Information:** Query movie/TV details with posters, ratings, cast, trailers, reviews, recommendations, viewing platforms, and season/episode info. Features **3-platform data integration** (TMDB + JustWatch + Trakt) with **JustWatch streaming charts**, real-time ranking trends, platform availability, Telegraph integration for long content, trending discovery, people search, and enhanced statistics with watch counts and community data. *(Whitelist required)*
-   🪙 **Crypto Prices:** Look up real-time cryptocurrency prices with support for custom amounts and currency conversion, including 24h and 7d percentage changes. *(Whitelist required)*
-   💳 **BIN Lookup:** Query credit card BIN (Bank Identification Number) information including card brand, type, issuing bank, and country details. *(Whitelist required)*
-   🌦️ **Weather Forecasts:** Detailed, multi-format weather forecasts (real-time, daily, hourly, minutely precipitation, and lifestyle indices). *(Whitelist required)*
-   💱 **Currency Conversion:** Real-time exchange rate lookups with mathematical expression support (e.g., `/rate USD 1+2*3`). *(Whitelist required)*
-   🎮 **Steam Prices:** Multi-region price comparison for Steam games, bundles, and comprehensive search functionality. *(Whitelist required)*
-   📱 **App Stores:** Application and in-app purchase price lookup for the App Store (detailed IAP items with pricing) and Google Play (IAP price ranges). *(Whitelist required)*
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
| `TMDB_API_KEY`              | **(Optional)** API Key from TMDB for the `/movie` and `/tv` commands.       |                         |
| `TRAKT_API_KEY`             | **(Optional)** API Key from Trakt for enhanced movie/TV statistics and trending data. |                         |
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

# WHOIS lookup (Enhanced with IP Geolocation)
/whois google.com         # Domain information with registrar details
/whois 8.8.8.8           # IP address with WHOIS registration + actual geographic location
/whois AS15169            # ASN information
/whois .com               # TLD information with IANA data
```

#### Whitelist-Only Commands
```bash
# BIN lookup
/bin 123456
/bin 12345678

# Cryptocurrency prices
/crypto btc
/crypto eth 0.5 usd

# Currency conversion (supports mathematical expressions)
/rate USD 100
/rate EUR JPY 50
/rate USD 1+1*2          # Mathematical expressions supported

# Weather forecasts (supports multiple formats)
/tq Beijing                # Current weather and forecast
/tq Tokyo 7                # 7-day forecast
/tq Shanghai 24h           # 24-hour hourly forecast
/tq Guangzhou indices      # Lifestyle indices

# Movies and TV shows
/movie Avengers            # Search movies (button selection)
/movies Avengers           # Search movies (text list)
/movie_hot                 # Multi-platform popular movies (TMDB + JustWatch + Trakt)
/movie_hot tmdb            # TMDB popular movies only
/movie_hot justwatch       # JustWatch streaming charts only
/movie_hot justwatch US    # JustWatch US streaming charts
/movie_detail 299536       # Movie details with JustWatch ranking info
/movie_videos 299536       # Movie trailers and videos
/movie_reviews 299536      # User reviews (Telegraph for long content)
/movie_rec 299536          # Movie recommendations
/movie_watch 299536        # Viewing platforms with JustWatch data
/movie_trending            # Trakt trending movies
/streaming_movie_ranking   # Comprehensive streaming movie ranking
/streaming_movie_ranking US # US streaming movie ranking
/movie_related 299536      # Trakt related movies
/tv Game of Thrones        # Search TV shows (button selection)
/tvs Game of Thrones       # Search TV shows (text list)
/tv_hot                    # Multi-platform popular TV shows (TMDB + JustWatch + Trakt)
/tv_hot tmdb               # TMDB popular TV shows only  
/tv_hot justwatch          # JustWatch streaming charts only
/tv_hot justwatch GB       # JustWatch UK streaming charts
/tv_detail 1399            # TV details with JustWatch ranking info
/tv_season 1399 1          # Season details
/tv_episode 1399 1 1       # Episode details
/tv_videos 1399            # TV trailers and videos
/tv_reviews 1399           # User reviews (Telegraph for long content)
/tv_rec 1399               # TV show recommendations
/tv_watch 1399             # Viewing platforms with JustWatch data
/tv_trending               # Trakt trending TV shows  
/streaming_tv_ranking      # Comprehensive streaming TV ranking
/streaming_tv_ranking GB   # UK streaming TV ranking
/tv_related 1399           # Trakt related TV shows

# Trending content
/trending                  # Today's trending movies, TV shows, and people
/trending_week             # This week's trending content
/now_playing               # Currently playing movies
/upcoming                  # Upcoming movie releases
/tv_airing                 # Today's airing TV shows
/tv_on_air                 # Currently airing TV shows

# People search
/person Tom Hanks          # Search for actors, directors, etc. (button selection)
/persons Tom Hanks         # Search for actors, directors, etc. (text list)
/person_detail 31          # Get person details and filmography

# Steam game prices and bundles
/steam Cyberpunk          # Game price lookup
/steam "Red Dead" US      # Multi-region game prices
/steamb "Valve Complete"  # Steam bundle prices
/steams cyberpunk         # Comprehensive search (games + bundles)

# App stores (with in-app purchase pricing)
/app WeChat                # App Store: detailed IAP items and pricing
/gp WhatsApp              # Google Play: IAP price ranges
# Note: Apple Store shows individual IAP items with prices; Google Play shows ranges (e.g., "$0.99-$99.99 per item")

# Apple services
/aps iCloud
```

#### Admin Commands
```bash
# User & Group Management
/add 123456789            # Add user to whitelist (also works with reply)
/addgroup                 # Add current group to whitelist
/admin                    # Open admin panel (interactive)

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

# Service Cache Management
/rate_cleancache          # Clear exchange rate cache
/crypto_cleancache        # Clear cryptocurrency cache
/bin_cleancache           # Clear BIN query cache
/movie_cleancache         # Clear movie/TV cache
/steamcc                  # Clear Steam cache
/nf_cleancache           # Clear Netflix cache
/ds_cleancache           # Clear Disney+ cache
/sp_cleancache           # Clear Spotify cache
/max_cleancache          # Clear HBO Max cache
/gp_cleancache           # Clear Google Play cache
/app_cleancache          # Clear App Store cache
/aps_cleancache          # Clear Apple services cache

# Weather Cache Management
/tq_cleancache           # Clear all weather cache
/tq_cleanlocation        # Clear weather location cache
/tq_cleanforecast        # Clear weather forecast cache
/tq_cleanrealtime        # Clear real-time weather cache

# News Cache Management
/news_cleancache         # Clear all news cache

# WHOIS Cache Management  
/whois_cleancache        # Clear WHOIS query cache

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

#### Command Refresh System (Latest Feature)
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
- **3-Platform Data Integration:** Combines TMDB, JustWatch, and Trakt APIs for comprehensive movie/TV information
- **JustWatch Streaming Charts:** Real-time streaming platform rankings with trend analysis and achievements
- **Multi-Source Popular Content:** `/movie_hot` and `/tv_hot` commands support 3 data sources (mixed display by default)
- **Flexible Data Source Selection:** Choose specific platforms with `/movie_hot tmdb|justwatch|trakt [country]`
- **Enhanced Ranking Display:** Current rank, trend indicators (📈📉➡️), historical achievements, and chart statistics
- **Platform Availability:** Shows up to 3 streaming platforms where content is available
- **Trend Analysis:** Rising/falling/stable status with ranking change indicators
- **Enhanced Search:** Interactive button-based movie/TV show selection
- **Rich Details:** Posters, ratings, cast, crew, trailers, and viewing platforms with JustWatch ranking info
- **Community Statistics:** Trakt integration provides watch counts, collector stats, and community engagement data
- **User Reviews:** Multi-source review system (TMDB + Trakt) with Telegraph integration for long content
- **Recommendation System:** Intelligent movie and TV show recommendations with Trakt-powered related content
- **Trending Discovery:** Real-time Trakt trending data with daily refresh for accuracy
- **Season/Episode Info:** Detailed TV show breakdowns with intelligent content truncation
- **People Search:** Actor, director, and crew information with filmography
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
- **Admin Cache Management:** Dedicated `/steamcc` command for cache control

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
- **TMDB API:** For movie and TV show information with Telegraph integration
- **Trakt API:** For enhanced movie/TV statistics, trending data, and community insights
- **JustWatch API:** For streaming platform rankings, charts, and platform availability data
- **HeFeng Weather API:** For weather forecast data
- **Steam API:** For game pricing information
- **IP-API.com:** For IP geolocation and actual server location data (free service)
- **Various streaming service APIs:** For subscription pricing

### 🤝 Contributing

Contributions, issues, and feature requests are welcome. Feel free to check the [issues page](https://github.com/SzeMeng76/domobot/issues).

### License

This project is licensed under the MIT License.
