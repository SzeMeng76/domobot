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

class TLDManager:
    """TLD数据管理器 - 直接从GitHub获取数据"""
    
    TLD_URL = "https://raw.githubusercontent.com/SzeMeng76/iana_tld_list/refs/heads/master/data/tld.json"
    
    def __init__(self):
        self._tld_data = None
        
    async def _fetch_tld_data(self) -> Optional[Dict[str, Any]]:
        """从GitHub获取TLD数据"""
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; DomoBot/1.0)"
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
        self._whois21 = None
        self._ipwhois = None
        self._python_whois = None
    
    def _import_libraries(self):
        """延迟导入WHOIS库"""
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
        
        # 尝试使用whois21
        if self._whois21:
            try:
                # 正确的whois21用法：实例化WHOIS类（在异步线程中执行）
                whois_obj = await asyncio.to_thread(self._whois21.WHOIS, domain)
                if whois_obj.success:
                    # whois21返回的是对象，需要获取其属性
                    data = self._extract_whois21_data(whois_obj)
                    if data:
                        result['success'] = True
                        result['data'] = data
                        result['source'] = 'whois21'
                        return result
            except Exception as e:
                logger.debug(f"whois21查询失败: {e}")
        
        # 备选方案：使用python-whois
        if self._python_whois and not result['success']:
            try:
                data = await asyncio.to_thread(self._python_whois.whois, domain)
                if data:
                    result['success'] = True
                    result['data'] = self._format_python_whois_data(data)
                    result['source'] = 'python-whois'
                    return result
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
            
            # 使用RDAP查询（推荐方式）- 正确的API使用方法
            obj = self._ipwhois.IPWhois(ip)
            data = await asyncio.to_thread(obj.lookup_rdap)
            
            # 添加调试信息
            logger.debug(f"IP查询返回数据类型: {type(data)}")
            if isinstance(data, dict):
                logger.debug(f"数据的顶级键: {list(data.keys())}")
            
            if data:
                # 检查data是否为字典类型
                if isinstance(data, dict):
                    try:
                        formatted_data = self._format_ip_data(data)
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
            
            # 使用任意IP查询ASN信息（使用8.8.8.8作为查询入口）
            obj = self._ipwhois.IPWhois('8.8.8.8')
            data = await asyncio.to_thread(obj.lookup_rdap, asn=asn_number)
            
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
        """提取whois21查询结果"""
        formatted = {}
        
        # 根据GitHub文档，主要从whois_data字典中提取数据
        if hasattr(whois_obj, 'whois_data') and whois_obj.whois_data:
            whois_data = whois_obj.whois_data
            
            # 域名信息
            if 'domain_name' in whois_data:
                formatted['域名'] = whois_data['domain_name']
            
            # 注册商信息  
            if 'registrar' in whois_data:
                formatted['注册商'] = whois_data['registrar']
            elif 'REGISTRAR' in whois_data:
                formatted['注册商'] = whois_data['REGISTRAR']
            
            # 注册商详细信息
            if 'REGISTRAR WHOIS SERVER' in whois_data:
                formatted['注册商WHOIS服务器'] = whois_data['REGISTRAR WHOIS SERVER']
            
            if 'REGISTRAR URL' in whois_data:
                formatted['注册商网址'] = whois_data['REGISTRAR URL']
                
            if 'REGISTRAR IANA ID' in whois_data:
                formatted['注册商IANA ID'] = whois_data['REGISTRAR IANA ID']
            
            # 域名ID
            if 'REGISTRY DOMAIN ID' in whois_data:
                formatted['域名ID'] = whois_data['REGISTRY DOMAIN ID']
        
        # 也检查直接属性 - 注意：日期字段是列表类型 List[datetime]
        if hasattr(whois_obj, 'creation_date') and whois_obj.creation_date:
            # whois21的日期字段是列表，取第一个元素
            if isinstance(whois_obj.creation_date, list) and len(whois_obj.creation_date) > 0:
                date_obj = whois_obj.creation_date[0]
                if hasattr(date_obj, 'strftime'):
                    formatted['创建时间'] = date_obj.strftime('%Y-%m-%d %H:%M:%S UTC')
                else:
                    formatted['创建时间'] = str(date_obj)
            else:
                formatted['创建时间'] = str(whois_obj.creation_date)
            
        # 注意：根据文档是 expires_date 不是 expiration_date，且是列表类型
        if hasattr(whois_obj, 'expires_date') and whois_obj.expires_date:
            # whois21的日期字段是列表，取第一个元素
            if isinstance(whois_obj.expires_date, list) and len(whois_obj.expires_date) > 0:
                date_obj = whois_obj.expires_date[0]
                if hasattr(date_obj, 'strftime'):
                    formatted['过期时间'] = date_obj.strftime('%Y-%m-%d %H:%M:%S UTC')
                else:
                    formatted['过期时间'] = str(date_obj)
            else:
                formatted['过期时间'] = str(whois_obj.expires_date)
            
        if hasattr(whois_obj, 'updated_date') and whois_obj.updated_date:
            # whois21的日期字段是列表，取第一个元素
            if isinstance(whois_obj.updated_date, list) and len(whois_obj.updated_date) > 0:
                date_obj = whois_obj.updated_date[0]
                if hasattr(date_obj, 'strftime'):
                    formatted['更新时间'] = date_obj.strftime('%Y-%m-%d %H:%M:%S UTC')
                else:
                    formatted['更新时间'] = str(date_obj)
            else:
                formatted['更新时间'] = str(whois_obj.updated_date)
        
        # 从whois_data中提取其他信息
        if hasattr(whois_obj, 'whois_data') and whois_obj.whois_data:
            whois_data = whois_obj.whois_data
            
            # 状态信息
            if 'status' in whois_data:
                status = whois_data['status']
                if isinstance(status, list):
                    formatted['状态'] = ', '.join(str(s) for s in status)
                else:
                    formatted['状态'] = str(status)
            elif 'DOMAIN STATUS' in whois_data:
                status = whois_data['DOMAIN STATUS']
                if isinstance(status, list):
                    formatted['状态'] = ', '.join(str(s) for s in status)
                else:
                    formatted['状态'] = str(status)
                    
            # DNS服务器信息
            if 'name_servers' in whois_data:
                name_servers = whois_data['name_servers']
                if isinstance(name_servers, list):
                    formatted['DNS服务器'] = ', '.join(str(ns) for ns in name_servers)
                else:
                    formatted['DNS服务器'] = str(name_servers)
            elif 'NAME SERVER' in whois_data:
                name_servers = whois_data['NAME SERVER']
                if isinstance(name_servers, list):
                    formatted['DNS服务器'] = ', '.join(str(ns) for ns in name_servers)
                else:
                    formatted['DNS服务器'] = str(name_servers)
            elif 'NSERVER' in whois_data:
                name_servers = whois_data['NSERVER']
                if isinstance(name_servers, list):
                    formatted['DNS服务器'] = ', '.join(str(ns) for ns in name_servers)
                else:
                    formatted['DNS服务器'] = str(name_servers)
            
            # 联系信息
            if 'EMAIL' in whois_data:
                formatted['邮箱'] = whois_data['EMAIL']
            elif 'E-MAIL' in whois_data:
                formatted['邮箱'] = whois_data['E-MAIL']
                
            if 'PHONE' in whois_data:
                formatted['电话'] = whois_data['PHONE']
                
            if 'FAX' in whois_data:
                formatted['传真'] = whois_data['FAX']
            elif 'FAX-NO' in whois_data:
                formatted['传真'] = whois_data['FAX-NO']
            
            # 注册商联系信息
            if 'REGISTRAR ABUSE CONTACT EMAIL' in whois_data:
                formatted['注册商举报邮箱'] = whois_data['REGISTRAR ABUSE CONTACT EMAIL']
                
            if 'REGISTRAR ABUSE CONTACT PHONE' in whois_data:
                formatted['注册商举报电话'] = whois_data['REGISTRAR ABUSE CONTACT PHONE']
        
        # 如果从whois_data没有获取到数据，尝试直接从对象属性获取
        if not formatted.get('注册商') and hasattr(whois_obj, 'registrar_name') and whois_obj.registrar_name:
            formatted['注册商'] = whois_obj.registrar_name
            
        if not formatted.get('状态') and hasattr(whois_obj, 'status') and whois_obj.status:
            if isinstance(whois_obj.status, list):
                formatted['状态'] = ', '.join(str(s) for s in whois_obj.status)
            else:
                formatted['状态'] = str(whois_obj.status)
                
        if not formatted.get('DNS服务器') and hasattr(whois_obj, 'name_servers') and whois_obj.name_servers:
            if isinstance(whois_obj.name_servers, list):
                formatted['DNS服务器'] = ', '.join(str(ns) for ns in whois_obj.name_servers)
            else:
                formatted['DNS服务器'] = str(whois_obj.name_servers)
        
        # 添加更多直接属性
        if not formatted.get('域名ID') and hasattr(whois_obj, 'registry_domain_id') and whois_obj.registry_domain_id:
            formatted['域名ID'] = whois_obj.registry_domain_id
            
        if not formatted.get('注册商WHOIS服务器') and hasattr(whois_obj, 'registrar_whois_server') and whois_obj.registrar_whois_server:
            formatted['注册商WHOIS服务器'] = whois_obj.registrar_whois_server
            
        if not formatted.get('注册商网址') and hasattr(whois_obj, 'registrar_url') and whois_obj.registrar_url:
            formatted['注册商网址'] = whois_obj.registrar_url
            
        if not formatted.get('注册商IANA ID') and hasattr(whois_obj, 'registrar_iana_id') and whois_obj.registrar_iana_id:
            formatted['注册商IANA ID'] = whois_obj.registrar_iana_id
            
        if not formatted.get('邮箱') and hasattr(whois_obj, 'emails') and whois_obj.emails:
            if isinstance(whois_obj.emails, list):
                formatted['邮箱'] = ', '.join(str(email) for email in whois_obj.emails)
            else:
                formatted['邮箱'] = str(whois_obj.emails)
                
        if not formatted.get('电话') and hasattr(whois_obj, 'phone_numbers') and whois_obj.phone_numbers:
            if isinstance(whois_obj.phone_numbers, list):
                formatted['电话'] = ', '.join(str(phone) for phone in whois_obj.phone_numbers)
            else:
                formatted['电话'] = str(whois_obj.phone_numbers)
                
        if not formatted.get('传真') and hasattr(whois_obj, 'fax_numbers') and whois_obj.fax_numbers:
            if isinstance(whois_obj.fax_numbers, list):
                formatted['传真'] = ', '.join(str(fax) for fax in whois_obj.fax_numbers)
            else:
                formatted['传真'] = str(whois_obj.fax_numbers)
        
        if not formatted.get('注册商举报邮箱') and hasattr(whois_obj, 'registrar_abuse_contact_email') and whois_obj.registrar_abuse_contact_email:
            formatted['注册商举报邮箱'] = whois_obj.registrar_abuse_contact_email
            
        if not formatted.get('注册商举报电话') and hasattr(whois_obj, 'registrar_abuse_contact_phone') and whois_obj.registrar_abuse_contact_phone:
            formatted['注册商举报电话'] = whois_obj.registrar_abuse_contact_phone
            
        return formatted

    def _format_domain_data(self, data: Dict) -> Dict[str, Any]:
        """格式化域名查询结果"""
        formatted = {}
        
        # 基础信息
        if 'domain_name' in data:
            formatted['域名'] = data['domain_name']
        
        # 注册商信息
        if 'registrar' in data:
            formatted['注册商'] = data['registrar']
        
        # 时间信息
        if 'creation_date' in data:
            formatted['创建时间'] = str(data['creation_date'])
        if 'expiration_date' in data:
            formatted['过期时间'] = str(data['expiration_date'])
        if 'updated_date' in data:
            formatted['更新时间'] = str(data['updated_date'])
        
        # 状态信息
        if 'status' in data:
            formatted['状态'] = data['status']
        
        # 名称服务器
        if 'name_servers' in data:
            formatted['DNS服务器'] = data['name_servers']
        
        return formatted
    
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
        """格式化IP查询结果"""
        formatted = {}
        
        # ASN信息（通常在顶级）
        if 'asn' in data:
            formatted['ASN'] = f"AS{data['asn']}"
        
        if 'asn_description' in data:
            formatted['ASN描述'] = data['asn_description']
            
        if 'asn_country_code' in data:
            formatted['ASN国家'] = data['asn_country_code']
            
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
                formatted['网络国家'] = network['country']
            if 'type' in network:
                formatted['网络类型'] = network['type']
        
        # 查找组织信息
        organization = None
        if 'entities' in data and isinstance(data['entities'], list):
            for entity in data['entities']:
                # 确保entity是字典
                if isinstance(entity, dict):
                    # 查找registrant或administrative角色
                    if entity.get('roles') and isinstance(entity['roles'], list):
                        if any(role in entity['roles'] for role in ['registrant', 'administrative', 'technical']):
                            if 'vcardArray' in entity and isinstance(entity['vcardArray'], list) and len(entity['vcardArray']) > 1:
                                vcard = entity['vcardArray'][1]
                                if isinstance(vcard, list):
                                    for item in vcard:
                                        if isinstance(item, list) and len(item) > 3:
                                            if item[0] == 'fn':  # Full name
                                                organization = item[3]
                                                break
                                            elif item[0] == 'org':  # Organization
                                                organization = item[3]
                                                break
                            if organization:
                                break
        
        if organization:
            formatted['组织'] = organization
        
        # 备用：查找objects中的信息
        if 'objects' in data and isinstance(data['objects'], dict):
            for obj_key, obj_data in data['objects'].items():
                if isinstance(obj_data, dict):
                    if 'contact' in obj_data and 'name' in obj_data['contact']:
                        formatted['联系人'] = obj_data['contact']['name']
                    if 'contact' in obj_data and 'organization' in obj_data['contact']:
                        if '组织' not in formatted:
                            formatted['组织'] = obj_data['contact']['organization']
        
        # 如果还是没有足够信息，添加一些调试信息
        if not formatted:
            # 至少显示一些基本信息
            if 'query' in data:
                formatted['查询IP'] = data['query']
            
            # 添加可用的顶级字段作为调试信息
            debug_fields = ['nir', 'raw', 'referral']
            for field in debug_fields:
                if field in data and data[field]:
                    formatted[f'调试_{field}'] = str(data[field])[:100] + "..." if len(str(data[field])) > 100 else str(data[field])
        
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

