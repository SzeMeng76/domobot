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

            # YouTube特殊处理：使用专用代理和cookie（如果配置）
            # YouTube 的 bot 检测非常严格，需要使用代理和cookie绕过
            if "youtube.com" in url.lower() or "youtu.be" in url.lower():
                youtube_proxy = os.getenv("YOUTUBE_PROXY")
                if youtube_proxy:
                    params["proxy"] = youtube_proxy
                    logger.info(f"🌐 [Patch] Using YouTube proxy: {youtube_proxy[:30]}...")

                # YouTube Cookie 支持：从环境变量读取 cookie 文件路径
                # Cookie 可以帮助 yt-dlp 解析元数据，绕过登录验证
                youtube_cookie_from_env = os.getenv("YOUTUBE_COOKIE")
                if youtube_cookie_from_env and "cookiefile" not in params:
                    logger.info(f"🍪 [Patch] YouTube cookie from env: {youtube_cookie_from_env}")
                    if os.path.exists(youtube_cookie_from_env):
                        params["cookiefile"] = youtube_cookie_from_env
                        logger.info(f"🍪 [Patch] Using YouTube cookie file: {youtube_cookie_from_env}")
                    else:
                        logger.warning(f"⚠️ [Patch] YouTube cookie file not found: {youtube_cookie_from_env}")

            # Add cookies if configured (FIX: YtParser doesn't handle cookies)
            # 参考: yt_dlp/YoutubeDL.py:349 - cookiefile: File name or text stream from where cookies should be read
            temp_cookie_file = None

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

        # Note: YtParser._parse doesn't need patching anymore - using original implementation
        # YouTube downloads will be handled by pytubefix in the download method
        logger.info("ℹ️ YtParser._parse: using original implementation (YouTube download via pytubefix)")

        # Patch YtVideoParseResult.download to use pytubefix for YouTube
        from parsehub.parsers.base.yt_dlp_parser import YtVideoParseResult
        from parsehub.types import DownloadResult, Video
        from parsehub.config import DownloadConfig
        from parsehub.types.error import DownloadError
        from pathlib import Path
        import time
        import asyncio

        original_yt_video_download = YtVideoParseResult.download

        async def patched_yt_video_download(self, path=None, callback=None, callback_args=(), config=DownloadConfig()):
            """Patched download that uses pytubefix for YouTube"""
            logger.info(f"🔍 [Patch] patched_yt_video_download called: is_url={self.media.is_url}, path={self.media.path[:100] if self.media.path else 'None'}")

            if not self.media.is_url:
                logger.info(f"⚠️ [Patch] media.is_url is False, returning media directly")
                return self.media

            # Check if this is a YouTube URL
            url_lower = self.media.path.lower() if self.media.path else ""
            is_youtube = any(domain in url_lower for domain in ['youtube.com', 'youtu.be'])

            if is_youtube:
                logger.info(f"📥 [Patch] Detected YouTube URL, using pytubefix: {self.media.path[:80]}...")

                # Download directory
                dir_ = (config.save_dir if path is None else Path(path)).joinpath(f"{time.time_ns()}")
                dir_.mkdir(parents=True, exist_ok=True)

                if callback:
                    await callback(0, 0, "正在下载...", *callback_args)

                try:
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
                            self.media.path,
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

                    logger.info(f"✅ [Patch] pytubefix download completed: {output_path}")

                    return DownloadResult(
                        self,
                        Video(
                            path=str(output_path),
                            thumb_url=yt.thumbnail_url if hasattr(yt, 'thumbnail_url') else None,
                            height=0,  # pytubefix doesn't provide these easily
                            width=0,
                            duration=yt.length if hasattr(yt, 'length') else 0,
                        ),
                        dir_,
                    )
                except Exception as e:
                    logger.error(f"❌ [Patch] pytubefix download failed: {e}, falling back to yt-dlp")
                    # Fallback to original yt-dlp download
                    return await original_yt_video_download(self, path, callback, callback_args, config)
            else:
                # Not a YouTube URL, use original yt-dlp download
                return await original_yt_video_download(self, path, callback, callback_args, config)

        YtVideoParseResult.download = patched_yt_video_download
        logger.info("✅ YtVideoParseResult.download patched: use pytubefix for YouTube")

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
            """Patched XhsParser.parse to handle empty download list and use TikHub as fallback"""
            from parsehub.types import VideoParseResult, ImageParseResult, MultimediaParseResult, Video, Image
            from parsehub.parsers.parser.xhs_ import XHS, Log

            # 调用原始逻辑获取数据（标题、描述等元数据）
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
                    logger.warning(f"🌐 [Patch] XHS video has no download URLs from official parser, trying TikHub...")

                    # 尝试使用 TikHub API 获取视频 URL
                    tikhub_api_key = os.getenv("TIKHUB_API_KEY")
                    if not tikhub_api_key:
                        raise ParseError("小红书视频解析失败：无法获取下载地址（未配置TikHub API）")

                    try:
                        # 从 URL 提取 note_id
                        # URL 格式: https://www.xiaohongshu.com/discovery/item/69649bec000000000d00bfbb?...
                        import re
                        note_id_match = re.search(r'/item/([a-f0-9]+)', url)
                        if not note_id_match:
                            raise ParseError(f"无法从URL提取note_id: {url}")

                        note_id = note_id_match.group(1)
                        logger.info(f"🎬 [TikHub] Fetching XHS video via TikHub: {note_id}")

                        # 调用 TikHub API
                        api_url = f"https://api.tikhub.io/api/v1/xiaohongshu/app/get_note_info_v2?note_id={note_id}"
                        headers = {"Authorization": f"Bearer {tikhub_api_key}"}

                        async with httpx.AsyncClient(timeout=30.0) as client:
                            response = await client.get(api_url, headers=headers)

                        if response.status_code != 200:
                            raise ParseError(f"TikHub API请求失败: HTTP {response.status_code}")

                        data = response.json()
                        if data.get("code") != 200:
                            raise ParseError(f"TikHub API返回错误: {data.get('message', 'Unknown error')}")

                        # 提取视频 URL（数据结构: data.data.videoInfo.videoUrl）
                        inner_data = data.get("data", {}).get("data", {})
                        video_info = inner_data.get("videoInfo", {})
                        video_url = video_info.get("videoUrl")

                        if not video_url:
                            raise ParseError("TikHub返回数据中没有视频URL")

                        logger.info(f"✅ [TikHub] Got XHS video URL: {video_url[:80]}")

                        # 返回结果：使用官方解析的标题/描述 + TikHub的视频URL
                        return VideoParseResult(video=video_url, **k)

                    except ParseError:
                        raise
                    except Exception as e:
                        logger.error(f"❌ [TikHub] XHS解析失败: {e}")
                        raise ParseError(f"小红书视频解析失败：官方和TikHub都无法获取下载地址 (TikHub error: {e})")
                else:
                    # 官方解析成功，直接返回
                    return VideoParseResult(video=download_list[0], **k)

            # 图文类型：检查下载地址是否为空
            elif result["作品类型"] == "图文":
                download_list = result.get("下载地址", [])
                if not download_list:
                    logger.warning(f"🌐 [Patch] XHS images have no download URLs, returning empty ImageParseResult")
                    return ImageParseResult(photo=[], **k)

                photos = []
                for i in download_list:
                    # 保留 URL 但强制转换为 JPEG 格式（兼容 AI 总结）
                    # 小红书 CDN 支持 imageView2 参数进行格式转换
                    # 移除原有参数，添加格式转换参数确保返回 JPEG
                    base_url = i.split('?')[0] if '?' in i else i
                    # 添加格式转换参数：转为 JPEG，质量 85，宽度限制 1080
                    img_url = f"{base_url}?imageView2/2/w/1080/format/jpg"
                    ext = "jpg"
                    photos.append(Image(img_url, ext))
                return ImageParseResult(photo=photos, **k)

            else:
                raise ParseError("不支持的类型")

        XhsParser.parse = patched_xhs_parse
        logger.info("✅ XhsParser patched: handle empty download list")

        # Patch DouyinParser to use TikHub API for direct download
        from parsehub.parsers.parser import DouyinParser

        original_douyin_parse = DouyinParser.parse

        async def patched_douyin_parse(self, url: str):
            """Patched parse that uses TikHub as fallback when official API fails"""
            from parsehub.types import VideoParseResult
            from parsehub.types.error import ParseError

            # Try official parser first
            try:
                return await original_douyin_parse(self, url)
            except (ParseError, Exception) as e:
                logger.warning(f"⚠️ [Douyin] Official parser failed: {e}, trying TikHub...")

            # Fallback to TikHub
            tikhub_api_key = os.getenv("TIKHUB_API_KEY")
            if not tikhub_api_key:
                raise ParseError("官方解析失败且未配置TikHub API")

            try:
                url = await self.get_raw_url(url)

                # Extract aweme_id from URL
                aweme_id_match = re.search(r'modal_id=(\d+)', url)
                if not aweme_id_match:
                    aweme_id_match = re.search(r'/video/(\d+)', url)

                if not aweme_id_match:
                    raise ParseError("无法从URL提取aweme_id")

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

                from parsehub.types import Video
                return VideoParseResult(
                    raw_url=url,
                    title=title,
                    desc=title,
                    video=Video(
                        download_url,
                        width=width,
                        height=height,
                        duration=duration,
                    ),
                )

            except Exception as e:
                logger.error(f"❌ [TikHub] Douyin解析失败: {e}")
                raise ParseError(f"TikHub解析失败: {e}")

        DouyinParser.parse = patched_douyin_parse
        logger.info("✅ DouyinParser patched: use TikHub as fallback when official parser fails")

        # Patch DouyinParser to handle TikTok with TikHub API
        original_douyin_parse_api = DouyinParser.parse_api

        async def patched_douyin_parse_with_tiktok(self, url: str):
            """Enhanced parse that uses TikHub for TikTok videos"""
            from parsehub.types import VideoParseResult, ImageParseResult
            from parsehub.types.error import ParseError

            # Check if it's a TikTok URL
            is_tiktok = "tiktok.com" in url.lower()

            if not is_tiktok:
                # For Douyin, use the existing patched version
                return await patched_douyin_parse(self, url)

            # For TikTok, use TikHub API
            tikhub_api_key = os.getenv("TIKHUB_API_KEY")
            if not tikhub_api_key:
                logger.warning("⚠️ [TikTok] TIKHUB_API_KEY not configured, trying official parser...")
                try:
                    return await patched_douyin_parse(self, url)
                except Exception as e:
                    raise ParseError(f"TikTok解析失败且未配置TikHub API: {e}")

            try:
                # Get real URL (follows redirects for short URLs like vt.tiktok.com)
                url = await self.get_raw_url(url)
                logger.info(f"🎬 [TikHub] Parsing TikTok video: {url[:80]}...")

                # Extract video ID from TikTok URL (after redirect)
                # Supports: https://www.tiktok.com/@username/video/1234567890
                video_id_match = re.search(r'/video/(\d+)', url)
                if not video_id_match:
                    logger.error(f"❌ [TikHub] Cannot extract video ID from URL: {url}")
                    raise ParseError(f"无法从URL提取TikTok视频ID: {url}")

                video_id = video_id_match.group(1)
                logger.info(f"🎬 [TikHub] Fetching TikTok video ID: {video_id}")

                # Call TikHub TikTok API (use app/v3 endpoint)
                api_url = f"https://api.tikhub.io/api/v1/tiktok/app/v3/fetch_one_video?aweme_id={video_id}"
                headers = {"Authorization": f"Bearer {tikhub_api_key}"}

                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.get(api_url, headers=headers)

                if response.status_code != 200:
                    raise ParseError(f"TikHub API请求失败: HTTP {response.status_code}")

                data = response.json()
                if data.get("code") != 200:
                    raise ParseError(f"TikHub API返回错误: {data.get('message', 'Unknown error')}")

                if not data.get("data"):
                    raise ParseError("TikHub API返回空数据")

                aweme_detail = data["data"].get("aweme_detail")
                if not aweme_detail:
                    raise ParseError("TikHub返回数据中没有aweme_detail")

                desc = aweme_detail.get("desc", "")
                video = aweme_detail.get("video", {})

                # Check if it's an image post (photo carousel)
                image_post_info = aweme_detail.get("image_post_info")
                if image_post_info:
                    from parsehub.types import Image
                    images = image_post_info.get("images", [])
                    if images:
                        image_list = []
                        for img in images:
                            image_url_list = img.get("display_image", {}).get("url_list", [])
                            if image_url_list:
                                image_list.append(Image(image_url_list[0]))

                        logger.info(f"✅ [TikHub] Got TikTok image post with {len(image_list)} images")
                        return ImageParseResult(
                            raw_url=url,
                            title=desc,
                            photo=image_list,
                        )

                # Handle video post - prefer H.264 codec for better compatibility
                # TikTok bit_rate list uses ByteVC1/ByteVC2 which may not be compatible with all players
                play_addr_h264 = video.get("play_addr_h264", {})
                url_list_h264 = play_addr_h264.get("url_list", [])

                if url_list_h264:
                    # Use H.264 encoded video for maximum compatibility
                    download_url = url_list_h264[0]
                    width = play_addr_h264.get("width", 0)
                    height = play_addr_h264.get("height", 0)
                    duration = video.get("duration", 0) // 1000

                    logger.info(f"✅ [TikHub] Got TikTok video (H.264, {width}x{height}, {duration}s)")

                    from parsehub.types import Video
                    return VideoParseResult(
                        raw_url=url,
                        title=desc,
                        video=Video(
                            download_url,
                            width=width,
                            height=height,
                            duration=duration,
                        ),
                    )

                # Fallback: use bit_rate list if H.264 not available
                bit_rates = video.get("bit_rate", [])
                if bit_rates:
                    # Sort by quality (highest first) and get best quality
                    bit_rates.sort(key=lambda x: x.get("bit_rate", 0), reverse=True)
                    best_video = bit_rates[0]
                    play_addr = best_video.get("play_addr", {})
                    url_list = play_addr.get("url_list", [])

                    if url_list:
                        download_url = url_list[0]
                        width = play_addr.get("width", 0)
                        height = play_addr.get("height", 0)
                        duration = video.get("duration", 0) // 1000

                        logger.info(f"✅ [TikHub] Got TikTok video ({best_video.get('gear_name', 'unknown')}, {width}x{height}, {duration}s)")

                        from parsehub.types import Video
                        return VideoParseResult(
                            raw_url=url,
                            title=desc,
                            video=Video(
                                download_url,
                                width=width,
                                height=height,
                                duration=duration,
                            ),
                        )

                # Fallback: try play_addr directly
                play_addr = video.get("play_addr", {})
                url_list = play_addr.get("url_list", [])
                if url_list:
                    download_url = url_list[0]
                    duration = video.get("duration", 0) // 1000

                    logger.info(f"✅ [TikHub] Got TikTok video (fallback URL)")

                    from parsehub.types import Video
                    return VideoParseResult(
                        raw_url=url,
                        title=desc,
                        video=Video(download_url, duration=duration),
                    )

                raise ParseError("TikHub返回数据中没有可用的视频或图片")

            except ParseError:
                raise
            except Exception as e:
                logger.error(f"❌ [TikHub] TikTok解析失败: {e}")
                # Try official parser as last resort
                try:
                    logger.info("🔄 [TikTok] Trying official parser as fallback...")
                    return await patched_douyin_parse(self, url)
                except Exception as fallback_error:
                    raise ParseError(f"TikHub和官方解析器都失败: TikHub={e}, Official={fallback_error}")

        DouyinParser.parse = patched_douyin_parse_with_tiktok
        logger.info("✅ DouyinParser patched: TikHub support for TikTok videos and images")

        # Patch TieBa to support Cookie and better headers
        from parsehub.provider_api.tieba import TieBa

        original_tieba_get_html = TieBa.get_html

        async def patched_tieba_get_html(self, t_url):
            """Patched get_html with Cookie support and better headers"""
            # Get cookie from environment variable or ParseConfig
            cookie_str = os.getenv('TIEBA_COOKIE', None)

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                'Referer': 'https://tieba.baidu.com/',
            }

            if cookie_str:
                headers['Cookie'] = cookie_str
                logger.info(f"✅ [TieBa] Using Cookie to bypass security verification")

            async with httpx.AsyncClient(proxy=self.proxy) as c:
                return await c.get(t_url, headers=headers, timeout=15, follow_redirects=True)

        TieBa.get_html = patched_tieba_get_html
        logger.info("✅ TieBa patched: Cookie and headers support to bypass security verification")

        # Patch InstagramParser to support username/reel/ URL format and fix cookie passing
        from parsehub.parsers.parser.instagram import InstagramParser

        # Update regex to support both /reel/xxx and username/reel/xxx
        InstagramParser.__match__ = r"^(http(s)?://)(www\.|)instagram\.com/(p|reel|share|.*/p|.*/reel)/.*"
        logger.info("✅ InstagramParser patched: Support username/reel/ URL format")

        # Patch Instagram parse method to pass cookie to _parse
        original_instagram_parse = InstagramParser.parse

        async def patched_instagram_parse(self, url: str):
            """Patched parse that passes cookie to _parse method"""
            from parsehub.types import VideoParseResult, ImageParseResult, MultimediaParseResult
            from parsehub.types import Video, Image
            from parsehub.types.error import ParseError

            url = await self.get_raw_url(url)

            shortcode = self.get_short_code(url)
            if not shortcode:
                raise ValueError("Instagram帖子链接无效")

            # Pass cookie to _parse (FIX: original code doesn't pass cookie)
            logger.info(f"✅ [Instagram] Passing cookie to _parse: {bool(self.cfg.cookie)}")
            post = await self._parse(url, shortcode, self.cfg.cookie)

            try:
                dimensions: dict = post._field("dimensions")
            except KeyError:
                dimensions = {}
            width, height = dimensions.get("width", 0) or 0, dimensions.get("height", 0) or 0

            k = {"title": post.title, "desc": post.caption, "raw_url": url}
            match post.typename:
                case "GraphSidecar":
                    media = [
                        Video(i.video_url, thumb_url=i.display_url, width=i.width, height=i.height)
                        if i.is_video
                        else Image(i.display_url, width=i.width, height=i.height)
                        for i in post.get_sidecar_nodes()
                    ]
                    return MultimediaParseResult(media=media, **k)
                case "GraphImage":
                    return ImageParseResult(photo=[Image(post.url, width=width, height=height)], **k)
                case "GraphVideo":
                    return VideoParseResult(
                        video=Video(
                            post.video_url,
                            thumb_url=post.url,
                            duration=int(post.video_duration),
                            width=width,
                            height=height,
                        ),
                        **k,
                    )
                case _:
                    raise ParseError("不支持的类型")

        InstagramParser.parse = patched_instagram_parse
        logger.info("✅ InstagramParser patched: Fix cookie passing to _parse method")

        # Patch MyInstaloaderContext to add better headers
        from parsehub.provider_api.instagram import MyInstaloaderContext
        import requests

        original_get_anonymous_session = MyInstaloaderContext.get_anonymous_session

        def patched_get_anonymous_session(self) -> requests.Session:
            from yt_dlp.utils.networking import random_user_agent

            session = original_get_anonymous_session(self)
            # Add more realistic headers with random UA (better anti-crawler)
            session.headers.update({
                'User-Agent': random_user_agent(),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7',
                'Referer': 'https://www.instagram.com/',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
            })
            return session

        MyInstaloaderContext.get_anonymous_session = patched_get_anonymous_session
        logger.info("✅ MyInstaloaderContext patched: Enhanced headers for better compatibility")

        # Patch FacebookParse to support watch/?v= URL format (with optional slash)
        from parsehub.parsers.parser.facebook import FacebookParse

        # Original regex: r"^(http(s)?://)?.+facebook.com/(watch\?v|share/[v,r]|.+/videos/|reel/).*"
        # Problem: watch\?v doesn't match watch/?v= (Facebook's actual URL format)
        # Fix: watch/?\?v makes the slash optional
        FacebookParse.__match__ = r"^(http(s)?://)?.+facebook.com/(watch/?\?v|share/[v,r]|.+/videos/|reel/).*"
        logger.info("✅ FacebookParse patched: Support watch/?v= URL format (with optional slash)")

        # Patch ParseHub.parse to skip get_raw_url for Facebook watch/?v= URLs
        # Root cause: ParseHub.parse() calls get_raw_url() BEFORE calling parser.parse()
        # This strips query parameters from Facebook URLs
        from parsehub.main import ParseHub
        original_parsehub_parse = ParseHub.parse

        async def patched_parsehub_parse(self, url: str):
            """Patched ParseHub.parse that skips get_raw_url for Facebook watch/?v= URLs"""
            parser = self.select_parser(url)
            if not parser:
                raise ValueError("不支持的平台")

            p = parser(parse_config=self.config)

            # Check if this is a Facebook watch/?v= URL
            if isinstance(p, FacebookParse) and "?v=" in url:
                logger.info(f"✅ [ParseHub] Detected Facebook watch/?v= URL, skipping get_raw_url")
                logger.info(f"✅ [ParseHub] Passing URL directly to parser: {url}")
                # Skip get_raw_url to preserve query parameters
                return await p.parse(url)
            else:
                # Use original implementation (calls get_raw_url first)
                url = await p.get_raw_url(url)
                return await p.parse(url)

        ParseHub.parse = patched_parsehub_parse
        logger.info("✅ ParseHub.parse patched: Skip get_raw_url for Facebook watch/?v= URLs")

        # Also patch FacebookParse.parse to skip its internal get_raw_url call
        original_facebook_parse = FacebookParse.parse

        async def patched_facebook_parse(self, url: str):
            """Patched FacebookParse.parse that skips get_raw_url for watch/?v= URLs"""
            if "?v=" in url:
                logger.info(f"✅ [Facebook] Detected ?v= parameter, calling _parse directly (skip get_raw_url)")
                # Skip all get_raw_url calls and call _parse directly
                # YtParser.parse also calls get_raw_url, so we bypass it too
                from parsehub.parsers.base.yt_dlp_parser import YtVideoParseResult
                video_info = await self._parse(url)
                return YtVideoParseResult(
                    video=video_info.url,
                    title=video_info.title,
                    desc=video_info.description,
                    raw_url=url,
                    dl=video_info,
                )
            else:
                # Use original implementation for other Facebook URLs
                return await original_facebook_parse(self, url)

        FacebookParse.parse = patched_facebook_parse
        logger.info("✅ FacebookParse.parse patched: Skip internal get_raw_url for watch/?v= URLs")

        return True

    except Exception as e:
        logger.error(f"❌ ParseHub patch failed: {e}")
        return False
