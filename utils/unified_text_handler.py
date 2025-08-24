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

@with_error_handling
async def unified_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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

# 注册统一文本处理器
from utils.command_factory import command_factory
from utils.permissions import Permission

command_factory.register_text_handler(
    unified_text_handler, 
    permission=Permission.USER, 
    description="统一文本处理器 - 智能分发地图、航班、人物、电影和TV服务"
)