#!/usr/bin/env python3
"""
WHOIS查询命令模块
支持域名、IP地址、ASN、TLD等WHOIS信息查询
"""

import logging
import re
import ipaddress
import json
import os
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
import asyncio
from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown

from utils.command_factory import command_factory
from utils.permissions import Permission
from utils.message_manager import send_message_with_auto_delete, send_error, delete_user_command
from utils.formatter import foldable_text_v2

logger = logging.getLogger(__name__)

# 全局变量
cache_manager = None

# Telegraph 相关配置
TELEGRAPH_API_URL = "https://api.telegra.ph"

class TLDManager:
    """TLD数据管理器 - 直接从GitHub获取数据"""
    
    TLD_URL = "https://raw.githubusercontent.com/SzeMeng76/iana_tld_list/refs/heads/master/data/tld.json"
    
    def __init__(self):
        self._tld_data = None
        
    async def _fetch_tld_data(self) -> Optional[Dict[str, Any]]:
        """从GitHub获取TLD数据"""
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; MengBot/1.0)"
        }
        try:
            from utils.http_client import create_custom_client
            
            async with create_custom_client(headers=headers) as client:
                response = await client.get(self.TLD_URL, timeout=20.0)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"获取TLD数据失败: {e}")
            return None
    
    async def get_tld_info(self, tld: str) -> Optional[Dict[str, Any]]:
        """获取TLD信息"""
        # 如果数据未加载，先获取数据
        if not self._tld_data:
            logger.info("正在从GitHub获取TLD数据...")
            self._tld_data = await self._fetch_tld_data()
            if self._tld_data:
                logger.info(f"成功获取 {len(self._tld_data)} 个TLD记录")
            else:
                logger.error("获取TLD数据失败")
                return None
            
        # 清理TLD输入
        tld_clean = tld.lower()
        if not tld_clean.startswith('.'):
            tld_clean = '.' + tld_clean
            
        logger.debug(f"查找TLD: '{tld_clean}'")
        
        # IANA数据是字典格式，key是完整的TLD（带点）
        if tld_clean in self._tld_data:
            item = self._tld_data[tld_clean]
            logger.debug(f"找到TLD数据: {item}")
            return {
                '类型': self._map_tld_type(item.get('tldType')),
                '管理机构': self._extract_nic_name(item.get('nic')),
                '创建时间': item.get('registration'),
                '最后更新': item.get('lastUpdate'),
                'WHOIS服务器': self._clean_whois_server(item.get('whois')),
                '国际化域名': '是' if item.get('isIDN') == 'True' else '否'
            }
        else:
            logger.debug(f"未找到TLD '{tld_clean}' 在数据中")
            return None
    
    def _clean_whois_server(self, whois: str) -> str:
        """清理WHOIS服务器信息"""
        if not whois or whois == 'NULL':
            return '无'
        return whois
    
    def _map_tld_type(self, tld_type: str) -> str:
        """映射TLD类型为中文"""
        type_map = {
            'gTLD': '通用顶级域名',
            'ccTLD': '国家代码顶级域名', 
            'iTLD': '基础设施顶级域名'
        }
        return type_map.get(tld_type, tld_type or '未知')
    
    def _extract_nic_name(self, nic_url: str) -> str:
        """从NIC URL提取机构名称"""
        if not nic_url:
            return '未知'
        
        # 清理NULL值
        if nic_url == 'NULL':
            return '未知'
        
        # 简单的URL到名称映射
        name_map = {
            'verisigninc.com': 'Verisign',
            'pir.org': 'PIR',
            'cnnic.cn': 'CNNIC',
            'neustar.biz': 'Neustar',
            'nominet.uk': 'Nominet',
            'jprs.jp': 'JPRS',
            'domain.me': 'doMEn d.o.o.',
            'icb.co.uk': 'ICB',
            'nic.io': 'Internet Computer Bureau'
        }
        
        for domain, name in name_map.items():
            if domain in nic_url.lower():
                return name
                
        # 如果没有匹配，返回清理后的URL
        try:
            from urllib.parse import urlparse
            parsed = urlparse(nic_url)
            domain = parsed.netloc or nic_url
            # 移除www前缀
            if domain.startswith('www.'):
                domain = domain[4:]
            return domain
        except:
            return nic_url or '未知'

def set_dependencies(c_manager):
    """设置依赖"""
    global cache_manager
    cache_manager = c_manager

