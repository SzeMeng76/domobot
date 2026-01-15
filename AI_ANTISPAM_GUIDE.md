# AI反垃圾功能部署和使用指南

## 功能概述

本机器人集成了基于 OpenAI GPT 的智能反垃圾功能，可以自动检测和封禁群组中的垃圾广告用户。

### 核心特点

✅ **智能检测**: 使用 GPT-5-mini 模型，理解语义，不依赖关键词
✅ **私聊管理**: 在私聊中通过输入群组ID管理，避免在群组中暴露操作
✅ **多群组支持**: 为不同群组单独开启/关闭，灵活控制
✅ **成本优化**: 只检测新用户（入群<3天或发言<3次），老用户自动跳过
✅ **误报纠正**: 管理员可点击"解禁"按钮快速纠正误封
✅ **实时统计**: 查看检测次数、封禁数、误报率等数据

---

## 部署步骤

### 方式一：Docker Compose 部署（推荐）

本项目使用 GitHub Actions 自动构建 Docker 镜像，支持一键部署。

#### 1. 准备配置文件

编辑项目根目录的 `.env` 文件，添加以下配置：

```env
# Telegram Bot 基础配置
BOT_TOKEN=你的机器人Token
SUPER_ADMIN_ID=你的Telegram用户ID

# 数据库配置（使用 docker-compose 时保持默认即可）
DB_HOST=mysql
DB_PORT=3306
DB_NAME=domobot
DB_USER=root
DB_PASSWORD=your_strong_password_here

# Redis配置（使用 docker-compose 时保持默认即可）
REDIS_HOST=redis
REDIS_PORT=6379

# OpenAI API配置（必需）
OPENAI_API_KEY=sk-your-api-key-here
OPENAI_MODEL=gpt-5-mini
# OPENAI_BASE_URL=https://your-proxy.com/v1  # 可选，国内代理

# AI反垃圾功能开关
ANTI_SPAM_ENABLED=true
ANTI_SPAM_DEFAULT_THRESHOLD=80
```

**获取 OpenAI API Key:**
1. 访问 https://platform.openai.com/api-keys
2. 登录或注册账号
3. 点击 "Create new secret key" 创建密钥
4. 复制密钥并粘贴到 `.env` 文件中

#### 2. 启动服务

```bash
# 拉取最新镜像并启动所有服务（MySQL + Redis + Bot）
docker-compose pull
docker-compose up -d

# 查看日志
docker-compose logs -f appbot
```

启动日志中应该看到：
```
🛡️ 初始化AI反垃圾功能...
✅ AI反垃圾功能初始化完成
✅ AI反垃圾处理器已注册
```

#### 3. 数据库自动初始化

首次启动时，MySQL 容器会自动执行 `database/init.sql` 初始化脚本，创建以下表：
- `users`, `admin_permissions`, `super_admins` 等基础表
- `anti_spam_config`: 群组配置表
- `anti_spam_user_info`: 用户信息表
- `anti_spam_logs`: 检测日志表
- `anti_spam_stats`: 统计数据表

**⚠️ 重要：如果您是从旧版本升级**

如果您的数据库已经存在（旧版本升级），MySQL 不会重新执行 `init.sql`。您需要手动创建 anti_spam 表：

