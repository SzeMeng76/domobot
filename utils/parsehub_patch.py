"""
Monkey patch for ParseHub yt_dlp_parser to fix issues:
1. Format selector: Invalid format causes Facebook/YouTube videos to fail
2. Cookie handling: YtParser doesn't pass cookies to yt-dlp
"""

def patch_parsehub_yt_dlp():
    """
    Patch ParseHub's YtParser to:
    1. Use correct format selector
    2. Pass cookies from ParseConfig to yt-dlp
    """
    try:
        import logging
        import os
        import tempfile
        logger = logging.getLogger(__name__)

        from parsehub.parsers.base.yt_dlp_parser import YtParser

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

            # Add cookies if configured (FIX: YtParser doesn't handle cookies)
            temp_cookie_file = None
            if self.cfg.cookie:
                # 检查cookie类型：文件路径或字符串
                if isinstance(self.cfg.cookie, str):
                    # 判断是文件路径还是cookie字符串
                    if os.path.exists(self.cfg.cookie):
                        # YouTube Netscape文件路径，直接使用
                        params["cookiefile"] = self.cfg.cookie
                        logger.info(f"🍪 [Patch] Using cookie file: {self.cfg.cookie}")
                    else:
                        # Bilibili/Twitter等cookie字符串，解析后写临时文件
                        logger.info(f"🍪 [Patch] Parsing cookie string (len={len(self.cfg.cookie)})")

                        # 解析cookie字符串为dict
                        cookie_dict = {}
                        for item in self.cfg.cookie.split(';'):
                            item = item.strip()
                            if '=' in item:
                                key, value = item.split('=', 1)
                                cookie_dict[key.strip()] = value.strip()

                        # 根据URL判断domain
                        url_lower = url.lower()
                        if "bili" in url_lower:
                            domain = ".bilibili.com"
                        elif "twitter.com" in url_lower or "x.com" in url_lower:
                            domain = ".twitter.com"
                        elif "instagram.com" in url_lower:
                            domain = ".instagram.com"
                        elif "kuaishou.com" in url_lower:
                            domain = ".kuaishou.com"
                        else:
                            domain = ".example.com"

                        # 写入临时Netscape格式文件
                        temp_cookie_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt')
                        temp_cookie_file.write("# Netscape HTTP Cookie File\n")
                        for key, value in cookie_dict.items():
                            temp_cookie_file.write(f"{domain}\tTRUE\t/\tFALSE\t0\t{key}\t{value}\n")
                        temp_cookie_file.close()

                        params["cookiefile"] = temp_cookie_file.name
                        logger.info(f"🍪 [Patch] Created temp cookie file for {domain}")

            try:
                with YoutubeDL(params) as ydl:
                    result = ydl.extract_info(url, download=False)

                # 清理临时cookie文件
                if temp_cookie_file and os.path.exists(temp_cookie_file.name):
                    os.unlink(temp_cookie_file.name)

                return result
            except Exception as e:
                # 清理临时cookie文件
                if temp_cookie_file and os.path.exists(temp_cookie_file.name):
                    os.unlink(temp_cookie_file.name)
                error_msg = f"{type(e).__name__}: {str(e)}"
                raise RuntimeError(error_msg) from None

        # Apply patches
        YtParser.params = fixed_params
        YtParser._extract_info = fixed_extract_info

        logger.info("✅ ParseHub patched: format selector + cookie handling")
        return True

    except Exception as e:
        logger.error(f"❌ ParseHub patch failed: {e}")
        return False