class WhoisService:
    """WHOIS查询服务类"""
    
    def __init__(self):
        # 延迟导入避免启动时的依赖问题
        self._asyncwhois = None
        self._whois21 = None
        self._ipwhois = None
        self._python_whois = None

    def _import_libraries(self):
        """延迟导入WHOIS和DNS库"""
        try:
            if self._asyncwhois is None:
                import asyncwhois
                self._asyncwhois = asyncwhois
        except ImportError:
            logger.warning("asyncwhois库未安装，域名查询功能受限")

        try:
            if self._whois21 is None:
                import whois21
                self._whois21 = whois21
        except ImportError:
            logger.warning("whois21库未安装，域名查询功能受限")

        try:
            if self._ipwhois is None:
                # 导入整个ipwhois模块，而不只是IPWhois类
                import ipwhois
                self._ipwhois = ipwhois
        except ImportError:
            logger.warning("ipwhois库未安装，IP/ASN查询功能不可用")

        try:
            if self._python_whois is None:
                import whois as python_whois
                self._python_whois = python_whois
        except ImportError:
            logger.warning("python-whois库未安装，域名查询备选方案不可用")

        try:
            if not hasattr(self, '_dns'):
                import dns.resolver
                import dns.reversename
                import dns.exception
                self._dns = dns
        except ImportError:
            logger.warning("dnspython库未安装，DNS查询功能不可用")
            self._dns = None
    
    async def query_domain(self, domain: str) -> Dict[str, Any]:
        """查询域名WHOIS信息"""
        self._import_libraries()

        # 清理域名输入
        domain = domain.lower().strip()
        if domain.startswith(('http://', 'https://')):
            domain = domain.split('//', 1)[1].split('/')[0]

        result = {
            'type': 'domain',
            'query': domain,
            'success': False,
            'data': {},
            'error': None,
            'source': None
        }

        # .ng 域名特殊处理 - 使用 Web WHOIS
        if domain.endswith('.ng'):
            try:
                ng_result = await self._query_ng_domain_web(domain)
                if ng_result['success']:
                    result.update(ng_result)
                    return result
                else:
                    logger.debug(f".ng Web查询失败: {ng_result.get('error')}")
            except Exception as e:
                logger.debug(f".ng Web查询异常: {e}")

        # 优先使用 whois21（快速且解析能力强）
        if self._whois21:
            try:
                whois_obj = await asyncio.wait_for(
                    asyncio.to_thread(self._whois21.WHOIS, domain),
                    timeout=10.0
                )
                if whois_obj.success:
                    data = self._extract_whois21_data(whois_obj)
                    if data:
                        result['success'] = True
                        result['data'] = data
                        result['source'] = 'whois21'

                        # 添加DNS信息
                        try:
                            dns_result = await self.query_dns(domain)
                            if dns_result['success'] and dns_result.get('data'):
                                for key, value in dns_result['data'].items():
                                    result['data'][f'🌐 {key}'] = value
                                logger.debug(f"已添加DNS信息到域名查询结果")
                        except Exception as e:
                            logger.debug(f"添加DNS信息失败: {e}")

                        return result
            except Exception as e:
                logger.debug(f"whois21查询失败: {e}")

        # 备选方案1：使用 asyncwhois（支持更多TLD）
        if self._asyncwhois and not result['success']:
            try:
                query_string, parsed_dict = await self._asyncwhois.aio_whois(
                    domain,
                    find_authoritative_server=True,
                    ignore_not_found=False,
                    timeout=15
                )

                if parsed_dict:
                    result['success'] = True
                    result['data'] = self._format_asyncwhois_data(parsed_dict)
                    result['source'] = 'asyncwhois'

                    # 添加DNS信息
                    try:
                        dns_result = await self.query_dns(domain)
                        if dns_result['success'] and dns_result.get('data'):
                            for key, value in dns_result['data'].items():
                                result['data'][f'🌐 {key}'] = value
                            logger.debug(f"已添加DNS信息到域名查询结果")
                    except Exception as e:
                        logger.debug(f"添加DNS信息失败: {e}")

                    return result
            except Exception as e:
                logger.debug(f"asyncwhois查询失败: {e}")

        # 备选方案2：使用 python-whois
        if self._python_whois and not result['success']:
            try:
                data = await asyncio.wait_for(
                    asyncio.to_thread(self._python_whois.whois, domain),
                    timeout=10.0
                )
                if data:
                    result['success'] = True
                    result['data'] = self._format_python_whois_data(data)
                    result['source'] = 'python-whois'

                    # 添加DNS信息
                    try:
                        dns_result = await self.query_dns(domain)
                        if dns_result['success'] and dns_result.get('data'):
                            for key, value in dns_result['data'].items():
                                result['data'][f'🌐 {key}'] = value
                            logger.debug(f"已添加DNS信息到域名查询结果")
                    except Exception as e:
                        logger.debug(f"添加DNS信息失败: {e}")
            except Exception as e:
                logger.debug(f"python-whois查询失败: {e}")
                result['error'] = str(e)

        if not result['success']:
            result['error'] = "无法查询域名信息，请检查域名是否有效"
        
        return result
    
    async def query_ip(self, ip: str) -> Dict[str, Any]:
        """查询IP地址WHOIS信息"""
        self._import_libraries()
        
        result = {
            'type': 'ip',
            'query': ip,
            'success': False,
            'data': {},
            'error': None,
            'source': 'ipwhois'
        }
        
        if not self._ipwhois:
            result['error'] = "IP查询功能不可用，请安装ipwhois库"
            return result
        
        try:
            # 验证IP地址格式
            ipaddress.ip_address(ip)

            # 使用RDAP查询（推荐方式）- 正确的API使用方法，添加15秒超时
            obj = self._ipwhois.IPWhois(ip)
            data = await asyncio.wait_for(
                asyncio.to_thread(obj.lookup_rdap),
                timeout=15.0
            )

            # 添加调试信息
            logger.debug(f"IP查询返回数据类型: {type(data)}")
            if isinstance(data, dict):
                logger.debug(f"数据的顶级键: {list(data.keys())}")
            
            if data:
                # 检查data是否为字典类型
                if isinstance(data, dict):
                    try:
                        formatted_data = self._format_ip_data(data)
                        
                        # 尝试获取地理位置信息
                        geolocation_data = await self._query_ip_geolocation(ip)
                        if geolocation_data:
                            # 将地理位置信息添加到结果中
                            geo_info = self._format_geolocation_data(geolocation_data)
                            formatted_data.update(geo_info)
                        
                        if formatted_data:  # 确保格式化后有数据
                            result['success'] = True
                            result['data'] = formatted_data
                        else:
                            # 如果格式化后没有数据，显示原始数据的一些关键字段
                            fallback_data = {}
                            if 'query' in data:
                                fallback_data['查询IP'] = data['query']
                            if 'asn' in data:
                                fallback_data['ASN'] = f"AS{data['asn']}"
                            if 'asn_description' in data:
                                fallback_data['ASN描述'] = data['asn_description']
                            
                            if fallback_data:
                                result['success'] = True
                                result['data'] = fallback_data
                            else:
                                # 显示所有顶级字段作为调试信息
                                debug_data = {}
                                for key, value in data.items():
                                    if isinstance(value, (str, int, float)):
                                        debug_data[f'调试_{key}'] = str(value)[:100]
                                    else:
                                        debug_data[f'调试_{key}'] = f"类型: {type(value).__name__}"
                                
                                result['success'] = True
                                result['data'] = debug_data if debug_data else {'调试': '无可显示数据'}
                    except Exception as format_error:
                        logger.error(f"格式化IP数据时出错: {format_error}")
                        # 直接显示原始数据结构
                        debug_data = {'调试错误': str(format_error)}
                        for key, value in data.items():
                            if isinstance(value, (str, int, float)):
                                debug_data[f'原始_{key}'] = str(value)[:100]
                            else:
                                debug_data[f'原始_{key}_类型'] = type(value).__name__
                        result['success'] = True
                        result['data'] = debug_data
                elif isinstance(data, str):
                    # 如果返回的是字符串，可能是错误信息或原始whois数据
                    result['success'] = True
                    result['data'] = {'原始数据': data[:500] + "..." if len(data) > 500 else data}
                else:
                    result['error'] = f"查询返回了意外的数据类型: {type(data)}"
            else:
                result['error'] = "未找到IP地址信息"
                
        except ValueError:
            result['error'] = "无效的IP地址格式"
        except Exception as e:
            logger.error(f"IP查询失败: {e}")
            result['error'] = f"查询失败: {str(e)}"
        
        return result
    
    async def query_asn(self, asn: str) -> Dict[str, Any]:
        """查询ASN信息"""
        self._import_libraries()
        
        result = {
            'type': 'asn',
            'query': asn,
            'success': False,
            'data': {},
            'error': None,
            'source': 'ipwhois'
        }
        
        if not self._ipwhois:
            result['error'] = "ASN查询功能不可用，请安装ipwhois库"
            return result
        
        try:
            # 提取ASN号码
            asn_match = re.match(r'^(?:AS)?(\d+)$', asn.upper())
            if not asn_match:
                result['error'] = "无效的ASN格式，请使用 AS1234 或 1234 格式"
                return result
            
            asn_number = asn_match.group(1)

            # 使用任意IP查询ASN信息（使用8.8.8.8作为查询入口），添加15秒超时
            obj = self._ipwhois.IPWhois('8.8.8.8')
            data = await asyncio.wait_for(
                asyncio.to_thread(obj.lookup_rdap, asn=asn_number),
                timeout=15.0
            )

            if data:
                if isinstance(data, dict) and 'asn' in data:
                    result['success'] = True
                    result['data'] = self._format_asn_data(data, asn_number)
                elif isinstance(data, str):
                    result['success'] = True
                    result['data'] = {'原始数据': data[:300] + "..." if len(data) > 300 else data}
                else:
                    result['error'] = f"未找到ASN {asn}的信息"
            else:
                result['error'] = f"未找到ASN {asn}的信息"
                
        except Exception as e:
            logger.error(f"ASN查询失败: {e}")
            result['error'] = f"查询失败: {str(e)}"
        
        return result
    
    async def _query_ip_geolocation(self, ip: str) -> Optional[Dict[str, Any]]:
        """查询IP地理位置信息 (使用IP-API.com)"""
        try:
            from utils.http_client import create_custom_client
            
            # IP-API.com 免费API
            url = f"http://ip-api.com/json/{ip}?fields=status,message,country,countryCode,region,regionName,city,zip,lat,lon,timezone,isp,org,as,query"
            
            headers = {
                "User-Agent": "Mozilla/5.0 (compatible; MengBot/1.0)"
            }
            
            async with create_custom_client(headers=headers) as client:
                response = await client.get(url, timeout=10.0)
                response.raise_for_status()
                data = response.json()
                
                if data.get('status') == 'success':
                    return data
                else:
                    logger.warning(f"IP地理位置查询失败: {data.get('message', '未知错误')}")
                    return None
                    
        except Exception as e:
            logger.error(f"IP地理位置查询异常: {e}")
            return None
    
    def _format_geolocation_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """格式化地理位置数据"""
        formatted = {}
        
        try:
            from utils.country_data import SUPPORTED_COUNTRIES, get_country_flag
            
            # 国家信息
            if 'country' in data and 'countryCode' in data:
                country_name = data['country']
                country_code = data['countryCode']
                try:
                    # 尝试获取旗帜
                    flag = get_country_flag(country_code)
                    formatted['🌍 实际国家'] = f"{flag} {country_name} ({country_code})"
                except:
                    formatted['🌍 实际国家'] = f"{country_name} ({country_code})"
            elif 'country' in data:
                formatted['🌍 实际国家'] = data['country']
            
            # 地区信息
            if 'regionName' in data:
                formatted['🏞️ 实际地区'] = data['regionName']
            
            # 城市信息
            if 'city' in data:
                formatted['🏙️ 实际城市'] = data['city']
            
            # 邮编
            if 'zip' in data and data['zip']:
                formatted['📮 邮政编码'] = data['zip']
            
            # 坐标信息
            if 'lat' in data and 'lon' in data:
                lat = data['lat']
                lon = data['lon']
                formatted['📍 坐标'] = f"{lat:.4f}, {lon:.4f}"
            
            # 时区
            if 'timezone' in data:
                formatted['🕐 时区'] = data['timezone']
            
            # ISP信息
            if 'isp' in data:
                formatted['🌐 ISP'] = data['isp']
            
            # 组织信息 (如果与ISP不同)
            if 'org' in data and data['org'] != data.get('isp'):
                formatted['🏢 实际组织'] = data['org']
            
            # AS信息
            if 'as' in data:
                formatted['🔢 实际AS'] = data['as']
                
        except ImportError:
            # 如果country_data不可用，使用简单格式
            if 'country' in data:
                if 'countryCode' in data:
                    formatted['🌍 实际国家'] = f"{data['country']} ({data['countryCode']})"
                else:
                    formatted['🌍 实际国家'] = data['country']
            
            if 'regionName' in data:
                formatted['🏞️ 实际地区'] = data['regionName']
            if 'city' in data:
                formatted['🏙️ 实际城市'] = data['city']
        
        return formatted
    
    async def query_tld(self, tld: str) -> Dict[str, Any]:
        """查询TLD信息"""
        result = {
            'type': 'tld',
            'query': tld,
            'success': False,
            'data': {},
            'error': None,
            'source': 'iana'
        }
        
        # 清理TLD输入
        tld = tld.lower().strip()
        if not tld.startswith('.'):
            tld = '.' + tld
        
        # 使用IANA数据库查询TLD信息
        tld_info = await self._get_tld_info(tld)
        if tld_info:
            result['success'] = True
            result['data'] = tld_info
        else:
            result['error'] = f"未找到TLD {tld}的信息"
        
        return result
    
    def _extract_whois21_data(self, whois_obj) -> Dict[str, Any]:
        """提取whois21查询结果，根据官方文档正确实现"""
        formatted = {}
        
        # 添加调试信息
        logger.debug(f"whois21对象类型: {type(whois_obj)}")
        logger.debug(f"whois21.success: {whois_obj.success}")
        
        # 检查查询是否成功
        if not whois_obj.success:
            logger.warning(f"whois21查询失败: {whois_obj.error}")
            return {}
        
        # 获取whois_data - 这是主要的数据源
        if hasattr(whois_obj, 'whois_data') and whois_obj.whois_data:
            whois_data = whois_obj.whois_data
            logger.debug(f"whois_data字段: {list(whois_data.keys())}")
            
            # 根据whois21的实际字段进行提取
            for key, value in whois_data.items():
                if value and value != []:  # 跳过空值
                    # 跳过不重要或过长的字段
                    if self._should_skip_field(key, value):
                        continue
                    
                    # 转换为更友好的中文字段名
                    chinese_key = self._translate_field_name(key)
                    
                    # 避免重复添加相同的字段
                    if chinese_key in formatted:
                        continue
                    
                    # 处理列表值
                    if isinstance(value, list):
                        if len(value) == 1:
                            formatted[chinese_key] = str(value[0])
                        else:
                            formatted[chinese_key] = ', '.join(str(v) for v in value)
                    else:
                        formatted[chinese_key] = str(value)
        
        # 获取日期信息 - whois21将这些作为对象属性
        if hasattr(whois_obj, 'creation_date') and whois_obj.creation_date:
            if isinstance(whois_obj.creation_date, list) and len(whois_obj.creation_date) > 0:
                date_obj = whois_obj.creation_date[0]
                if hasattr(date_obj, 'strftime'):
                    formatted['创建时间'] = date_obj.strftime('%Y-%m-%d %H:%M:%S UTC')
                else:
                    formatted['创建时间'] = str(date_obj)
            
        if hasattr(whois_obj, 'expires_date') and whois_obj.expires_date:
            if isinstance(whois_obj.expires_date, list) and len(whois_obj.expires_date) > 0:
                date_obj = whois_obj.expires_date[0]
                if hasattr(date_obj, 'strftime'):
                    formatted['过期时间'] = date_obj.strftime('%Y-%m-%d %H:%M:%S UTC')
                else:
                    formatted['过期时间'] = str(date_obj)
            
        if hasattr(whois_obj, 'updated_date') and whois_obj.updated_date:
            if isinstance(whois_obj.updated_date, list) and len(whois_obj.updated_date) > 0:
                date_obj = whois_obj.updated_date[0]
                if hasattr(date_obj, 'strftime'):
                    formatted['更新时间'] = date_obj.strftime('%Y-%m-%d %H:%M:%S UTC')
                else:
                    formatted['更新时间'] = str(date_obj)
        
        # 如果提取的数据很少，添加原始数据用于调试
        if len(formatted) < 3:
            logger.warning(f"whois21数据提取结果很少: {formatted}")
            if hasattr(whois_obj, 'raw') and whois_obj.raw:
                try:
                    raw_text = whois_obj.raw.decode('utf-8') if isinstance(whois_obj.raw, bytes) else str(whois_obj.raw)
                    formatted['原始WHOIS数据'] = raw_text[:500]  # 限制长度
                except Exception as e:
                    logger.debug(f"无法获取原始数据: {e}")

        logger.debug(f"最终提取的数据: {formatted}")
        return formatted

    def _format_asyncwhois_data(self, parsed_dict: Dict[str, Any]) -> Dict[str, Any]:
        """格式化 asyncwhois 返回的数据"""
        formatted = {}

        # asyncwhois 返回的字段映射
        field_mapping = {
            'domain_name': '域名',
            'registrar': '注册商',
            'whois_server': '注册商WHOIS服务器',
            'registrar_url': '注册商网址',
            'updated': '更新时间',
            'created': '创建时间',
            'expires': '过期时间',
            'name_servers': 'DNS服务器',
            'status': '状态',
            'dnssec': 'DNSSEC',
            'registrant_name': '注册人',
            'registrant_organization': '注册组织',
            'registrant_country': '注册国家',
            'registrant_state': '注册省/州',
            'registrant_city': '注册城市',
            'registrant_address': '注册地址',
            'registrant_zipcode': '注册邮编',
            'registrant_email': '注册邮箱',
            'admin_name': '管理员',
            'admin_email': '管理员邮箱',
            'tech_name': '技术联系人',
            'tech_email': '技术联系人邮箱',
        }

        for eng_key, cn_key in field_mapping.items():
            if eng_key in parsed_dict and parsed_dict[eng_key]:
                value = parsed_dict[eng_key]

                # 处理列表值
                if isinstance(value, list):
                    if len(value) == 1:
                        formatted[cn_key] = str(value[0])
                    else:
                        formatted[cn_key] = ', '.join(str(v) for v in value)
                # 处理日期时间对象
                elif isinstance(value, datetime):
                    formatted[cn_key] = value.strftime('%Y-%m-%d %H:%M:%S UTC')
                else:
                    formatted[cn_key] = str(value)

        logger.debug(f"asyncwhois格式化后的数据: {formatted}")
        return formatted

    async def _query_ng_domain_web(self, domain: str) -> Dict[str, Any]:
        """通过 Web 接口查询 .ng 域名"""
        result = {
            'type': 'domain',
            'query': domain,
            'success': False,
            'data': {},
            'error': None,
            'source': 'whois.net.ng'
        }

        try:
            from utils.http_client import create_custom_client
            from bs4 import BeautifulSoup

            url = f"https://whois.net.ng/whois/?domain={domain}"
            headers = {
                "User-Agent": "Mozilla/5.0 (compatible; MengBot/1.0)"
            }

            async with create_custom_client(headers=headers) as client:
                response = await client.get(url, timeout=15.0)
                # 不检查状态码，因为该网站返回403但仍包含有效数据
                # response.raise_for_status()

                # 解析 HTML
                soup = BeautifulSoup(response.text, 'html.parser')

                # 查找包含 WHOIS 数据的表格
                tables = soup.find_all('table', class_='table')
                if not tables:
                    result['error'] = "未找到 WHOIS 数据"
                    return result

                whois_data = {}
                for table in tables:
                    rows = table.find_all('tr')
                    for row in rows:
                        cols = row.find_all('td')
                        if len(cols) >= 2:
                            # 提取字段名，转换为小写以支持不区分大小写的匹配
                            key = cols[0].get_text(strip=True).rstrip(':').strip().lower()
                            value = cols[1].get_text(separator=' ', strip=True)

                            # 映射字段名为中文（使用小写键）
                            field_map = {
                                'domain': '域名',
                                'registrar': '注册商',
                                'registered on': '创建时间',
                                'expires on': '过期时间',
                                'updated on': '更新时间',
                                'status': '状态',
                                'name servers': 'DNS服务器',
                                'registrar abuse contact email': '注册商举报邮箱',
                                'registrar abuse contact phone': '注册商举报电话',
                                'registrar country': '注册商国家',
                            }

                            if key in field_map:
                                chinese_key = field_map[key]
                                # 避免重复
                                if chinese_key not in whois_data:
                                    whois_data[chinese_key] = value

                if whois_data:
                    result['success'] = True
                    result['data'] = whois_data
                    logger.debug(f".ng域名Web查询成功: {domain}")
                else:
                    result['error'] = "域名未注册或查询失败"

        except Exception as e:
            logger.error(f".ng域名Web查询失败: {e}")
            result['error'] = f"查询失败: {str(e)}"

        return result

    def _should_skip_field(self, key: str, value: Any) -> bool:
        """判断是否应该跳过某个字段"""
        # 转换为字符串进行检查
        str_value = str(value) if not isinstance(value, list) else ', '.join(str(v) for v in value)
        
        # 跳过过长的字段 (超过200字符)
        if len(str_value) > 200:
            return True
        
        # 跳过隐私保护的字段 (REDACTED)
        if 'REDACTED' in str_value.upper():
            return True
        
        # 跳过不重要的字段
        skip_patterns = [
            # 法律声明和条款
            'TERMS OF USE', 'TERMS AND CONDITIONS', 'DISCLAIMER', 'NOTICE',
            'COPYRIGHT', 'LEGAL NOTICE', 'ABUSE CONTACT', 'PRIVACY POLICY',
            
            # 冗长的描述文本
            'DESCRIPTION', 'REMARKS', 'COMMENT', 'NOTE', 'NOTES',
            
            # 技术细节
            'LAST UPDATE OF WHOIS DATABASE', 'WHOIS SERVER', 'REGISTRY WHOIS INFO',
            'WHOIS DATABASE RESPONSES', 'DATABASE LAST UPDATED ON',
            
            # 重复的联系信息块 (通常都是REDACTED)
            'REGISTRANT ORGANIZATION', 'REGISTRANT NAME', 'REGISTRANT EMAIL',
            'REGISTRANT PHONE', 'REGISTRANT FAX', 'REGISTRANT ADDRESS',
            'REGISTRANT STREET', 'REGISTRANT CITY', 'REGISTRANT STATE',
            'REGISTRANT POSTAL CODE', 'REGISTRANT COUNTRY',
            'ADMIN ORGANIZATION', 'ADMIN NAME', 'ADMIN EMAIL', 'ADMIN STREET',
            'ADMIN CITY', 'ADMIN STATE', 'ADMIN POSTAL CODE', 'ADMIN COUNTRY',
            'ADMIN PHONE', 'ADMIN FAX', 'ADMIN PHONE EXT', 'ADMIN FAX EXT',
            'TECH ORGANIZATION', 'TECH NAME', 'TECH EMAIL', 'TECH STREET',
            'TECH CITY', 'TECH STATE', 'TECH POSTAL CODE', 'TECH COUNTRY',
            'TECH PHONE', 'TECH FAX', 'TECH PHONE EXT', 'TECH FAX EXT',
            'BILLING ORGANIZATION', 'BILLING NAME', 'BILLING EMAIL',
            
            # URL和链接
            'URL', 'HTTP', 'HTTPS', 'WWW',
            
            # 其他不重要信息
            'SPONSORING REGISTRAR IANA ID', 'BILLING CONTACT',
            'RESELLER', 'REGISTRY', 'WHOIS LOOKUP',
        ]
        
        # 检查字段名是否包含跳过模式
        key_upper = key.upper()
        for pattern in skip_patterns:
            if pattern in key_upper:
                return True
        
        # 跳过明显的网址和长链接
        if any(url_part in str_value.lower() for url_part in ['http://', 'https://', 'www.', '.com/', '.net/', '.org/']):
            if len(str_value) > 50:  # 长网址
                return True
        
        # 跳过包含大量法律文本的字段
        legal_keywords = ['copyright', 'trademark', 'reserved', 'prohibited', 'violation', 'legal', 'terms', 'conditions']
        if any(keyword in str_value.lower() for keyword in legal_keywords) and len(str_value) > 100:
            return True
        
        return False
    
    def _translate_field_name(self, field_name: str) -> str:
        """将英文字段名翻译为中文"""
        translations = {
            # 基本域名信息
            'DOMAIN NAME': '域名',
            'domain name': '域名',
            'Domain Name': '域名',
            'domain_name': '域名',
            
            # 注册商信息
            'REGISTRAR': '注册商',
            'registrar': '注册商',
            'Registrar': '注册商',
            'REGISTRAR NAME': '注册商',
            'registrar_name': '注册商',
            'SPONSORING REGISTRAR': '注册商',
            
            # 注册商详细信息
            'REGISTRAR WHOIS SERVER': '注册商WHOIS服务器',
            'registrar_whois_server': '注册商WHOIS服务器',
            'REGISTRAR URL': '注册商网址',
            'registrar_url': '注册商网址',
            'REGISTRAR IANA ID': '注册商IANA ID',
            'registrar_iana_id': '注册商IANA ID',
            
            # 域名ID和状态
            'REGISTRY DOMAIN ID': '域名ID',
            'registry_domain_id': '域名ID',
            'domain_id': '域名ID',
            'DOMAIN ID': '域名ID',
            'Domain ID': '域名ID',
            
            # 状态信息
            'STATUS': '状态',
            'status': '状态',
            'Status': '状态',
            'DOMAIN STATUS': '域名状态',
            'domain_status': '域名状态',
            'Domain Status': '域名状态',
            
            # 时间信息
            'CREATION DATE': '创建时间',
            'creation_date': '创建时间',
            'Creation Date': '创建时间',
            'CREATED DATE': '创建时间',
            'created': '创建时间',
            'CREATED': '创建时间',
            'Registration Date': '创建时间',
            
            'REGISTRY EXPIRY DATE': '过期时间',
            'EXPIRY DATE': '过期时间',
            'expiry_date': '过期时间',
            'expires': '过期时间',
            'EXPIRES': '过期时间',
            'Expiry Date': '过期时间',
            'Expiration Date': '过期时间',
            'EXPIRATION DATE': '过期时间',
            
            'UPDATED DATE': '更新时间',
            'updated_date': '更新时间',
            'Updated Date': '更新时间',
            'changed': '更新时间',
            'CHANGED': '更新时间',
            'Last Modified': '更新时间',
            'LAST MODIFIED': '更新时间',
            
            # DNS和网络信息
            'NAME SERVER': 'DNS服务器',
            'name_servers': 'DNS服务器',
            'NAME SERVERS': 'DNS服务器',
            'nameservers': 'DNS服务器',
            'NAMESERVERS': 'DNS服务器',
            'nserver': 'DNS服务器',
            'NSERVER': 'DNS服务器',
            'Name Server': 'DNS服务器',
            
            # 联系信息
            'EMAIL': '邮箱',
            'email': '邮箱',
            'E-MAIL': '邮箱',
            'e-mail': '邮箱',
            'Email': '邮箱',
            
            'PHONE': '电话',
            'phone': '电话',
            'Phone': '电话',
            'TELEPHONE': '电话',
            'telephone': '电话',
            
            'FAX': '传真',
            'fax': '传真',
            'FAX-NO': '传真',
            'fax-no': '传真',
            'Fax': '传真',
            
            # 安全和联系信息
            'REGISTRAR ABUSE CONTACT EMAIL': '注册商举报邮箱',
            'registrar_abuse_contact_email': '注册商举报邮箱',
            'REGISTRAR ABUSE CONTACT PHONE': '注册商举报电话',
            'registrar_abuse_contact_phone': '注册商举报电话',
            
            # 联系人类型
            'admin_c': '管理联系人',
            'ADMIN-C': '管理联系人',
            'admin-c': '管理联系人',
            'tech_c': '技术联系人',
            'TECH-C': '技术联系人',
            'tech-c': '技术联系人',
            'billing_c': '计费联系人',
            'BILLING-C': '计费联系人',
            'billing-c': '计费联系人',
            'registrant_c': '注册人联系人',
            'REGISTRANT-C': '注册人联系人',
            'registrant-c': '注册人联系人',
            
            # 其他信息
            'DNSSEC': 'DNSSEC',
            'dnssec': 'DNSSEC',
            'Dnssec': 'DNSSEC',
            'WHOIS SERVER': 'WHOIS服务器',
            'whois_server': 'WHOIS服务器',
            'Whois Server': 'WHOIS服务器',
            
            # .pl域名特有字段
            'REGISTRANT TYPE': '注册人类型',
            'registrant_type': '注册人类型',
            'RENEWAL DATE': '续费时间',
            'renewal_date': '续费时间',
            'OPTION': '选项',
            'option': '选项',
            'TEL': '电话',
            'tel': '电话',
            'WHOIS DATABASE RESPONSES': 'WHOIS数据库响应',
            'whois_database_responses': 'WHOIS数据库响应',
            
            # 通用联系信息
            'ORGANIZATION': '组织',
            'organization': '组织',
            'Organization': '组织',
            'ORG': '组织',
            'org': '组织',
            'COUNTRY': '国家',
            'country': '国家',
            'Country': '国家',
            'CITY': '城市',
            'city': '城市',
            'City': '城市',
            'STATE': '州/省',
            'state': '州/省',
            'State': '州/省',
            'POSTAL CODE': '邮编',
            'postal_code': '邮编',
            'Postal Code': '邮编',
            'ADDRESS': '地址',
            'address': '地址',
            'Address': '地址',
        }
        
        # 首先尝试直接匹配
        if field_name in translations:
            return translations[field_name]
        
        # 尝试大小写不敏感匹配
        for key, value in translations.items():
            if key.lower() == field_name.lower():
                return value
        
        # 如果没有翻译，返回原字段名
        return field_name
    
    def _format_python_whois_data(self, data) -> Dict[str, Any]:
        """格式化python-whois查询结果"""
        formatted = {}
        
        if hasattr(data, 'domain_name') and data.domain_name:
            domain = data.domain_name[0] if isinstance(data.domain_name, list) else data.domain_name
            formatted['域名'] = str(domain) if domain else None
        
        if hasattr(data, 'registrar') and data.registrar:
            registrar = data.registrar[0] if isinstance(data.registrar, list) else data.registrar
            formatted['注册商'] = str(registrar) if registrar else None
        
        if hasattr(data, 'creation_date') and data.creation_date:
            date = data.creation_date[0] if isinstance(data.creation_date, list) else data.creation_date
            if hasattr(date, 'strftime'):
                formatted['创建时间'] = date.strftime('%Y-%m-%d %H:%M:%S')
            else:
                formatted['创建时间'] = str(date)
        
        if hasattr(data, 'expiration_date') and data.expiration_date:
            date = data.expiration_date[0] if isinstance(data.expiration_date, list) else data.expiration_date
            if hasattr(date, 'strftime'):
                formatted['过期时间'] = date.strftime('%Y-%m-%d %H:%M:%S')
            else:
                formatted['过期时间'] = str(date)
        
        if hasattr(data, 'updated_date') and data.updated_date:
            date = data.updated_date[0] if isinstance(data.updated_date, list) else data.updated_date
            if hasattr(date, 'strftime'):
                formatted['更新时间'] = date.strftime('%Y-%m-%d %H:%M:%S')
            else:
                formatted['更新时间'] = str(date)
        
        if hasattr(data, 'status') and data.status:
            if isinstance(data.status, list):
                formatted['状态'] = ', '.join(str(s) for s in data.status)
            else:
                formatted['状态'] = str(data.status)
        
        if hasattr(data, 'name_servers') and data.name_servers:
            if isinstance(data.name_servers, list):
                formatted['DNS服务器'] = ', '.join(str(ns) for ns in data.name_servers)
            else:
                formatted['DNS服务器'] = str(data.name_servers)
        
        return formatted
    
    def _format_ip_data(self, data: Dict) -> Dict[str, Any]:
        """格式化IP查询结果，增强地理位置信息提取"""
        formatted = {}
        
        # ASN信息（通常在顶级）
        if 'asn' in data:
            formatted['ASN'] = f"AS{data['asn']}"
        
        if 'asn_description' in data:
            formatted['ASN描述'] = data['asn_description']
            
        if 'asn_country_code' in data:
            # 使用country_data优化国家显示
            country_code = data['asn_country_code']
            try:
                from utils.country_data import SUPPORTED_COUNTRIES, get_country_flag
                if country_code in SUPPORTED_COUNTRIES:
                    country_name = SUPPORTED_COUNTRIES[country_code]['name']
                    flag = get_country_flag(country_code)
                    formatted['ASN国家'] = f"{flag} {country_name} ({country_code})"
                else:
                    formatted['ASN国家'] = country_code
            except ImportError:
                formatted['ASN国家'] = country_code
            
        if 'asn_registry' in data:
            formatted['ASN注册机构'] = data['asn_registry']
        
        # 网络信息
        if 'network' in data and isinstance(data['network'], dict):
            network = data['network']
            if 'name' in network:
                formatted['网络名称'] = network['name']
            if 'cidr' in network:
                formatted['IP段'] = network['cidr']
            if 'start_address' in network:
                formatted['起始地址'] = network['start_address']
            if 'end_address' in network:
                formatted['结束地址'] = network['end_address']
            if 'country' in network:
                # 优化网络国家显示
                country_code = network['country']
                try:
                    from utils.country_data import SUPPORTED_COUNTRIES, get_country_flag
                    if country_code in SUPPORTED_COUNTRIES:
                        country_name = SUPPORTED_COUNTRIES[country_code]['name']
                        flag = get_country_flag(country_code)
                        formatted['网络国家'] = f"{flag} {country_name} ({country_code})"
                    else:
                        formatted['网络国家'] = country_code
                except ImportError:
                    formatted['网络国家'] = country_code
            if 'type' in network:
                formatted['网络类型'] = network['type']
        
        # 增强的地理位置和组织信息提取
        organization = None
        location_info = {}
        
        if 'entities' in data and isinstance(data['entities'], list):
            for entity in data['entities']:
                if isinstance(entity, dict):
                    # 查找所有类型的角色，不仅限于特定角色
                    if entity.get('roles') and isinstance(entity['roles'], list):
                        # 提取vCard信息
                        if 'vcardArray' in entity and isinstance(entity['vcardArray'], list) and len(entity['vcardArray']) > 1:
                            vcard = entity['vcardArray'][1]
                            if isinstance(vcard, list):
                                for item in vcard:
                                    if isinstance(item, list) and len(item) > 3:
                                        field_type = item[0].lower()
                                        field_value = item[3]
                                        
                                        # 组织信息
                                        if field_type == 'fn' and not organization:  # Full name
                                            organization = field_value
                                        elif field_type == 'org' and not organization:  # Organization
                                            organization = field_value
                                        
                                        # 地理位置信息
                                        elif field_type == 'adr':  # Address
                                            # vCard地址格式: [post-office-box, extended-address, street-address, locality, region, postal-code, country-name]
                                            if isinstance(field_value, list) and len(field_value) >= 7:
                                                if field_value[3]:  # locality (city)
                                                    location_info['城市'] = field_value[3]
                                                if field_value[4]:  # region (state/province)
                                                    location_info['地区'] = field_value[4]
                                                if field_value[6]:  # country-name
                                                    # 尝试优化国家显示
                                                    country = field_value[6]
                                                    if len(country) == 2:  # 可能是国家代码
                                                        try:
                                                            from utils.country_data import SUPPORTED_COUNTRIES, get_country_flag
                                                            if country.upper() in SUPPORTED_COUNTRIES:
                                                                country_name = SUPPORTED_COUNTRIES[country.upper()]['name']
                                                                flag = get_country_flag(country.upper())
                                                                location_info['国家'] = f"{flag} {country_name} ({country.upper()})"
                                                            else:
                                                                location_info['国家'] = country
                                                        except ImportError:
                                                            location_info['国家'] = country
                                                    else:
                                                        location_info['国家'] = country
                                                if field_value[5]:  # postal-code
                                                    location_info['邮编'] = field_value[5]
                                        
                                        elif field_type == 'geo':  # Geographic position
                                            if isinstance(field_value, str) and ',' in field_value:
                                                lat, lon = field_value.split(',', 1)
                                                location_info['地理坐标'] = f"{lat.strip()}, {lon.strip()}"
        
        # 添加组织信息
        if organization:
            formatted['组织'] = organization
            
        # 添加地理位置信息
        formatted.update(location_info)
        
        # 查找网络块中的国家信息作为备选
        if '国家' not in formatted and 'asn_country_code' in data:
            country_code = data['asn_country_code']
            try:
                from utils.country_data import SUPPORTED_COUNTRIES, get_country_flag
                if country_code in SUPPORTED_COUNTRIES:
                    country_name = SUPPORTED_COUNTRIES[country_code]['name']
                    flag = get_country_flag(country_code)
                    formatted['国家'] = f"{flag} {country_name} ({country_code})"
                else:
                    formatted['国家'] = country_code
            except ImportError:
                formatted['国家'] = country_code
        
        # 尝试从其他字段提取地理信息
        if 'objects' in data and isinstance(data['objects'], dict):
            for obj_key, obj_data in data['objects'].items():
                if isinstance(obj_data, dict):
                    # 联系信息
                    if 'contact' in obj_data:
                        contact = obj_data['contact']
                        if isinstance(contact, dict):
                            if 'name' in contact and '联系人' not in formatted:
                                formatted['联系人'] = contact['name']
                            if 'organization' in contact and '组织' not in formatted:
                                formatted['组织'] = contact['organization']
                            
                            # 地址信息
                            if 'address' in contact:
                                addr = contact['address']
                                if isinstance(addr, dict):
                                    if 'city' in addr and '城市' not in formatted:
                                        formatted['城市'] = addr['city']
                                    if 'region' in addr and '地区' not in formatted:
                                        formatted['地区'] = addr['region']
                                    if 'country' in addr and '国家' not in formatted:
                                        country = addr['country']
                                        if len(country) == 2:  # 可能是国家代码
                                            try:
                                                from utils.country_data import SUPPORTED_COUNTRIES, get_country_flag
                                                if country.upper() in SUPPORTED_COUNTRIES:
                                                    country_name = SUPPORTED_COUNTRIES[country.upper()]['name']
                                                    flag = get_country_flag(country.upper())
                                                    formatted['国家'] = f"{flag} {country_name} ({country.upper()})"
                                                else:
                                                    formatted['国家'] = country
                                            except ImportError:
                                                formatted['国家'] = country
                                        else:
                                            formatted['国家'] = country
                                elif isinstance(addr, list):
                                    # 处理地址列表格式
                                    for line in addr:
                                        if isinstance(line, str) and len(line) < 50:  # 避免过长的地址行
                                            # 简单的国家/地区识别
                                            if any(country in line.upper() for country in ['CN', 'US', 'UK', 'DE', 'FR', 'JP']):
                                                if '国家' not in formatted:
                                                    # 提取国家代码并优化显示
                                                    for cc in ['CN', 'US', 'UK', 'DE', 'FR', 'JP']:
                                                        if cc in line.upper():
                                                            try:
                                                                from utils.country_data import SUPPORTED_COUNTRIES, get_country_flag
                                                                if cc in SUPPORTED_COUNTRIES:
                                                                    country_name = SUPPORTED_COUNTRIES[cc]['name']
                                                                    flag = get_country_flag(cc)
                                                                    formatted['国家'] = f"{flag} {country_name} ({cc})"
                                                                    break
                                                                else:
                                                                    formatted['国家'] = line.strip()
                                                            except ImportError:
                                                                formatted['国家'] = line.strip()
                                                            break
        
        # 如果仍然没有足够信息，添加调试信息
        if len(formatted) < 3:
            if 'query' in data:
                formatted['查询IP'] = data['query']
            
            # 添加一些有用的调试字段
            debug_fields = ['nir', 'referral']
            for field in debug_fields:
                if field in data and data[field]:
                    value = str(data[field])
                    formatted[f'调试_{field}'] = value[:100] + "..." if len(value) > 100 else value
            
            # 如果有原始数据，提取一些关键信息
            if 'raw' in data and isinstance(data['raw'], list):
                for raw_item in data['raw'][:3]:  # 只取前3个原始条目
                    if isinstance(raw_item, dict):
                        for key, value in raw_item.items():
                            if key.lower() in ['country', 'city', 'address', 'location'] and isinstance(value, str):
                                formatted[f'原始_{key}'] = value[:50]
        
        # 添加说明信息，解释WHOIS与地理位置的区别
        if 'asn_description' in data and any(keyword in data['asn_description'].upper() for keyword in ['MICROSOFT', 'AMAZON', 'GOOGLE', 'AZURE', 'AWS']):
            formatted['💡 说明'] = 'WHOIS显示IP注册信息，实际位置见下方地理位置数据'
        
        return formatted
    
    def _format_asn_data(self, data: Dict, asn_number: str) -> Dict[str, Any]:
        """格式化ASN查询结果"""
        formatted = {'ASN': f"AS{asn_number}"}
        
        if 'asn_description' in data:
            formatted['描述'] = data['asn_description']
        
        if 'asn_country_code' in data:
            formatted['国家'] = data['asn_country_code']
        
        if 'asn_registry' in data:
            formatted['注册机构'] = data['asn_registry']
        
        return formatted
    
    async def _get_tld_info(self, tld: str) -> Optional[Dict[str, Any]]:
        """获取TLD基础信息 - 直接从GitHub获取IANA数据"""
        try:
            # 使用TLD管理器获取信息
            tld_manager = getattr(self, '_tld_manager', None)
            if not tld_manager:
                self._tld_manager = TLDManager()
                tld_manager = self._tld_manager
            
            return await tld_manager.get_tld_info(tld)
        except Exception as e:
            logger.debug(f"获取TLD信息失败: {e}")
            # 如果GitHub数据不可用，回退到基础硬编码数据
            return self._get_fallback_tld_info(tld)
    
    def _get_fallback_tld_info(self, tld: str) -> Optional[Dict[str, Any]]:
        """回退的TLD信息（硬编码）"""
        tld_database = {
            '.com': {'类型': 'gTLD', '管理机构': 'Verisign', '创建时间': '1985-01-01', '用途': '商业'},
            '.net': {'类型': 'gTLD', '管理机构': 'Verisign', '创建时间': '1985-01-01', '用途': '网络'},
            '.org': {'类型': 'gTLD', '管理机构': 'PIR', '创建时间': '1985-01-01', '用途': '组织'},
            '.cn': {'类型': 'ccTLD', '管理机构': 'CNNIC', '国家': '中国', '用途': '中国国家域名'},
            '.us': {'类型': 'ccTLD', '管理机构': 'Neustar', '国家': '美国', '用途': '美国国家域名'},
            '.uk': {'类型': 'ccTLD', '管理机构': 'Nominet', '国家': '英国', '用途': '英国国家域名'},
            '.jp': {'类型': 'ccTLD', '管理机构': 'JPRS', '国家': '日本', '用途': '日本国家域名'},
            '.io': {'类型': 'ccTLD', '管理机构': 'ICB', '国家': '英属印度洋领地', '用途': '技术公司'},
            '.ai': {'类型': 'ccTLD', '管理机构': 'Government of Anguilla', '国家': '安圭拉', '用途': 'AI公司'},
            '.dev': {'类型': 'gTLD', '管理机构': 'Google', '创建时间': '2019-01-01', '用途': '开发者'},
        }
        
        return tld_database.get(tld.lower())
    
    async def query_dns(self, domain: str) -> Dict[str, Any]:
        """查询域名DNS记录"""
        self._import_libraries()
        
        result = {
            'type': 'dns',
            'query': domain,
            'success': False,
            'data': {},
            'error': None,
            'source': 'dnspython'
        }
        
        if not self._dns:
            result['error'] = "DNS查询功能不可用，请安装dnspython库"
            return result
        
        # 清理域名输入
        domain = domain.lower().strip()
        if domain.startswith(('http://', 'https://')):
            domain = domain.split('//', 1)[1].split('/')[0]
        
        dns_data = {}
        
        # 定义要查询的DNS记录类型
        record_types = [
            ('A', 'IPv4地址'),
            ('AAAA', 'IPv6地址'),
            ('MX', '邮件服务器'),
            ('NS', '域名服务器'),
            ('CNAME', '别名记录'),
            ('TXT', '文本记录'),
            ('SOA', '授权开始')
        ]
        
        try:
            for record_type, description in record_types:
                try:
                    answers = await asyncio.to_thread(
                        self._dns.resolver.resolve, domain, record_type
                    )
                    
                    records = []
                    for rdata in answers:
                        if record_type == 'MX':
                            records.append(f"{rdata.preference} {rdata.exchange}")
                        elif record_type == 'SOA':
                            # 将SOA记录格式化为多行显示
                            soa_info = (
                                f"{rdata.mname} {rdata.rname} "
                                f"序列:{rdata.serial} 刷新:{rdata.refresh}s "
                                f"重试:{rdata.retry}s 过期:{rdata.expire}s TTL:{rdata.minimum}s"
                            )
                            records.append(soa_info)
                        else:
                            records.append(str(rdata))
                    
                    if records:
                        dns_data[f'{record_type}记录'] = records
                        logger.debug(f"DNS查询 - {record_type}记录: {len(records)} 条, 内容: {records}")
                        
                except self._dns.resolver.NoAnswer:
                    # 没有该类型的记录，跳过
                    continue
                except self._dns.resolver.NXDOMAIN:
                    # 域名不存在
                    result['error'] = f"域名 {domain} 不存在"
                    return result
                except Exception as e:
                    logger.debug(f"查询{record_type}记录失败: {e}")
                    continue
            
            # 尝试反向DNS查询（如果有A记录）
            if 'A记录' in dns_data and dns_data['A记录']:
                try:
                    first_ip = dns_data['A记录'][0]
                    reversed_name = self._dns.reversename.from_address(first_ip)
                    ptr_answers = await asyncio.to_thread(
                        self._dns.resolver.resolve, reversed_name, 'PTR'
                    )
                    ptr_records = [str(rdata) for rdata in ptr_answers]
                    if ptr_records:
                        dns_data['PTR记录'] = ptr_records
                except Exception as e:
                    logger.debug(f"反向DNS查询失败: {e}")
            
            if dns_data:
                result['success'] = True
                result['data'] = dns_data
            else:
                result['error'] = f"未找到域名 {domain} 的DNS记录"
                
        except Exception as e:
            logger.error(f"DNS查询失败: {e}")
            result['error'] = f"DNS查询失败: {str(e)}"
        
        return result