```bash
# 方案一：直接在容器中执行 SQL（推荐，不影响现有数据）
docker-compose exec mysql mysql -u root -p

# 输入密码后，执行以下 SQL：
USE bot;

CREATE TABLE IF NOT EXISTS anti_spam_config (
    group_id BIGINT PRIMARY KEY COMMENT '群组ID',
    enabled BOOLEAN DEFAULT FALSE COMMENT '是否启用反垃圾功能',
    joined_time_threshold INT DEFAULT 3 COMMENT '新用户判定阈值（天数）',
    speech_count_threshold INT DEFAULT 3 COMMENT '新用户判定阈值（发言次数）',
    verification_times_threshold INT DEFAULT 1 COMMENT '需要验证的次数',
    spam_score_threshold INT DEFAULT 80 COMMENT '垃圾分数阈值（0-100）',
    auto_delete_delay INT DEFAULT 120 COMMENT '自动删除通知延迟（秒）',
    check_text BOOLEAN DEFAULT TRUE COMMENT '检测文本消息',
    check_photo BOOLEAN DEFAULT TRUE COMMENT '检测图片消息',
    check_sticker BOOLEAN DEFAULT FALSE COMMENT '检测贴纸消息',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='反垃圾配置表';

CREATE TABLE IF NOT EXISTS anti_spam_user_info (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL COMMENT '用户ID',
    group_id BIGINT NOT NULL COMMENT '群组ID',
    username VARCHAR(255) COMMENT '用户名',
    first_name VARCHAR(255) COMMENT '名字',
    joined_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '入群时间',
    number_of_speeches INT DEFAULT 0 COMMENT '发言次数',
    verification_times INT DEFAULT 0 COMMENT '已验证次数',
    is_verified BOOLEAN DEFAULT FALSE COMMENT '是否已通过验证',
    last_message_time TIMESTAMP NULL COMMENT '最后发言时间',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY unique_user_group (user_id, group_id),
    INDEX idx_user_id (user_id),
    INDEX idx_group_id (group_id),
    INDEX idx_is_verified (is_verified)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户反垃圾信息表';

CREATE TABLE IF NOT EXISTS anti_spam_logs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL COMMENT '用户ID',
    group_id BIGINT NOT NULL COMMENT '群组ID',
    username VARCHAR(255) COMMENT '用户名',
    message_type VARCHAR(20) COMMENT '消息类型: text, photo, sticker',
    message_text TEXT COMMENT '消息内容（文本）',
    spam_score INT COMMENT 'AI评分（0-100）',
    spam_reason TEXT COMMENT '判定原因',
    spam_mock_text TEXT COMMENT '讽刺评论',
    is_spam BOOLEAN DEFAULT FALSE COMMENT '是否为垃圾',
    is_banned BOOLEAN DEFAULT FALSE COMMENT '是否已封禁',
    detection_time_ms INT COMMENT '检测耗时（毫秒）',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_id (user_id),
    INDEX idx_group_id (group_id),
    INDEX idx_is_spam (is_spam),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='垃圾检测日志表';

CREATE TABLE IF NOT EXISTS anti_spam_stats (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    group_id BIGINT NOT NULL COMMENT '群组ID',
    date DATE NOT NULL COMMENT '统计日期',
    total_checks INT DEFAULT 0 COMMENT '总检测次数',
    spam_detected INT DEFAULT 0 COMMENT '检测到垃圾次数',
    users_banned INT DEFAULT 0 COMMENT '封禁用户数',
    false_positives INT DEFAULT 0 COMMENT '误报次数（管理员解禁）',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY unique_group_date (group_id, date),
    INDEX idx_group_id (group_id),
    INDEX idx_date (date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='反垃圾统计表';

exit;

# 方案二：使用 SQL 文件导入（会跳过已存在的表）
docker-compose exec mysql mysql -u root -p bot < database/init.sql

# 执行完成后重启机器人
docker-compose restart appbot
```

验证表已创建：
```bash
docker-compose exec mysql mysql -u root -p -e "USE bot; SHOW TABLES LIKE 'anti_spam%';"
```

#### 4. 更新到最新版本

```bash
# 停止服务
docker-compose down

# 拉取最新镜像
docker-compose pull

# 重新启动
docker-compose up -d
```

---

### 方式二：手动部署（开发环境）

如果不使用 Docker，可以手动部署：

#### 1. 安装依赖

```bash
pip install -r requirements.txt
```

#### 2. 初始化数据库

```bash
mysql -u root -p your_database < database/init.sql
```

#### 3. 配置环境变量

编辑 `.env` 文件（参考上面的配置）

#### 4. 启动机器人

```bash
python main.py
```

---

## 使用指南

### 管理员操作流程

#### 1. 打开管理面板
在与机器人的私聊中发送：
```
/admin
```

#### 2. 进入反垃圾管理
点击 **"🛡️ AI反垃圾管理"** 按钮

#### 3. 选择要管理的群组

**方式一：查看群组列表**
- 系统会显示所有白名单群组
- 选择一个群组进行管理

**方式二：输入群组ID**
- 点击 **"🔍 输入群组ID"** 按钮
- 输入群组ID（负数，例如：`-1001234567890`）

**如何获取群组ID？**
1. 在群组中发送任意消息
2. 转发该消息给 @userinfobot 或 @getidsbot
3. 机器人会回复群组ID

#### 4. 启用反垃圾功能
- 点击 **"✅ 启用"** 按钮
- 系统会显示"✅ 已成功启用"

