"""
Monkey patch for ParseHub to fix issues:
1. YtParser format selector: Invalid format causes Facebook/YouTube videos to fail
2. YtParser cookie handling: YtParser doesn't pass cookies to yt-dlp
3. BiliAPI anti-crawler: BiliAPI doesn't set Referer headers for API calls
4. XhsParser empty download list: XhsParser crashes when download_list is empty
"""


def patch_parsehub_yt_dlp():
    """
    Patch ParseHub's YtParser to:
    1. Use correct format selector
    2. Pass cookies from ParseConfig to yt-dlp
    3. Patch BiliAPI to add Referer headers for anti-crawler
    4. Patch XhsParser to handle empty download list gracefully
    """
    try:
        import logging
        import os
        import tempfile
        logger = logging.getLogger(__name__)

        from parsehub.parsers.base.yt_dlp_parser import YtParser
        from parsehub.provider_api.bilibili import BiliAPI
        from parsehub.parsers.parser.xhs_ import XhsParser

        logger.info("🔧 Starting ParseHub patch...")

        def fixed_extract_info(self, url):
            """Fixed _extract_info that passes cookies to yt-dlp and stores TikHub download URL"""
            import re
            import httpx
            from yt_dlp import YoutubeDL

            params = self.params.copy()

            # Add proxy if configured
            if self.cfg.proxy:
                params["proxy"] = self.cfg.proxy

            # JavaScript runtime配置：
            # yt-dlp默认支持deno，会自动检测PATH中的deno
            # 不需要手动配置js_runtimes (Dockerfile已安装deno并添加到PATH)

            # Add headers (Referer/Origin) for anti-crawler
            # yt-dlp需要这些headers才能绕过各平台的反爬虫检测
            # 重要：不要覆盖params["http_headers"]，而是更新现有headers
            # 参考: yt_dlp/YoutubeDL.py:742 - params['http_headers'] = HTTPHeaderDict(std_headers, self.params.get('http_headers'))
            url_lower = url.lower()

            # 获取现有headers（如果有的话），否则使用空dict
            http_headers = params.get("http_headers", {})
            if not isinstance(http_headers, dict):
                http_headers = {}

            # 不设置User-Agent，让yt-dlp使用random_user_agent()（更好的反爬虫）
            # 参考: yt_dlp/utils/networking.py:162 - 'User-Agent': random_user_agent()

            # 根据平台添加Referer和Origin（这些是必需的反爬虫headers）
            if "youtube.com" in url_lower or "youtu.be" in url_lower:
                http_headers.update({
                    "Referer": "https://www.youtube.com/",
                    "Origin": "https://www.youtube.com"
                })
                logger.info(f"🌐 [Patch] Added YouTube headers (Referer/Origin)")
            elif "bilibili.com" in url_lower or "b23.tv" in url_lower:
                http_headers.update({
                    "Referer": "https://www.bilibili.com/",
                    "Origin": "https://www.bilibili.com"
                })
                logger.info(f"🌐 [Patch] Added Bilibili headers (Referer/Origin)")
            elif "twitter.com" in url_lower or "x.com" in url_lower:
                http_headers.update({
                    "Referer": "https://twitter.com/",
                    "Origin": "https://twitter.com"
                })
                logger.info(f"🌐 [Patch] Added Twitter headers (Referer/Origin)")
            elif "instagram.com" in url_lower:
                http_headers.update({
                    "Referer": "https://www.instagram.com/",
                    "Origin": "https://www.instagram.com"
                })
                logger.info(f"🌐 [Patch] Added Instagram headers (Referer/Origin)")
            elif "kuaishou.com" in url_lower:
                http_headers.update({
                    "Referer": "https://www.kuaishou.com/",
                    "Origin": "https://www.kuaishou.com"
                })
                logger.info(f"🌐 [Patch] Added Kuaishou headers (Referer/Origin)")
            elif "facebook.com" in url_lower or "fb.watch" in url_lower:
                http_headers.update({
                    "Referer": "https://www.facebook.com/",
                    "Origin": "https://www.facebook.com"
                })
                logger.info(f"🌐 [Patch] Added Facebook headers (Referer/Origin)")

            # 更新params（而不是覆盖）
            params["http_headers"] = http_headers
            logger.info(f"🔍 [Patch] Final http_headers: {http_headers}")

            # Add cookies if configured (FIX: YtParser doesn't handle cookies)
            # 参考: yt_dlp/YoutubeDL.py:349 - cookiefile: File name or text stream from where cookies should be read
            temp_cookie_file = None

            # YouTube特殊处理：从环境变量读取cookie文件路径
            # （因为ParseConfig会把文件路径解析成dict）
            # 优先级：环境变量 > ParseConfig
            if ("youtube.com" in url.lower() or "youtu.be" in url.lower()) and "cookiefile" not in params:
                youtube_cookie_from_env = os.getenv("YOUTUBE_COOKIE")
                if youtube_cookie_from_env:
                    logger.info(f"🍪 [Patch] YouTube cookie from env: {youtube_cookie_from_env}")
                    if os.path.exists(youtube_cookie_from_env):
                        params["cookiefile"] = youtube_cookie_from_env
                        logger.info(f"🍪 [Patch] Using YouTube cookie file: {youtube_cookie_from_env}")
                    else:
                        logger.warning(f"⚠️ [Patch] YouTube cookie file not found: {youtube_cookie_from_env}")

            # 其他平台cookie处理（从ParseConfig传递）
            # 只有在cookiefile还没设置时才处理
            if self.cfg.cookie and "cookiefile" not in params:
                logger.info(f"🍪 [Patch] Received cookie type: {type(self.cfg.cookie)}, value preview: {str(self.cfg.cookie)[:100]}")
                # 检查cookie类型：文件路径或字符串
                if isinstance(self.cfg.cookie, str):
                    logger.info(f"🍪 [Patch] Cookie is string, checking if file exists: {self.cfg.cookie}")
                    # 判断是文件路径还是cookie字符串
                    if os.path.exists(self.cfg.cookie):
                        logger.info(f"🍪 [Patch] File exists! Setting cookiefile parameter")
                        # Netscape文件路径，直接使用
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

                # For YouTube URLs, try to get TikHub direct download URL
                youtube_patterns = [
                    r'(?:https?://)?(?:www\.)?(?:youtube\.com|youtu\.be)/',
                    r'(?:https?://)?(?:www\.)?youtube\.com/watch\?v=',
                    r'(?:https?://)?youtu\.be/'
                ]
                is_youtube = any(re.search(pattern, url, re.IGNORECASE) for pattern in youtube_patterns)

                if is_youtube and result:
                    try:
                        # Extract video ID from URL
                        video_id_match = re.search(r'(?:v=|/)([0-9A-Za-z_-]{11})(?:[?&]|$)', url)
                        if video_id_match:
                            video_id = video_id_match.group(1)

                            # TikHub API key from config (via environment variable TIKHUB_API_KEY)
                            # Note: We use os.getenv here because self.cfg is ParseConfig, not BotConfig
                            # The API key should be set in environment variable TIKHUB_API_KEY
                            tikhub_api_key = os.getenv("TIKHUB_API_KEY")
                            if not tikhub_api_key:
                                logger.debug(f"⚠️ [TikHub] TIKHUB_API_KEY not set, skipping TikHub API")
                                return result

                            logger.info(f"🎬 [TikHub] Fetching direct download URL for YouTube video: {video_id}")

                            # Call TikHub API
                            api_url = f"https://api.tikhub.io/api/v1/youtube/web/get_video_info?video_id={video_id}"
                            headers = {"Authorization": f"Bearer {tikhub_api_key}"}

                            with httpx.Client(timeout=30.0) as client:
                                response = client.get(api_url, headers=headers)

                            if response.status_code == 200:
                                data = response.json()
                                if data.get("code") == 200 and data.get("data"):
                                    video_data = data["data"]
                                    videos = video_data.get("videos", {}).get("items", [])

                                    if videos:
                                        # Find best video with audio (itag=18 is 360p with audio)
                                        best_video = None
                                        for v in videos:
                                            if v.get("hasAudio"):
                                                best_video = v
                                                break

                                        if not best_video:
                                            # No video with audio, use first video
                                            best_video = videos[0]

                                        # Store TikHub direct URL in result
                                        result["_tikhub_url"] = best_video["url"]
                                        result["_tikhub_quality"] = best_video.get("quality", "unknown")
                                        logger.info(f"✅ [TikHub] Got direct download URL ({best_video.get('quality', 'unknown')}, {best_video.get('sizeText', 'unknown')})")
                                    else:
                                        logger.warning(f"⚠️ [TikHub] No videos found in API response")
                                else:
                                    logger.warning(f"⚠️ [TikHub] API returned error: {data.get('message', 'Unknown error')}")
                            else:
                                logger.warning(f"⚠️ [TikHub] API request failed: HTTP {response.status_code}")

                    except Exception as e:
                        logger.warning(f"⚠️ [TikHub] Failed to fetch direct URL: {e}")

                return result
            except Exception as e:
                # 清理临时cookie文件
                if temp_cookie_file and os.path.exists(temp_cookie_file.name):
                    os.unlink(temp_cookie_file.name)
                error_msg = f"{type(e).__name__}: {str(e)}"
                raise RuntimeError(error_msg) from None

        # Apply YtParser patches
        # Note: Don't patch params property - it breaks subtitle configs and other settings
        # Only patch _extract_info method which handles js_runtimes internally
        YtParser._extract_info = fixed_extract_info
        logger.info("✅ YtParser patched: js_runtimes + cookie handling + headers")

        # Patch BiliAPI to support cookies and add Referer headers
        # Problem: BiliAPI.__init__ doesn't accept cookie parameter
        # Solution: Patch __init__ to accept cookie, and patch get_video_info to use it
        original_bili_init = BiliAPI.__init__
        original_get_video_info = BiliAPI.get_video_info

        def patched_bili_init(self, proxy: str = None, cookie: dict = None):
            """Patched BiliAPI.__init__ to accept cookie parameter"""
            original_bili_init(self, proxy)
            # 保存cookie供API调用使用
            self.cookie = cookie
            # 添加Referer和Origin headers
            self.headers.update({
                "Referer": "https://www.bilibili.com/",
                "Origin": "https://www.bilibili.com"
            })
            if cookie:
                logger.info(f"🌐 [Patch] BiliAPI initialized with cookie and anti-crawler headers")
            else:
                logger.info(f"🌐 [Patch] BiliAPI initialized with anti-crawler headers (no cookie)")

        async def patched_get_video_info(self, url: str):
            """Patched get_video_info to use self.cookie"""
            bvid = self.get_bvid(url)
            # 使用self.cookie而不是硬编码None
            response = await self._get_client().get(
                "https://api.bilibili.com/x/web-interface/view/detail",
                params={"bvid": bvid},
                cookies=self.cookie  # 传入cookie！
            )
            return response.json()

        BiliAPI.__init__ = patched_bili_init
        BiliAPI.get_video_info = patched_get_video_info

        # Note: BiliParse.bili_api_parse creates BiliAPI without cookie
        # But since we patched BiliAPI.__init__ to accept cookie parameter,
        # we need to ensure cookie is passed. The easiest way is to patch
        # the BiliAPI creation call in BiliParse, but that's complex.
        #
        # Instead, we rely on the fact that ParseConfig.cookie is accessible
        # via self.cfg.cookie in BiliParse. We just need BiliParse to pass it.
        #
        # Since we can't easily modify the calling code, we make BiliAPI
        # read cookie from environment if not provided in __init__.

        # Update: Simplify - patch BiliAPI to read from environment variable
        original_bili_init_v2 = BiliAPI.__init__

        def patched_bili_init_v2(self, proxy: str = None, cookie: dict = None):
            """Enhanced BiliAPI.__init__ that reads cookie from env if not provided"""
            # 如果没传cookie，尝试从环境变量读取
            if not cookie:
                import os
                cookie_str = os.getenv("BILIBILI_COOKIE")
                if cookie_str:
                    cookie = {}
                    for item in cookie_str.split(';'):
                        item = item.strip()
                        if '=' in item:
                            key, value = item.split('=', 1)
                            cookie[key.strip()] = value.strip()
                    logger.info(f"🌐 [Patch] BiliAPI loaded cookie from environment")

            # 调用之前patch的版本
            patched_bili_init(self, proxy, cookie)

        BiliAPI.__init__ = patched_bili_init_v2
        logger.info("✅ BiliAPI patched: cookie support (from env) + anti-crawler headers")

        # Patch XhsParser to handle empty download list
        # Reference: parsehub/parsers/parser/xhs_.py - parse method line 15
        original_xhs_parse = XhsParser.parse

        async def patched_xhs_parse(self, url: str):
            """Patched XhsParser.parse to handle empty download list"""
            from parsehub.types import VideoParseResult, ImageParseResult, MultimediaParseResult, Video, Image
            from parsehub.parsers.parser.xhs_ import XHS, Log

            # 调用原始逻辑获取数据
            url = await self.get_raw_url(url)
            async with XHS(user_agent="", cookie="") as xhs:
                x_result = await xhs.extract(url, False, log=Log)

            from parsehub.types.error import ParseError
            if not x_result or not (result := x_result[0]):
                raise ParseError("小红书解析失败")

            desc = self.hashtag_handler(result["作品描述"])
            k = {"title": result["作品标题"], "desc": desc, "raw_url": url}

            # Livephoto处理
            if all(result["动图地址"]):
                return MultimediaParseResult(media=[Video(i) for i in result["动图地址"]], **k)

            # 视频类型：检查下载地址是否为空
            elif result["作品类型"] == "视频":
                download_list = result.get("下载地址", [])
                if not download_list or len(download_list) == 0:
                    logger.warning(f"🌐 [Patch] XHS video has no download URLs, returning empty VideoParseResult")
                    return VideoParseResult(video=None, **k)
                else:
                    return VideoParseResult(video=download_list[0], **k)

            # 图文类型：检查下载地址是否为空
            elif result["作品类型"] == "图文":
                download_list = result.get("下载地址", [])
                if not download_list:
                    logger.warning(f"🌐 [Patch] XHS images have no download URLs, returning empty ImageParseResult")
                    return ImageParseResult(photo=[], **k)

                photos = []
                for i in download_list:
                    # Remove ?imageView2/format/png params - causes CDN 500 error
                    # Use base URL without params
                    img_url = i.split('?')[0] if '?' in i else i
                    ext = (await self.get_ext_by_url(img_url)) or "png"
                    photos.append(Image(img_url, ext))
                return ImageParseResult(photo=photos, **k)

            else:
                raise ParseError("不支持的类型")

        XhsParser.parse = patched_xhs_parse
        logger.info("✅ XhsParser patched: handle empty download list")

        return True

    except Exception as e:
        logger.error(f"❌ ParseHub patch failed: {e}")
        return False
