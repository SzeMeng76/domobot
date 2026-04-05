import logging

from telegram import Update
from telegram.ext import ContextTypes

from utils.cache_commands import delegate_to_cache_cleaner, delegate_to_service_handler
from utils.command_factory import command_factory
from utils.permissions import Permission

logger = logging.getLogger(__name__)


async def netflix_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /netflix command."""
    await delegate_to_service_handler(
        update,
        context,
        service_key="netflix_price_bot",
        service_display_name="Netflix",
    )


async def netflix_clean_cache_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """Handles the /netflix_cleancache command."""
    await delegate_to_cache_cleaner(
        update,
        context,
        service_key="netflix_price_bot",
        service_display_name="Netflix",
    )


# Register commands
command_factory.register_command(
    "nf", netflix_command, permission=Permission.USER, description="Netflix订阅价格查询"
)
command_factory.register_command(
    "nf_cleancache",
    netflix_clean_cache_command,
    permission=Permission.ADMIN,
    description="清理Netflix缓存",
)

logger.info("Netflix 命令已注册")
