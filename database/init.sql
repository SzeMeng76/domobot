-- Telegram Bot 数据库初始化脚本
-- 使用现有变量名保持兼容性

-- 创建数据库（如果需要）
-- CREATE DATABASE IF NOT EXISTS bot DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
-- USE bot;

-- 用户表（保持现有字段名）
CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,  -- 使用 telegram_id 作为主键
    username VARCHAR(255),
    first_name VARCHAR(255),
    last_name VARCHAR(255),
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_username (username),
    INDEX idx_last_seen (last_seen)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 管理员权限表（与现有 admin_permissions 对应）
CREATE TABLE IF NOT EXISTS admin_permissions (
    user_id BIGINT PRIMARY KEY,
    granted_by BIGINT NOT NULL,
    granted_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_granted_by (granted_by),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 超级管理员表（从配置中的 SUPER_ADMIN_ID 初始化）
CREATE TABLE IF NOT EXISTS super_admins (
    user_id BIGINT PRIMARY KEY,
    added_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 用户白名单表（与现有 user_whitelist 对应）
CREATE TABLE IF NOT EXISTS user_whitelist (
    user_id BIGINT PRIMARY KEY,
    added_by BIGINT NOT NULL,
    added_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_added_by (added_by),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 群组白名单表（与现有 group_whitelist 对应）
CREATE TABLE IF NOT EXISTS group_whitelist (
    group_id BIGINT PRIMARY KEY,
    group_name VARCHAR(255),
    added_by BIGINT NOT NULL,
    added_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_added_by (added_by)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 管理员操作日志表（可选，用于审计）
CREATE TABLE IF NOT EXISTS admin_logs (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    admin_id BIGINT NOT NULL,
    action VARCHAR(100) NOT NULL,
    target_type VARCHAR(50),  -- 'user', 'group', 'cache', etc.
    target_id BIGINT,
    details TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_admin_id (admin_id),
    INDEX idx_action (action),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 命令使用统计表（可选，用于分析）
CREATE TABLE IF NOT EXISTS command_stats (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    command VARCHAR(50) NOT NULL,
    user_id BIGINT NOT NULL,
    chat_id BIGINT NOT NULL,
    chat_type VARCHAR(20),  -- 'private', 'group', 'supergroup'
    executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_command (command),
    INDEX idx_user_id (user_id),
    INDEX idx_executed_at (executed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 创建视图：活跃管理员（包括超级管理员）
CREATE OR REPLACE VIEW active_admins AS
SELECT u.user_id, u.username, u.first_name, u.last_name, 
       CASE WHEN sa.user_id IS NOT NULL THEN 'super_admin' ELSE 'admin' END as admin_type
FROM users u
LEFT JOIN admin_permissions ap ON u.user_id = ap.user_id
LEFT JOIN super_admins sa ON u.user_id = sa.user_id
WHERE ap.user_id IS NOT NULL OR sa.user_id IS NOT NULL;

-- 创建存储过程：检查用户权限
DELIMITER //
CREATE PROCEDURE check_user_permission(IN p_user_id BIGINT)
BEGIN
    SELECT
        u.user_id,
        u.username,
        CASE
            WHEN sa.user_id IS NOT NULL THEN 'SUPER_ADMIN'
            WHEN ap.user_id IS NOT NULL THEN 'ADMIN'
            WHEN uw.user_id IS NOT NULL THEN 'WHITELISTED'
            ELSE 'USER'
        END as permission_level
    FROM users u
    LEFT JOIN super_admins sa ON u.user_id = sa.user_id
    LEFT JOIN admin_permissions ap ON u.user_id = ap.user_id
    LEFT JOIN user_whitelist uw ON u.user_id = uw.user_id
    WHERE u.user_id = p_user_id;
END//
DELIMITER ;

-- ============================================================================
-- AI反垃圾功能相关表
-- ============================================================================

-- 反垃圾配置表（按群组）
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

-- 用户反垃圾信息表
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

-- 垃圾检测日志表
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

-- 反垃圾统计表
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