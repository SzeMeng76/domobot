# Reddit 功能集成指南

## ✨ 功能特性

- 📱 解析 Reddit 帖子（文本、图片、视频、图集）
- 💬 显示 Top 评论
- 🤖 AI 总结功能（中文翻译 + 内容总结）
- 🔘 Inline 按钮切换显示/隐藏 AI 总结
- 📦 Redis 缓存（避免重复请求）

## 📦 已创建的文件

1. `utils/reddit_client.py` - Reddit API 客户端
2. `commands/reddit_command.py` - Reddit 命令模块
3. `handlers/reddit_ai_summary_callback_handler.py` - AI 总结 callback handler
4. `test_reddit.py` - 测试脚本

## 🔧 集成步骤

### 1. 在 `main.py` 中初始化 Reddit 客户端

在 `main()` 函数中添加：

```python
# 初始化 Reddit 客户端
from utils.reddit_client import RedditClient
reddit_client = RedditClient(
    client_id=config.reddit_client_id,
    client_secret=config.reddit_client_secret
)
logger.info("✅ Reddit 客户端已初始化")

# 设置 Reddit 客户端到命令模块
from commands import reddit_command
reddit_command.set_reddit_client(reddit_client)
reddit_command.set_cache_manager(cache_manager)

# 如果启用了 AI 总结，设置 AI 总结器
if config.enable_ai_summary:
    from utils.ai_summary import AISummarizer
    ai_summarizer = AISummarizer(
        api_key=config.openai_api_key,
        base_url=config.openai_base_url or None,
        model=config.ai_summary_model or "gpt-5-mini"
    )
    reddit_command.set_ai_summarizer(ai_summarizer)
    logger.info("✅ Reddit AI 总结已启用")

# 注册 Reddit AI 总结 callback handler
from handlers import reddit_ai_summary_callback_handler
reddit_ai_summary_callback_handler.set_reddit_client(reddit_client)
reddit_ai_summary_callback_handler.set_cache_manager(cache_manager)
if config.enable_ai_summary:
    reddit_ai_summary_callback_handler.set_ai_summarizer(ai_summarizer)

application.add_handler(reddit_ai_summary_callback_handler.get_reddit_ai_summary_handler())
logger.info("✅ Reddit AI 总结 callback handler 已注册")
```

### 2. 在 `.env` 中添加配置

```env
# Reddit API 凭据
REDDIT_CLIENT_ID=5WMgPk_kkBlnsPYGW4pvhg
REDDIT_CLIENT_SECRET=FPj28pCIS8WYhMv72XQn92HlLvbafA
```

### 3. 在 `utils/config_manager.py` 中添加配置项

在 `BotConfig` 类中添加：

```python
# Reddit API
self.reddit_client_id = os.getenv("REDDIT_CLIENT_ID", "")
self.reddit_client_secret = os.getenv("REDDIT_CLIENT_SECRET", "")
```

## 📝 使用方法

### 基础命令

```
/reddit <Reddit链接>
```

### 示例

```
/reddit https://www.reddit.com/r/python/comments/xxx/
```

### AI 总结

发送帖子后，点击 "📝 AI总结" 按钮即可生成中文总结。

## 🎯 AI 总结特点

- 🇨🇳 自动翻译英文内容为中文
- 📊 总结帖子核心内容和关键要点
- 💬 总结 Top 评论观点
- 🎨 使用 HTML 格式，支持粗体、斜体、代码等
- 📦 缓存总结结果（24小时）

## 🧪 测试

运行测试脚本：

```bash
python test_reddit.py
```

## 📋 支持的内容类型

- ✅ 文本帖子（selftext）
- ✅ 单张图片
- ✅ 图集（最多10张）
- ✅ 视频链接（暂不支持下载）
- ✅ 评论（Top 5）

## ⚠️ 注意事项

1. **API 限制**：Reddit API 有速率限制（60请求/分钟）
2. **视频处理**：Reddit 视频暂不支持下载，只显示链接
3. **权限设置**：默认为 `Permission.USER`（白名单用户）
4. **缓存时间**：帖子数据和 AI 总结缓存 24 小时

## 🔍 调试

查看日志：

```python
logger.info(f"Reddit 帖子: {post.title}")
logger.info(f"AI 总结缓存: cache:reddit:reddit_ai_summary:{url_hash}")
```

## 📚 参考

- Reddit API 文档: https://www.reddit.com/dev/api
- MCP Reddit Server: https://github.com/SzeMeng76/mcp-server-reddit-ts
