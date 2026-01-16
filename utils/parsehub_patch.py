"""
Monkey patch for ParseHub yt_dlp_parser to fix Facebook parsing
Issue: Invalid format selector in ParseHub causes Facebook videos to fail
Fix: Override the format parameter with a valid yt-dlp format selector
"""

def patch_parsehub_yt_dlp():
    """Patch ParseHub's YtParser.params to use correct format selector"""
    try:
        from parsehub.parsers.base.yt_dlp_parser import YtParser

        # Save original params property
        original_params = YtParser.params

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

        print("[ParseHub Patch] Successfully patched YtParser.params")
        return True

    except Exception as e:
        print(f"[ParseHub Patch] Failed to patch: {e}")
        return False
