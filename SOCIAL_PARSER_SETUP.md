# 社交媒体解析功能 - 部署指南

## 📋 功能概述

成功整合了 **ParseHub** 社交媒体解析功能到你的 domobot 项目！

### ✨ 主要特性

1. **支持20+平台**：抖音、快手、B站、YouTube、TikTok、小红书、Twitter/X、Instagram、Facebook、微博等
2. **两种工作模式**：
   - **命令模式**：`/parse <链接>` 手动解析
   - **自动监听模式**：在启用的群组中自动检测并解析链接
3. **完整的管理面板**：通过 `/admin` 命令管理群组的自动解析功能
4. **权限控制**：整合到你现有的白名单和权限系统
5. **统计功能**：记录解析统计数据

---

## 🗄️ 数据库部署

### 步骤1：添加数据库表

将以下SQL语句添加到你的 `database/init.sql` 文件末尾：

```sql
-- ============================================================================
-- 社交媒体解析功能相关表
-- ============================================================================

-- 群组自动解析配置表
CREATE TABLE IF NOT EXISTS social_parser_config (
    group_id BIGINT PRIMARY KEY COMMENT '群组ID',
    auto_parse_enabled BOOLEAN DEFAULT FALSE COMMENT '是否启用自动解析',
    enabled_by BIGINT NOT NULL COMMENT '启用者ID',
    enabled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '启用时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_auto_parse_enabled (auto_parse_enabled),
    FOREIGN KEY (group_id) REFERENCES group_whitelist(group_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='社交媒体解析配置表';

-- 解析统计表
CREATE TABLE IF NOT EXISTS social_parser_stats (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL COMMENT '用户ID',
    group_id BIGINT COMMENT '群组ID（私聊为NULL）',
    platform VARCHAR(50) NOT NULL COMMENT '平台名称',
    url TEXT NOT NULL COMMENT '解析的URL',
    parse_success BOOLEAN DEFAULT TRUE COMMENT '是否解析成功',
    parse_time_ms INT COMMENT '解析耗时（毫秒）',
    error_message TEXT COMMENT '错误信息',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_id (user_id),
    INDEX idx_group_id (group_id),
    INDEX idx_platform (platform),
    INDEX idx_created_at (created_at),
    INDEX idx_parse_success (parse_success)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='社交媒体解析统计表';
```

### 步骤2：运行数据库迁移

```bash
# 如果你的数据库已存在，运行以下命令创建新表
mysql -u your_user -p your_database < database/init.sql

# 或者只运行新增的表
mysql -u your_user -p your_database << 'EOF'
-- 粘贴上面的SQL语句
EOF
```

---

## ⚙️ 环境变量配置（新增）

在你的 `.env` 文件中添加以下配置（已添加到 `.env.example`）：

