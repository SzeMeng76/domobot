"""
统一的文本消息处理器
负责协调多个服务的文本输入处理，避免处理器冲突
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes
from utils.error_handling import with_error_handling

logger = logging.getLogger(__name__)

# 导入会话管理器
# 动态导入避免循环导入
map_session_manager = None
flight_session_manager = None
person_session_manager = None
movie_session_manager = None
tv_session_manager = None
map_text_handler_core = None
flight_text_handler_core = None
person_text_handler_core = None
movie_text_handler_core = None
tv_text_handler_core = None

async def unified_text_handler_core(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    统一文本处理器 - 根据活动会话智能分发到对应服务
    """
    global map_session_manager, flight_session_manager, person_session_manager, movie_session_manager, tv_session_manager
    global map_text_handler_core, flight_text_handler_core, person_text_handler_core, movie_text_handler_core, tv_text_handler_core
    
    # 延迟导入避免循环导入
    if map_session_manager is None:
        from commands.map import map_session_manager as _map_sm, map_text_handler_core as _map_core
        from commands.flight import flight_session_manager as _flight_sm, flight_text_handler_core as _flight_core
        from commands.movie import person_session_manager as _person_sm, person_text_handler_core as _person_core
        from commands.movie import movie_session_manager as _movie_sm, movie_text_handler_core as _movie_core
        from commands.movie import tv_session_manager as _tv_sm, tv_text_handler_core as _tv_core
        map_session_manager = _map_sm
        flight_session_manager = _flight_sm
        person_session_manager = _person_sm
        movie_session_manager = _movie_sm
        tv_session_manager = _tv_sm
        map_text_handler_core = _map_core
        flight_text_handler_core = _flight_core
        person_text_handler_core = _person_core
        movie_text_handler_core = _movie_core
        tv_text_handler_core = _tv_core
    
    if not update.message or not update.message.text:
        return
    
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    logger.debug(f"UnifiedTextHandler: Processing message from user {user_id}: {text[:50]}")
    
    # 检查地图会话
    map_session = map_session_manager.get_session(user_id)
    if map_session:
        logger.info(f"UnifiedTextHandler: Routing to map service for user {user_id}")
        await map_text_handler_core(update, context)
        return
    
    # 检查航班会话
    flight_session = flight_session_manager.get_session(user_id)
    if flight_session:
        logger.info(f"UnifiedTextHandler: Routing to flight service for user {user_id}")
        await flight_text_handler_core(update, context)
        return
    
    # 检查人物会话
    person_session = person_session_manager.get_session(user_id)
    if person_session:
        logger.info(f"UnifiedTextHandler: Routing to person service for user {user_id}")
        await person_text_handler_core(update, context)
        return
    
    # 检查电影会话
    movie_session = movie_session_manager.get_session(user_id)
    if movie_session:
        logger.info(f"UnifiedTextHandler: Routing to movie service for user {user_id}")
        await movie_text_handler_core(update, context)
        return
    
    # 检查TV会话
    tv_session = tv_session_manager.get_session(user_id)
    if tv_session:
        logger.info(f"UnifiedTextHandler: Routing to TV service for user {user_id}")
        await tv_text_handler_core(update, context)
        return
    
    # 没有活动会话，忽略消息
    logger.debug(f"UnifiedTextHandler: No active session for user {user_id}, ignoring message")


@with_error_handling
async def unified_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    统一文本处理器包装器 - 只在有活动会话时进行处理
    """
    if not update.message or not update.message.text:
        return
    
    user_id = update.effective_user.id
    
    # 快速检查是否有任何活动会话
    # 延迟导入避免循环导入
    global map_session_manager, flight_session_manager, person_session_manager, movie_session_manager, tv_session_manager
    
    if map_session_manager is None:
        from commands.map import map_session_manager as _map_sm
        from commands.flight import flight_session_manager as _flight_sm
        from commands.movie import person_session_manager as _person_sm, movie_session_manager as _movie_sm, tv_session_manager as _tv_sm
        map_session_manager = _map_sm
        flight_session_manager = _flight_sm
        person_session_manager = _person_sm
        movie_session_manager = _movie_sm
        tv_session_manager = _tv_sm
    
    # 检查是否有任何活动会话
    has_active_session = (
        map_session_manager.get_session(user_id) is not None or
        flight_session_manager.get_session(user_id) is not None or
        person_session_manager.get_session(user_id) is not None or
        movie_session_manager.get_session(user_id) is not None or
        tv_session_manager.get_session(user_id) is not None
    )
    
    if not has_active_session:
        logger.debug(f"UnifiedTextHandler: No active session for user {user_id}, ignoring message")
        return
    
    # 有活动会话时才调用核心处理器，应用速率限制
    logger.debug(f"UnifiedTextHandler: Processing message from user {user_id} (has active session)")
    
    # 手动应用速率限制
    from utils.error_handling import rate_limiter_manager, send_error, delete_user_command
    
    rate_limiter = rate_limiter_manager.get_rate_limiter("unified_text_handler", max_calls=10, time_window=60)
    
    if await rate_limiter.acquire(user_id):
        await unified_text_handler_core(update, context)
    else:
        # 发送频率限制错误消息
        await send_error(
            context=context,
            chat_id=update.effective_chat.id,
            text="⚠️ 请求频率过高，请稍后重试。"
        )
        
        # 删除用户命令消息
        if (
            hasattr(update, "effective_message")
            and getattr(update.effective_message, "message_id", None)
        ):
            await delete_user_command(
                context=context,
                chat_id=update.effective_chat.id,
                message_id=update.effective_message.message_id
            )

# 注册统一文本处理器
from utils.command_factory import command_factory
from utils.permissions import Permission

command_factory.register_text_handler(
    unified_text_handler, 
    permission=Permission.USER, 
    description="统一文本处理器 - 智能分发地图、航班、人物、电影和TV服务",
    use_rate_limit=False  # 在包装器层面不使用速率限制，避免普通群聊消息触发限制
)