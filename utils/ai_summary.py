"""
AI 总结工具
使用 OpenAI API 生成内容总结
"""

import logging
from typing import Optional
from parsehub.types import ParseResult

logger = logging.getLogger(__name__)


class AISummaryGenerator:
    """AI 总结生成器"""

    def __init__(self, api_key: str, model: str = "gpt-5-mini", base_url: Optional[str] = None):
        """
        初始化总结生成器

        Args:
            api_key: OpenAI API密钥
            model: 使用的模型
            base_url: API基础URL（可选，用于代理）
        """
        self.api_key = api_key
        self.model = model
        self.base_url = base_url

    async def generate(self, result: ParseResult, max_length: int = 50) -> Optional[str]:
        """
        生成内容总结

        Args:
            result: 解析结果
            max_length: 总结最大字数

        Returns:
            总结文本，失败返回None
        """
        try:
            import openai

            client = openai.AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url or None
            )

            # 构建提示词
            content = f"标题: {result.title or '无标题'}\n"
            if result.desc:
                content += f"描述: {result.desc[:500]}\n"  # 限制描述长度

            prompt = f"请用{max_length}字以内总结以下内容的核心要点，要简洁精炼：\n\n{content}"

            response = await client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是一个专业的内容总结助手，擅长提炼关键信息。输出要简洁、准确、易读。"},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=200,
                temperature=0.7
            )

            summary = response.choices[0].message.content.strip()
            logger.info(f"✅ AI总结生成成功: {summary[:30]}...")
            return summary

        except Exception as e:
            logger.error(f"AI总结生成失败: {e}")
            return None


async def generate_summary(
    result: ParseResult,
    api_key: str,
    model: str = "gpt-5-mini",
    base_url: Optional[str] = None,
    max_length: int = 50
) -> Optional[str]:
    """
    便捷函数：生成内容总结

    Args:
        result: 解析结果
        api_key: OpenAI API密钥
        model: 使用的模型
        base_url: API基础URL
        max_length: 总结最大字数

    Returns:
        总结文本，失败返回None
    """
    generator = AISummaryGenerator(api_key, model, base_url)
    return await generator.generate(result, max_length)