async def create_telegraph_page(title: str, content: str) -> Optional[str]:
    """创建Telegraph页面"""
    try:
        from utils.http_client import create_custom_client
        
        # 创建Telegraph账户
        account_data = {
            "short_name": "MengBot",
            "author_name": "MengBot WHOIS",
            "author_url": "https://t.me/mengpricebot"
        }
        
        async with create_custom_client() as client:
            response = await client.post(f"{TELEGRAPH_API_URL}/createAccount", data=account_data)
            if response.status_code != 200:
                logger.warning(f"Telegraph账户创建失败: {response.status_code}")
                return None
                
            account_info = response.json()
            if not account_info.get("ok"):
                logger.warning(f"Telegraph账户创建响应失败: {account_info}")
                return None
                
            access_token = account_info["result"]["access_token"]
            
            # 创建页面内容
            page_content = [
                {
                    "tag": "p",
                    "children": [content]
                }
            ]
            
            page_data = {
                "access_token": access_token,
                "title": title,
                "content": json.dumps(page_content),
                "return_content": "true"
            }
            
            response = await client.post(f"{TELEGRAPH_API_URL}/createPage", data=page_data)
            if response.status_code != 200:
                logger.warning(f"Telegraph页面创建失败: {response.status_code}")
                return None
                
            page_info = response.json()
            if not page_info.get("ok"):
                logger.warning(f"Telegraph页面创建响应失败: {page_info}")
                return None
                
            return page_info["result"]["url"]
    
    except Exception as e:
        logger.error(f"创建Telegraph页面失败: {e}")
        return None

