"""
反爬虫代理服务器
自动为所有请求添加伪装headers，绕过B站/YouTube等平台的反爬虫检测

使用说明：
1. 这是一个HTTP代理服务器，监听本地端口（默认8765）
2. 自动为所有通过它的HTTP请求添加伪装的浏览器headers
3. 支持平台特定的Referer/Origin设置
4. 保留原始Cookie和Authorization headers
"""

import asyncio
import logging
from aiohttp import web
import aiohttp
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class AntiCrawlerProxy:
    """反爬虫代理服务器，自动注入headers"""

    def __init__(self, host: str = "127.0.0.1", port: int = 8765):
        self.host = host
        self.port = port
        self.app = web.Application()
        # 注册路由 - 处理所有HTTP方法
        self.app.router.add_route('*', '/{tail:.*}', self.handle_proxy)

        # 伪装headers - 模拟真实Chrome浏览器
        self.fake_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate',
            'DNT': '1',
            'Connection': 'keep-alive',
        }

        # 平台特定headers（添加Referer和Origin来伪装来源）
        self.platform_headers = {
            'bilibili.com': {
                'Referer': 'https://www.bilibili.com/',
                'Origin': 'https://www.bilibili.com',
            },
            'b23.tv': {
                'Referer': 'https://www.bilibili.com/',
            },
            'youtube.com': {
                'Referer': 'https://www.youtube.com/',
                'Origin': 'https://www.youtube.com',
            },
            'youtu.be': {
                'Referer': 'https://www.youtube.com/',
            },
            'twitter.com': {
                'Referer': 'https://twitter.com/',
            },
            'x.com': {
                'Referer': 'https://x.com/',
            },
        }

    async def handle_proxy(self, request: web.Request):
        """
        处理代理请求

        HTTP代理的工作方式：
        1. 客户端发送请求，URL格式为：http://proxy:port/real_url
        2. 代理解析real_url，添加伪装headers
        3. 代理转发请求到真实服务器
        4. 代理返回响应给客户端
        """
        try:
            # 获取真实目标URL（从请求路径中提取）
            # 例如：请求 http://127.0.0.1:8765/https://www.bilibili.com/video/xxx
            # 提取出：https://www.bilibili.com/video/xxx
            path = request.match_info.get('tail', '')

            # 如果path是完整URL（以http开头）
            if path.startswith('http://') or path.startswith('https://'):
                target_url = path
            else:
                # 否则，从X-Target-URL header中获取（yt-dlp等工具可能会这样传递）
                target_url = request.headers.get('X-Target-URL')
                if not target_url:
                    # 最后尝试：使用Host header构建URL
                    host = request.headers.get('Host', request.url.host)
                    scheme = 'https' if request.url.scheme == 'https' else 'http'
                    target_url = f"{scheme}://{host}{request.path}"

            logger.info(f"🔄 代理请求: {request.method} {target_url}")

            # 解析目标URL以获取域名
            parsed = urlparse(target_url)
            target_domain = parsed.netloc

            # 构建headers - 从伪装headers开始
            headers = dict(self.fake_headers)

            # 添加Host header（必须）
            headers['Host'] = target_domain

            # 添加平台特定headers
            for domain, platform_headers in self.platform_headers.items():
                if domain in target_domain:
                    headers.update(platform_headers)
                    logger.debug(f"🎭 为 {domain} 添加平台特定headers")
                    break

            # 保留原始请求中的重要headers
            preserve_headers = [
                'Cookie', 'Authorization', 'Range',
                'If-None-Match', 'If-Modified-Since'
            ]
            for header in preserve_headers:
                if header in request.headers:
                    headers[header] = request.headers[header]
                    if header == 'Cookie':
                        logger.debug(f"🍪 保留Cookie: {request.headers[header][:50]}...")

            # 移除可能暴露代理身份的headers
            headers.pop('X-Forwarded-For', None)
            headers.pop('Via', None)
            headers.pop('Proxy-Connection', None)
            headers.pop('X-Target-URL', None)

            # 读取请求体（如果有）
            body = await request.read() if request.can_read_body and request.content_length else None

            # 发送请求到目标服务器
            timeout = aiohttp.ClientTimeout(total=60, connect=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.request(
                    method=request.method,
                    url=target_url,
                    headers=headers,
                    data=body,
                    allow_redirects=True,
                    ssl=False  # 跳过SSL验证（有些平台证书可能有问题）
                ) as resp:
                    # 读取响应体
                    response_body = await resp.read()

                    # 构建响应headers
                    response_headers = {}
                    for name, value in resp.headers.items():
                        # 排除可能导致问题的headers
                        if name.lower() not in ['transfer-encoding', 'content-encoding']:
                            response_headers[name] = value

                    logger.info(f"✅ 代理响应: {resp.status} ({len(response_body)} bytes)")

                    return web.Response(
                        body=response_body,
                        status=resp.status,
                        headers=response_headers
                    )

        except Exception as e:
            logger.error(f"❌ 代理请求失败: {e}", exc_info=True)
            return web.Response(
                text=f"Proxy Error: {str(e)}",
                status=502
            )

    async def start(self):
        """启动代理服务器"""
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        logger.info(f"🚀 反爬虫代理服务器已启动: http://{self.host}:{self.port}")
        logger.info(f"   使用方法：在.env中配置")
        logger.info(f"   PARSER_PROXY=http://{self.host}:{self.port}")
        logger.info(f"   DOWNLOADER_PROXY=http://{self.host}:{self.port}")

    def run(self):
        """运行代理服务器（阻塞模式）"""
        asyncio.run(self._run_async())

    async def _run_async(self):
        """异步运行代理服务器"""
        await self.start()
        # 保持运行
        await asyncio.Event().wait()


# 如果直接运行此文件，启动代理服务器（用于测试）
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    logger.info("🧪 测试模式：启动独立代理服务器")
    logger.info("   按 Ctrl+C 停止")

    proxy = AntiCrawlerProxy(host="127.0.0.1", port=8765)

    try:
        proxy.run()
    except KeyboardInterrupt:
        logger.info("⏹️ 代理服务器已停止")
