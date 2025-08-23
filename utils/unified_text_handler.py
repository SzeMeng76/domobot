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
map_text_handler_core = None
flight_text_handler_core = None

@with_error_handling
async def unified_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    统一文本处理器 - 根据活动会话智能分发到对应服务
    """
    global map_session_manager, flight_session_manager, map_text_handler_core, flight_text_handler_core
    
    # 延迟导入避免循环导入
    if map_session_manager is None:
        from commands.map import map_session_manager as _map_sm, map_text_handler_core as _map_core
        from commands.flight import flight_session_manager as _flight_sm, flight_text_handler_core as _flight_core
        map_session_manager = _map_sm
        flight_session_manager = _flight_sm
        map_text_handler_core = _map_core
        flight_text_handler_core = _flight_core
    
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
    
    # 没有活动会话，忽略消息
    logger.debug(f"UnifiedTextHandler: No active session for user {user_id}, ignoring message")

# 注册统一文本处理器
from utils.command_factory import command_factory
from utils.permissions import Permission

command_factory.register_text_handler(
    unified_text_handler, 
    permission=Permission.USER, 
    description="统一文本处理器 - 智能分发地图和航班服务"
)