def format_whois_result_for_telegraph(result: Dict[str, Any]) -> str:
    """将WHOIS/DNS查询结果格式化为Telegraph友好的纯文本格式"""
    if not result['success']:
        error_msg = result.get('error', '查询失败')
        return f"❌ 查询失败\n\n{error_msg}"
    
    query_type_map = {
        'domain': '🌐 域名',
        'ip': '🖥️ IP地址', 
        'asn': '🔢 ASN',
        'tld': '🏷️ 顶级域名',
        'dns': '🔍 DNS记录'
    }
    
    query_type = query_type_map.get(result['type'], '🔍 查询')
    query = result['query']
    source_info = f" ({result['source']})" if result.get('source') else ""
    
    # 标题部分
    lines = [f"✅ {query_type}查询结果{source_info}"]
    lines.append("=" * 50)
    lines.append(f"🔍 查询对象: {query}")
    lines.append("")
    
    # 格式化数据 - 按类别分组（Telegraph版本不需要Markdown转义）
    data = result.get('data', {})
    if data:
        # 定义字段分组和显示顺序
        field_groups = {
            '📋 基本信息': ['域名', '域名ID', '查询IP', '类型', '注册人类型'],
            '🏢 注册商信息': ['注册商', '注册商WHOIS服务器', '注册商网址', '注册商IANA ID', '管理机构', '组织'],
            '📅 时间信息': ['创建时间', '过期时间', '更新时间', '最后更新', '续费时间'],
            '📊 状态信息': ['状态', '域名状态', '选项'],
            '🌐 网络信息': ['DNS服务器', 'ASN', 'ASN描述', 'ASN国家', 'ASN注册机构', '网络名称', 'IP段', '起始地址', '结束地址', '网络国家', '网络类型', 'WHOIS服务器', '国际化域名', 'DNSSEC'],
            '🔍 DNS记录': ['🌐 A记录', '🌐 AAAA记录', '🌐 MX记录', '🌐 NS记录', '🌐 CNAME记录', '🌐 TXT记录', '🌐 SOA记录', '🌐 PTR记录', 'A记录', 'AAAA记录', 'MX记录', 'NS记录', 'CNAME记录', 'TXT记录', 'SOA记录', 'PTR记录'],
            '📍 注册位置': ['国家', '地区', '城市', '邮编', '地理坐标'],
            '🌍 实际位置': ['🌍 实际国家', '🏞️ 实际地区', '🏙️ 实际城市', '📮 邮政编码', '📍 坐标', '🕐 时区'],
            '🏢 实际网络': ['🌐 ISP', '🏢 实际组织', '🔢 实际AS'],
            '📞 联系信息': ['邮箱', '电话', '传真', '联系人', '地址'],
            '🛡️ 安全信息': ['注册商举报邮箱', '注册商举报电话'],
            '🔗 参考信息': ['WHOIS数据库响应', '选项'],
            '💡 说明信息': ['💡 说明'],
            '📄 其他信息': []  # 未分类的字段
        }
        
        # 创建字段到分组的映射
        field_to_group = {}
        for group, fields in field_groups.items():
            for field in fields:
                field_to_group[field] = group
        
        # 按分组组织数据
        grouped_data = {}
        for key, value in data.items():
            group = field_to_group.get(key, '📄 其他信息')
            if group not in grouped_data:
                grouped_data[group] = []
            grouped_data[group].append((key, value))
        
        # 按分组顺序显示
        for group_name in field_groups.keys():
            if group_name != '📄 其他信息' and group_name in grouped_data and grouped_data[group_name]:
                lines.append(f"{group_name}")
                lines.append("-" * 30)
                for key, value in grouped_data[group_name]:
                    if isinstance(value, list):
                        if len(value) > 1:
                            lines.append(f"• {key}:")
                            for item in value:
                                lines.append(f"  ◦ {item}")
                        else:
                            lines.append(f"• {key}: {value[0]}")
                    else:
                        lines.append(f"• {key}: {value}")
                lines.append("")  # 分组间空行
        
        # 显示其他未分类字段（全部显示，不限制数量）
        if '📄 其他信息' in grouped_data and grouped_data['📄 其他信息']:
            lines.append("📄 其他信息")
            lines.append("-" * 30)
            for key, value in grouped_data['📄 其他信息']:
                if isinstance(value, list):
                    if len(value) > 1:
                        lines.append(f"• {key}:")
                        for item in value:
                            lines.append(f"  ◦ {item}")
                    else:
                        lines.append(f"• {key}: {value[0]}")
                else:
                    lines.append(f"• {key}: {value}")
    
    return '\n'.join(lines)

