"""
Monkey patch for ParseHub to fix issues:
1. YtParser format selector: Invalid format causes Facebook/YouTube videos to fail
2. YtParser cookie handling: YtParser doesn't pass cookies to yt-dlp
3. BiliAPI anti-crawler: BiliAPI doesn't set Referer headers for API calls
4. XhsParser empty download list: XhsParser crashes when download_list is empty
5. FacebookParse regex: watch/?v= URLs not recognized (Facebook redirects /watch?v= to /watch/?v=)
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
        import re
        import httpx
        logger = logging.getLogger(__name__)

        from parsehub.parsers.base.ytdlp import YtParser
        from parsehub.provider_api.bilibili import BiliAPI
        # ParseHub 1.5.11+ renamed xhs_.py to xhs.py
        try:
            from parsehub.parsers.parser.xhs import XHSParser as XhsParser
        except ImportError:
            try:
                from parsehub.parsers.parser.xhs import XhsParser
            except ImportError:
                from parsehub.parsers.parser.xhs_ import XhsParser

        logger.info("🔧 Starting ParseHub patch...")

        # ParseHub 2.1.0: cli_args 替代 params，使用子进程调用 yt-dlp
        # 不再 patch _extract_info，而是 patch cli_args 和 get_cookie_text

        # Patch YtParser.get_cookie_text to handle cookie from ParseConfig
        original_get_cookie_text = YtParser.get_cookie_text

        def patched_get_cookie_text(self) -> str | None:
            """Patched get_cookie_text that handles cookies from ParseConfig"""
            # 首先尝试原有逻辑（YouTube 特定处理）
            result = original_get_cookie_text(self)
            if result:
                return result

            # 处理从 ParseConfig 传递的 cookie
            if not self.cookie:
                return None

            cookie_value = self.cookie.get_value() if hasattr(self.cookie, 'get_value') else self.cookie
            if not cookie_value:
                return None

            # 如果是文件路径，直接读取文件内容
            if isinstance(cookie_value, str) and os.path.exists(cookie_value):
                logger.info(f"🍪 [Patch] Reading cookie from file: {cookie_value}")
                with open(cookie_value, 'r') as f:
                    return f.read()

            # 如果是 cookie 字符串，需要判断平台并转换为 Netscape 格式
            # 但在这里我们无法获取 URL，所以返回 None，让 ParseHub 使用原有逻辑
            logger.info(f"🍪 [Patch] Cookie exists but not a file, skipping")
            return None

        YtParser.get_cookie_text = patched_get_cookie_text
        logger.info("✅ YtParser.get_cookie_text patched for ParseHub 2.1.0")

        # Patch YtbParse.get_cookie_text to support YOUTUBE_COOKIE environment variable
        from parsehub.parsers.parser.youtube import YtbParse
        original_ytb_get_cookie_text = YtbParse.get_cookie_text

        def patched_ytb_get_cookie_text(self) -> str | None:
            """Patched YouTube get_cookie_text that supports env var cookie file"""
            # 首先尝试原有逻辑（从 self.cookie 读取）
            result = original_ytb_get_cookie_text(self)
            if result:
                return result

            # 尝试从环境变量读取 YouTube cookie 文件
            youtube_cookie_file = os.getenv("YOUTUBE_COOKIE")
            if youtube_cookie_file and os.path.exists(youtube_cookie_file):
                logger.info(f"🍪 [Patch] Using YouTube cookie from env: {youtube_cookie_file}")
                with open(youtube_cookie_file, 'r') as f:
                    return f.read()

            return None

        YtbParse.get_cookie_text = patched_ytb_get_cookie_text
        logger.info("✅ YtbParse.get_cookie_text patched: support YOUTUBE_COOKIE env var")

        # Patch YtParser._parse to handle missing 'description' field (e.g. bangumi)
        import asyncio
        from parsehub.parsers.base.ytdlp import YtVideoInfo
        original_yt_parse = YtParser._parse

        async def fixed_yt_parse(self, url):
            try:
                # ParseHub 2.1.0: _extract_info 已改为异步方法，直接 await 调用
                dl = await asyncio.wait_for(self._extract_info(url), timeout=30)
            except TimeoutError as e:
                from parsehub.errors import ParseError
                raise ParseError("解析视频信息超时") from e
            except Exception as e:
                from parsehub.errors import ParseError
                raise ParseError(f"解析视频信息失败: {str(e)}") from e

            if dl.get("_type") and dl["_type"] == "playlist":
                entries = dl.get("entries", [])
                if entries:
                    entries = list(entries)
                if not entries:
                    from parsehub.errors import ParseError
                    raise ParseError("播放列表为空")
                dl = entries[0]
                url = dl.get("webpage_url", url)
            return YtVideoInfo(
                title=dl.get("title", ""),
                description=dl.get("description", ""),
                thumbnail=dl.get("thumbnail", ""),
                duration=dl.get("duration", 0),
                url=url,
                width=dl.get("width", 0),
                height=dl.get("height", 0),
                info_json=dl,  # ParseHub 2.1.0: 使用 info_json 而非 paramss
            )

        YtParser._parse = fixed_yt_parse
        logger.info("✅ YtParser._parse patched: safe .get() for missing fields (bangumi support)")

        # Note: YtParser._parse doesn't need patching anymore - using original implementation
        # YouTube downloads: Primary = yt-dlp, Fallback = pytubefix
        logger.info("ℹ️ YtParser._parse: using original implementation (YouTube download: yt-dlp → pytubefix)")

        # Patch YtVideoParseResult.download to use pytubefix for YouTube
        from parsehub.parsers.base.ytdlp import YtVideoParseResult
        from parsehub.types import DownloadResult, VideoFile
        from parsehub.errors import DownloadError
        from pathlib import Path
        import time
        import asyncio

        original_yt_video_download = YtVideoParseResult._do_download

        async def patched_yt_video_download(self, *, output_dir, callback=None, callback_args=(), callback_kwargs=None, proxy=None, headers=None, connections=4):
            """Patched _do_download that uses yt-dlp for YouTube (with pytubefix fallback)"""
            # 2.0.1: YtVideoParseResult.video (VideoRef) 存储在 self.media 中
            # 优先使用 self.dl.url (原始YouTube URL)，fallback 到 self.media.url 或 self.raw_url
            video_url = (self.dl.url if self.dl else None) or (self.media.url if self.media else None) or self.raw_url or ""
            logger.info(f"🔍 [Patch] patched_yt_video_download called: url={video_url[:100] if video_url else 'None'}")

            # Check if this is a YouTube URL
            url_lower = video_url.lower()
            is_youtube = any(domain in url_lower for domain in ['youtube.com', 'youtu.be'])

            if is_youtube:
                logger.info(f"📥 [Patch] Detected YouTube URL, using yt-dlp (primary): {video_url[:80]}...")

                # Try yt-dlp first (primary method)
                try:
                    logger.info(f"🎬 [yt-dlp] Attempting download with yt-dlp...")
                    result = await original_yt_video_download(self, output_dir=output_dir, callback=callback, callback_args=callback_args, callback_kwargs=callback_kwargs, proxy=proxy, headers=headers, connections=connections)
                    logger.info(f"✅ [Patch] yt-dlp download completed successfully")
                    return result
                except Exception as e:
                    logger.warning(f"⚠️ [Patch] yt-dlp download failed: {e}, falling back to pytubefix")

                    # Fallback to pytubefix (secondary method)
                    try:
                        # Download directory
                        dir_ = Path(output_dir)
                        dir_.mkdir(parents=True, exist_ok=True)

                        if callback:
                            if callback_kwargs is None:
                                callback_kwargs = {}
                            await callback(0, 0, "正在下载 (pytubefix)...", *callback_args, **callback_kwargs)

                        # Use pytubefix to download
                        from pytubefix import YouTube

                        def download_with_pytubefix():
                            """Synchronous function to download with pytubefix"""
                            # Check if YouTube proxy is configured
                            youtube_proxy = os.getenv("YOUTUBE_PROXY")
                            proxies = None
                            if youtube_proxy:
                                # Parse proxy URL to dict format for pytubefix
                                # pytubefix expects: {'http': 'proxy_url', 'https': 'proxy_url'}
                                proxies = {
                                    'http': youtube_proxy,
                                    'https': youtube_proxy
                                }
                                logger.info(f"🌐 [pytubefix] Using YouTube proxy: {youtube_proxy[:30]}...")

                            # Check if OAuth token is configured
                            youtube_oauth_token = os.getenv("YOUTUBE_OAUTH_TOKEN")
                            use_oauth = False
                            token_file = None

                            if youtube_oauth_token and os.path.exists(youtube_oauth_token):
                                use_oauth = True
                                token_file = youtube_oauth_token
                                logger.info(f"🔐 [pytubefix] Using YouTube OAuth token: {youtube_oauth_token}")

                            # Use 'WEB' client to enable automatic po_token generation
                            # This bypasses YouTube's bot detection without manual token extraction
                            # nodejs dependency is automatically installed via nodejs-wheel-binaries
                            # OAuth can be used as alternative to proxy (but requires Google account)
                            yt = YouTube(
                                video_url,
                                client='WEB',
                                proxies=proxies,
                                use_oauth=use_oauth,
                                allow_oauth_cache=True,
                                token_file=token_file
                            )

                            # Get highest resolution progressive stream (video + audio)
                            stream = yt.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').desc().first()

                            if not stream:
                                # Fallback to highest resolution stream
                                stream = yt.streams.get_highest_resolution()

                            if not stream:
                                raise DownloadError("No suitable stream found")

                            # Download to directory
                            logger.info(f"🎬 [pytubefix] Downloading: {yt.title} ({stream.resolution})")
                            output_path = stream.download(output_path=str(dir_), filename=f"video_{time.time_ns()}.mp4")

                            return output_path, yt

                        # Run in thread to avoid blocking
                        output_path, yt = await asyncio.to_thread(download_with_pytubefix)

                        logger.info(f"✅ [Patch] pytubefix fallback download completed: {output_path}")

                        return DownloadResult(
                            VideoFile(
                                path=str(output_path),
                                height=0,  # pytubefix doesn't provide these easily
                                width=0,
                                duration=yt.length if hasattr(yt, 'length') else 0,
                            ),
                            dir_,
                        )
                    except Exception as pytubefix_error:
                        logger.error(f"❌ [Patch] pytubefix fallback also failed: {pytubefix_error}")
                        # Both methods failed, raise the original yt-dlp error
                        raise DownloadError(f"YouTube download failed: yt-dlp error: {e}, pytubefix error: {pytubefix_error}")
            else:
                # Not a YouTube URL, use original yt-dlp download
                return await original_yt_video_download(self, output_dir=output_dir, callback=callback, callback_args=callback_args, callback_kwargs=callback_kwargs, proxy=proxy, headers=headers, connections=connections)

        YtVideoParseResult._do_download = patched_yt_video_download
        logger.info("✅ YtVideoParseResult._do_download patched: use yt-dlp for YouTube (pytubefix fallback)")

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

            # 添加必要的headers
            from yt_dlp.utils.networking import random_user_agent
            self.headers.update({
                "Referer": "https://www.bilibili.com/",
                "Origin": "https://www.bilibili.com",
                "User-Agent": random_user_agent()
            })
            if cookie:
                logger.info(f"🌐 [Patch] BiliAPI initialized with cookie and anti-crawler headers")
            else:
                logger.info(f"🌐 [Patch] BiliAPI initialized with anti-crawler headers (no cookie)")

        async def patched_get_video_info(self, url: str):
            """Patched get_video_info to use self.cookie and handle 412 security error"""
            bvid = self.get_bvid(url)
            # 使用self.cookie而不是硬编码None
            response = await self._get_client().get(
                "https://api.bilibili.com/x/web-interface/view/detail",
                params={"bvid": bvid},
                cookies=self.cookie  # 传入cookie！
            )
            # ParseHub 1.5.12+: Handle Bilibili security policy (HTTP 412)
            if response.status_code == 412:
                raise Exception('由于触发哔哩哔哩安全风控策略，该次访问请求被拒绝。')
            return response.json()

        BiliAPI.__init__ = patched_bili_init
        BiliAPI.get_video_info = patched_get_video_info

        # Note: BiliParse.bili_api_parse creates BiliAPI without cookie
        # But since we patched BiliAPI.__init__ to accept cookie parameter,
        # we need to ensure cookie is passed. The easiest way is to patch
        # the BiliAPI creation call in BiliParse, but that's complex.
        #
        # Instead, we rely on the fact that ParseConfig.cookie is accessible
        # via self.cookie in BiliParse. We just need BiliParse to pass it.
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

        # Patch XhsParser to handle empty download list and TikHub fallback
        # ParseHub 1.5.11+ uses new XHSAPI class, older versions use XHS class
        original_xhs_parse = XhsParser._do_parse

        # Check if we're using the new API (1.5.11+)
        try:
            from parsehub.provider_api.xhs import XHSAPI, XHSMediaType as MediaType, XHSPostType as PostType
            USE_NEW_XHS_API = True
            logger.info("🔍 [XHS] Detected ParseHub 1.5.13+ (new XHSAPI)")

            # Patch XHSAPI.__fetch_html to add follow_redirects=True
            # Without this, xhslink.com short URLs (302 redirect) are not followed,
            # causing empty HTML and truncated /no urlDefault fields on non-mainland IPs
            async def patched_xhsapi_fetch(self, url: str):
                async with httpx.AsyncClient(proxy=self.proxy, follow_redirects=True) as client:
                    return (await client.get(url, timeout=30)).text

            XHSAPI._XHSAPI__fetch_html = patched_xhsapi_fetch
            logger.info("✅ XHSAPI.__fetch_html patched: follow_redirects=True for short URL support")
        except ImportError:
            try:
                from parsehub.provider_api.xhs import XHSAPI, MediaType, PostType
                USE_NEW_XHS_API = True
                logger.info("🔍 [XHS] Detected ParseHub 1.5.11+ (new XHSAPI)")
            except ImportError:
                USE_NEW_XHS_API = False
                logger.info("🔍 [XHS] Detected ParseHub <1.5.11 (old XHS class)")

        async def patched_xhs_parse(self, url: str):
            """Patched XhsParser._do_parse to use TikHub as fallback"""
            from parsehub.types import VideoParseResult, ImageParseResult, VideoRef, ImageRef
            from parsehub.errors import ParseError

            # Call original parse, if it fails or returns empty, use TikHub
            try:
                result = await original_xhs_parse(self, url)
                if result:
                    return result
            except Exception as e:
                logger.warning(f"🌐 [Patch] XHS official parse failed: {e}, trying TikHub...")

            # TikHub fallback
            logger.warning(f"🌐 [Patch] XHS parse failed, trying TikHub...")
            tikhub_api_key = os.getenv("TIKHUB_API_KEY")
            if not tikhub_api_key:
                raise ParseError("小红书解析失败：无法获取下载地址（未配置TikHub API）")

            try:
                note_id_match = re.search(r'/(?:item|explore)/([a-f0-9]+)', url)
                if not note_id_match:
                    # Try to resolve short URL (e.g. xhslink.com)
                    try:
                        async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
                            r = await client.get(url)
                            resolved_url = str(r.url)
                        note_id_match = re.search(r'/(?:item|explore)/([a-f0-9]+)', resolved_url)
                    except Exception:
                        pass
                if not note_id_match:
                    raise ParseError(f"无法从URL提取note_id: {url}")

                note_id = note_id_match.group(1)
                headers = {"Authorization": f"Bearer {tikhub_api_key}"}

                # Primary: web/get_note_info_v7 (最稳定)
                logger.info(f"🎬 [TikHub] Trying primary endpoint: web/get_note_info_v7 (note_id={note_id})")
                try:
                    api_url = f"https://api.tikhub.io/api/v1/xiaohongshu/web/get_note_info_v7?note_id={note_id}"
                    async with httpx.AsyncClient(timeout=30.0, proxy=self.proxy) as client:
                        response = await client.get(api_url, headers=headers)

                    if response.status_code == 200:
                        data = response.json()
                        items = data.get("data", [])
                        if isinstance(items, list) and items:
                            note_item = items[0].get("note_list", [{}])[0]
                            title = note_item.get("title", "")
                            desc = note_item.get("desc", "")
                            note_type = note_item.get("type", "")

                            if note_type == "video":
                                video = note_item.get("video", {})
                                consumer = video.get("consumer", {})
                                origin_video_key = consumer.get("origin_video_key", "")
                                if origin_video_key:
                                    video_url = f"https://sns-na-i6.xhscdn.com/{origin_video_key}"
                                    logger.info(f"✅ [TikHub] XHS video via web/get_note_info_v7")
                                    return VideoParseResult(video=VideoRef(url=video_url), title=title, content=desc)

                            images_list = note_item.get("images_list", [])
                            if images_list:
                                photos = []
                                for img in images_list:
                                    img_url = img.get("url", "") or img.get("url_multi_level", {}).get("high", "")
                                    if img_url:
                                        img_url = re.sub(r'format/(heif|heic|webp|avif)', 'format/jpg', img_url)
                                        photos.append(ImageRef(url=img_url, ext="jpg", width=img.get("width", 0), height=img.get("height", 0)))
                                if photos:
                                    logger.info(f"✅ [TikHub] XHS {len(photos)} images via web/get_note_info_v7")
                                    return ImageParseResult(photo=photos, title=title, content=desc)
                except Exception as v7_error:
                    logger.warning(f"⚠️ [TikHub] web/get_note_info_v7 failed: {v7_error}")

                logger.info(f"🔄 [TikHub] Fallback to app_v2 endpoints")

                # First call video endpoint to check note type
                api_url = f"https://api.tikhub.io/api/v1/xiaohongshu/app_v2/get_video_note_detail?note_id={note_id}"
                async with httpx.AsyncClient(timeout=30.0, proxy=self.proxy) as client:
                    response = await client.get(api_url, headers=headers)

                if response.status_code == 200:
                    data = response.json()
                    if data.get("code") == 200 and data.get("data", {}).get("data"):
                        note_data = data["data"]["data"][0]
                        note_type = note_data.get("type", "")

                        if note_type == "video":
                            title = note_data.get("title", "")
                            desc = note_data.get("desc", "")
                            k_th = {"title": title, "content": desc}

                            video_info_v2 = note_data.get("video_info_v2", {})
                            media = video_info_v2.get("media", {})
                            stream = media.get("stream", {})

                            h264_list = stream.get("h264", [])
                            if h264_list:
                                video_stream = h264_list[0]
                                video_url = video_stream.get("master_url", "")
                                if not video_url:
                                    backup_urls = video_stream.get("backup_urls", [])
                                    if backup_urls:
                                        video_url = backup_urls[0]

                                if video_url:
                                    video_meta = media.get("video", {})
                                    width = video_stream.get("width", 0) or video_meta.get("width", 0)
                                    height = video_stream.get("height", 0) or video_meta.get("height", 0)
                                    duration = video_stream.get("duration", 0) // 1000

                                    logger.info(f"✅ [TikHub] Got XHS video URL (app_v2): {video_url[:80]}")
                                    return VideoParseResult(
                                        video=VideoRef(url=video_url, width=width, height=height, duration=duration),
                                        **k_th
                                    )
                        else:
                            # note_type is not "video", it's an image post
                            # Call image endpoint with retry
                            max_retries = 3
                            for attempt in range(max_retries):
                                try:
                                    logger.info(f"🎬 [TikHub] Detected image post, calling image endpoint (attempt {attempt + 1}/{max_retries})")
                                    api_url = f"https://api.tikhub.io/api/v1/xiaohongshu/app_v2/get_image_note_detail?note_id={note_id}"
                                    async with httpx.AsyncClient(timeout=30.0, proxy=self.proxy) as client:
                                        response = await client.get(api_url, headers=headers)

                                    if response.status_code == 200:
                                        data = response.json()
                                        if data.get("code") == 200 and data.get("data", {}).get("data"):
                                            note_data = data["data"]["data"][0]

                                            # Try data.data[0].note_list[0] structure first (app_v2 format)
                                            note_list = note_data.get("note_list", [])
                                            if note_list:
                                                note_item = note_list[0]
                                                title = note_item.get("title", "")
                                                desc = note_item.get("desc", "")
                                                k_th = {"title": title, "content": desc}
                                                images_list = note_item.get("images_list", [])
                                            else:
                                                # Fallback: data.data[0] directly
                                                title = note_data.get("title", "")
                                                desc = note_data.get("desc", "")
                                                k_th = {"title": title, "content": desc}
                                                images_list = note_data.get("images_list", [])

                                            if images_list:
                                                photos = []
                                                for img in images_list:
                                                    img_url = img.get("url", "")
                                                    if img_url:
                                                        # Force JPEG: replace heif/webp/avif format params in URL
                                                        img_url = re.sub(r'format/(heif|heic|webp|avif)', 'format/jpg', img_url)
                                                        width = img.get("width", 0)
                                                        height = img.get("height", 0)
                                                        photos.append(ImageRef(url=img_url, ext="jpg", width=width, height=height))

                                                if photos:
                                                    logger.info(f"✅ [TikHub] Got XHS {len(photos)} images (app_v2)")
                                                    return ImageParseResult(photo=photos, **k_th)

                                    logger.warning(f"⚠️ [TikHub] Image endpoint attempt {attempt + 1} failed, retrying...")
                                except Exception as e:
                                    logger.warning(f"⚠️ [TikHub] Image endpoint attempt {attempt + 1} error: {e}")
                                    if attempt == max_retries - 1:
                                        break

                # Fallback: app/get_note_info (handles both video and image, returns international CDN URLs)
                logger.info(f"🔄 [TikHub] Trying fallback endpoint: app/get_note_info")
                try:
                    api_url = f"https://api.tikhub.io/api/v1/xiaohongshu/app/get_note_info?note_id={note_id}"
                    async with httpx.AsyncClient(timeout=30.0, proxy=self.proxy) as client:
                        response = await client.get(api_url, headers=headers)

                    if response.status_code == 200:
                        data = response.json()
                        if data.get("code") == 200 and data.get("data", {}).get("data"):
                            note_data = data["data"]["data"][0]
                            note_list = note_data.get("note_list", [])
                            note_item = note_list[0] if note_list else note_data

                            title = note_item.get("title", "")
                            desc = note_item.get("desc", "")
                            k_th = {"title": title, "content": desc}
                            note_type = note_item.get("type", "")

                            if note_type == "video":
                                video = note_item.get("video", {})
                                consumer = video.get("consumer", {})
                                origin_video_key = consumer.get("origin_video_key", "")
                                if origin_video_key:
                                    video_url = f"https://sns-na-i6.xhscdn.com/{origin_video_key}"
                                    logger.info(f"✅ [TikHub] Got XHS video via app/get_note_info")
                                    return VideoParseResult(video=VideoRef(url=video_url), **k_th)

                            images_list = note_item.get("images_list", [])
                            if images_list:
                                photos = []
                                for img in images_list:
                                    img_url = img.get("url", "")
                                    if not img_url:
                                        # Try url_multi_level.high
                                        img_url = img.get("url_multi_level", {}).get("high", "")
                                    if img_url:
                                        img_url = re.sub(r'format/(heif|heic|webp|avif)', 'format/jpg', img_url)
                                        width = img.get("width", 0)
                                        height = img.get("height", 0)
                                        photos.append(ImageRef(url=img_url, ext="jpg", width=width, height=height))
                                if photos:
                                    logger.info(f"✅ [TikHub] Got XHS {len(photos)} images via app/get_note_info")
                                    return ImageParseResult(photo=photos, **k_th)
                except Exception as app_error:
                    logger.warning(f"⚠️ [TikHub] app/get_note_info failed: {app_error}")

                raise ParseError("TikHub所有endpoint均无法获取视频或图片URL")

            except ParseError:
                raise
            except Exception as e:
                logger.error(f"❌ [TikHub] XHS解析失败: {e}")
                raise ParseError(f"小红书解析失败：官方和TikHub都无法获取下载地址 (TikHub error: {e})")

        XhsParser._do_parse = patched_xhs_parse
        logger.info("✅ XhsParser patched: handle empty download list + TikHub fallback")

        # Patch DouyinParser to use TikHub API for direct download
        from parsehub.parsers.parser import DouyinParser

        original_douyin_parse = DouyinParser._do_parse

        async def patched_douyin_parse(self, url: str):
            """Patched _do_parse that uses TikHub as fallback when official API fails"""
            from parsehub.types import VideoParseResult
            from parsehub.errors import ParseError

            # Try official parser first (now supports Story/日常 with SignerPy)
            try:
                result = await original_douyin_parse(self, url)
                # 检查是否为Story/日常类型
                if '/note/' in url:
                    logger.info(f"✅ [Douyin] Story/日常解析成功 (官方API)")
                return result
            except (ParseError, Exception) as e:
                error_msg = str(e)
                # 如果是SignerPy缺失错误，提示用户安装
                if "SignerPy" in error_msg:
                    logger.error(f"❌ [Douyin] 抖音Story/日常需要安装SignerPy: pip install SignerPy")
                    raise ParseError("抖音Story/日常解析失败: 缺少SignerPy依赖，请运行 pip install SignerPy")
                logger.warning(f"⚠️ [Douyin] Official parser failed: {e}, trying TikHub...")

            # Fallback to TikHub
            tikhub_api_key = os.getenv("TIKHUB_API_KEY")
            if not tikhub_api_key:
                raise ParseError("官方解析失败且未配置TikHub API")

            try:
                # Extract aweme_id from URL (支持 /video/, /note/, modal_id 三种格式)
                aweme_id_match = re.search(r'modal_id=(\d+)', url)
                if not aweme_id_match:
                    aweme_id_match = re.search(r'/video/(\d+)', url)
                if not aweme_id_match:
                    aweme_id_match = re.search(r'/note/(\d+)', url)  # Story/日常格式

                if not aweme_id_match:
                    raise ParseError(f"无法从URL提取aweme_id: {url}")

                aweme_id = aweme_id_match.group(1)
                logger.info(f"🎬 [TikHub] Fetching Douyin video via TikHub: {aweme_id}")

                # Call TikHub Douyin API
                api_url = f"https://api.tikhub.io/api/v1/douyin/web/fetch_one_video?aweme_id={aweme_id}"
                headers = {"Authorization": f"Bearer {tikhub_api_key}"}

                with httpx.Client(timeout=30.0) as client:
                    response = client.get(api_url, headers=headers)

                if response.status_code != 200:
                    raise ParseError(f"TikHub API请求失败: HTTP {response.status_code}")

                data = response.json()
                if data.get("code") != 200 or not data.get("data"):
                    raise ParseError(f"TikHub API返回错误: {data.get('message', 'Unknown error')}")

                aweme_detail = data["data"]["aweme_detail"]
                video = aweme_detail.get("video", {})
                bit_rates = video.get("bit_rate", [])

                if not bit_rates:
                    raise ParseError("TikHub返回数据中没有视频")

                # Use best quality (first item)
                best_video = bit_rates[0]
                play_addr = best_video.get("play_addr", {})
                url_list = play_addr.get("url_list", [])

                if not url_list:
                    raise ParseError("TikHub返回数据中没有下载URL")

                download_url = url_list[0]
                title = aweme_detail.get("desc", "")

                # Get video metadata
                width = play_addr.get("width", 0)
                height = play_addr.get("height", 0)
                # Get duration from video object (in milliseconds), convert to seconds
                duration = video.get("duration", 0) // 1000

                file_size_mb = play_addr.get("data_size", 0) / 1024 / 1024
                logger.info(f"✅ [TikHub] Got Douyin video ({best_video.get('gear_name', 'unknown')}, {width}x{height}, {duration}s, {file_size_mb:.2f}MB)")

                from parsehub.types import VideoRef
                return VideoParseResult(
                    title=title,
                    content=title,
                    video=VideoRef(
                        url=download_url,
                        width=width,
                        height=height,
                        duration=duration,
                    ),
                )

            except Exception as e:
                logger.error(f"❌ [TikHub] Douyin解析失败: {e}")
                raise ParseError(f"TikHub解析失败: {e}")

        DouyinParser._do_parse = patched_douyin_parse
        logger.info("✅ DouyinParser patched: use TikHub as fallback when official parser fails")

        # Patch TikTokParser: try official App API first, fall back to TikHub
        from parsehub.parsers.parser.tiktok import TikTokParser

        original_tiktok_do_parse = TikTokParser._do_parse
        original_tiktok_fetch_api = TikTokParser._fetch_api_result

        async def patched_tiktok_fetch_api(self, url: str):
            """Override to use max_retries=1 so fallback to TikHub is fast."""
            from parsehub.provider_api.tiktok import TikTokWebCrawler
            from parsehub.parsers.parser.tiktok import TikTokApiResult
            from parsehub.errors import ParseError
            crawler = TikTokWebCrawler(proxy=self.proxy, cookie=self.cookie, max_retries=1)
            try:
                response = await crawler.parse(url)
                return TikTokApiResult.parse(response)
            except ParseError:
                raise
            except Exception as e:
                raise ParseError(f"TikTok 解析失败: {e}") from e

        TikTokParser._fetch_api_result = patched_tiktok_fetch_api

        async def patched_tiktok_parse(self, url: str):
            """Try official TikTokParser first, fall back to TikHub on failure."""
            from parsehub.types import VideoParseResult, ImageParseResult
            from parsehub.errors import ParseError

            # Try official parser (new App API, max_retries=1 for fast fallback)
            try:
                return await original_tiktok_do_parse(self, url)
            except (ParseError, Exception) as e:
                logger.warning(f"⚠️ [TikTok] Official parser failed: {e}, trying TikHub...")

            tikhub_api_key = os.getenv("TIKHUB_API_KEY")
            if not tikhub_api_key:
                raise ParseError(f"TikTok官方解析失败且未配置TikHub API")

            try:
                logger.info(f"🎬 [TikHub] Parsing TikTok: {url[:80]}...")

                # Need aweme_id — resolve short links first if needed
                video_id_match = re.search(r'/(?:video|photo)/(\d+)', url)
                if not video_id_match:
                    # Try to resolve redirect to get canonical URL
                    async with httpx.AsyncClient(
                        timeout=15.0,
                        follow_redirects=True,
                        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                    ) as client:
                        r = await client.get(url)
                        video_id_match = re.search(r'/(?:video|photo)/(\d+)', str(r.url))

                if not video_id_match:
                    raise ParseError(f"无法从URL提取TikTok视频ID: {url}")

                video_id = video_id_match.group(1)
                logger.info(f"🎬 [TikHub] Fetching TikTok aweme_id: {video_id}")

                api_url = f"https://api.tikhub.io/api/v1/tiktok/app/v3/fetch_one_video?aweme_id={video_id}"
                headers = {"Authorization": f"Bearer {tikhub_api_key}"}

                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.get(api_url, headers=headers)

                if response.status_code != 200:
                    raise ParseError(f"TikHub API请求失败: HTTP {response.status_code}")

                data = response.json()
                if data.get("code") != 200 or not data.get("data"):
                    raise ParseError(f"TikHub API返回错误: {data.get('message', 'Unknown error')}")

                aweme_detail = data["data"].get("aweme_detail")
                if not aweme_detail:
                    raise ParseError("TikHub返回数据中没有aweme_detail")

                desc = aweme_detail.get("desc", "")
                video = aweme_detail.get("video", {})

                # Image post (photo carousel)
                image_post_info = aweme_detail.get("image_post_info")
                if image_post_info:
                    from parsehub.types import ImageRef
                    image_list = []
                    for img in image_post_info.get("images", []):
                        url_list = img.get("display_image", {}).get("url_list", [])
                        if url_list:
                            image_list.append(ImageRef(url=url_list[0]))
                    if not image_list:
                        raise ParseError("TikHub返回图文数据但图片列表为空")
                    logger.info(f"✅ [TikHub] Got TikTok image post with {len(image_list)} images")
                    return ImageParseResult(title=desc, photo=image_list)

                # Video post — prefer H.264 for compatibility
                play_addr_h264 = video.get("play_addr_h264", {})
                url_list_h264 = play_addr_h264.get("url_list", [])
                if url_list_h264:
                    width = play_addr_h264.get("width", 0)
                    height = play_addr_h264.get("height", 0)
                    duration = video.get("duration", 0) // 1000
                    logger.info(f"✅ [TikHub] Got TikTok video (H.264, {width}x{height}, {duration}s)")
                    from parsehub.types import VideoRef
                    return VideoParseResult(
                        title=desc,
                        video=VideoRef(url=url_list_h264[0], width=width, height=height, duration=duration),
                    )

                # Fallback: best quality from bit_rate list
                bit_rates = video.get("bit_rate", [])
                if bit_rates:
                    bit_rates.sort(key=lambda x: x.get("bit_rate", 0), reverse=True)
                    best = bit_rates[0]
                    play_addr = best.get("play_addr", {})
                    url_list = play_addr.get("url_list", [])
                    if url_list:
                        width = play_addr.get("width", 0)
                        height = play_addr.get("height", 0)
                        duration = video.get("duration", 0) // 1000
                        logger.info(f"✅ [TikHub] Got TikTok video ({best.get('gear_name', 'unknown')}, {width}x{height}, {duration}s)")
                        from parsehub.types import VideoRef
                        return VideoParseResult(
                            title=desc,
                            video=VideoRef(url=url_list[0], width=width, height=height, duration=duration),
                        )

                # Last resort: play_addr directly
                play_addr = video.get("play_addr", {})
                url_list = play_addr.get("url_list", [])
                if url_list:
                    duration = video.get("duration", 0) // 1000
                    logger.info(f"✅ [TikHub] Got TikTok video (play_addr fallback)")
                    from parsehub.types import VideoRef
                    return VideoParseResult(
                        title=desc,
                        video=VideoRef(url=url_list[0], duration=duration),
                    )

                raise ParseError("TikHub返回数据中没有可用的视频或图片")

            except ParseError:
                raise
            except Exception as e:
                logger.error(f"❌ [TikHub] TikTok解析失败: {e}")
                raise ParseError(f"TikTok官方和TikHub都失败: {e}")

        TikTokParser._do_parse = patched_tiktok_parse
        logger.info("✅ TikTokParser patched: official App API first, TikHub fallback")

        # Note: TieBa API in ParseHub 2.0.15+ doesn't require Cookie
        # The new fetch_post_data method uses API endpoint which works without authentication
        logger.info("ℹ️ TieBa: No patch needed (2.0.15+ API works without Cookie)")

        # Note: ParseHub 2.0.34+ removed instaloader entirely and rewrote Instagram
        # parsing on top of a self-hosted InstagramAPI (GraphQL/v1). __match__ now
        # natively supports reels/username paths, so that regex patch is no longer needed.
        from parsehub.parsers.parser.instagram import InstagramParser
        from parsehub.provider_api.instagram import InstagramAPI, InstagramMediaType

        # Patch Instagram parse method to pass cookie to _parse
        # (ParseHub 2.0.39's official _do_parse still doesn't forward self.cookie to _parse)
        original_instagram_parse = InstagramParser._do_parse

        async def patched_instagram_parse(self, url: str):
            """Patched _do_parse that passes cookie to _parse method"""
            from parsehub.types import VideoParseResult, ImageParseResult, MultimediaParseResult
            from parsehub.types import VideoRef, ImageRef
            from parsehub.errors import ParseError

            shortcode = self.get_short_code(url)
            if not shortcode:
                raise ValueError("Instagram帖子链接无效")

            # Pass cookie to _parse (FIX: original code doesn't pass cookie)
            logger.info(f"✅ [Instagram] Passing cookie to _parse: {bool(self.cookie)}")
            post = await self._parse(url, shortcode, self.cookie)

            width, height = post.width, post.height

            k = {"title": post.title, "content": post.caption}
            match post.typename:
                case InstagramMediaType.SIDECAR:
                    media = [
                        VideoRef(url=i.video_url, thumb_url=i.display_url, width=i.width, height=i.height)
                        if i.is_video and i.video_url
                        else ImageRef(url=i.display_url, width=i.width, height=i.height)
                        for i in post.get_sidecar_nodes()
                    ]
                    return MultimediaParseResult(media=media, **k)
                case InstagramMediaType.IMAGE:
                    return ImageParseResult(photo=[ImageRef(url=post.url, width=width, height=height)], **k)
                case InstagramMediaType.VIDEO:
                    return VideoParseResult(
                        video=VideoRef(
                            url=post.video_url or post.url,
                            thumb_url=post.url,
                            duration=int(post.video_duration or 0),
                            width=width,
                            height=height,
                        ),
                        **k,
                    )
                case _:
                    raise ParseError("不支持的类型")

        InstagramParser._do_parse = patched_instagram_parse
        logger.info("✅ InstagramParser patched: Fix cookie passing to _parse method")

        # Patch InstagramAPI's HTTP client to use randomized UA + more anti-crawler headers
        # (replaces the old MyInstaloaderContext header patch, removed with instaloader in 2.0.34+)
        original_instagram_new_client = InstagramAPI._new_client

        def patched_instagram_new_client(self):
            from yt_dlp.utils.networking import random_user_agent

            client = original_instagram_new_client(self)
            client.headers.update({
                'User-Agent': random_user_agent(),
                'Accept-Language': 'zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7',
                'Sec-Fetch-Dest': 'empty',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'same-origin',
            })
            return client

        InstagramAPI._new_client = patched_instagram_new_client
        logger.info("✅ InstagramAPI patched: Enhanced headers for better compatibility")

        # Patch BiliParse to support bangumi/play/ URL format (番剧/影视)
        from parsehub.parsers.parser.bilibili import BiliParse

        # Original regex: r"^(http(s)?://)?((((w){3}.|(m).|(t).)?bilibili\.com)/(video|opus|\b\d{18,19}\b)|b23.tv|bili2233.cn).*"
        # Problem: bangumi/play/epXXX URLs (番剧) are not matched
        # Fix: Add bangumi/play to the path alternatives
        BiliParse.__match__ = r"^(http(s)?://)?((((w){3}.|(m).|(t).)?bilibili\.com)/(video|opus|bangumi/play|\b\d{18,19}\b)|b23.tv|bili2233.cn).*"
        logger.info("✅ BiliParse patched: Support bangumi/play/ URL format (番剧/影视)")

        # Patch FacebookParse to support watch/?v= URL format (with optional slash)
        from parsehub.parsers.parser.facebook import FacebookParse

        # Original regex: r"^(http(s)?://)?.+facebook.com/(watch\?v|share/[v,r]|.+/videos/|reel/).*"
        # Problem: watch\?v doesn't match watch/?v= (Facebook's actual URL format)
        # Fix: watch/?\?v makes the slash optional
        FacebookParse.__match__ = r"^(http(s)?://)?.+facebook.com/(watch/?\?v|share/[v,r]|.+/videos/|reel/).*"
        logger.info("✅ FacebookParse patched: Support watch/?v= URL format (with optional slash)")

        # Patch FacebookParse cli_args property to use compatible format selector
        # ParseHub 2.1.0: cli_args 替代 params，返回 CLI 参数列表
        original_facebook_cli_args = FacebookParse.cli_args.fget

        def patched_facebook_cli_args(self) -> list[str]:
            """Patched cli_args property with Facebook-compatible format selector"""
            args = original_facebook_cli_args(self).copy()
            # Add format selector for Facebook (progressive video streams)
            args.extend(["--format", "best[res<=1080]/best"])
            return args

        FacebookParse.cli_args = property(patched_facebook_cli_args)
        logger.info("✅ FacebookParse.cli_args patched: Use compatible format selector (best[res<=1080]/best)")

        # Patch ParseHub.parse to skip get_raw_url for Facebook watch/?v= URLs
        # Root cause: ParseHub.parse() calls get_raw_url() BEFORE calling parser.parse()
        # This strips query parameters from Facebook URLs
        from parsehub import ParseHub
        original_parsehub_parse = ParseHub.parse

        async def patched_parsehub_parse(self, url: str, *, proxy: str | None = None, cookie: str | dict | None = None):
            """Patched ParseHub.parse that skips get_raw_url for Facebook watch/?v= URLs"""
            from parsehub.utils.helpers import SecretCookie

            parser = self._select_parser(url)
            if not parser:
                raise ValueError("不支持的平台")

            # BUG FIX: must wrap raw cookie in SecretCookie like the official implementation does
            # (parsehub/__init__.py: `parser(proxy=proxy, cookie=SecretCookie(cookie))`).
            # Passing the raw str/dict/None value directly sets self.cookie to that raw value,
            # and every parser's .params/._parse calls self.cookie.get_value() expecting a
            # SecretCookie object — when cookie=None (e.g. YouTube, which intentionally passes
            # None here since its cookie goes through a separate cookiefile/env-var path), this
            # crashes with "'NoneType' object has no attribute 'get_value'".
            p = parser(proxy=proxy, cookie=SecretCookie(cookie))

            # Check if this is a Facebook watch/?v= URL
            if isinstance(p, FacebookParse) and "?v=" in url:
                logger.info(f"✅ [ParseHub] Detected Facebook watch/?v= URL, skipping get_raw_url")
                logger.info(f"✅ [ParseHub] Calling _do_parse directly to preserve query parameters: {url}")
                # Skip parse() method entirely to preserve query parameters
                # Call _do_parse directly and set platform manually
                result = await p._do_parse(url)
                result.platform = p.__platform__
                return result
            else:
                # Use original implementation (calls get_raw_url first)
                return await p.parse(url)

        ParseHub.parse = patched_parsehub_parse
        logger.info("✅ ParseHub.parse patched: Skip get_raw_url for Facebook watch/?v= URLs")

        # Also patch FacebookParse.parse to skip its internal get_raw_url call
        original_facebook_parse = FacebookParse._do_parse

        async def patched_facebook_parse(self, url: str):
            """Patched FacebookParse._do_parse that skips get_raw_url for watch/?v= URLs"""
            if "?v=" in url:
                logger.info(f"✅ [Facebook] Detected ?v= parameter, calling _parse directly (skip get_raw_url)")
                # Skip all get_raw_url calls and call _parse directly
                # YtParser.parse also calls get_raw_url, so we bypass it too
                from parsehub.parsers.base.ytdlp import YtVideoParseResult
                from parsehub.types import VideoRef
                video_info = await self._parse(url)
                return YtVideoParseResult(
                    video=VideoRef(
                        url=video_info.url,
                        thumb_url=video_info.thumbnail,
                        width=video_info.width,
                        height=video_info.height,
                        duration=video_info.duration,
                    ),
                    title=video_info.title,
                    content=video_info.description,
                    dl=video_info,
                )
            else:
                # Use original implementation for other Facebook URLs
                return await original_facebook_parse(self, url)

        FacebookParse._do_parse = patched_facebook_parse
        logger.info("✅ FacebookParse._do_parse patched: Skip internal get_raw_url for watch/?v= URLs")

        return True

    except Exception as e:
        logger.error(f"❌ ParseHub patch failed: {e}")
        return False
