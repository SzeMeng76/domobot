#!/usr/bin/env python3
"""
语言检测工具模块
用于自动检测用户的语言偏好，支持中英文识别
"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class LanguageDetector:
    """语言检测器"""
    
    # 中文字符范围 (包括中文汉字、标点符号等)
    CHINESE_REGEX = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff\u3000-\u303f\uff00-\uffef]')
    
    # 常见中文关键词
    CHINESE_KEYWORDS = {
        '地图', '导航', '位置', '路线', '附近', '搜索', '查找', '怎么走', '在哪里', 
        '到', '从', '去', '路径', '距离', '时间', '公里', '米', '分钟', '小时',
        '餐厅', '医院', '银行', '加油站', '超市', '学校', '酒店', '商场',
        '地址', '坐标', '经纬度', '定位'
    }
    
    # 常见英文关键词  
    ENGLISH_KEYWORDS = {
        'map', 'navigation', 'location', 'route', 'nearby', 'search', 'find', 'how to get',
        'where is', 'to', 'from', 'go to', 'path', 'distance', 'time', 'km', 'meter', 
        'minute', 'hour', 'restaurant', 'hospital', 'bank', 'gas station', 'supermarket',
        'school', 'hotel', 'mall', 'address', 'coordinate', 'latitude', 'longitude', 'gps'
    }
    
    @classmethod
    def detect_language(cls, text: str, user_locale: Optional[str] = None) -> str:
        """
        检测文本语言
        
        Args:
            text: 要检测的文本
            user_locale: 用户的语言环境 (来自Telegram客户端)
            
        Returns:
            'zh' for Chinese, 'en' for English
        """
        if not text:
            return cls._get_default_by_locale(user_locale)
        
        text = text.strip().lower()
        
        # 1. 首先检查中文字符
        chinese_chars = len(cls.CHINESE_REGEX.findall(text))
        total_chars = len(text)
        
        if total_chars == 0:
            return cls._get_default_by_locale(user_locale)
        
        # 如果中文字符占比超过30%，判断为中文
        chinese_ratio = chinese_chars / total_chars
        if chinese_ratio > 0.3:
            logger.debug(f"检测为中文 (中文字符占比: {chinese_ratio:.2%})")
            return 'zh'
        
        # 2. 检查关键词
        chinese_keyword_count = sum(1 for keyword in cls.CHINESE_KEYWORDS if keyword in text)
        english_keyword_count = sum(1 for keyword in cls.ENGLISH_KEYWORDS if keyword in text)
        
        if chinese_keyword_count > english_keyword_count:
            logger.debug(f"检测为中文 (中文关键词: {chinese_keyword_count}, 英文关键词: {english_keyword_count})")
            return 'zh'
        elif english_keyword_count > chinese_keyword_count:
            logger.debug(f"检测为英文 (英文关键词: {english_keyword_count}, 中文关键词: {chinese_keyword_count})")
            return 'en'
        
        # 3. 检查用户语言环境
        if user_locale:
            if user_locale.startswith('zh'):
                logger.debug(f"根据用户语言环境检测为中文: {user_locale}")
                return 'zh'
            elif user_locale.startswith('en'):
                logger.debug(f"根据用户语言环境检测为英文: {user_locale}")
                return 'en'
        
        # 4. 默认判断：如果有任何中文字符就是中文，否则英文
        if chinese_chars > 0:
            logger.debug("检测到中文字符，判断为中文")
            return 'zh'
        else:
            logger.debug("未检测到中文字符，判断为英文")
            return 'en'
    
    @classmethod
    def _get_default_by_locale(cls, user_locale: Optional[str]) -> str:
        """根据用户语言环境获取默认语言"""
        if user_locale and user_locale.startswith('zh'):
            return 'zh'
        return 'en'
    
    @classmethod
    def is_chinese_text(cls, text: str) -> bool:
        """判断文本是否为中文"""
        return cls.detect_language(text) == 'zh'
    
    @classmethod
    def is_english_text(cls, text: str) -> bool:
        """判断文本是否为英文"""
        return cls.detect_language(text) == 'en'


def detect_user_language(text: str, user_locale: Optional[str] = None) -> str:
    """
    便捷的语言检测函数
    
    Args:
        text: 要检测的文本
        user_locale: 用户语言环境
        
    Returns:
        'zh' 或 'en'
    """
    return LanguageDetector.detect_language(text, user_locale)


def get_map_service(language: str) -> str:
    """
    根据语言选择地图服务
    
    Args:
        language: 语言代码 ('zh' 或 'en')
        
    Returns:
        'amap' 或 'google_maps'
    """
    return 'amap' if language == 'zh' else 'google_maps'