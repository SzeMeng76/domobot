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
    sharpReview: Optional[str] = None


class MemeWithDescription(BaseModel):
    """包含描述的表情包数据结构"""
    url: str
    description: Optional[str] = None
    media_id: Optional[int] = None


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


async def get_media_details(media_id: int) -> Optional[str]:
    """
    获取单个媒体内容的详细描述信息
    
    Args:
        media_id: 媒体内容ID
        
    Returns:
        描述信息（优先级：sharpReview > llmDescription > None）
    """
    try:
        logger.debug(f"获取媒体 {media_id} 的详细信息")
        url = urljoin(BASE_URL, f"media/{media_id}")
        
        response = await _httpx_client.get(
            url=url,
            headers={"uuid": "domobot-mcp"},
            timeout=5.0
        )
        response.raise_for_status()
        
        # 解析响应
        response_data = response.json()
        logger.debug(f"媒体 {media_id} API响应状态: {response_data.get('status')}")
        
        if response_data.get("status") != 200:
            logger.warning(f"媒体 {media_id} API返回非200状态: {response_data}")
            return None
        
        media_data = response_data.get("data", {})
        sharp_review = media_data.get("sharpReview")
        llm_description = media_data.get("llmDescription")
        
        logger.debug(f"媒体 {media_id} - sharpReview: {bool(sharp_review)}, llmDescription: {bool(llm_description)}")
        
        # 按优先级返回描述（与前端逻辑一致）
        if sharp_review and sharp_review.strip():
            logger.debug(f"媒体 {media_id} 使用sharpReview")
            return sharp_review.strip()
        elif llm_description and llm_description.strip():
            logger.debug(f"媒体 {media_id} 使用llmDescription")
            return llm_description.strip()
        else:
            logger.debug(f"媒体 {media_id} 没有可用的描述信息")
            return None
            
    except Exception as e:
        logger.warning(f"获取媒体 {media_id} 详细信息失败: {e}")
        return None


async def get_memes(limit: int = 10, retry_for_description: bool = True) -> List[MemeWithDescription]:
    """
    从 memes.bupt.site 获取随机表情包（包含描述信息）
    
    Args:
        limit: 获取数量 (1-20)
        retry_for_description: 当limit=1且无描述时是否重试
        
    Returns:
        包含URL和描述的表情包列表
    """
    if not 1 <= limit <= 20:
        raise ValueError("limit must be between 1 and 20")
    
    # 智能重试逻辑：当limit=1时，如果没有获取到描述，重试几次
    max_retries = 3 if (limit == 1 and retry_for_description) else 1
    
    for attempt in range(max_retries):
        if attempt > 0:
            logger.info(f"第 {attempt + 1} 次尝试获取有描述的表情包")
            
        # 重试时跳过缓存，确保获取不同的表情包
        use_cache_for_retry = (attempt == 0)  # 只有第一次尝试使用缓存
        result = await _fetch_memes_once(limit, use_cache_for_retry)
        
        # 如果是单个表情包且启用重试
        if limit == 1 and retry_for_description and result:
            if result[0].description:
                logger.info(f"成功获取到有描述的表情包 (第 {attempt + 1} 次尝试)")
                return result
            elif attempt < max_retries - 1:
                logger.info(f"表情包无描述，将重试获取 (尝试 {attempt + 1}/{max_retries})")
                continue
        
        # 其他情况直接返回
        return result
    
    # 如果所有重试都失败了，返回最后一次的结果
    logger.warning(f"经过 {max_retries} 次尝试仍未获取到有描述的表情包")
    return result or []


async def _fetch_memes_once(limit: int, use_cache: bool = True) -> List[MemeWithDescription]:
    """单次获取表情包的内部函数"""
    
    # 检查缓存（只有在use_cache=True时才使用）
    cache_key = f"memes_{limit}"
    if _cache_manager and use_cache:
        try:
            cached_data = await _cache_manager.load_cache(cache_key, subdirectory="memes")
            if cached_data:
                logger.info(f"使用缓存获取 {limit} 个表情包")
                # 将缓存的URL列表转换为MemeWithDescription对象（无描述信息）
                # 注意：缓存的数据没有描述信息，但通过重试机制可以获得有描述的表情包
                return [MemeWithDescription(url=url) for url in cached_data]
        except Exception as e:
            logger.warning(f"缓存读取失败: {e}")
    
    try:
        logger.info(f"从 memes API 获取 {limit} 个表情包 (缓存: {'启用' if use_cache else '禁用'})")
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
        
        # 提取图片URL和媒体ID，并获取描述信息
        meme_list = []
        logger.info(f"API返回 {len(response_model.data)} 个submission")
        
        for item in response_model.data:
            if (len(item.mediaContentIdList) == 1 
                and item.mediaContentList[0].dataType == "IMAGE"):
                media_content = item.mediaContentList[0]
                media_id = media_content.id
                url = media_content.dataContent
                
                logger.info(f"处理表情包 ID: {media_id}")
                
                # 获取详细描述信息
                description = await get_media_details(media_id)
                
                meme_list.append(MemeWithDescription(
                    url=url,
                    description=description,
                    media_id=media_id
                ))
        
        logger.info(f"最终获取 {len(meme_list)} 个表情包，其中有描述的: {sum(1 for m in meme_list if m.description)}")
        
        # 缓存结果（使用配置的缓存时长，但只在use_cache=True时缓存）
        if _cache_manager and meme_list and use_cache:
            try:
                # 为了向后兼容，缓存时只存储URL列表
                cache_urls = [meme.url for meme in meme_list]
                await _cache_manager.save_cache(cache_key, cache_urls, subdirectory="memes")
            except Exception as e:
                logger.warning(f"缓存写入失败: {e}")
        
        return meme_list
        
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
        meme_list = await get_memes(limit)
        
        # 删除加载提示
        await loading_message.delete()
        
        if not meme_list:
            await send_error(
                context,
                update.effective_chat.id,
                "❌ 暂时无法获取表情包，请稍后重试"
            )
        else:
            # 发送成功获取的消息
            success_text = f"🎭 成功获取 {len(meme_list)} 个表情包："
            await send_success(
                context,
                update.effective_chat.id,
                success_text
            )
            
            # 逐个发送表情包图片
            for i, meme in enumerate(meme_list, 1):
                try:
                    # 构建标题，包含描述信息
                    caption = f"🎭 表情包 {i}/{len(meme_list)}"
                    if meme.description:
                        caption += f"\n💬 {meme.description}"
                    
                    logger.info(f"尝试发送表情包 {i}: {meme.url}")
                    photo_message = await context.bot.send_photo(
                        chat_id=update.effective_chat.id,
                        photo=meme.url,
                        caption=caption
                    )
                    logger.info(f"表情包 {i} 发送成功: message_id={photo_message.message_id}")
                    
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
                            logger.info(f"已调度表情包 {i} 删除: message_id={photo_message.message_id}")
                        else:
                            logger.warning(f"调度器不可用，无法调度表情包 {i} 自动删除")
                    except Exception as e:
                        logger.warning(f"调度表情包 {i} 自动删除失败: {e}")
                        
                except Exception as e:
                    logger.warning(f"发送表情包 {i} 失败: {e}")
                    try:
                        # 构建fallback消息，包含描述信息
                        fallback_text = f"🖼️ 表情包 {i}: [点击查看]({meme.url})"
                        if meme.description:
                            fallback_text += f"\n💬 {meme.description}"
                        
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
        
        logger.info(f"成功获取并发送 {len(meme_list)} 个表情包")
        
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