def detect_query_type(query: str) -> str:
    """智能检测查询类型"""
    query = query.strip()
    
    # 检查是否为IP地址
    try:
        ipaddress.ip_address(query)
        return 'ip'
    except ValueError:
        pass
    
    # 检查是否为ASN
    if re.match(r'^(?:AS)?\d+$', query.upper()):
        return 'asn'
    
    # 检查是否为TLD
    if query.startswith('.') and '.' not in query[1:]:
        return 'tld'
    
    # 默认为域名
    return 'domain'

def safe_escape_markdown(text: Any, version: int = 2) -> str:
    """安全转义Markdown，处理可能的None值和特殊字符"""
    if text is None:
        return "N/A"
    
    text_str = str(text)
    if not text_str.strip():
        return "N/A"
    
    try:
        # 先清理一些可能导致问题的字符
        cleaned_text = text_str.replace('\x00', '').replace('\r', ' ').replace('\n', ' ')
        # 限制长度防止过长，但对于DNS记录等重要信息给予更多空间
        max_length = 500 if any(keyword in text_str for keyword in ['序列:', 'refresh', 'retry', 'expire', 'minimum', '记录']) else 200
        if len(cleaned_text) > max_length:
            cleaned_text = cleaned_text[:max_length-3] + "..."
        
        return escape_markdown(cleaned_text, version=version)
    except Exception as e:
        logger.debug(f"转义失败，使用安全回退: {e}")
        # 如果转义失败，使用更简单的方法
        safe_text = re.sub(r'[^\w\s\-\.@:/]', '', text_str)
        max_length = 500 if any(keyword in text_str for keyword in ['序列:', 'refresh', 'retry', 'expire', 'minimum', '记录']) else 200
        return safe_text[:max_length] if len(safe_text) > max_length else safe_text