def format_whois_result(result: Dict[str, Any]) -> str:
    """格式化WHOIS查询结果为美化的Markdown"""
    if not result['success']:
        error_msg = escape_markdown(result.get('error', '查询失败'), version=2)
        return f"❌ **查询失败**\n\n{error_msg}"
    
    query_type_map = {
        'domain': '🌐 域名',
        'ip': '🖥️ IP地址', 
        'asn': '🔢 ASN',
        'tld': '🏷️ 顶级域名'
    }
    
    query_type = query_type_map.get(result['type'], '🔍 查询')
    safe_query = escape_markdown(result['query'], version=2)
    
    # 正确转义source信息
    if result.get('source'):
        safe_source = escape_markdown(result['source'], version=2)
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
            '📋 基本信息': ['域名', '域名ID', '查询IP', '类型'],
            '🏢 注册商信息': ['注册商', '注册商WHOIS服务器', '注册商网址', '注册商IANA ID', '管理机构'],
            '📅 时间信息': ['创建时间', '过期时间', '更新时间', '最后更新'],
            '📊 状态信息': ['状态'],
            '🌐 网络信息': ['DNS服务器', 'ASN', 'ASN描述', 'ASN国家', 'ASN注册机构', '网络名称', 'IP段', '起始地址', '结束地址', '网络国家', '网络类型', '组织', 'WHOIS服务器', '国际化域名'],
            '📞 联系信息': ['邮箱', '电话', '传真', '联系人'],
            '🛡️ 安全信息': ['注册商举报邮箱', '注册商举报电话'],
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
            if group_name in grouped_data and grouped_data[group_name]:
                lines.append(f"**{group_name}**")
                for key, value in grouped_data[group_name]:
                    safe_key = escape_markdown(str(key), version=2)
                    
                    if isinstance(value, list):
                        # 对列表中的每个元素单独转义，然后用逗号连接
                        safe_values = [escape_markdown(str(v), version=2) for v in value]
                        safe_value = ', '.join(safe_values)
                    else:
                        safe_value = escape_markdown(str(value), version=2)
                    
                    # 使用更美观的格式
                    lines.append(f"  • **{safe_key}**: {safe_value}")
                lines.append("")  # 分组间空行
        
        # 显示其他未分类字段
        if '📄 其他信息' in grouped_data and grouped_data['📄 其他信息']:
            lines.append("**📄 其他信息**")
            for key, value in grouped_data['📄 其他信息']:
                safe_key = escape_markdown(str(key), version=2)
                
                if isinstance(value, list):
                    safe_values = [escape_markdown(str(v), version=2) for v in value]
                    safe_value = ', '.join(safe_values)
                else:
                    safe_value = escape_markdown(str(value), version=2)
                
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
                "• 🌐 域名: `example\\.com`\n"
                "• 🖥️ IP地址: `8\\.8\\.8\\.8`\n"
                "• 🔢 ASN: `AS15169` 或 `15169`\n"
                "• 🏷️ TLD: `\\.com` 或 `com`\n\n"
                "**专用命令:**\n"
                "• `/whois_domain <域名>`\n"
                "• `/whois_ip <IP地址>`\n"
                "• `/whois_asn <ASN>`\n"
                "• `/whois_tld <TLD>`\n\n"
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
        response = format_whois_result(result)
        
        await send_message_with_auto_delete(
            context=context,
            chat_id=update.effective_chat.id,
            text=response,
            parse_mode=ParseMode.MARKDOWN_V2
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

async def whois_clean_cache_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """清理WHOIS查询缓存"""
    if not update.message or not update.effective_chat:
        return
    
    try:
        if cache_manager:
            await cache_manager.clear_cache(subdirectory="whois")
            success_message = "✅ WHOIS查询缓存已清理完成。\n\n包括：域名、IP地址、ASN和TLD查询结果。"
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
command_factory.register_command("whois", whois_command, permission=Permission.NONE, description="WHOIS查询（智能识别类型）")
command_factory.register_command("whois_domain", whois_domain_command, permission=Permission.NONE, description="域名WHOIS查询")
command_factory.register_command("whois_ip", whois_ip_command, permission=Permission.NONE, description="IP地址WHOIS查询")
command_factory.register_command("whois_asn", whois_asn_command, permission=Permission.NONE, description="ASN WHOIS查询")
command_factory.register_command("whois_tld", whois_tld_command, permission=Permission.NONE, description="TLD信息查询")
command_factory.register_command("whois_cleancache", whois_clean_cache_command, permission=Permission.ADMIN, description="清理WHOIS查询缓存")