```env
# =============================================================================
# 社交媒体解析功能配置 (ParseHub)
# =============================================================================

# 基础代理配置 (可选 - 仅用于IP更换，反爬虫headers由ParseHub自动注入)
# PARSER_PROXY=http://your-proxy:port      # 可选：解析使用的代理
# DOWNLOADER_PROXY=http://your-proxy:port  # 可选：下载使用的代理

# YouTube专用代理 (强烈推荐 - YouTube bot检测严格，需要代理绕过)
# YOUTUBE_PROXY=http://your-proxy:port     # YouTube解析和下载专用代理（支持http/https/socks5）

# 缓存配置
PARSER_CACHE_DURATION=86400                # 解析结果缓存时间（秒，默认24小时）

# 抖音API配置 (可选 - 提供更稳定的抖音解析)
# DOUYIN_API=                               # 抖音API地址

# TikHub API配置 (可选 - 用于TikTok/Douyin/小红书解析)
# 支持TikTok视频解析（国际版抖音，官方ParseHub不支持）
# 支持Douyin/小红书视频解析（当官方ParseHub失败时作为备选方案）
# TIKHUB_API_KEY=your_tikhub_api_key_here  # TikHub API密钥（从 https://api.tikhub.io 获取）

# AI总结功能配置 (可选 - 使用你已有的 OPENAI_API_KEY)
ENABLE_AI_SUMMARY=false                    # 是否启用AI总结功能
AI_SUMMARY_MODEL=gpt-5-mini                # AI总结使用的模型（gpt-5-mini 更快更便宜）

# 图床上传配置 (可选 - 用于大文件上传)
ENABLE_IMAGE_HOST=false                    # 是否启用图床上传
IMAGE_HOST_SERVICE=catbox                  # 图床服务: catbox, litterbox, zioooo
# CATBOX_USERHASH=                         # Catbox 用户哈希（可选）
# ZIOOOO_STORAGE_ID=                       # Zio.ooo 存储ID（可选）

# Telegraph发布配置 (可选 - 用于长图文内容)
ENABLE_TELEGRAPH=false                     # 是否启用Telegraph发布
TELEGRAPH_TOKEN=                           # Telegraph访问令牌（留空自动创建）
TELEGRAPH_AUTHOR=DomoBot                   # Telegraph作者名称

# 视频分割配置 (可选 - 需要FFmpeg)
ENABLE_VIDEO_SPLIT=false                   # 是否启用视频分割功能
VIDEO_SPLIT_SIZE=45                        # 分割大小（MB，默认45MB）
FFMPEG_PATH=ffmpeg                         # FFmpeg路径（默认ffmpeg，需在PATH中）

# 语音转录配置 (可选 - 视频转文字)
ENABLE_TRANSCRIPTION=false                 # 是否启用转录功能
TRANSCRIPTION_PROVIDER=openai              # 转录服务: openai, azure, fast_whisper
# TRANSCRIPTION_API_KEY=                   # 转录API密钥（默认使用 OPENAI_API_KEY）
# TRANSCRIPTION_BASE_URL=                  # 转录API地址（可选）

# 平台Cookie配置 (可选 - 用于解析受限内容)
# 支持Cookie的平台：Twitter, Instagram, Bilibili, Kuaishou, YouTube
# 不支持：Facebook（基于yt-dlp，ParseHub库未实现cookie支持）
#
# ⚠️ 重要：长Cookie必须用引号包裹，避免被截断！
# 示例：TWITTER_COOKIE="auth_token=xxx; ct0=yyy"
#
# Twitter Cookie（格式：auth_token=xxx; ct0=xxx，必需：auth_token, ct0）
# TWITTER_COOKIE="auth_token=your_token; ct0=your_ct0"
#
# Instagram Cookie（格式：sessionid=xxx）
# INSTAGRAM_COOKIE=""
#
# Bilibili Cookie（格式：SESSDATA=xxx; bili_jct=xxx）
# BILIBILI_COOKIE=""
#
# Kuaishou Cookie（格式：did=xxx; kpn=xxx）
# KUAISHOU_COOKIE=""
#
# YouTube Cookie（用于绕过"Sign in to confirm you're not a bot"错误）
# 方式1: 使用浏览器扩展导出Netscape格式文件
#   - 安装扩展: Get cookies.txt LOCALLY
#   - 访问 youtube.com 并登录
#   - 导出为 youtube_cookies.txt
#   - 配置文件路径: YOUTUBE_COOKIE=/path/to/youtube_cookies.txt
# 方式2: 手动输入Cookie字符串（不推荐，太长）
#   - YOUTUBE_COOKIE="SID=xxx; HSID=yyy; ..."
# YOUTUBE_COOKIE=/app/cookies/youtube_cookies.txt
```

---

## 🎯 功能说明

### 核心功能（开箱即用）✅
1. **20+平台解析** - 抖音、B站、YouTube、TikTok、小红书、Twitter等
2. **命令模式** - `/parse <链接>` 手动解析
3. **自动监听模式** - 群组中自动检测链接并解析
4. **权限控制** - 整合到白名单系统
5. **管理面板** - `/admin` 中管理自动解析

### 高级功能（可选启用）⭐

#### 1. **AI总结功能** 📝
自动生成内容摘要，提取核心要点。

**启用方法**：
```env
ENABLE_AI_SUMMARY=true
AI_SUMMARY_MODEL=gpt-5-mini
```

**要求**：需要配置 `OPENAI_API_KEY`（你已有）

**效果**：解析后会在描述下方显示AI生成的50字摘要

