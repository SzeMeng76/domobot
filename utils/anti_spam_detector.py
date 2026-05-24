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
            user_profile += "\n  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            user_profile += "\n  🔍 简介风险评估（必读，按语义推理，禁止只看字面词）："
            user_profile += "\n"
            user_profile += "\n  ❶ 先问：这条简介是「自我介绍」还是「广告/引流」？"
            user_profile += "\n     - 自我介绍：描述用户是谁、做什么的、有什么爱好/职业、个人频道/社交媒体链接。"
            user_profile += "\n       例：'技术宅 | Web开发者 | https://twitter.com/xxx' → 自我介绍"
            user_profile += "\n     - 广告/引流：向陌生人推销服务/项目/收益机会，附加联系方式或入群链接。"
            user_profile += "\n       例：'进群了解，自己在平台洗金 t.me/xxx' → 广告/引流"
            user_profile += "\n       例：'今年最新项目一天稳定8万来找我小白也带，进群链接：t.me/xxx' → 广告/引流"
            user_profile += "\n       例：'承接各类支付通道 USDT 兑换 联系 @xxx' → 广告/引流"
            user_profile += "\n"
            user_profile += "\n  ❷ 若是广告/引流，再判断属于以下哪类高风险（任一即触发）："
            user_profile += "\n     • 赌博/博彩/跑分/洗钱：平台、台子、彩、博、跑分、洗金、出U、码商、菠菜、白菜、官方直推等任何博彩/资金清洗语义"
            user_profile += "\n     • 网赚/刷单/兼职暴利：日入X万、稳定收益、躺赚、带项目、带小白、手把手、靠谱项目、最新项目等任何收益承诺"
            user_profile += "\n     • 非法支付/通道/卡商：通道、出U、收U、USDT兑换、人民币结算、支付接口等"
            user_profile += "\n     • 加密喊单/带单：进场价、止盈止损、做多做空、跟单等"
            user_profile += "\n     • 灰产服务：尼日利亚相关、护照、签证代办、解封、电报会员代充等"
            user_profile += "\n     • 引流话术：'进群了解'、'看简介'、'点我私聊'、'加我'、'扫码'等召唤性动词，配合任何上述语义"
            user_profile += "\n"
            user_profile += "\n  ❸ 关键原则（违反会漏判，仔细阅读）："
            user_profile += "\n     ⚡ 上面列的关键词只是【示例】，不是【完整列表】。靠语义判断，不靠字面匹配。"
            user_profile += "\n     ⚡ '洗金' = 帮赌博平台清洗资金，是赌博/跑分语义；'在平台' = 在博彩平台，是赌博语义。"
            user_profile += "\n     ⚡ 一条简介只要让一个正常用户读完会有「这是广告/拉人头」的直觉，就属于高风险。"
            user_profile += "\n     ⚡ 真正的「自我介绍」不会向陌生人推销服务、不会承诺收益、不会说'进群了解'。"
            user_profile += "\n"
            user_profile += "\n  ❹ 一旦判定简介属于高风险广告/引流，无论当前消息内容是什么（'.'、'你好'、'1'、表情、贴纸都算），"
            user_profile += "\n     都判定为【养号顶帖】：state=1, spam_score>=85。"
            user_profile += "\n     原因：这类账号简介本身就是广告载体，发任何消息只是为了把自己置顶到群顶部、曝光简介给别人看。"
            user_profile += "\n  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

        if risk_factors:
            user_profile += f"\n- 风险因素：{', '.join(risk_factors)}"
            # 特别标注高风险 DC
            if any('DC4' in factor or 'DC5' in factor for factor in risk_factors):
                user_profile += "\n  ⚠️ 注意：用户来自高风险数据中心"
            # 特别标注货币相关昵称
            if any('货币' in factor or '昵称包含货币关键词' in factor for factor in risk_factors):
                user_profile += "\n  ⚠️ 警告：昵称包含货币兑换关键词，极高疑似广告商，应提高评分"

        return user_profile

    def _get_text_detection_prompt(self, user_info_text: str, message_text: str,
                                   days_since_join: int, speech_count: int) -> str:
        """获取文本检测提示词"""
        # 根据用户状态调整检测策略
        if days_since_join < 3 or speech_count < 3:
            strategy_note = "注意：新用户，短消息谨慎判断，降低误封率（但简介若判定为广告/引流，按上方四步流程必须判养号顶帖，不豁免）。"
        else:
            strategy_note = "注意：老用户短消息通常更宽容，但仅当简介属于真实自我介绍时适用。简介一旦判定为广告/引流（赌博/网赚/支付通道/喊单/灰产/引流话术），老用户也按养号顶帖判定。"

        return f"""你是Telegram反垃圾机器人，分析消息是否为垃圾广告。

{user_info_text}

消息内容：
{message_text}

{strategy_note}

垃圾广告特征：
1. 虚假支付/银行卡、非法支付/赌博/禁止物品
2. 恶意引流（商业推广、赌博、网赚、飞机会员、刷单）
3. 尼日利亚服务（NIGERIAN BANKS/NIN/BVN/ESIM/PASSPORT/GMAIL）
4. 加密货币喊单（币种+交易指令：进场价/止盈/止损/做多/做空）
5. 赌博平台（PG平台、赌台、官方直推、风口、日入、稳定收益）
6. 货币兑换广告（主动提供exchange服务，多种货币代码，大量emoji）
7. 订阅服务推广（subscription/VIP/premium/membership/available）
8. 典型广告格式（全大写、大量emoji、24/7 ACTIVE、谐音/错别字/特殊符号混淆、零宽字符）
9. 引流看简介（"看简介"、"点简介"、"看号主简介"、"点击此号"、"看我简介"等引导他人查看简介的话术，配合简介含推广内容）

判定规则：
- 推销vs询问：主动"出售XX"是广告，询问"有人卖XX吗"是正常
- 简介链接不是依据：个人简介中的链接（联盟/推广/社交媒体）是正常的，除非消息本身包含主动推销
- 货币兑换：主动提供exchange是广告，询问"有人能换汇吗"是正常
- 订阅服务：主动推广subscription/VIP/premium，评分>=85
- 昵称含货币关键词（USDT/BTC/NAIRA/EXCHANGE）的用户发推广消息，+25分
- 🚨 简介高风险 → 自动判定养号顶帖：严格按上方「简介风险评估」四步流程推理。一旦判定简介属于广告/引流（赌博/跑分/洗钱、网赚、非法支付、加密喊单、灰产、引流话术任一），无论当前消息是什么（'.'、'你好'、'1'、表情、单字、贴纸都算），都判定为养号顶帖：state=1, spam_score>=85。不要用字面关键词查表，要用语义理解——"洗金"="帮赌博平台清洗资金"=赌博语义，"在平台"=博彩平台，"进群了解"=引流召唤。
- 🚨 引流看简介：消息含"看简介"、"点简介"、"看号主"、"点击此号"等引导查看简介的话术，且简介含推广内容，直接判定垃圾广告，评分>=85
- 新用户正常提问/闲聊不封，只封主动推销/引流
- 老用户（>7天且>10次发言）短消息更宽容
- ⚠️ 引用/回复垃圾广告：如果[引用内容]或[回复内容]是垃圾广告（评分>=80），且用户消息很短（<10字）且无实质内容（如"👏"、"好"、"vk9"等），判定为顶帖行为，评分>=85
- 短消息豁免规则（默认情况）：短消息（<10字）且无明显广告特征，认定正常（state=0, spam_score<50）。
- ⚠️ 短消息豁免的反向条件（不豁免）：以下任一情况，短消息也不能豁免，按上方规则判定：
  (1) 引用/回复了垃圾广告（顶帖行为）
  (2) 简介判定为广告/引流（按上方四步流程，养号曝光行为）
  (3) 用户昵称含货币兑换关键词
  (4) 风险评分>=60 且简介非空

返回JSON：
{{
  "state": 1或0,  // 1=垃圾, 0=正常
  "spam_score": 0-100,
  "spam_reason": "判定原因",
  "spam_mock_text": "讽刺评论"
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
