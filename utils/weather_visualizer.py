"""
天气数据可视化工具
使用 matplotlib 生成温度趋势图和降水概率图
"""

import io
import logging
from typing import Optional, List, Dict
from datetime import datetime

try:
    import matplotlib
    matplotlib.use('Agg')  # 使用非GUI后端
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.font_manager import FontProperties
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    logging.warning("matplotlib 未安装，图表功能将不可用")

logger = logging.getLogger(__name__)

# 字体路径优先级（Docker 环境优先）
FONT_PATHS = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",  # Docker Noto CJK
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    "C:\\Windows\\Fonts\\msyh.ttc",  # Windows 微软雅黑
    "/System/Library/Fonts/PingFang.ttc",  # macOS 苹方
]


class WeatherVisualizer:
    """天气数据可视化工具"""

    def __init__(self):
        self.font_prop = None
        if MATPLOTLIB_AVAILABLE:
            self._setup_font()

    def _setup_font(self):
        """设置中文字体"""
        for font_path in FONT_PATHS:
            try:
                self.font_prop = FontProperties(fname=font_path)
                logger.info(f"使用字体: {font_path}")
                break
            except:
                continue

        if not self.font_prop:
            logger.warning("未找到中文字体，图表中文可能显示为方块")

    def draw_hourly_temp_chart(self, hourly_data: List[Dict], location_name: str) -> Optional[bytes]:
        """
        绘制逐小时温度趋势图

        Args:
            hourly_data: 逐小时天气数据列表
            location_name: 地点名称

        Returns:
            PNG图片的字节数据
        """
        if not MATPLOTLIB_AVAILABLE:
            logger.error("matplotlib 未安装")
            return None

        if not hourly_data or len(hourly_data) < 2:
            logger.warning("数据不足，无法绘制图表")
            return None

        try:
            # 提取数据
            times = []
            temps = []
            for item in hourly_data[:24]:  # 只取24小时
                try:
                    time_str = item.get("fxTime", "")
                    temp_str = item.get("temp", "0")

                    # 解析时间
                    time_obj = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
                    times.append(time_obj)
                    temps.append(float(temp_str))
                except Exception as e:
                    logger.warning(f"解析数据失败: {e}")
                    continue

            if len(times) < 2:
                return None

            # 创建图表
            fig, ax = plt.subplots(figsize=(12, 6))

            # 绘制温度曲线
            ax.plot(times, temps, marker='o', linewidth=2, markersize=6,
                   color='#FF6B6B', label='温度')

            # 填充区域
            ax.fill_between(times, temps, alpha=0.3, color='#FF6B6B')

            # 设置标题和标签
            title = f"{location_name} 未来24小时温度趋势"
            if self.font_prop:
                ax.set_title(title, fontproperties=self.font_prop, fontsize=16, pad=20)
                ax.set_xlabel("时间", fontproperties=self.font_prop, fontsize=12)
                ax.set_ylabel("温度 (°C)", fontproperties=self.font_prop, fontsize=12)
            else:
                ax.set_title(title, fontsize=16, pad=20)
                ax.set_xlabel("Time", fontsize=12)
                ax.set_ylabel("Temperature (C)", fontsize=12)

            # 格式化x轴
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            ax.xaxis.set_major_locator(mdates.HourLocator(interval=3))
            plt.xticks(rotation=45)

            # 添加网格
            ax.grid(True, alpha=0.3, linestyle='--')

            # 在每个点上标注温度值
            for i, (time, temp) in enumerate(zip(times, temps)):
                if i % 3 == 0:  # 每3个小时标注一次
                    ax.annotate(f'{temp:.1f}°',
                              xy=(time, temp),
                              xytext=(0, 10),
                              textcoords='offset points',
                              ha='center',
                              fontsize=9)

            # 调整布局
            plt.tight_layout()

            # 保存到字节流
            buf = io.BytesIO()
            plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
            buf.seek(0)
            plt.close(fig)

            return buf.getvalue()

        except Exception as e:
            logger.error(f"绘制温度图表失败: {e}", exc_info=True)
            return None

    def draw_daily_temp_chart(self, daily_data: List[Dict], location_name: str) -> Optional[bytes]:
        """
        绘制逐日温度趋势图

        Args:
            daily_data: 逐日天气数据列表
            location_name: 地点名称

        Returns:
            PNG图片的字节数据
        """
        if not MATPLOTLIB_AVAILABLE:
            return None

        if not daily_data or len(daily_data) < 2:
            return None

        try:
            # 提取数据
            dates = []
            temp_max = []
            temp_min = []

            for item in daily_data[:7]:  # 只取7天
                try:
                    date_str = item.get("fxDate", "")
                    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                    dates.append(date_obj)
                    temp_max.append(float(item.get("tempMax", 0)))
                    temp_min.append(float(item.get("tempMin", 0)))
                except Exception as e:
                    logger.warning(f"解析数据失败: {e}")
                    continue

            if len(dates) < 2:
                return None

            # 创建图表
            fig, ax = plt.subplots(figsize=(12, 6))

            # 绘制最高温和最低温曲线
            ax.plot(dates, temp_max, marker='o', linewidth=2, markersize=8,
                   color='#FF6B6B', label='最高温')
            ax.plot(dates, temp_min, marker='o', linewidth=2, markersize=8,
                   color='#4ECDC4', label='最低温')

            # 填充区域
            ax.fill_between(dates, temp_max, temp_min, alpha=0.2, color='#95E1D3')

            # 设置标题和标签
            title = f"{location_name} 未来7天温度趋势"
            if self.font_prop:
                ax.set_title(title, fontproperties=self.font_prop, fontsize=16, pad=20)
                ax.set_xlabel("日期", fontproperties=self.font_prop, fontsize=12)
                ax.set_ylabel("温度 (°C)", fontproperties=self.font_prop, fontsize=12)
                ax.legend(prop=self.font_prop, loc='upper right')
            else:
                ax.set_title(title, fontsize=16, pad=20)
                ax.set_xlabel("Date", fontsize=12)
                ax.set_ylabel("Temperature (C)", fontsize=12)
                ax.legend(loc='upper right')

            # 格式化x轴
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
            plt.xticks(rotation=45)

            # 添加网格
            ax.grid(True, alpha=0.3, linestyle='--')

            # 标注温度值
            for date, t_max, t_min in zip(dates, temp_max, temp_min):
                ax.annotate(f'{t_max:.0f}°', xy=(date, t_max), xytext=(0, 10),
                          textcoords='offset points', ha='center', fontsize=9, color='#FF6B6B')
                ax.annotate(f'{t_min:.0f}°', xy=(date, t_min), xytext=(0, -15),
                          textcoords='offset points', ha='center', fontsize=9, color='#4ECDC4')

            plt.tight_layout()

            # 保存到字节流
            buf = io.BytesIO()
            plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
            buf.seek(0)
            plt.close(fig)

            return buf.getvalue()

        except Exception as e:
            logger.error(f"绘制日温度图表失败: {e}", exc_info=True)
            return None

    def draw_precipitation_chart(self, hourly_data: List[Dict], location_name: str) -> Optional[bytes]:
        """
        绘制降水概率图

        Args:
            hourly_data: 逐小时天气数据列表
            location_name: 地点名称

        Returns:
            PNG图片的字节数据
        """
        if not MATPLOTLIB_AVAILABLE:
            return None

        if not hourly_data or len(hourly_data) < 2:
            return None

        try:
            # 提取数据
            times = []
            pops = []  # 降水概率
            precips = []  # 降水量

            for item in hourly_data[:24]:
                try:
                    time_str = item.get("fxTime", "")
                    time_obj = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
                    times.append(time_obj)
                    pops.append(float(item.get("pop", 0)))
                    precips.append(float(item.get("precip", 0)))
                except Exception as e:
                    continue

            if len(times) < 2:
                return None

            # 创建图表
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

            # 上图：降水概率
            ax1.bar(times, pops, width=0.03, color='#4ECDC4', alpha=0.7)
            ax1.plot(times, pops, marker='o', linewidth=2, markersize=4, color='#2C7A7B')

            title1 = f"{location_name} 未来24小时降水概率"
            if self.font_prop:
                ax1.set_title(title1, fontproperties=self.font_prop, fontsize=14, pad=15)
                ax1.set_ylabel("降水概率 (%)", fontproperties=self.font_prop, fontsize=11)
            else:
                ax1.set_title(title1, fontsize=14, pad=15)
                ax1.set_ylabel("Precipitation Probability (%)", fontsize=11)

            ax1.grid(True, alpha=0.3, linestyle='--')
            ax1.set_ylim(0, 100)

            # 下图：降水量
            ax2.bar(times, precips, width=0.03, color='#5DADE2', alpha=0.7)

            if self.font_prop:
                ax2.set_ylabel("降水量 (mm)", fontproperties=self.font_prop, fontsize=11)
                ax2.set_xlabel("时间", fontproperties=self.font_prop, fontsize=11)
            else:
                ax2.set_ylabel("Precipitation (mm)", fontsize=11)
                ax2.set_xlabel("Time", fontsize=11)

            ax2.grid(True, alpha=0.3, linestyle='--')

            # 格式化x轴
            ax2.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            ax2.xaxis.set_major_locator(mdates.HourLocator(interval=3))
            plt.xticks(rotation=45)

            plt.tight_layout()

            # 保存到字节流
            buf = io.BytesIO()
            plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
            buf.seek(0)
            plt.close(fig)

            return buf.getvalue()

        except Exception as e:
            logger.error(f"绘制降水图表失败: {e}", exc_info=True)
            return None
