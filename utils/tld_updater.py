#!/usr/bin/env python3
"""
TLD数据更新工具
从IANA获取最新的TLD信息
"""

import json
import logging
import asyncio
import aiohttp
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

class TLDUpdater:
    """TLD数据更新器"""
    
    def __init__(self, data_dir="data/tld"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.tld_file = self.data_dir / "tld.json"
        self.last_update_file = self.data_dir / "last_update.txt"
        
        # IANA数据源
        self.iana_tld_url = "https://raw.githubusercontent.com/jophy/iana_tld_list/master/data/tld.json"
        self.fallback_url = "https://data.iana.org/TLD/tlds-alpha-by-domain.txt"
    
    async def should_update(self, force: bool = False) -> bool:
        """检查是否需要更新"""
        if force:
            return True
            
        if not self.tld_file.exists():
            return True
            
        if not self.last_update_file.exists():
            return True
            
        try:
            with open(self.last_update_file, 'r') as f:
                last_update_str = f.read().strip()
                last_update = datetime.fromisoformat(last_update_str)
                
            # 7天更新一次
            if datetime.now() - last_update > timedelta(days=7):
                return True
                
        except Exception as e:
            logger.debug(f"检查更新时间失败: {e}")
            return True
            
        return False
    
    async def download_tld_data(self) -> Optional[List[Dict[str, Any]]]:
        """从GitHub下载TLD数据"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.iana_tld_url) as response:
                    if response.status == 200:
                        data = await response.json()
                        logger.info(f"成功下载 {len(data)} 个TLD记录")
                        return data
                    else:
                        logger.warning(f"下载失败，状态码: {response.status}")
        except Exception as e:
            logger.error(f"下载TLD数据失败: {e}")
            
        return None
    
    async def download_fallback_data(self) -> Optional[List[str]]:
        """下载IANA官方TLD列表作为备选"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.fallback_url) as response:
                    if response.status == 200:
                        text = await response.text()
                        # 解析文本格式的TLD列表
                        tlds = []
                        for line in text.strip().split('\n'):
                            line = line.strip()
                            if line and not line.startswith('#'):
                                tlds.append(line.lower())
                        logger.info(f"成功下载 {len(tlds)} 个TLD名称")
                        return tlds
        except Exception as e:
            logger.error(f"下载备选TLD数据失败: {e}")
            
        return None
    
    def create_minimal_tld_data(self, tlds: List[str]) -> List[Dict[str, Any]]:
        """从TLD名称创建最小化数据结构"""
        data = []
        for tld in tlds:
            # 基本的TLD类型判断
            tld_type = 'ccTLD' if len(tld) == 2 else 'gTLD'
            
            data.append({
                'tld': tld,
                'dm': f'.{tld}',
                'isIDN': False,  # 需要更复杂的判断
                'tldType': tld_type,
                'nic': '',
                'whois': '',
                'lastUpdate': datetime.now().strftime('%Y-%m-%d'),
                'registration': ''
            })
        
        return data
    
    async def update_data(self, force: bool = False) -> bool:
        """更新TLD数据"""
        if not await self.should_update(force):
            logger.debug("TLD数据不需要更新")
            return True
            
        logger.info("开始更新TLD数据...")
        
        # 优先尝试下载完整数据
        data = await self.download_tld_data()
        
        # 如果失败，尝试备选数据
        if not data:
            logger.warning("使用备选数据源...")
            tlds = await self.download_fallback_data()
            if tlds:
                data = self.create_minimal_tld_data(tlds)
        
        if not data:
            logger.error("所有数据源都失败了")
            return False
            
        try:
            # 保存数据
            with open(self.tld_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                
            # 记录更新时间
            with open(self.last_update_file, 'w') as f:
                f.write(datetime.now().isoformat())
                
            logger.info(f"TLD数据更新成功，共 {len(data)} 条记录")
            return True
            
        except Exception as e:
            logger.error(f"保存TLD数据失败: {e}")
            return False
    
    def get_data_info(self) -> Dict[str, Any]:
        """获取数据信息"""
        info = {
            'exists': self.tld_file.exists(),
            'count': 0,
            'last_update': None,
            'size': 0
        }
        
        if info['exists']:
            try:
                with open(self.tld_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    info['count'] = len(data)
                    
                info['size'] = self.tld_file.stat().st_size
                
                if self.last_update_file.exists():
                    with open(self.last_update_file, 'r') as f:
                        info['last_update'] = f.read().strip()
                        
            except Exception as e:
                logger.error(f"获取数据信息失败: {e}")
                
        return info

async def main():
    """命令行测试"""
    logging.basicConfig(level=logging.INFO)
    
    updater = TLDUpdater()
    info = updater.get_data_info()
    
    print(f"TLD数据信息:")
    print(f"  文件存在: {info['exists']}")
    print(f"  记录数量: {info['count']}")
    print(f"  文件大小: {info['size']} 字节")
    print(f"  最后更新: {info['last_update']}")
    
    if await updater.should_update():
        print("\n开始更新...")
        success = await updater.update_data(force=True)
        print(f"更新结果: {'成功' if success else '失败'}")
    else:
        print("\n数据已是最新")

if __name__ == "__main__":
    asyncio.run(main())