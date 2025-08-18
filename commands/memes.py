#!/usr/bin/env python3
"""
表情包(memes)命令模块
从 memes.bupt.site API 获取随机表情包图片
"""

import logging
from typing import List, Optional
from urllib.parse import urljoin

from telegram import Update
from telegram.ext import ContextTypes
from pydantic import BaseModel, ValidationError

from utils.command_factory import command_factory
from utils.config_manager import get_config
from utils.error_handling import with_error_handling
from utils.message_manager import (
    send_message_with_auto_delete,
    delete_user_command,
    send_error,
    send_success,
    send_help
)
from utils.permissions import Permission

logger = logging.getLogger(__name__)

# API配置
BASE_URL = "https://api.memes.bupt.site/api/"

# 全局变量
_cache_manager = None
_httpx_client = None

def set_dependencies(cache_manager, httpx_client):
    """设置依赖"""
    global _cache_manager, _httpx_client
    _cache_manager = cache_manager
    _httpx_client = httpx_client


# Pydantic数据模型
class MediaContent(BaseModel):
    id: int
    dataType: str
    dataContent: str
    userId: str
    checksum: Optional[str] = None
    llmDescription: Optional[str] = None
    llmModerationStatus: Optional[str] = None
    rejectionReason: Optional[str] = None
    tags: Optional[str] = None
    fileSize: Optional[str] = None
    metadata: Optional[str] = None
    status: Optional[str] = None


class DataItem(BaseModel):
    id: int
    mediaContentIdList: List[int]
    likesCount: int
    dislikesCount: int
    tags: Optional[str] = None
    mediaContentList: List[MediaContent]


class ResponseModel(BaseModel):
    status: int
    message: str
    data: List[DataItem]
    timestamp: int


async def get_memes(limit: int = 10) -> List[dict]:
    """
    从 memes.bupt.site 获取随机表情包
    
    Args:
        limit: 获取数量 (1-20)
        
    Returns:
        表情包信息列表，包含URL和描述
    """
    if not 1 <= limit <= 20:
        raise ValueError("limit must be between 1 and 20")
    
    # 检查缓存
    cache_key = f"memes_{limit}"
    if _cache_manager:
        try:
            cached_data = await _cache_manager.load_cache(cache_key, subdirectory="memes")
            if cached_data:
                logger.info(f"使用缓存获取 {limit} 个表情包")
                return cached_data
        except Exception as e:
            logger.warning(f"缓存读取失败: {e}")
    
    try:
        logger.info(f"从 memes API 获取 {limit} 个表情包")
        url = urljoin(BASE_URL, "submission")
        
        response = await _httpx_client.get(
            url=url,
            params={"pageSize": str(limit), "random": "true"},
            headers={"uuid": "domobot-mcp"},
            timeout=10.0
        )
        response.raise_for_status()
        
        # 使用Pydantic验证响应数据
        response_model = ResponseModel(**response.json())
        
        # 提取图片URL和描述信息
        meme_data = []
        for item in response_model.data:
            if (len(item.mediaContentIdList) == 1 
                and item.mediaContentList[0].dataType == "IMAGE"):
                media_content = item.mediaContentList[0]
                meme_info = {
                    'url': media_content.dataContent,
                    'description': media_content.llmDescription,
                    'id': media_content.id
                }
                meme_data.append(meme_info)
        
        # 缓存结果（使用配置的缓存时长）
        if _cache_manager and meme_data:
            try:
                await _cache_manager.save_cache(cache_key, meme_data, subdirectory="memes")
            except Exception as e:
                logger.warning(f"缓存写入失败: {e}")
        
        return meme_data
        
    except ValidationError as e:
        logger.error(f"API响应数据格式错误: {e}")
        raise ValueError(f"Invalid API response: {str(e)}")
    except Exception as e:
        logger.error(f"获取表情包失败: {e}")
        raise