---

#### 2. **视频分割功能** ✂️
自动分割大视频（>50MB）为多个片段。

**启用方法**：
```env
ENABLE_VIDEO_SPLIT=true
VIDEO_SPLIT_SIZE=45         # 每段45MB
FFMPEG_PATH=ffmpeg          # 确保FFmpeg在PATH中
```

**要求**：需要安装 FFmpeg
```bash
# Windows (Chocolatey)
choco install ffmpeg

# macOS
brew install ffmpeg

# Linux
apt-get install ffmpeg
```

**效果**：大视频会自动分割为多个片段逐个发送

---

#### 3. **图床上传功能** 📤
将大文件上传到图床，生成永久链接。

**启用方法**：
```env
ENABLE_IMAGE_HOST=true
IMAGE_HOST_SERVICE=catbox    # 或 litterbox, zioooo
```

**支持的图床**：
- **Catbox** - 永久存储，无需注册
- **Litterbox** - 72小时临时存储
- **Zio.ooo** - 需要配置 `ZIOOOO_STORAGE_ID`

**效果**：视频>50MB且分割失败时，自动上传到图床并发送链接

---

#### 4. **Telegraph发布功能** 📰
将长图文内容发布到Telegraph。

**启用方法**：
```env
ENABLE_TELEGRAPH=true
TELEGRAPH_AUTHOR=DomoBot
```

**效果**：图文内容会生成Telegraph页面链接（功能待完善）

---

#### 5. **语音转录功能** 🎤
将视频音频转录为文字。

**启用方法**：
```env
ENABLE_TRANSCRIPTION=true
TRANSCRIPTION_PROVIDER=openai
```

**支持的服务**：
- **OpenAI Whisper** - 最准确，需要 API 密钥
- **Azure Speech** - 企业级，需要 Azure 订阅
- **FastWhisper** - 本地运行，需要安装 `faster-whisper`

**效果**：视频发送时会附带转录文字（限制300字）

---

#### 6. **平台Cookie配置** 🍪
某些平台需要登录才能访问完整内容。

**配置方法**：
```env
# Twitter Cookie（必需，否则无法解析某些内容）
TWITTER_COOKIE=auth_token=xxx; ct0=xxx

# Instagram Cookie（可选）
INSTAGRAM_COOKIE=sessionid=xxx

# YouTube Cookie（推荐 - 帮助yt-dlp解析元数据）
YOUTUBE_COOKIE=/path/to/youtube_cookies.txt
```

**如何获取Cookie**：
1. 浏览器登录对应平台
2. 打开开发者工具（F12）
3. 进入 Application/Storage → Cookies
4. 复制需要的Cookie值

**YouTube Cookie特殊说明**：
- 推荐使用浏览器扩展 "Get cookies.txt LOCALLY" 导出Netscape格式
- Cookie文件帮助yt-dlp解析视频元数据，绕过登录验证
- Docker环境需在 docker-compose.yml 中挂载文件

---

#### 7. **YouTube OAuth认证** 🔐
使用Google账号认证绕过YouTube bot检测，替代昂贵的代理方案。

**⚠️ 重要提示**：
- 使用OAuth有封号风险，建议使用专门的Google账号
- OAuth免费但需要Google账号
- 优先级：OAuth > Cookie > Proxy

**配置步骤**：

1. **本地生成OAuth Token**：
```bash
# 安装 pytubefix
pip install pytubefix

# 运行生成脚本
python -c "from pytubefix import YouTube; yt=YouTube('https://youtube.com/watch?v=dQw4w9WgXcQ', use_oauth=True, allow_oauth_cache=True, token_file='youtube_oauth_token.json'); print(yt.title)"
```

2. **完成Google授权**：
   - 脚本会显示设备码（如：BPD-JYY-DYJL）
   - 浏览器打开 https://www.google.com/device
   - 输入设备码并用Google账号授权
   - 完成后在终端按回车

3. **部署到服务器**：
```env
# .env 文件配置
YOUTUBE_OAUTH_TOKEN=/app/youtube_oauth_token.json
```