def format_whois_result(result: Dict[str, Any]) -> str:
    """格式化WHOIS查询结果为美化的Markdown"""
    if not result['success']:
        error_msg = safe_escape_markdown(result.get('error', '查询失败'))
        return f"❌ **查询失败**\n\n{error_msg}"
    
    query_type_map = {
        'domain': '🌐 域名',
        'ip': '🖥️ IP地址', 
        'asn': '🔢 ASN',
        'tld': '🏷️ 顶级域名',
        'dns': '🔍 DNS记录'
    }
    
    query_type = query_type_map.get(result['type'], '🔍 查询')
    safe_query = safe_escape_markdown(result['query'])
    
    # 正确转义source信息
    if result.get('source'):
        safe_source = safe_escape_markdown(result['source'])
        source_info = f" \\({safe_source}\\)"
    else:
        source_info = ""
    
    # 标题部分
    lines = [f"✅ **{query_type}查询结果**{source_info}"]
    lines.append("━" * 30)
    lines.append(f"🔍 **查询对象**: `{safe_query}`")
    lines.append("")
    
    # 格式化数据 - 按类别分组
    data = result.get('data', {})
    if data:
        # 定义字段分组和显示顺序
        field_groups = {
            '📋 基本信息': ['域名', '域名ID', '查询IP', '类型', '注册人类型'],
            '🏢 注册商信息': ['注册商', '注册商WHOIS服务器', '注册商网址', '注册商IANA ID', '管理机构', '组织'],
            '📅 时间信息': ['创建时间', '过期时间', '更新时间', '最后更新', '续费时间'],
            '📊 状态信息': ['状态', '域名状态', '选项'],
            '🌐 网络信息': ['DNS服务器', 'ASN', 'ASN描述', 'ASN国家', 'ASN注册机构', '网络名称', 'IP段', '起始地址', '结束地址', '网络国家', '网络类型', 'WHOIS服务器', '国际化域名', 'DNSSEC'],
            '🔍 DNS记录': ['🌐 A记录', '🌐 AAAA记录', '🌐 MX记录', '🌐 NS记录', '🌐 CNAME记录', '🌐 TXT记录', '🌐 SOA记录', '🌐 PTR记录', 'A记录', 'AAAA记录', 'MX记录', 'NS记录', 'CNAME记录', 'TXT记录', 'SOA记录', 'PTR记录'],
            '📍 注册位置': ['国家', '地区', '城市', '邮编', '地理坐标'],
            '🌍 实际位置': ['🌍 实际国家', '🏞️ 实际地区', '🏙️ 实际城市', '📮 邮政编码', '📍 坐标', '🕐 时区'],
            '🏢 实际网络': ['🌐 ISP', '🏢 实际组织', '🔢 实际AS'],
            '📞 联系信息': ['邮箱', '电话', '传真', '联系人', '地址'],
            '🛡️ 安全信息': ['注册商举报邮箱', '注册商举报电话'],
            '🔗 参考信息': ['WHOIS数据库响应', '选项'],
            '💡 说明信息': ['💡 说明'],
            '📄 其他信息': []  # 未分类的字段
        }
        
        # 创建字段到分组的映射
        field_to_group = {}
        for group, fields in field_groups.items():
            for field in fields:
                field_to_group[field] = group
        
        # 按分组组织数据
        grouped_data = {}
        for key, value in data.items():
            group = field_to_group.get(key, '📄 其他信息')
            if group not in grouped_data:
                grouped_data[group] = []
            grouped_data[group].append((key, value))
        
        # 按分组顺序显示 (除了"其他信息"，单独处理)
        # 特别处理DNS记录分组 - 确保DNS记录显示在正确位置
        for group_name in field_groups.keys():
            if group_name != '📄 其他信息' and group_name in grouped_data and grouped_data[group_name]:
                # 特别处理DNS记录分组
                if group_name == '🔍 DNS记录':
                    logger.debug(f"处理DNS记录分组，包含字段: {[key for key, value in grouped_data[group_name]]}")
                lines.append(f"**{group_name}**")
                for key, value in grouped_data[group_name]:
                    safe_key = safe_escape_markdown(key)
                    
                    if isinstance(value, list):
                        # 对列表中的每个元素单独转义
                        safe_values = [safe_escape_markdown(v) for v in value]
                        
                        # DNS记录和其他多条记录的显示处理
                        if group_name == '🔍 DNS记录' and len(safe_values) > 1:
                            # 多条DNS记录使用换行显示，不限制数量
                            safe_value = '\n    ◦ ' + '\n    ◦ '.join(safe_values)
                        elif len(safe_values) > 1:
                            # 其他多条记录使用换行显示
                            safe_value = '\n    ◦ ' + '\n    ◦ '.join(safe_values)
                        else:
                            # 单条记录直接显示
                            safe_value = ', '.join(safe_values)
                    else:
                        safe_value = safe_escape_markdown(value)
                    
                    # 使用更美观的格式
                    lines.append(f"  • **{safe_key}**: {safe_value}")
                lines.append("")  # 分组间空行
        
        # 显示其他未分类字段（全部显示，不限制数量）
        if '📄 其他信息' in grouped_data and grouped_data['📄 其他信息']:
            other_fields = grouped_data['📄 其他信息']
            
            lines.append("**📄 其他信息**")
            for key, value in other_fields:
                safe_key = safe_escape_markdown(key)
                
                if isinstance(value, list):
                    safe_values = [safe_escape_markdown(v) for v in value]
                    
                    # 多条记录使用换行显示，不限制数量
                    if len(safe_values) > 1:
                        safe_value = '\n    ◦ ' + '\n    ◦ '.join(safe_values)
                    else:
                        safe_value = ', '.join(safe_values)
                else:
                    safe_value = safe_escape_markdown(value)
                
                lines.append(f"  • **{safe_key}**: {safe_value}")
    
    # 移除最后的空行
    while lines and lines[-1] == "":
        lines.pop()
    
    return '\n'.join(lines)

