"""
AI反垃圾检测器
使用 OpenAI API 进行垃圾消息检测
"""
import logging
import json
import time
from typing import Dict, Optional, Tuple
from openai import AsyncOpenAI
from datetime import datetime

logger = logging.getLogger(__name__)


class SpamDetectionResult:
    """垃圾检测结果"""
    def __init__(self, state: int, spam_score: int, spam_reason: str, spam_mock_text: str):
        self.state = state  # 1=垃圾, 0=正常
        self.spam_score = spam_score  # 0-100
        self.spam_reason = spam_reason
        self.spam_mock_text = spam_mock_text
        self.is_spam = state == 1 and spam_score >= 80

    def to_dict(self) -> Dict:
        return {
            'state': self.state,
            'spam_score': self.spam_score,
            'spam_reason': self.spam_reason,
            'spam_mock_text': self.spam_mock_text,
            'is_spam': self.is_spam
        }


class AntiSpamDetector:
    """AI反垃圾检测器"""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini", base_url: str | None = None):
        """
        初始化检测器

        Args:
            api_key: OpenAI API Key
            model: 使用的模型
            base_url: API基础URL（可选，用于代理）
        """
        self.model = model
        if base_url:
            self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        else:
            self.client = AsyncOpenAI(api_key=api_key)
        logger.info(f"AntiSpamDetector initialized with model: {model}")

    async def _chat(self, messages: list, use_json_mode: bool = False) -> str:
        """统一的流式 chat 调用，兼容强制流式的模型（如 grok）"""
        kwargs = {"model": self.model, "messages": messages, "stream": True}
        if use_json_mode:
            try:
                stream = await self.client.chat.completions.create(
                    **kwargs, response_format={"type": "json_object"}
                )
            except Exception:
                stream = await self.client.chat.completions.create(**kwargs)
        else:
            stream = await self.client.chat.completions.create(**kwargs)
        result = ""
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                result += chunk.choices[0].delta.content
        return result

    def _extract_json(self, text: str) -> Dict:
        """
        从模型响应中提取 JSON
        处理 markdown 代码块和其他格式
        """
        import re

        # Try to parse directly first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try to extract JSON from markdown code block
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try to find JSON object in text
        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass

        # If all fails, log the raw response and raise
        logger.error(f"Failed to extract JSON from response: {text[:500]}")
        raise ValueError(f"Could not extract valid JSON from response")

    def _build_user_info_prompt(self, user_info: Dict) -> str:
        """构建用户信息提示词（包含风险评分和bio）"""
        joined_time = user_info.get('joined_time')
        days_since_join = (datetime.now() - joined_time).days if joined_time else 0
        speech_count = user_info.get('number_of_speeches', 0)

        # 计算风险评分
        risk_score = user_info.get('risk_score', 0)
        risk_factors = user_info.get('risk_factors', [])
        bio = user_info.get('bio')

        user_profile = f"""用户信息：
- 入群天数：{days_since_join}天
- 发言次数：{speech_count}次
- 用户名：{user_info.get('username', '未知')}
- 昵称：{user_info.get('first_name', '未知')}
- 风险评分：{risk_score}/100"""

        if bio:
            user_profile += f"\n- 个人简介：{bio}"
            user_profile += "\n  ⚠️ 注意：简介中的链接需结合内容判断，自我介绍性质的频道链接（如'频道: https://t.me/xxx'）是正常的，但如果包含商业推广、赌博、网赚等广告内容则应判定为垃圾"

        if risk_factors:
            user_profile += f"\n- 风险因素：{', '.join(risk_factors)}"
            # 特别标注高风险 DC
            if any('DC4' in factor or 'DC5' in factor for factor in risk_factors):
                user_profile += "\n  ⚠️ 注意：用户来自高风险数据中心"

        return user_profile

    def _get_text_detection_prompt(self, user_info_text: str, message_text: str,
                                   days_since_join: int, speech_count: int) -> str:
        """获取文本检测提示词"""
        # 根据用户状态调整检测策略
        if days_since_join < 3 or speech_count < 3:
            strategy_note = "注意：这是新用户，对短消息请谨慎判断，降低误封率。"
        else:
            strategy_note = "注意：这是老用户，如果消息很短且无明显广告特征，强制认定不是广告。"

        return f"""你是一个Telegram群组反垃圾机器人。请分析以下消息是否为垃圾广告。

{user_info_text}

消息内容：
{message_text}

{strategy_note}

垃圾广告特征包括：
1. 虚假支付机构、银行卡信息
2. **恶意引流**：诱导加入其他群组/频道进行商业推广、赌博、网赚等（注意：用户简介中单纯分享自己频道链接如"频道: https://t.me/xxx"是正常的自我介绍，不算广告）
3. 非法支付、赌博、禁止物品贩卖
4. 非法服务（飞机会员、刷单、赌台、网赚、日入千金等）
5. 使用谐音、错别字、特殊符号混淆的变体
6. **尼日利亚相关服务广告**（NIGERIAN BANKS, NIN, BVN, ESIM, PASSPORT, GMAIL, SUBSCRIPTIONS等）
7. 全大写、大量emoji、24/7 ACTIVE等典型广告特征
8. 高风险用户（无头像、无bio、无用户名）发送的商业信息
9. **加密货币喊单广告**：包含币种代码（如BTC、ETH、ZEC、BNB等）加上进场价/止盈/止损/限价/做多/做空等交易指令组合，这类消息是典型的付费喊单群引流广告，即使格式简短也应判定为垃圾广告
10. **赌博平台推广**：包含"PG平台"、"赌博"、"赌资"、"赌台"、"官方直推"、"风口"、"日入"、"稳定收益"等关键词
11. **零宽字符和特殊符号混淆**：消息中包含零宽字符（如\u200b、\u200c、\u200d、\ufeff）或大量特殊Unicode字符（如͇‌͇等组合变音符）来规避检测，这是典型的垃圾广告技巧

**重要判定规则**：
- **区分正常分享和恶意广告**：用户简介中包含"频道: https://t.me/xxx"、"双向: @xxx_bot"等自我介绍性质的链接是正常的，不应判定为广告。只有当简介或消息包含明显的商业推广、赌博、网赚、引流等内容时才判定为垃圾
- 如果消息使用零宽字符或大量特殊符号混淆关键词（如"风.口"、"快.来"），应视为高度可疑，结合用户信息综合判断
- 老用户（入群>7天且发言>10次）的短消息应更宽容，除非有明确广告特征

请以JSON格式返回结果：
{{
  "state": 1或0,  // 1=垃圾广告, 0=正常消息
  "spam_score": 0-100,  // 威胁分数
  "spam_reason": "判定原因",
  "spam_mock_text": "讽刺性评论（如果是垃圾）"
}}"""

    async def detect_text(self, message_text: str, user_info: Dict) -> Tuple[Optional[SpamDetectionResult], int]:
        """
        检测文本消息

        Args:
            message_text: 消息文本
            user_info: 用户信息

        Returns:
            (检测结果, 耗时毫秒)
        """
        start_time = time.time()

        try:
            user_info_text = self._build_user_info_prompt(user_info)
            joined_time = user_info.get('joined_time')
            days_since_join = (datetime.now() - joined_time).days if joined_time else 0
            speech_count = user_info.get('number_of_speeches', 0)

            prompt = self._get_text_detection_prompt(
                user_info_text, message_text, days_since_join, speech_count
            )

            result_text = await self._chat(
                [{"role": "user", "content": prompt}], use_json_mode=True
            )

            # Extract JSON from response (handle markdown code blocks)
            result_json = self._extract_json(result_text)

            detection_time = int((time.time() - start_time) * 1000)

            return SpamDetectionResult(
                state=result_json.get('state', 0),
                spam_score=result_json.get('spam_score', 0),
                spam_reason=result_json.get('spam_reason', ''),
                spam_mock_text=result_json.get('spam_mock_text', '')
            ), detection_time

        except Exception as e:
            logger.error(f"Failed to detect text: {e}")
            detection_time = int((time.time() - start_time) * 1000)
            return None, detection_time

    async def detect_photo(self, photo_url: str, user_info: Dict,
                          caption: str | None = None) -> Tuple[Optional[SpamDetectionResult], int]:
        """
        检测图片消息

        Args:
            photo_url: 图片URL
            user_info: 用户信息
            caption: 图片说明文字

        Returns:
            (检测结果, 耗时毫秒)
        """
        start_time = time.time()

        try:
            user_info_text = self._build_user_info_prompt(user_info)

            prompt = f"""你是一个Telegram群组反垃圾机器人。请分析这张图片是否包含垃圾广告。

{user_info_text}

图片说明：{caption if caption else '无'}

请检查图片中是否包含垃圾广告特征（支付信息、赌博、非法服务等）。

请以JSON格式返回结果：
{{
  "state": 1或0,
  "spam_score": 0-100,
  "spam_reason": "判定原因",
  "spam_mock_text": "讽刺性评论"
}}"""

            result_text = await self._chat([{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": photo_url}}
                ]
            }], use_json_mode=True)

            # Extract JSON from response (handle markdown code blocks)
            result_json = self._extract_json(result_text)

            detection_time = int((time.time() - start_time) * 1000)

            return SpamDetectionResult(
                state=result_json.get('state', 0),
                spam_score=result_json.get('spam_score', 0),
                spam_reason=result_json.get('spam_reason', ''),
                spam_mock_text=result_json.get('spam_mock_text', '')
            ), detection_time

        except Exception as e:
            logger.error(f"Failed to detect photo: {e}")
            detection_time = int((time.time() - start_time) * 1000)
            return None, detection_time