4. **Docker配置**（在 docker-compose.yml 添加）：
```yaml
volumes:
  - ./youtube_oauth_token.json:/app/youtube_oauth_token.json
```

**工作原理**：
- pytubefix使用 `client='WEB'` 自动生成 po_token 绕过bot检测
- OAuth token提供额外的Google账号认证
- Token文件可重复使用，无需每次授权
- 服务器端使用token文件，无需浏览器交互

---

#### 8. **YouTube专用代理** 🌐
针对YouTube的bot检测问题，使用专用代理进行解析和下载。

**启用方法**：
```env
# YouTube专用代理（优先级高于全局代理）
YOUTUBE_PROXY=http://your-proxy:port
```

**支持的代理协议**：
- HTTP: `http://proxy:port`
- HTTPS: `https://proxy:port`
- SOCKS5: `socks5://proxy:port`

**使用场景**：
- YouTube bot检测严格时使用
- 国内服务器访问YouTube
- OAuth/Cookie失效时的备选方案

**优先级**：`YOUTUBE_PROXY` > `PARSER_PROXY`（全局代理）

---

#### 9. **TikHub API集成** 🚀
使用TikHub API解析TikTok、抖音、小红书视频，提供稳定的备选方案。

**启用方法**：
```env
# TikHub API密钥
TIKHUB_API_KEY=your_tikhub_api_key_here
```

**获取API密钥**：
1. 访问 https://api.tikhub.io
2. 注册账号并获取API密钥
3. 配置到 `.env` 文件

**支持的平台**：
- ✅ **TikTok** (国际版抖音) - 主要解析方式，官方ParseHub不支持
- ✅ **Douyin** (抖音) - 当官方ParseHub失败时的备选方案
- ✅ **XHS** (小红书) - 当官方ParseHub失败时的备选方案
- ❌ **不支持YouTube** - YouTube使用yt-dlp + Cookie/OAuth/Proxy方案

**工作机制**：
- TikTok：优先使用TikHub API（官方不支持），支持视频和图集
- Douyin/小红书：先尝试官方ParseHub，失败后fallback到TikHub
- 稳定性高，成功率接近100%
- 无需代理、Cookie或OAuth

**费用**：
- 付费API服务，具体价格见官网
- 适合对TikTok解析有需求的场景

---

### 配置优先级说明

**代理配置**：
- 不配置 = 不使用代理（国外服务器推荐）
- 配置全局代理 (`PARSER_PROXY`) = 所有平台使用
- 配置YouTube专用代理 (`YOUTUBE_PROXY`) = 仅YouTube使用，优先级高于全局代理
- 平台Cookie + 代理 = 最佳效果

**YouTube解析优先级**：
1. **OAuth Token** (`YOUTUBE_OAUTH_TOKEN`) - 免费，需Google账号，有封号风险
2. **Cookie文件** (`YOUTUBE_COOKIE`) - 免费，需手动导出，定期过期
3. **YouTube代理** (`YOUTUBE_PROXY`) - 付费代理，稳定但需成本
4. **全局代理** (`PARSER_PROXY`) - 最后选择

**TikTok/Douyin/小红书解析优先级**：
1. **TikHub API** (`TIKHUB_API_KEY`) - TikTok主要方案，Douyin/XHS备选方案
2. **官方ParseHub解析** - Douyin/XHS优先使用，免费
3. **全局代理** (`PARSER_PROXY`) - 辅助所有平台

**功能开关**：
- 所有高级功能默认 **禁用**
- 按需启用，不影响核心功能
- 某些功能有依赖（如FFmpeg）

---

## 📦 安装依赖

```bash
pip install -r requirements.txt
```

新增的依赖包（已自动添加到 requirements.txt）：

**核心依赖**（必需）：
- `parsehub>=1.5.10` - 社交媒体聚合解析器（支持20+平台）
- `pillow>=12.1.0` - 图像处理库
- `pillow-heif>=1.1.1` - HEIF/HEIC 图片格式支持
- `lxml-html-clean>=0.4.3` - HTML 清理工具
- `markdown>=3.10` - Markdown 转换器
- `pyyaml>=6.0.3` - YAML配置文件解析
- `tenacity>=9.1.2` - 重试机制（用于图床上传）

