"""
Monkey patch for ParseHub yt_dlp_parser to fix issues:
1. Facebook parsing: Invalid format selector causes Facebook videos to fail
2. Bilibili 412 error: yt-dlp not receiving cookies from ParseConfig
"""

def patch_parsehub_yt_dlp():
    """
    Patch ParseHub's YtParser to:
    1. Use correct format selector for Facebook/YouTube
    2. Pass cookies from ParseConfig to yt-dlp
    """
    try:
        import logging
        logger = logging.getLogger(__name__)

        from parsehub.parsers.base.yt_dlp_parser import YtParser
        import tempfile
        import os

        # Save original methods
        original_params = YtParser.params
        original_extract_info = YtParser._extract_info

        logger.info("🔧 Starting ParseHub patch...")

        @property
        def fixed_params(self) -> dict:
            """Fixed params with correct format selector"""
            params = {
                "format": "bestvideo[height<=1080]+bestaudio/best",  # Fixed format
                "quiet": True,
                "playlist_items": "1",
            }
            return params

        def fixed_extract_info(self, url):
            """Fixed _extract_info that passes cookies to yt-dlp"""
            from yt_dlp import YoutubeDL

            params = self.params.copy()

            # Add proxy if configured
            if self.cfg.proxy:
                params["proxy"] = self.cfg.proxy

            # Add cookies if configured (FIX for Bilibili 412 error)
            if self.cfg.cookie:
                # yt-dlp expects cookies in Netscape format file
                # We need to write cookies to a temp file
                cookie_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt')
                try:
                    # Write Netscape cookie format
                    cookie_file.write("# Netscape HTTP Cookie File\n")
                    for key, value in self.cfg.cookie.items():
                        # Format: domain flag path secure expiration name value
                        domain = ".bilibili.com" if "bili" in url.lower() else ".twitter.com" if "twitter" in url.lower() or "x.com" in url.lower() else ".instagram.com"
                        cookie_file.write(f"{domain}\tTRUE\t/\tFALSE\t0\t{key}\t{value}\n")
                    cookie_file.close()

                    params["cookiefile"] = cookie_file.name
                    print(f"[ParseHub Patch] Using cookie file: {cookie_file.name}")
                except Exception as e:
                    print(f"[ParseHub Patch] Failed to write cookie file: {e}")
                    if os.path.exists(cookie_file.name):
                        os.unlink(cookie_file.name)

            try:
                with YoutubeDL(params) as ydl:
                    result = ydl.extract_info(url, download=False)

                # Clean up cookie file
                if "cookiefile" in params and os.path.exists(params["cookiefile"]):
                    os.unlink(params["cookiefile"])

                return result
            except Exception as e:
                # Clean up cookie file on error
                if "cookiefile" in params and os.path.exists(params["cookiefile"]):
                    os.unlink(params["cookiefile"])
                error_msg = f"{type(e).__name__}: {str(e)}"
                raise RuntimeError(error_msg) from None

        # Apply patches
        YtParser.params = fixed_params
        YtParser._extract_info = fixed_extract_info

        print("[ParseHub Patch] Successfully patched YtParser (format + cookies)")
        return True

    except Exception as e:
        print(f"[ParseHub Patch] Failed to patch: {e}")
        return False
