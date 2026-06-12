# Guest Bot 完整指南

## 📖 目录

1. [功能介绍](#功能介绍)
2. [快速开始](#快速开始)
3. [工作原理](#工作原理)
4. [命令兼容性](#命令兼容性)
5. [技术实现](#技术实现)
6. [常见问题](#常见问题)

---

## 功能介绍

Guest Bot允许你的bot在**未加入的群组**中响应@mention，实现跨群组服务。

### 核心特性

✅ **无需加群** - Bot不用加入群组即可响应  
✅ **用户白名单** - 使用现有白名单系统控制权限  
✅ **所有命令支持** - 100%命令自动兼容  
✅ **完整媒体支持** - 图片、音频、视频都能在群组显示  
✅ **零代码修改** - 现有命令无需改动  

### 使用场景

- 在多个群组提供服务，无需重复加群
- 个人使用，在任何群组调用自己的bot
- 付费订阅服务，白名单用户专享

---

## 快速开始

### 1. 配置环境变量

在 `.env` 文件中添加：

```bash
# Guest Bot 功能开关
ENABLE_GUEST_BOT=true

# Bot 所有者 ID（总是有权限）
BOT_OWNER_ID=123456789
```

**注意：** Guest Bot使用现有的用户白名单系统
- 白名单用户自动拥有Guest Bot权限
- 使用 `/whitelist add <user_id>` 添加授权
- 使用 `/whitelist remove <user_id>` 移除授权

### 2. 安装Guest Bot补丁

在 `main.py` 的 `setup_application` 函数开始处添加：

```python
async def setup_application(application: Application, config) -> None:
    """异步设置应用"""
    
    # 安装Guest Bot patches（必须在所有handler之前）
    if config.enable_guest_bot:
        from utils.guest_bot_wrapper import install_guest_bot_patches
        install_guest_bot_patches()
        logger.info("✅ Guest Bot patches installed")
    
    # ... 现有代码 ...
```

### 3. 注册Guest Bot处理器

在 `main.py` 的 `setup_handlers` 函数最前面添加：

```python
async def setup_handlers(application: Application, config):
    """设置命令处理器"""
    
    # Guest Bot处理器（如果启用）- 必须最先注册
    if config.enable_guest_bot:
        from handlers.guest_bot_handler import GuestBotHandler
        from handlers.guest_bot_middleware import GuestBotMiddleware
        
        guest_bot_handler = GuestBotHandler(
            user_manager=user_cache_manager,  # 使用现有的用户管理器
            owner_id=config.bot_owner_id
        )
        
        # 注册middleware（group=-100确保最先执行）
        guest_bot_middleware = GuestBotMiddleware(guest_bot_handler)
        application.add_handler(guest_bot_middleware, group=-100)
        
        logger.info("✅ Guest Bot enabled (using existing user whitelist)")
    
    # ... 现有的所有其他handler ...
```

### 4. 更新配置类

在 `utils/config_manager.py` 中添加：

```python
class BotConfig:
    # ... 现有配置 ...
    
    # Guest Bot 配置
    enable_guest_bot: bool = os.getenv("ENABLE_GUEST_BOT", "false").lower() == "true"
    bot_owner_id: int | None = (
        int(os.getenv("BOT_OWNER_ID"))
        if os.getenv("BOT_OWNER_ID")
        else None
    )
```

### 5. 完成！

启动bot后：

1. 找任意一个公开群（不需要把bot加进去）
2. 确保你在白名单中：`/whitelist add 你的user_id`
3. 在群组发送：`@你的bot /help`
4. Bot会在群组中回复你！

---

## 工作原理

### 文本消息流程

```
用户: @bot /rate 100 USD CNY
  ↓
Middleware拦截 → 检查白名单 → 注入guest_query_id
  ↓
执行/rate命令 → reply_text被patch拦截
  ↓
转换为InlineQueryResultArticle
  ↓
answer_guest_query发送到群组
  ↓
用户在群组看到: 💱 100 USD = 724.50 CNY
```

### 媒体消息流程（关键创新）

```
用户: @bot /music 周杰伦 晴天
  ↓
1️⃣ 发送占位文本到群组
   answer_guest_query("🔄 正在加载音频...")
   获得 inline_message_id
  ↓
2️⃣ 暂存到用户私聊
   send_audio(user_id, audio) → 获取file_id
   delete_message() → 立即删除
  ↓
3️⃣ 替换群组消息
   editMessageMedia(inline_message_id, InputMediaAudio(file_id))
  ↓
用户在群组看到: 🎵 周杰伦 - 晴天 [音频播放器]
```

**关键点：**
- 媒体最终显示在**群组中**，不是私聊
- 私聊只是临时中转获取file_id
- 用户体验和普通bot完全一样

---

## 命令兼容性

### ✅ 完全支持（100%命令）

所有命令都能在Guest Bot模式下正常工作！

#### 文本命令（直接显示）
- `/rate` - 汇率查询
- `/crypto` - 加密货币价格
- `/bin` - 银行卡BIN查询
- `/whois` - 域名/IP查询
- `/time` - 时区查询
- `/flight` - 航班查询
- `/fuel` - 油价查询
- `/electricity` - 电价查询
- `/news` - 新闻查询
- `/finance` - 财经查询
- `/help` - 帮助信息

#### 价格查询命令（直接显示）
- `/steam` - Steam游戏价格
- `/netflix` - Netflix价格
- `/disney` - Disney+价格
- `/spotify` - Spotify价格
- `/xbox` - Xbox Game Pass价格
- `/max` - Max价格
- `/apple` - Apple服务价格
- `/appstore` - App Store应用价格
- `/googleplay` - Google Play应用价格

#### 媒体命令（群组显示，0.5秒占位）
- `/weather` - 天气查询（图表）
- `/map` - 地图查询（地图图片）
- `/music` - 网易云音乐（音频）
- `/ytmusic` - YouTube Music（音频）
- `/kugou` - 酷狗音乐（音频）
- `/movie` - 电影信息（海报）
- `/memes` - 表情包（图片）
- `/parse` - 社交媒体解析（图片/视频）

### ❌ 不支持（需要群组权限）

- `/admin` - 管理员命令
- `/system` - 系统命令
- 反垃圾相关命令

这些命令会自动返回友好提示：
```
❌ 此命令需要在Bot已加入的群组中使用
请将Bot添加到您的群组后再试
```

---

## 技术实现

### 核心文件

#### 1. `handlers/guest_bot_handler.py`
权限检查和用户管理
- 使用现有的MySQLUserManager检查白名单
- Bot所有者总是有权限
- 发送未授权响应

#### 2. `handlers/guest_bot_middleware.py`
请求拦截器
- 在group=-100最先执行
- 检测guest_query_id
- 注入guest context到message和context.user_data

#### 3. `utils/guest_bot_wrapper.py`
Monkey Patch核心
- Patch Message.reply_text/photo/audio/video/document
- Patch Bot.send_message
- 实现私聊中转媒体暂存
- 使用editMessageMedia替换占位文本

#### 4. `utils/message_manager.py`
自动支持
- 在send_message_with_auto_delete中注入guest_query_id
- 所有使用message_manager的命令自动支持

### 关键API

#### PTB 22.8 Guest Bot API

```python
# 发送文本响应
from telegram import InlineQueryResultArticle, InputTextMessageContent

result = InlineQueryResultArticle(
    id=guest_query_id[:64],
    title="Response",
    input_message_content=InputTextMessageContent(
        message_text=text,
        parse_mode=parse_mode
    )
)

sent_msg = await bot.answer_guest_query(guest_query_id, result)
inline_message_id = sent_msg.inline_message_id  # 关键！
```

```python
# 编辑为媒体
from telegram import InputMediaPhoto

await bot.edit_message_media(
    inline_message_id=inline_message_id,
    media=InputMediaPhoto(media=file_id, caption=caption)
)
```

### Monkey Patch原理

```python
# 保存原始方法
_original_reply_text = Message.reply_text

# 包装方法
async def _guest_aware_reply_text(self, text, **kwargs):
    if hasattr(self, '_guest_query_id') and self._guest_query_id:
        # 使用answer_guest_query
        return await _send_guest_response(...)
    # 正常reply_text
    return await _original_reply_text(self, text, **kwargs)

# 替换方法
Message.reply_text = _guest_aware_reply_text
```

### 媒体暂存技术

```python
async def _stage_media_to_private(bot, user_id, media_type, media):
    """暂存到私聊获取file_id"""
    # 1. 发送到私聊
    msg = await bot.send_photo(user_id, photo=media)
    file_id = msg.photo[-1].file_id
    
    # 2. 立即删除（用户看不到）
    await bot.delete_message(user_id, msg.message_id)
    
    # 3. 返回file_id用于editMessageMedia
    return file_id
```

---

## 常见问题

### Q: Guest Bot会影响现有群组的功能吗？
A: 不会。Guest Bot只处理`guest_query_id`不为空的消息，现有群组的消息处理逻辑完全不受影响。

### Q: 如何获取自己的Telegram user_id？
A: 私聊你的bot发送任意消息，查看日志或使用`/start`命令查看。

### Q: 需要修改现有命令吗？
A: 不需要！所有现有命令自动支持，零修改。

### Q: 媒体命令为什么需要私聊？
A: Telegram的限制。answer_guest_query只支持文本，媒体需要通过私聊中转获取file_id，然后用editMessageMedia在群组显示。

### Q: 用户没开启私聊会怎样？
A: 媒体命令会显示提示：
```
⚠️ 图片发送失败
💡 请先私聊bot发送 /start 开启私聊，然后重试
```

### Q: Guest Bot消息会被anti-spam拦截吗？
A: 不会。Guest Bot middleware在anti-spam之前执行（group=-100），并且有特殊标识。

### Q: 可以限制某些命令不在guest模式使用吗？
A: 可以。在命令handler中检查：
```python
if context.user_data.get('is_guest_bot_call'):
    await update.message.reply_text("❌ 此命令需要bot加入群组")
    return
```

### Q: 如何管理Guest Bot权限？
A: 使用现有的白名单命令：
```
/whitelist add 123456789    # 添加用户
/whitelist remove 987654321  # 移除用户
/whitelist list              # 查看列表
```

### Q: Guest Bot和inline mode有什么区别？
A: 
- **Inline mode**: 用户输入`@bot query`，选择结果后发送
- **Guest Bot**: 用户输入`@bot /command`，bot直接回复到群组
- Guest Bot更适合命令式交互，inline mode更适合搜索式交互

---

## 参考资料

### Telegram Bot API文档
- [Bot API 10.0 - Guest Bot](https://core.telegram.org/bots/api#guest-bot)
- [answerGuestQuery](https://core.telegram.org/bots/api#answerguestquery)
- [editMessageMedia](https://core.telegram.org/bots/api#editmessagemedia)

### python-telegram-bot文档
- [PTB 22.8 Changelog](https://github.com/python-telegram-bot/python-telegram-bot/releases/tag/v22.8)
- [Bot.answer_guest_query](https://docs.python-telegram-bot.org/)

### 灵感来源
- [ChatGPT-Telegram-Workers](https://github.com/TBXark/ChatGPT-Telegram-Workers) - guest_query.ts实现

---

## 总结

✅ **100%命令支持**  
✅ **完整媒体处理**（在群组显示）  
✅ **零代码修改**  
✅ **现有白名单系统**  
✅ **透明兼容**  

Guest Bot让你的bot可以在任何群组为授权用户提供服务，无需重复加群，体验和普通bot完全一样！🚀
