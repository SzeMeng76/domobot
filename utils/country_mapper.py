"""
统一国家名称映射工具

提供统一的国家输入解析，支持：
- 国家代码: US, TR, CN, UK, JP
- 中文名称: 美国, 土耳其, 中国
- 英文全名: USA, Turkey, China, United Kingdom, Japan
"""

import logging

logger = logging.getLogger(__name__)

# 延迟导入避免循环依赖
_ENGLISH_NAME_TO_CODE = None
_COUNTRY_NAME_TO_CODE = None
_SUPPORTED_COUNTRIES = None


def _lazy_init():
    """延迟初始化映射表"""
    global _ENGLISH_NAME_TO_CODE, _COUNTRY_NAME_TO_CODE, _SUPPORTED_COUNTRIES

    if _ENGLISH_NAME_TO_CODE is not None:
        return

    try:
        from utils.country_data import (
            COUNTRY_CODE_TO_ENGLISH,
            COUNTRY_NAME_TO_CODE,
            SUPPORTED_COUNTRIES,
        )

        _ENGLISH_NAME_TO_CODE = {v: k for k, v in COUNTRY_CODE_TO_ENGLISH.items()}
        _COUNTRY_NAME_TO_CODE = COUNTRY_NAME_TO_CODE
        _SUPPORTED_COUNTRIES = SUPPORTED_COUNTRIES

        logger.debug("国家映射表已初始化")
    except ImportError as e:
        logger.error(f"初始化国家映射表失败: {e}")
        # 降级：只使用基础的 SUPPORTED_COUNTRIES
        from utils.country_data import COUNTRY_NAME_TO_CODE, SUPPORTED_COUNTRIES

        _ENGLISH_NAME_TO_CODE = {}
        _COUNTRY_NAME_TO_CODE = COUNTRY_NAME_TO_CODE
        _SUPPORTED_COUNTRIES = SUPPORTED_COUNTRIES


def get_country_code(country_input: str) -> str | None:
    """
    统一的国家输入解析函数

    支持输入:
    - 国家代码: US, TR, CN, UK, JP
    - 中文名称: 美国, 土耳其, 中国
    - 英文全名: USA, Turkey, China, United Kingdom, Japan

    Args:
        country_input: 用户输入的国家标识

    Returns:
        str: 国家代码（大写），如 "US", "TR"
        None: 无效输入
    """
    _lazy_init()

    if not country_input:
        return None

    # 1. 尝试作为国家代码（大写匹配）
    country_upper = country_input.upper()
    if country_upper in _SUPPORTED_COUNTRIES:
        return country_upper

    # 2. 尝试作为中文名称（精确匹配）
    if country_input in _COUNTRY_NAME_TO_CODE:
        return _COUNTRY_NAME_TO_CODE[country_input]

    # 3. 尝试作为英文名称（精确匹配）
    if country_input in _ENGLISH_NAME_TO_CODE:
        return _ENGLISH_NAME_TO_CODE[country_input]

    # 4. 尝试大小写不敏感的英文名称匹配
    for english_name, code in _ENGLISH_NAME_TO_CODE.items():
        if english_name.lower() == country_input.lower():
            return code

    return None


def is_valid_country_input(country_input: str) -> bool:
    """
    检查是否为有效的国家输入

    Args:
        country_input: 用户输入的国家标识

    Returns:
        bool: 是否为有效的国家输入
    """
    return get_country_code(country_input) is not None


def get_country_display_name(country_code: str, language: str = "cn") -> str:
    """
    获取国家的显示名称

    Args:
        country_code: 国家代码（如 "US", "TR"）
        language: 语言 ("cn" 为中文, "en" 为英文)

    Returns:
        str: 国家显示名称，如果未找到则返回国家代码
    """
    _lazy_init()

    country_code_upper = country_code.upper()

    if language == "en":
        # 返回英文名称
        for english_name, code in _ENGLISH_NAME_TO_CODE.items():
            if code == country_code_upper:
                return english_name
    else:
        # 返回中文名称
        if country_code_upper in _SUPPORTED_COUNTRIES:
            return _SUPPORTED_COUNTRIES[country_code_upper].get(
                "name", country_code_upper
            )

    return country_code_upper


def get_all_supported_country_codes() -> list[str]:
    """
    获取所有支持的国家代码列表

    Returns:
        list[str]: 国家代码列表（大写）
    """
    _lazy_init()
    return list(_SUPPORTED_COUNTRIES.keys())


def get_all_supported_country_names(language: str = "cn") -> list[str]:
    """
    获取所有支持的国家名称列表

    Args:
        language: 语言 ("cn" 为中文, "en" 为英文)

    Returns:
        list[str]: 国家名称列表
    """
    _lazy_init()

    if language == "en":
        return list(_ENGLISH_NAME_TO_CODE.keys())
    else:
        return list(_COUNTRY_NAME_TO_CODE.keys())