async def whois_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """WHOIS查询命令 - 智能识别查询类型"""
    try:
        if not context.args:
            help_text = (
                "🔍 **WHOIS查询帮助**\n\n"
                "**使用方法:**\n"
                "• `/whois <查询内容>` \\- 智能识别并查询\n\n"
                "**支持查询类型:**\n"
                "• 🌐 域名: `example\\.com` \\(包含DNS记录\\)\n"
                "• 🖥️ IP地址: `8\\.8\\.8\\.8`\n"
                "• 🔢 ASN: `AS15169` 或 `15169`\n"
                "• 🏷️ TLD: `\\.com` 或 `com`\n\n"
                "**专用命令:**\n"
                "• `/whois_domain <域名>`\n"
                "• `/whois_ip <IP地址>`\n"
                "• `/whois_asn <ASN>`\n"
                "• `/whois_tld <TLD>`\n"
                "• `/dns <域名>` \\- 仅查询DNS记录\n\n"
                "**示例:**\n"
                "• `/whois google\\.com`\n"
                "• `/whois 1\\.1\\.1\\.1`\n"
                "• `/whois AS13335`\n"
                "• `/whois \\.io`"
            )
            
            await send_message_with_auto_delete(
                context=context,
                chat_id=update.effective_chat.id,
                text=help_text,
                parse_mode=ParseMode.MARKDOWN_V2
            )
            await delete_user_command(
                context=context,
                chat_id=update.effective_chat.id,
                message_id=update.effective_message.message_id
            )
            return
        
        query = ' '.join(context.args)
        query_type = detect_query_type(query)
        
        # 检查缓存
        cache_key = f"whois_{query_type}_{query}"
        cached_result = None
        if cache_manager:
            try:
                cached_result = await cache_manager.load_cache(cache_key, subdirectory="whois")
            except Exception as e:
                logger.debug(f"缓存读取失败: {e}")
        
        if cached_result:
            result = cached_result
        else:
            # 执行查询
            service = WhoisService()
            
            if query_type == 'domain':
                result = await service.query_domain(query)
            elif query_type == 'ip':
                result = await service.query_ip(query)
            elif query_type == 'asn':
                result = await service.query_asn(query)
            elif query_type == 'tld':
                result = await service.query_tld(query)
            else:
                result = {'success': False, 'error': '未知的查询类型'}
            
            # 缓存结果
            if cache_manager and result['success']:
                try:
                    # 成功的查询结果缓存
                    await cache_manager.save_cache(
                        cache_key, 
                        result, 
                        subdirectory="whois"
                    )
                except Exception as e:
                    logger.debug(f"缓存保存失败: {e}")
        
        # 格式化并发送结果
        try:
            response = format_whois_result(result)
            logger.debug(f"格式化后的响应长度: {len(response)}")
            
            # 检查消息长度并选择合适的处理方式
            if len(response) > 4000:  # Telegram消息限制约4096字符
                logger.info(f"WHOIS响应过长({len(response)}字符)，尝试使用Telegraph。查询: {query}")
                
                # 创建Telegraph页面
                query_type = result.get('type', 'unknown')
                query_obj = result.get('query', query)
                telegraph_title = f"{query_obj} - {query_type.upper()}查询结果"
                telegraph_content = format_whois_result_for_telegraph(result)
                telegraph_url = await create_telegraph_page(telegraph_title, telegraph_content)
                
                if telegraph_url:
                    # 创建简化的Telegram消息，包含Telegraph链接
                    query_type_map = {
                        'domain': '🌐 域名',
                        'ip': '🖥️ IP地址', 
                        'asn': '🔢 ASN',
                        'tld': '🏷️ 顶级域名',
                        'dns': '🔍 DNS记录'
                    }
                    query_type_display = query_type_map.get(query_type, '🔍 查询')
                    source_info = f" \\({safe_escape_markdown(result['source'])}\\)" if result.get('source') else ""
                    safe_query_obj = safe_escape_markdown(query_obj)
                    
                    # 提取一些关键信息显示在消息中
                    data = result.get('data', {})
                    key_info_lines = []
                    
                    # 根据查询类型显示关键信息
                    if query_type == 'domain':
                        if '注册商' in data:
                            key_info_lines.append(f"• **注册商**: {safe_escape_markdown(str(data['注册商']))}")
                        if '创建时间' in data:
                            key_info_lines.append(f"• **创建时间**: {safe_escape_markdown(str(data['创建时间']))}")
                        if '🌐 A记录' in data:
                            a_records = data['🌐 A记录']
                            if isinstance(a_records, list) and a_records:
                                key_info_lines.append(f"• **A记录**: {safe_escape_markdown(str(a_records[0]))}")
                    elif query_type == 'ip':
                        if 'ASN' in data:
                            key_info_lines.append(f"• **ASN**: {safe_escape_markdown(str(data['ASN']))}")
                        if '🌍 实际国家' in data:
                            key_info_lines.append(f"• **国家**: {safe_escape_markdown(str(data['🌍 实际国家']))}")
                        if '🏙️ 实际城市' in data:
                            key_info_lines.append(f"• **城市**: {safe_escape_markdown(str(data['🏙️ 实际城市']))}")
                    elif query_type == 'dns':
                        record_count = len([k for k in data.keys() if '记录' in k])
                        key_info_lines.append(f"• **DNS记录类型**: {record_count} 种")
                    
                    short_response_lines = [
                        f"✅ **{query_type_display}查询结果**{source_info}",
                        "━" * 30,
                        f"🔍 **查询对象**: `{safe_query_obj}`",
                        ""
                    ]
                    
                    if key_info_lines:
                        short_response_lines.append("**📋 关键信息**:")
                        short_response_lines.extend(key_info_lines)
                        short_response_lines.append("")
                    
                    short_response_lines.extend([
                        f"📄 **完整查询结果**: 内容较长，已生成Telegraph页面",
                        f"🔗 **查看完整信息**: {telegraph_url}"
                    ])
                    
                    response = '\n'.join(short_response_lines)
                    logger.info(f"WHOIS响应已生成Telegraph页面: {telegraph_url}")
                else:
                    # Telegraph创建失败，使用foldable text
                    from utils.formatter import foldable_text_with_markdown_v2
                    response = foldable_text_with_markdown_v2(response)
                    logger.warning(f"Telegraph页面创建失败，使用foldable text。查询: {query}")
                    
                    # 如果仍然过长，截断
                    if len(response) > 4000:
                        response = response[:3900] + "\n\n⚠️ 内容过长，已截断显示"
                        logger.warning(f"WHOIS响应即使使用foldable text仍过长，已截断。查询: {query}")
            
            await send_message_with_auto_delete(
                context=context,
                chat_id=update.effective_chat.id,
                text=response,
                parse_mode=ParseMode.MARKDOWN_V2
            )
        except Exception as format_error:
            logger.error(f"格式化或发送响应失败: {format_error}")
            # 发送简化的错误信息
            simple_response = f"✅ 查询完成\n查询对象: {query}\n类型: {result.get('type', 'unknown')}\n\n⚠️ 格式化显示时出现问题，请尝试其他查询。"
            await send_message_with_auto_delete(
                context=context,
                chat_id=update.effective_chat.id,
                text=simple_response,
                parse_mode=None  # 使用普通文本模式
            )
        
        await delete_user_command(
            context=context,
            chat_id=update.effective_chat.id,
            message_id=update.effective_message.message_id
        )
        
    except Exception as e:
        logger.error(f"WHOIS查询失败: {e}")
        await send_error(
            context=context,
            chat_id=update.effective_chat.id,
            text="查询失败，请稍后重试"
        )
        await delete_user_command(
            context=context,
            chat_id=update.effective_chat.id,
            message_id=update.effective_message.message_id
        )