**可选依赖**（按需安装）：
- `faster-whisper` - 本地语音转录（如果使用 FastWhisper）
- `azure-cognitiveservices-speech` - Azure语音转录（如果使用 Azure）

---

## 🚀 使用指南

### 1. 基础命令（所有用户）

#### 查看支持的平台
```
/platforms
```

返回所有支持的20+平台列表。

### 2. 解析命令（白名单用户）

#### 手动解析链接
```
/parse https://www.douyin.com/video/xxxxx
```

#### 回复消息解析
```
# 回复一条包含链接的消息，然后发送：
/parse
```

### 3. 管理员功能

#### 打开管理面板
```
/admin
```

在管理面板中，选择 **📱 社交解析管理** 进入配置界面。

#### 配置步骤：

1. **选择群组**：
   - 从白名单群组列表中选择
   - 或点击"🔍 输入群组ID"手动输入

2. **启用/禁用自动解析**：
   - 点击"✅ 启用自动解析"开启群组自动监听
   - 点击"❌ 禁用自动解析"关闭群组自动监听

3. **切换群组**：
   - 点击"🔄 切换群组"选择其他群组

---

## 📱 支持的平台列表

| 平台类别 | 支持的平台 |
|---------|-----------|
| **中国视频** | 抖音、快手、B站 |
| **国际视频** | YouTube、YouTube Music、TikTok |
| **社交媒体** | Twitter/X、Instagram、Facebook、微博 |
| **内容平台** | 小红书、百度贴吧、知乎 |
| **其他** | 更多平台持续更新... |

---

## 🔧 工作原理

### 命令模式
用户主动使用 `/parse` 命令解析链接，适合私聊和所有场景。

### 自动监听模式
1. 管理员在群组中启用自动解析
2. Bot监听群组中的所有文本和图片描述消息
3. 检测到支持的平台链接时自动解析
4. 解析完成后发送媒体内容

### 权限控制
- `/platforms` - 所有用户可用
- `/parse` - 白名单用户可用
- 自动解析 - 仅在启用的白名单群组中工作
- 管理面板 - 仅管理员可用

---

## 📊 架构说明

### 新增文件

1. **`utils/parse_hub_adapter.py`**
   - ParseHub 适配器，将 Pyrogram 框架适配到 python-telegram-bot
   - 处理URL检测、解析、下载、缓存等核心逻辑
   - 管理群组自动解析配置

2. **`commands/social_parser.py`**
   - 解析命令模块
   - 实现 `/parse` 和 `/platforms` 命令
   - 处理媒体发送逻辑（视频、图片、混合媒体）

3. **`handlers/auto_parse_handler.py`**
   - 自动解析处理器
   - 监听群组消息，自动检测并解析链接
   - 只在启用的群组中工作

4. **`database/init.sql`** (已更新)
   - 添加了 `social_parser_config` 表
   - 添加了 `social_parser_stats` 表

5. **`commands/admin_commands.py`** (已更新)
   - 添加了社交解析管理面板
   - 新增状态：`SOCIAL_PARSER_PANEL`, `AWAITING_SOCIAL_PARSER_GROUP_ID`

6. **`main.py`** (已更新)
   - 初始化 ParseHub 适配器
   - 注册自动解析处理器
   - 注入依赖到命令模块

---

## 🐛 故障排除

### 1. 解析失败

**问题**：提示"未检测到支持的平台链接"

**解决**：
- 检查链接是否完整
- 确认平台在支持列表中
- 使用 `/platforms` 查看支持的平台

### 2. 自动解析不工作

**问题**：群组中发送链接，Bot没有反应

**检查清单**：
- ✅ 群组是否在白名单中？
- ✅ 自动解析是否已启用？（通过 `/admin` 检查）
- ✅ Bot是否有发送消息的权限？
- ✅ 链接是否是支持的平台？

### 3. 文件上传失败

**问题**：提示"❌ 处理失败"或视频无法发送

**原因**：
- Telegram 限制视频文件大小 50MB
- 网络问题导致下载失败
- Telegram API超时（图片已上传但响应超时）

