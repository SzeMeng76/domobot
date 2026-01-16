"""
Monkey patch for ParseHub yt_dlp_parser to fix format selector issue
Facebook/YouTube parsing: Invalid format selector causes videos to fail
"""

def patch_parsehub_yt_dlp():
    """
    Patch ParseHub's YtParser to use correct format selector
    """
    try:
        import logging
        logger = logging.getLogger(__name__)

        from parsehub.parsers.base.yt_dlp_parser import YtParser

        logger.info("🔧 Starting ParseHub patch (format selector only)...")

        @property
        def fixed_params(self) -> dict:
            """Fixed params with correct format selector"""
            params = {
                "format": "bestvideo[height<=1080]+bestaudio/best",  # Fixed format
                "quiet": True,
                "playlist_items": "1",
            }
            return params

        # Apply patch
        YtParser.params = fixed_params

        logger.info("✅ ParseHub patched: format selector fixed")
        return True

    except Exception as e:
        logger.error(f"❌ ParseHub patch failed: {e}")
        return False