async def whois_domain_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """域名WHOIS查询"""
    if not context.args:
        await send_error(context, update.effective_chat.id, "请提供域名，例如: /whois_domain google.com")
        return
    
    domain = ' '.join(context.args)
    service = WhoisService()
    result = await service.query_domain(domain)
    response = format_whois_result(result)
    
    await send_message_with_auto_delete(
        context=context,
        chat_id=update.effective_chat.id,
        text=response,
        parse_mode=ParseMode.MARKDOWN_V2
    )
    await delete_user_command(context, update.effective_chat.id, update.effective_message.message_id)

async def whois_ip_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """IP地址WHOIS查询"""
    if not context.args:
        await send_error(context, update.effective_chat.id, "请提供IP地址，例如: /whois_ip 8.8.8.8")
        return
    
    ip = context.args[0]
    service = WhoisService()
    result = await service.query_ip(ip)
    response = format_whois_result(result)
    
    await send_message_with_auto_delete(
        context=context,
        chat_id=update.effective_chat.id,
        text=response,
        parse_mode=ParseMode.MARKDOWN_V2
    )
    await delete_user_command(context, update.effective_chat.id, update.effective_message.message_id)

async def whois_asn_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ASN WHOIS查询"""
    if not context.args:
        await send_error(context, update.effective_chat.id, "请提供ASN，例如: /whois_asn AS15169")
        return
    
    asn = context.args[0]
    service = WhoisService()
    result = await service.query_asn(asn)
    response = format_whois_result(result)
    
    await send_message_with_auto_delete(
        context=context,
        chat_id=update.effective_chat.id,
        text=response,
        parse_mode=ParseMode.MARKDOWN_V2
    )
    await delete_user_command(context, update.effective_chat.id, update.effective_message.message_id)

async def whois_tld_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """TLD WHOIS查询"""
    if not context.args:
        await send_error(context, update.effective_chat.id, "请提供TLD，例如: /whois_tld .com")
        return
    
    tld = context.args[0]
    service = WhoisService()
    result = await service.query_tld(tld)
    response = format_whois_result(result)
    
    await send_message_with_auto_delete(
        context=context,
        chat_id=update.effective_chat.id,
        text=response,
        parse_mode=ParseMode.MARKDOWN_V2
    )
    await delete_user_command(context, update.effective_chat.id, update.effective_message.message_id)

async def dns_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """DNS记录查询命令"""
    try:
        if not context.args:
            help_text = (
                "🔍 **DNS查询帮助**\n\n"
                "**使用方法:**\n"
                "• `/dns <域名>` \\- 查询域名的DNS记录\n\n"
                "**支持的DNS记录类型:**\n"
                "• 🅰️ A记录 \\- IPv4地址\n"
                "• 🅰️🅰️🅰️🅰️ AAAA记录 \\- IPv6地址\n"
                "• 📧 MX记录 \\- 邮件服务器\n"
                "• 🌐 NS记录 \\- 域名服务器\n"
                "• 🔗 CNAME记录 \\- 别名记录\n"
                "• 📄 TXT记录 \\- 文本记录\n"
                "• 🏛️ SOA记录 \\- 授权开始\n"
                "• ↩️ PTR记录 \\- 反向DNS\n\n"
                "**示例:**\n"
                "• `/dns google\\.com`\n"
                "• `/dns github\\.com`"
            )
            
            await send_message_with_auto_delete(
                context=context,
                chat_id=update.effective_chat.id,
                text=help_text,
                parse_mode=ParseMode.MARKDOWN_V2
            )
            await delete_user_command(
                context=context,
                chat_id=update.effective_chat.id,
                message_id=update.effective_message.message_id
            )
            return
        
        domain = ' '.join(context.args)
        
        # 检查缓存
        cache_key = f"dns_{domain}"
        cached_result = None
        if cache_manager:
            try:
                cached_result = await cache_manager.load_cache(cache_key, subdirectory="dns")
            except Exception as e:
                logger.debug(f"缓存读取失败: {e}")
        
        if cached_result:
            result = cached_result
        else:
            # 执行DNS查询
            service = WhoisService()
            result = await service.query_dns(domain)
            
            # 缓存结果
            if cache_manager and result['success']:
                try:
                    await cache_manager.save_cache(
                        cache_key, 
                        result, 
                        subdirectory="dns"
                    )
                except Exception as e:
                    logger.debug(f"缓存保存失败: {e}")
        
        # 格式化并发送结果
        try:
            response = format_whois_result(result)
            logger.debug(f"格式化后的响应长度: {len(response)}")
            
            # 检查消息长度并选择合适的处理方式
            if len(response) > 4000:
                logger.info(f"DNS响应过长({len(response)}字符)，尝试使用Telegraph。查询: {domain}")
                
                # 创建Telegraph页面
                telegraph_title = f"{domain} - DNS记录查询结果"
                telegraph_content = format_whois_result_for_telegraph(result)
                telegraph_url = await create_telegraph_page(telegraph_title, telegraph_content)
                
                if telegraph_url:
                    # 创建简化的Telegram消息，包含Telegraph链接
                    safe_domain = safe_escape_markdown(domain)
                    
                    # 提取DNS记录概要
                    data = result.get('data', {})
                    record_summary = []
                    record_types = ['A记录', 'AAAA记录', 'MX记录', 'NS记录', 'CNAME记录', 'TXT记录', 'SOA记录', 'PTR记录']
                    
                    for record_type in record_types:
                        if record_type in data:
                            records = data[record_type]
                            if isinstance(records, list):
                                count = len(records)
                                if count > 0:
                                    record_summary.append(f"• **{record_type}**: {count} 条")
                    
                    short_response_lines = [
                        f"✅ **🔍 DNS记录查询结果** \\(dnspython\\)",
                        "━" * 30,
                        f"🔍 **查询对象**: `{safe_domain}`",
                        ""
                    ]
                    
                    if record_summary:
                        short_response_lines.append("**📋 记录概要**:")
                        short_response_lines.extend(record_summary)
                        short_response_lines.append("")
                    
                    short_response_lines.extend([
                        f"📄 **完整DNS记录**: 内容较长，已生成Telegraph页面",
                        f"🔗 **查看完整记录**: {telegraph_url}"
                    ])
                    
                    response = '\n'.join(short_response_lines)
                    logger.info(f"DNS响应已生成Telegraph页面: {telegraph_url}")
                else:
                    # Telegraph创建失败，使用foldable text
                    from utils.formatter import foldable_text_with_markdown_v2
                    response = foldable_text_with_markdown_v2(response)
                    logger.warning(f"Telegraph页面创建失败，使用foldable text。查询: {domain}")
                    
                    # 如果仍然过长，截断
                    if len(response) > 4000:
                        response = response[:3900] + "\n\n⚠️ 内容过长，已截断显示"
                        logger.warning(f"DNS响应即使使用foldable text仍过长，已截断。查询: {domain}")
            
            await send_message_with_auto_delete(
                context=context,
                chat_id=update.effective_chat.id,
                text=response,
                parse_mode=ParseMode.MARKDOWN_V2
            )
        except Exception as format_error:
            logger.error(f"格式化或发送响应失败: {format_error}")
            simple_response = f"✅ DNS查询完成\n查询对象: {domain}\n\n⚠️ 格式化显示时出现问题，请尝试其他查询。"
            await send_message_with_auto_delete(
                context=context,
                chat_id=update.effective_chat.id,
                text=simple_response,
                parse_mode=None
            )
        
        await delete_user_command(
            context=context,
            chat_id=update.effective_chat.id,
            message_id=update.effective_message.message_id
        )
        
    except Exception as e:
        logger.error(f"DNS查询失败: {e}")
        await send_error(
            context=context,
            chat_id=update.effective_chat.id,
            text="DNS查询失败，请稍后重试"
        )
        await delete_user_command(
            context=context,
            chat_id=update.effective_chat.id,
            message_id=update.effective_message.message_id
        )

async def whois_clean_cache_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """清理WHOIS查询缓存"""
    if not update.message or not update.effective_chat:
        return
    
    try:
        if cache_manager:
            await cache_manager.clear_cache(subdirectory="whois")
            await cache_manager.clear_cache(subdirectory="dns")
            success_message = "✅ WHOIS和DNS查询缓存已清理完成。\n\n包括：域名、IP地址、ASN、TLD和DNS查询结果。"
        else:
            success_message = "⚠️ 缓存管理器未初始化。"
        
        await send_message_with_auto_delete(
            context=context,
            chat_id=update.effective_chat.id,
            text=success_message,
            parse_mode=ParseMode.MARKDOWN_V2
        )
        await delete_user_command(
            context=context,
            chat_id=update.effective_chat.id,
            message_id=update.effective_message.message_id
        )
        
    except Exception as e:
        logger.error(f"清理WHOIS缓存失败: {e}")
        error_message = f"❌ 清理WHOIS缓存时发生错误: {str(e)}"
        await send_error(
            context=context,
            chat_id=update.effective_chat.id,
            text=error_message
        )
        await delete_user_command(
            context=context,
            chat_id=update.effective_chat.id,
            message_id=update.effective_message.message_id
        )

# 注册命令
command_factory.register_command("whois", whois_command, permission=Permission.NONE, description="WHOIS查询（智能识别类型，包含DNS记录）")
command_factory.register_command("whois_domain", whois_domain_command, permission=Permission.NONE, description="域名WHOIS查询")
command_factory.register_command("whois_ip", whois_ip_command, permission=Permission.NONE, description="IP地址WHOIS查询")
command_factory.register_command("whois_asn", whois_asn_command, permission=Permission.NONE, description="ASN WHOIS查询")
command_factory.register_command("whois_tld", whois_tld_command, permission=Permission.NONE, description="TLD信息查询")
command_factory.register_command("dns", dns_command, permission=Permission.NONE, description="DNS记录查询")
# 已迁移到统一缓存管理命令 /cleancache
# command_factory.register_command("whois_cleancache", whois_clean_cache_command, permission=Permission.ADMIN, description="清理WHOIS和DNS查询缓存")