@with_error_handling
async def meme_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """表情包命令处理器"""
    config = get_config()
    args = context.args or []
    
    # 如果没有参数，显示帮助信息
    if not args:
        help_text = (
            "🎭 **表情包功能使用指南**\n\n"
            "**基本用法:**\n"
            "`/meme [数量]` - 获取指定数量的随机表情包\n\n"
            "**参数说明:**\n"
            "• 数量范围: 1-20\n"
            "• 必须提供数量参数\n\n"
            "**使用示例:**\n"
            "• `/meme 3` - 获取3个表情包\n"
            "• `/meme 5` - 获取5个表情包\n"
            "• `/meme 1` - 获取1个表情包\n\n"
            "🌐 数据来源: memes.bupt.site\n"
            "🔄 支持缓存，快速响应"
        )
        
        await send_help(
            context,
            update.effective_chat.id,
            help_text,
            parse_mode='Markdown'
        )
        
        # 删除用户命令
        if update.message:
            await delete_user_command(context, update.effective_chat.id, update.message.message_id)
        return
    
    # 解析参数
    if args[0] in ['-h', '--help', 'help']:
        help_text = (
            "🎭 **表情包功能使用指南**\n\n"
            "**基本用法:**\n"
            "`/meme [数量]` - 获取指定数量的随机表情包\n\n"
            "**参数说明:**\n"
            "• 数量范围: 1-20\n"
            "• 必须提供数量参数\n\n"
            "**使用示例:**\n"
            "• `/meme 3` - 获取3个表情包\n"
            "• `/meme 5` - 获取5个表情包\n"
            "• `/meme 1` - 获取1个表情包\n\n"
            "🌐 数据来源: memes.bupt.site\n"
            "🔄 支持缓存，快速响应"
        )
        
        await send_help(
            context,
            update.effective_chat.id,
            help_text,
            parse_mode='Markdown'
        )
        
        # 删除用户命令
        if update.message:
            await delete_user_command(context, update.effective_chat.id, update.message.message_id)
        return
    
    # 尝试解析数量参数
    try:
        limit = int(args[0])
        if not 1 <= limit <= 20:
            await send_error(
                context,
                update.effective_chat.id,
                "❌ 数量必须在1-20之间\n\n使用 `/meme` 查看使用说明"
            )
            
            # 删除用户命令
            if update.message:
                await delete_user_command(context, update.effective_chat.id, update.message.message_id)
            return
    except ValueError:
        await send_error(
            context,
            update.effective_chat.id,
            f"❌ 无效的数量参数: `{args[0]}`\n\n请使用数字（1-20），使用 `/meme` 查看使用说明",
            parse_mode='Markdown'
        )
        
        # 删除用户命令
        if update.message:
            await delete_user_command(context, update.effective_chat.id, update.message.message_id)
        return
    
    # 发送加载提示
    loading_message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🎭 正在获取 {limit} 个随机表情包..."
    )
    
    try:
        # 获取表情包
        meme_data = await get_memes(limit)
        
        # 删除加载提示
        await loading_message.delete()
        
        if not meme_data:
            await send_error(
                context,
                update.effective_chat.id,
                "❌ 暂时无法获取表情包，请稍后重试"
            )
        else:
            # 发送成功获取的消息
            success_text = f"🎭 成功获取 {len(meme_data)} 个表情包："
            await send_success(
                context,
                update.effective_chat.id,
                success_text
            )
            
            # 逐个发送表情包图片
            for i, meme_info in enumerate(meme_data, 1):
                url = meme_info['url']
                description = meme_info.get('description')
                
                # 构建caption
                caption = f"🎭 表情包 {i}/{len(meme_data)}"
                if description and description.strip():
                    caption += f"\n💬 {description.strip()}"
                
                try:
                    photo_message = await context.bot.send_photo(
                        chat_id=update.effective_chat.id,
                        photo=url,
                        caption=caption
                    )
                    # 调度自动删除表情包消息
                    try:
                        scheduler = context.bot_data.get("message_delete_scheduler")
                        if scheduler and hasattr(scheduler, "schedule_deletion"):
                            await scheduler.schedule_deletion(
                                update.effective_chat.id, 
                                photo_message.message_id, 
                                900,  # 15分钟后删除
                                None
                            )
                    except Exception as e:
                        logger.warning(f"调度表情包 {i} 自动删除失败: {e}")
                        
                except Exception as e:
                    logger.warning(f"发送表情包 {i} 失败: {e}")
                    try:
                        # 构建fallback消息
                        fallback_text = f"🖼️ 表情包 {i}: [点击查看]({url})"
                        if description and description.strip():
                            fallback_text += f"\n💬 {description.strip()}"
                        
                        fallback_message = await context.bot.send_message(
                            chat_id=update.effective_chat.id,
                            text=fallback_text,
                            parse_mode='Markdown'
                        )
                        # 调度自动删除链接消息
                        try:
                            scheduler = context.bot_data.get("message_delete_scheduler")
                            if scheduler and hasattr(scheduler, "schedule_deletion"):
                                await scheduler.schedule_deletion(
                                    update.effective_chat.id, 
                                    fallback_message.message_id, 
                                    900,  # 15分钟后删除
                                    None
                                )
                        except Exception as e:
                            logger.warning(f"调度表情包链接 {i} 自动删除失败: {e}")
                    except Exception as e:
                        logger.error(f"发送表情包链接 {i} 也失败: {e}")
        
        # 删除用户命令
        if update.message:
            await delete_user_command(context, update.effective_chat.id, update.message.message_id)
        
        logger.info(f"成功获取并发送 {len(meme_data)} 个表情包")
        
    except ValueError as e:
        # 删除加载提示
        try:
            await loading_message.delete()
        except:
            pass
        
        await send_error(
            context,
            update.effective_chat.id,
            f"❌ {str(e)}"
        )
        
        # 删除用户命令
        if update.message:
            await delete_user_command(context, update.effective_chat.id, update.message.message_id)
        
    except Exception as e:
        # 删除加载提示
        try:
            await loading_message.delete()
        except:
            pass
        
        logger.error(f"表情包命令执行失败: {e}")
        await send_error(
            context,
            update.effective_chat.id,
            "❌ 获取表情包失败，请稍后重试"
        )
        
        # 删除用户命令
        if update.message:
            await delete_user_command(context, update.effective_chat.id, update.message.message_id)


