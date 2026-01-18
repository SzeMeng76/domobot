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

    def __init__(self, api_key: str, model: str = "gpt-4o-mini", base_url: str = None):
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

    def _build_user_info_prompt(self, user_info: Dict) -> str:
        """构建用户信息提示词（包含风险评分）"""
        joined_time = user_info.get('joined_time')
        days_since_join = (datetime.now() - joined_time).days if joined_time else 0
        speech_count = user_info.get('number_of_speeches', 0)

        # 计算风险评分
        risk_score = user_info.get('risk_score', 0)
        risk_factors = user_info.get('risk_factors', [])

        user_profile = f"""用户信息：
- 入群天数：{days_since_join}天
- 发言次数：{speech_count}次
- 用户名：{user_info.get('username', '未知')}
- 昵称：{user_info.get('first_name', '未知')}
- 风险评分：{risk_score}/100"""

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
2. 诱导加入群组的链接
3. 非法支付、赌博、禁止物品贩卖
4. 非法服务（飞机会员、刷单、赌台、网赚等）
5. 使用谐音、错别字、特殊符号混淆的变体
6. **尼日利亚相关服务广告**（NIGERIAN BANKS, NIN, BVN, ESIM, PASSPORT, GMAIL, SUBSCRIPTIONS等）
7. 全大写、大量emoji、24/7 ACTIVE等典型广告特征
8. 高风险用户（无头像、无bio、无用户名）发送的商业信息

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

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )

            result_text = response.choices[0].message.content
            result_json = json.loads(result_text)

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
                          caption: str = None) -> Tuple[Optional[SpamDetectionResult], int]:
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

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": photo_url}}
                    ]
                }],
                response_format={"type": "json_object"}
            )

            result_text = response.choices[0].message.content
            result_json = json.loads(result_text)

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