#### 5. 查看统计数据
- 点击 **"📊 详细统计"** 查看：
  - 总检测次数
  - 检测到的垃圾消息数
  - 封禁用户数
  - 误报次数
  - 准确率
  - 每日详细数据

#### 6. 切换到其他群组
- 点击 **"🔄 切换群组"** 返回群组选择界面
- 选择其他群组进行管理

---

## 工作原理

### 检测流程

```
新用户加入群组
    ↓
系统记录入群时间
    ↓
用户发送消息
    ↓
增加发言计数
    ↓
判断是否需要检测
├─ 入群 < 3天？ → 需要检测
├─ 发言 < 3次？ → 需要检测
└─ 已验证通过？ → 跳过检测
    ↓
AI 分析消息
├─ 文本消息
└─ 图片消息（含OCR）
    ↓
评分判定
├─ 分数 ≥ 80 → 封禁用户
└─ 分数 < 80 → 标记已验证
    ↓
发送通知（带解禁按钮）
    ↓
2分钟后自动删除通知
```

### 检测策略

**新用户保护**（入群<3天或发言<3次）:
- 对短消息谨慎判断
- 降低误封率
- 只在明显垃圾时才判定

**老用户宽松**（入群≥3天且发言≥3次）:
- 自动跳过检测
- 节省 API 费用
- 避免误封活跃用户

### 垃圾特征识别

AI 会检测以下特征：
1. 虚假支付机构、银行卡信息
2. 诱导加入群组的链接
3. 非法支付、赌博、禁止物品
4. 非法服务（刷单、网赚等）
5. 使用谐音、错别字混淆的变体

---

## 配置说明

### 群组配置参数

可以通过数据库直接修改 `anti_spam_config` 表：

| 参数 | 说明 | 默认值 | 建议范围 |
|------|------|--------|----------|
| `enabled` | 是否启用 | false | true/false |
| `spam_score_threshold` | 垃圾分数阈值 | 80 | 80-90 |
| `joined_time_threshold` | 新用户天数 | 3 | 1-7天 |
| `speech_count_threshold` | 新用户发言数 | 3 | 1-10次 |
| `verification_times_threshold` | 需要验证次数 | 1 | 1-3次 |
| `auto_delete_delay` | 通知删除延迟 | 120 | 60-300秒 |
| `check_text` | 检测文本消息 | true | true/false |
| `check_photo` | 检测图片消息 | true | true/false |
| `check_sticker` | 检测贴纸消息 | false | true/false |

### 修改配置示例

```sql
-- 为群组 -1001234567890 调整阈值为85分
UPDATE anti_spam_config
SET spam_score_threshold = 85
WHERE group_id = -1001234567890;

-- 将新用户判定改为7天
UPDATE anti_spam_config
SET joined_time_threshold = 7
WHERE group_id = -1001234567890;

-- 禁用图片检测（节省成本）
UPDATE anti_spam_config
SET check_photo = FALSE
WHERE group_id = -1001234567890;
```

---

## 成本估算

### 按检测类型

- **文本检测**: ~$0.0002/次
- **图片检测**: ~$0.002/次

### 按群组规模

| 群组规模 | 每日新用户 | 每日消息 | 月度成本（仅文本） | 月度成本（含图片） |
|----------|------------|----------|-------------------|-------------------|
| 小型 | 5-10人 | 50条 | $0.3-0.6 | $3-6 |
| 中型 | 20-50人 | 200条 | $1.2-3 | $12-30 |
| 大型 | 100+人 | 500+条 | $3-10 | $30-100 |

**成本优化建议**：
1. 只对新用户检测（默认开启）
2. 禁用贴纸检测（默认禁用）
3. 对低活跃群组禁用图片检测
4. 提高分数阈值减少不必要的检测

---

## 误报处理

### 解禁被误封的用户

1. 群组中会显示封禁通知
2. 管理员点击 **"✅ 解禁此用户"** 按钮
3. 用户立即解封
4. 系统自动记录为误报
5. 误报数据会反映在统计中

### 调整策略减少误报

如果误报率 > 10%，建议：

1. **提高分数阈值**
   ```sql
   UPDATE anti_spam_config
   SET spam_score_threshold = 85  -- 从80提高到85
   WHERE group_id = -1001234567890;
   ```