@with_error_handling
async def memes_clean_cache_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """清理表情包缓存命令"""
    if not update.message:
        return

    try:
        if _cache_manager:
            await _cache_manager.clear_cache(subdirectory="memes")
            message = "✅ 表情包缓存已清理完成"
            logger.info("表情包缓存手动清理完成")
        else:
            message = "❌ 缓存管理器不可用"
            
        await send_success(
            context,
            update.effective_chat.id,
            message
        )
        
        # 删除用户命令
        if update.message:
            await delete_user_command(context, update.effective_chat.id, update.message.message_id)
            
    except Exception as e:
        logger.error(f"清理表情包缓存时发生错误: {e}")
        await send_error(
            context,
            update.effective_chat.id,
            f"❌ 清理表情包缓存时发生错误: {e}"
        )
        
        # 删除用户命令
        if update.message:
            await delete_user_command(context, update.effective_chat.id, update.message.message_id)


# 注册命令
command_factory.register_command(
    "meme",
    meme_command,
    permission=Permission.NONE,
    description="获取随机表情包 (需要参数)"
)

# 已迁移到统一缓存管理命令 /cleancache
# command_factory.register_command(
#     "memes_cleancache",
#     memes_clean_cache_command,
#     permission=Permission.ADMIN,
#     description="清理表情包缓存"
# )

logger.info("表情包命令模块已加载")