**解决**：
- Bot会自动处理大文件，发送缩略图和链接
- 检查服务器网络连接
- 查看日志文件：`logs/bot.log`
- 已增加API超时时间到60秒处理慢速网络

### 3.5. 临时文件占用空间

**问题**：担心临时文件累积占用磁盘空间

**解决**：Bot已内置自动清理机制
- ✅ 每天UTC 4:00自动清理超过24小时的临时文件
- ✅ 清理目录：`/tmp/domobot_parse/`
- ✅ 无需手动干预

**手动清理**（如需立即清理）：
```bash
# Linux/Docker
rm -rf /tmp/domobot_parse/*

# 或使用Python清理函数
python -c "from utils.parse_hub_adapter import ParseHubAdapter; import asyncio; asyncio.run(ParseHubAdapter().cleanup_temp_files(older_than_hours=0))"
```

### 4. 数据库错误

**问题**：启动时提示表不存在

**解决**：
```bash
# 确认数据库表已创建
mysql -u your_user -p your_database -e "SHOW TABLES LIKE 'social_parser%';"

# 如果表不存在，运行初始化脚本
mysql -u your_user -p your_database < database/init.sql
```

---

## 📈 性能优化建议

### 1. 缓存配置

ParseHub 适配器内置24小时缓存，相同链接在缓存期内会直接返回结果。

### 2. 临时文件自动清理 ✅

Bot已内置自动清理机制，无需手动配置：

**自动清理任务**：
- ⏰ 每天UTC 4:00自动执行
- 🗑️ 清理超过24小时的临时文件
- 📁 清理目录：`/tmp/domobot_parse/`
- 🔄 自动重复，无需干预

**手动调整清理时间**（可选）：
```python
# 在 main.py 中修改清理间隔
await parse_adapter.cleanup_temp_files(older_than_hours=12)  # 改为12小时
```

**查看清理日志**：
```bash
# 查看定时任务日志
grep "临时文件清理" logs/bot.log
```

### 3. 数据库维护

定期清理旧的统计数据：

```sql
-- 清理90天前的统计记录
DELETE FROM social_parser_stats WHERE created_at < DATE_SUB(NOW(), INTERVAL 90 DAY);
```

---

## 🔐 安全建议

1. **只在可信群组启用自动解析**
2. **定期检查解析统计**，发现异常及时禁用
3. **限制Bot的文件发送权限**，避免滥用
4. **配置代理**（如需要）：
   ```python
   # 在 parse_url 调用时传入代理
   result, platform, parse_time = await adapter.parse_url(
       text, user_id, group_id,
       proxy="http://127.0.0.1:7890"  # 可选
   )
   ```

---

## 📝 更新日志

### v1.0.0 (2026-01-16)

**核心功能**：
- ✅ 支持20+社交媒体平台解析
- ✅ 命令模式 (`/parse`)
- ✅ 自动监听模式（群组自动检测）
- ✅ 管理员面板整合 (`/admin`)
- ✅ 权限系统整合（白名单控制）
- ✅ Redis缓存（24小时）
- ✅ 解析统计记录

**高级功能**：
- ✅ AI总结功能（使用gpt-5-mini）
- ✅ 视频分割功能（FFmpeg）
- ✅ 图床上传功能（Catbox/Litterbox/Zio.ooo）
- ✅ Telegraph发布功能
- ✅ 语音转录功能（OpenAI/Azure/FastWhisper）
- ✅ 平台Cookie配置（Twitter/Instagram/Facebook）
- ✅ 代理配置（全局/平台特定）

**技术亮点**：
- 所有配置集中在 `.env` 文件
- 模块化设计，易于扩展
- 完整的错误处理和日志
- 支持大文件处理（分割/图床）
- 异步处理，高性能

---

## 🤝 贡献

如遇到问题或有改进建议，欢迎提交 Issue 或 Pull Request。

---

## 📄 相关链接

- [ParseHub 项目](https://github.com/z-mio/ParseHub)
- [python-telegram-bot 文档](https://docs.python-telegram-bot.org/)
- [Telegram Bot API](https://core.telegram.org/bots/api)

---

## 🎉 完成！

所有功能已整合完成。运行 `python main.py` 启动Bot，开始使用社交媒体解析功能！