2. **延长新用户判定时间**
   ```sql
   UPDATE anti_spam_config
   SET joined_time_threshold = 5  -- 从3天延长到5天
   WHERE group_id = -1001234567890;
   ```

3. **观察统计数据**
   - 定期检查误报率
   - 根据实际情况调整

---

## 机器人权限要求

确保机器人在群组中有以下权限：

✅ **必需权限**:
- 删除消息
- 封禁用户
- 查看成员列表

❌ **不需要的权限**:
- 钉选消息
- 邀请用户
- 更改群组信息

**如何设置权限？**
1. 打开群组设置
2. 点击"管理员"
3. 选择机器人
4. 勾选必需的权限

---

## 常见问题

### Q1: 启用后没有任何反应？

**检查步骤**:
1. 确认 `OPENAI_API_KEY` 已正确配置
2. 查看启动日志是否有 "✅ AI反垃圾功能初始化完成"
3. 确认群组已在白名单中
4. 确认机器人有足够权限

### Q2: 成本比预期高？

**优化方案**:
1. 禁用图片检测：文本检测成本仅为图片的1/10
2. 提高阈值：减少不必要的检测
3. 调整新用户判定：只检测最新的用户

### Q3: 出现误封怎么办？

**立即处理**:
1. 点击通知中的"解禁"按钮
2. 用户立即恢复正常

**长期优化**:
1. 查看统计数据中的误报率
2. 如果误报率 > 10%，提高阈值
3. 观察1-2天后再调整

### Q4: 如何查看某个群组的配置？

```sql
SELECT * FROM anti_spam_config
WHERE group_id = -1001234567890;
```

### Q5: 如何完全禁用某个群组的反垃圾功能？

在 /admin 面板中：
1. 选择该群组
2. 点击"❌ 禁用"按钮

或通过数据库：
```sql
UPDATE anti_spam_config
SET enabled = FALSE
WHERE group_id = -1001234567890;
```

---

## 技术支持

### 查看日志

**Docker 部署:**
```bash
# 查看实时日志
docker-compose logs -f appbot

# 查看最近 100 行日志
docker-compose logs --tail=100 appbot

# 过滤反垃圾相关日志
docker-compose logs appbot | grep -i "spam\|anti"
```

**手动部署:**
```bash
tail -f logs/bot-*.log | grep -i "spam\|anti"
```

### 进入 MySQL 容器查询

**Docker 部署:**
```bash
# 进入 MySQL 容器
docker-compose exec mysql mysql -u root -p

# 或者直接执行 SQL
docker-compose exec mysql mysql -u root -p -e "USE domobot; SELECT * FROM anti_spam_config;"
```

### 查看统计数据

```sql
-- 查看总体统计
SELECT
    group_id,
    SUM(total_checks) as total,
    SUM(spam_detected) as spam,
    SUM(users_banned) as banned,
    SUM(false_positives) as false_pos
FROM anti_spam_stats
GROUP BY group_id;

-- 查看最近检测日志
SELECT * FROM anti_spam_logs
ORDER BY created_at DESC
LIMIT 20;
```

### 备份配置

**Docker 部署:**
```bash
# 备份整个数据库
docker-compose exec mysql mysqldump -u root -p domobot > backup_$(date +%Y%m%d).sql

# 只备份反垃圾相关表
docker-compose exec mysql mysqldump -u root -p domobot anti_spam_config anti_spam_user_info anti_spam_logs anti_spam_stats > anti_spam_backup_$(date +%Y%m%d).sql
```

**手动部署:**
```bash
mysqldump -u root -p domobot anti_spam_config anti_spam_user_info > anti_spam_backup.sql
```

### 常用 Docker 命令

```bash
# 查看运行状态
docker-compose ps

# 重启机器人
docker-compose restart appbot

# 查看资源占用
docker stats appbot

# 清理日志（如果日志太大）
docker-compose logs --tail=0 -f appbot
```

---

## 总结

✅ **已完成的集成**:
1. 数据库表结构
2. AI检测核心功能
3. 管理面板集成
4. 私聊管理支持
5. 多群组管理
6. 统计和日志
7. 误报纠正

✅ **优势**:
- 智能语义理解
- 成本优化策略
- 灵活的配置选项
- 完善的统计功能
- 私聊管理避免暴露

🎉 **现在你可以开始使用了！**

发送 `/admin` → 点击 "🛡️ AI反垃圾管理" → 输入群组ID → 启用功能

祝使用愉快！
