"""
已知数据点加载器 - 用于从JSON文件加载Telegram用户ID映射数据
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Optional


class KnownPointsLoader:
    """已知数据点加载器类"""
    
    def __init__(self, data_file: str = "data/known_points.json"):
        """
        初始化数据点加载器
        
        Args:
            data_file: JSON数据文件路径，相对于项目根目录
        """
        # 获取项目根目录
        current_dir = Path(__file__).parent
        self.data_file = current_dir / data_file
        self._cache = None
        self._last_modified = None
        
    def _should_reload(self) -> bool:
        """检查是否需要重新加载数据"""
        if not self.data_file.exists():
            return False
            
        if self._cache is None:
            return True
            
        current_modified = self.data_file.stat().st_mtime
        return current_modified != self._last_modified
        
    def _load_from_file(self) -> Optional[dict]:
        """从文件加载数据"""
        try:
            if not self.data_file.exists():
                print(f"⚠️ 数据文件不存在: {self.data_file}")
                return None
                
            with open(self.data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            self._last_modified = self.data_file.stat().st_mtime
            return data
            
        except json.JSONDecodeError as e:
            print(f"❌ JSON格式错误: {e}")
            return None
        except Exception as e:
            print(f"❌ 读取数据文件失败: {e}")
            return None
            
    def get_known_points(self) -> List[Tuple[int, datetime]]:
        """
        获取已知数据点列表
        
        Returns:
            包含 (user_id, datetime) 元组的列表，按user_id排序
        """
        # 检查是否需要重新加载
        if self._should_reload():
            data = self._load_from_file()
            if data:
                self._cache = data
            else:
                # 如果加载失败，返回空列表或使用后备数据
                return self._get_fallback_points()
                
        if not self._cache:
            return self._get_fallback_points()
            
        try:
            points = []
            for point in self._cache.get("known_points", []):
                user_id = int(point["user_id"])
                date_str = point["date"]
                date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                points.append((user_id, date_obj))
                
            # 按user_id排序 - 这对插值算法至关重要！
            points.sort(key=lambda x: x[0])
            return points
            
        except (ValueError, KeyError, TypeError) as e:
            print(f"❌ 数据格式错误: {e}")
            return self._get_fallback_points()
            
    def _get_fallback_points(self) -> List[Tuple[int, datetime]]:
        """
        获取后备数据点（当JSON文件不可用时使用）
        
        Returns:
            基本的后备数据点列表
        """
        return [
            (1, datetime(2013, 8, 14)),           # Telegram创始人
            (777000, datetime(2015, 7, 1)),       # 早期bot时期
            (9000000000, datetime(2024, 12, 1)),  # 预估高ID
        ]
        
    def get_stats(self) -> dict:
        """
        获取数据统计信息
        
        Returns:
            包含统计信息的字典
        """
        if self._should_reload():
            data = self._load_from_file()
            if data:
                self._cache = data
                
        if not self._cache:
            return {
                "total_points": 0,
                "verified_points": 0,
                "data_source": "fallback",
                "last_updated": "unknown"
            }
            
        points = self._cache.get("known_points", [])
        verified_count = sum(1 for p in points if "✅" in p.get("note", ""))
        
        return {
            "total_points": len(points),
            "verified_points": verified_count,
            "estimated_points": len(points) - verified_count,
            "data_source": "json_file",
            "last_updated": self._cache.get("last_updated", "unknown"),
            "version": self._cache.get("version", "unknown")
        }
        
    def reload(self) -> bool:
        """
        强制重新加载数据
        
        Returns:
            是否成功重新加载
        """
        self._cache = None
        self._last_modified = None
        data = self._load_from_file()
        if data:
            self._cache = data
            return True
        return False


# 全局实例
_loader_instance = None


def get_known_points_loader(data_file: str = "data/known_points.json") -> KnownPointsLoader:
    """
    获取已知数据点加载器实例（单例模式）
    
    Args:
        data_file: JSON数据文件路径
        
    Returns:
        KnownPointsLoader实例
    """
    global _loader_instance
    if _loader_instance is None:
        _loader_instance = KnownPointsLoader(data_file)
    return _loader_instance


def load_known_points() -> List[Tuple[int, datetime]]:
    """
    便捷函数：加载已知数据点
    
    Returns:
        包含 (user_id, datetime) 元组的列表
    """
    loader = get_known_points_loader()
    return loader.get_known_points()