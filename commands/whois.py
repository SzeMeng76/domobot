#!/usr/bin/env python3
"""
WHOIS查询命令模块
支持域名、IP地址、ASN、TLD等WHOIS信息查询
"""

import logging
import re
import ipaddress
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
                from ipwhois import IPWhois
                self._ipwhois = IPWhois
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
            
            # 使用RDAP查询（推荐方式）
            obj = self._ipwhois(ip)
            data = await asyncio.to_thread(obj.lookup_rdap)
            
            if data:
                result['success'] = True
                result['data'] = self._format_ip_data(data)
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
            obj = self._ipwhois('8.8.8.8')
            data = await asyncio.to_thread(obj.lookup_rdap, asn=asn_number)
            
            if data and 'asn' in data:
                result['success'] = True
                result['data'] = self._format_asn_data(data, asn_number)
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
            'source': 'manual'
        }
        
        # 清理TLD输入
        tld = tld.lower().strip()
        if not tld.startswith('.'):
            tld = '.' + tld
        
        # 由于TLD查询比较复杂，先提供基础信息
        tld_info = self._get_tld_info(tld)
        if tld_info:
            result['success'] = True
            result['data'] = tld_info
        else:
            result['error'] = f"未找到TLD {tld}的信息"
        
        return result
    
    def _extract_whois21_data(self, whois_obj) -> Dict[str, Any]:
        """提取whois21查询结果"""
        formatted = {}
        
        # whois21对象的属性提取
        if hasattr(whois_obj, 'domain_name') and whois_obj.domain_name:
            formatted['域名'] = whois_obj.domain_name
        
        if hasattr(whois_obj, 'registrar') and whois_obj.registrar:
            formatted['注册商'] = whois_obj.registrar
            
        if hasattr(whois_obj, 'creation_date') and whois_obj.creation_date:
            formatted['创建时间'] = str(whois_obj.creation_date)
            
        if hasattr(whois_obj, 'expiration_date') and whois_obj.expiration_date:
            formatted['过期时间'] = str(whois_obj.expiration_date)
            
        if hasattr(whois_obj, 'updated_date') and whois_obj.updated_date:
            formatted['更新时间'] = str(whois_obj.updated_date)
            
        if hasattr(whois_obj, 'status') and whois_obj.status:
            formatted['状态'] = whois_obj.status
            
        if hasattr(whois_obj, 'name_servers') and whois_obj.name_servers:
            formatted['DNS服务器'] = whois_obj.name_servers
            
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
            formatted['域名'] = data.domain_name[0] if isinstance(data.domain_name, list) else data.domain_name
        
        if hasattr(data, 'registrar') and data.registrar:
            formatted['注册商'] = data.registrar[0] if isinstance(data.registrar, list) else data.registrar
        
        if hasattr(data, 'creation_date') and data.creation_date:
            date = data.creation_date[0] if isinstance(data.creation_date, list) else data.creation_date
            formatted['创建时间'] = str(date)
        
        if hasattr(data, 'expiration_date') and data.expiration_date:
            date = data.expiration_date[0] if isinstance(data.expiration_date, list) else data.expiration_date
            formatted['过期时间'] = str(date)
        
        if hasattr(data, 'status') and data.status:
            formatted['状态'] = data.status
        
        if hasattr(data, 'name_servers') and data.name_servers:
            formatted['DNS服务器'] = data.name_servers
        
        return formatted
    
    def _format_ip_data(self, data: Dict) -> Dict[str, Any]:
        """格式化IP查询结果"""
        formatted = {}
        
        if 'network' in data:
            network = data['network']
            if 'name' in network:
                formatted['网络名称'] = network['name']
            if 'cidr' in network:
                formatted['IP段'] = network['cidr']
            if 'start_address' in network:
                formatted['起始地址'] = network['start_address']
            if 'end_address' in network:
                formatted['结束地址'] = network['end_address']
        
        if 'entities' in data:
            for entity in data['entities']:
                if entity.get('roles') and 'registrant' in entity['roles']:
                    if 'vcardArray' in entity:
                        vcard = entity['vcardArray'][1] if len(entity['vcardArray']) > 1 else []
                        for item in vcard:
                            if item[0] == 'fn':
                                formatted['组织'] = item[3]
                            elif item[0] == 'adr':
                                formatted['地址'] = item[3]
        
        if 'asn' in data:
            formatted['ASN'] = f"AS{data['asn']}"
        
        if 'asn_description' in data:
            formatted['ASN描述'] = data['asn_description']
        
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
    
    def _get_tld_info(self, tld: str) -> Optional[Dict[str, Any]]:
        """获取TLD基础信息"""
        # 常见TLD信息字典
        tld_database = {
            '.com': {'类型': 'gTLD', '管理机构': 'Verisign', '创建': '1985', '用途': '商业'},
            '.net': {'类型': 'gTLD', '管理机构': 'Verisign', '创建': '1985', '用途': '网络'},
            '.org': {'类型': 'gTLD', '管理机构': 'PIR', '创建': '1985', '用途': '组织'},
            '.cn': {'类型': 'ccTLD', '管理机构': 'CNNIC', '国家': '中国', '用途': '中国国家域名'},
            '.us': {'类型': 'ccTLD', '管理机构': 'Neustar', '国家': '美国', '用途': '美国国家域名'},
            '.uk': {'类型': 'ccTLD', '管理机构': 'Nominet', '国家': '英国', '用途': '英国国家域名'},
            '.jp': {'类型': 'ccTLD', '管理机构': 'JPRS', '国家': '日本', '用途': '日本国家域名'},
            '.io': {'类型': 'ccTLD', '管理机构': 'ICB', '国家': '英属印度洋领地', '用途': '技术公司'},
            '.ai': {'类型': 'ccTLD', '管理机构': 'Government of Anguilla', '国家': '安圭拉', '用途': 'AI公司'},
            '.dev': {'类型': 'gTLD', '管理机构': 'Google', '创建': '2019', '用途': '开发者'},
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
    """格式化WHOIS查询结果为Markdown"""
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
    
    lines = [f"✅ **{query_type}查询结果**{source_info}\n"]
    lines.append(f"**查询对象**: `{safe_query}`\n")
    
    # 格式化数据
    data = result.get('data', {})
    if data:
        for key, value in data.items():
            safe_key = escape_markdown(str(key), version=2)
            
            if isinstance(value, list):
                # 对列表中的每个元素单独转义，然后用逗号连接
                safe_values = [escape_markdown(str(v), version=2) for v in value]
                safe_value = ', '.join(safe_values)
            else:
                safe_value = escape_markdown(str(value), version=2)
            
            lines.append(f"**{safe_key}**: {safe_value}")
    
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
                cached_result = await cache_manager.get_cache(cache_key, subdirectory="whois")
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

# 注册命令
command_factory.register_command("whois", whois_command, permission=Permission.NONE, description="WHOIS查询（智能识别类型）")
command_factory.register_command("whois_domain", whois_domain_command, permission=Permission.NONE, description="域名WHOIS查询")
command_factory.register_command("whois_ip", whois_ip_command, permission=Permission.NONE, description="IP地址WHOIS查询")
command_factory.register_command("whois_asn", whois_asn_command, permission=Permission.NONE, description="ASN WHOIS查询")
command_factory.register_command("whois_tld", whois_tld_command, permission=Permission.NONE, description="TLD信息查询")