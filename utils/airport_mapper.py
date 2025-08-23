"""
机场映射工具
参考 timezone_mapper.py 架构，提供智能机场代码解析和城市到机场的映射
主要用于优化用户输入体验，将自然语言输入转换为IATA机场代码
"""

import re
from typing import Dict, List, Tuple, Optional
from .country_data import SUPPORTED_COUNTRIES, get_country_flag

# 主要国际机场城市映射 - 重点支持常用航线
MAJOR_CITIES_AIRPORTS = {
    # 中国大陆主要城市
    "北京": {
        "primary": "PEK", 
        "secondary": ["PKX"], 
        "airports": [
            {"code": "PEK", "name": "北京首都国际机场", "name_en": "Beijing Capital International Airport", "note": "T1/T2/T3航站楼"},
            {"code": "PKX", "name": "北京大兴国际机场", "name_en": "Beijing Daxing International Airport", "note": "新机场,距市区较远"}
        ]
    },
    "上海": {
        "primary": "PVG", 
        "secondary": ["SHA"], 
        "airports": [
            {"code": "PVG", "name": "上海浦东国际机场", "name_en": "Shanghai Pudong International Airport", "note": "国际航班主要机场"},
            {"code": "SHA", "name": "上海虹桥国际机场", "name_en": "Shanghai Hongqiao International Airport", "note": "国内及少量国际航班"}
        ]
    },
    "广州": {
        "primary": "CAN", 
        "secondary": [], 
        "airports": [
            {"code": "CAN", "name": "广州白云国际机场", "name_en": "Guangzhou Baiyun International Airport", "note": "华南地区枢纽"}
        ]
    },
    "深圳": {
        "primary": "SZX", 
        "secondary": [], 
        "airports": [
            {"code": "SZX", "name": "深圳宝安国际机场", "name_en": "Shenzhen Bao'an International Airport", "note": "毗邻香港"}
        ]
    },
    "成都": {
        "primary": "CTU", 
        "secondary": ["TFU"], 
        "airports": [
            {"code": "CTU", "name": "成都双流国际机场", "name_en": "Chengdu Shuangliu International Airport", "note": "西南地区枢纽"},
            {"code": "TFU", "name": "成都天府国际机场", "name_en": "Chengdu Tianfu International Airport", "note": "新建机场"}
        ]
    },
    "重庆": {
        "primary": "CKG", 
        "secondary": [], 
        "airports": [
            {"code": "CKG", "name": "重庆江北国际机场", "name_en": "Chongqing Jiangbei International Airport", "note": "西南重要枢纽"}
        ]
    },
    "杭州": {
        "primary": "HGH", 
        "secondary": [], 
        "airports": [
            {"code": "HGH", "name": "杭州萧山国际机场", "name_en": "Hangzhou Xiaoshan International Airport", "note": "长三角重要机场"}
        ]
    },
    "南京": {
        "primary": "NKG", 
        "secondary": [], 
        "airports": [
            {"code": "NKG", "name": "南京禄口国际机场", "name_en": "Nanjing Lukou International Airport", "note": "江苏省主要机场"}
        ]
    },
    "西安": {
        "primary": "XIY", 
        "secondary": [], 
        "airports": [
            {"code": "XIY", "name": "西安咸阳国际机场", "name_en": "Xi'an Xianyang International Airport", "note": "西北地区枢纽"}
        ]
    },
    "厦门": {
        "primary": "XMN", 
        "secondary": [], 
        "airports": [
            {"code": "XMN", "name": "厦门高崎国际机场", "name_en": "Xiamen Gaoqi International Airport", "note": "对台重要门户"}
        ]
    },
    "昆明": {
        "primary": "KMG", 
        "secondary": [], 
        "airports": [
            {"code": "KMG", "name": "昆明长水国际机场", "name_en": "Kunming Changshui International Airport", "note": "面向南亚东南亚枢纽"}
        ]
    },
    "天津": {
        "primary": "TSN", 
        "secondary": [], 
        "airports": [
            {"code": "TSN", "name": "天津滨海国际机场", "name_en": "Tianjin Binhai International Airport", "note": "京津冀重要机场"}
        ]
    },
    "武汉": {
        "primary": "WUH", 
        "secondary": [], 
        "airports": [
            {"code": "WUH", "name": "武汉天河国际机场", "name_en": "Wuhan Tianhe International Airport", "note": "华中地区枢纽"}
        ]
    },
    "郑州": {
        "primary": "CGO", 
        "secondary": [], 
        "airports": [
            {"code": "CGO", "name": "郑州新郑国际机场", "name_en": "Zhengzhou Xinzheng International Airport", "note": "中原地区重要机场"}
        ]
    },
    "沈阳": {
        "primary": "SHE", 
        "secondary": [], 
        "airports": [
            {"code": "SHE", "name": "沈阳桃仙国际机场", "name_en": "Shenyang Taoxian International Airport", "note": "东北地区重要机场"}
        ]
    },
    "大连": {
        "primary": "DLC", 
        "secondary": [], 
        "airports": [
            {"code": "DLC", "name": "大连周水子国际机场", "name_en": "Dalian Zhoushuizi International Airport", "note": "东北沿海重要机场"}
        ]
    },
    "青岛": {
        "primary": "TAO", 
        "secondary": [], 
        "airports": [
            {"code": "TAO", "name": "青岛胶东国际机场", "name_en": "Qingdao Jiaodong International Airport", "note": "山东省重要机场"}
        ]
    },
    "长沙": {
        "primary": "CSX", 
        "secondary": [], 
        "airports": [
            {"code": "CSX", "name": "长沙黄花国际机场", "name_en": "Changsha Huanghua International Airport", "note": "湖南省重要机场"}
        ]
    },
    "南昌": {
        "primary": "KHN", 
        "secondary": [], 
        "airports": [
            {"code": "KHN", "name": "南昌昌北国际机场", "name_en": "Nanchang Changbei International Airport", "note": "江西省重要机场"}
        ]
    },
    "合肥": {
        "primary": "HFE", 
        "secondary": [], 
        "airports": [
            {"code": "HFE", "name": "合肥新桥国际机场", "name_en": "Hefei Xinqiao International Airport", "note": "安徽省重要机场"}
        ]
    },
    
    # 港澳台
    "香港": {
        "primary": "HKG", 
        "secondary": [], 
        "airports": [
            {"code": "HKG", "name": "香港国际机场", "name_en": "Hong Kong International Airport", "note": "亚太重要枢纽"}
        ]
    },
    "澳门": {
        "primary": "MFM", 
        "secondary": [], 
        "airports": [
            {"code": "MFM", "name": "澳门国际机场", "name_en": "Macau International Airport", "note": "珠三角门户"}
        ]
    },
    "台北": {
        "primary": "TPE", 
        "secondary": ["TSA"], 
        "airports": [
            {"code": "TPE", "name": "台湾桃园国际机场", "name_en": "Taiwan Taoyuan International Airport", "note": "台湾主要国际机场"},
            {"code": "TSA", "name": "台北松山机场", "name_en": "Taipei Songshan Airport", "note": "市区机场,少量国际航班"}
        ]
    },
    # 补充台湾其他城市机场 - 基于Wikipedia完整数据
    "高雄": {
        "primary": "KHH", 
        "secondary": [], 
        "airports": [
            {"code": "KHH", "name": "高雄国际机场", "name_en": "Kaohsiung International Airport", "note": "台湾第二大国际机场"}
        ]
    },
    "台中": {
        "primary": "RMQ", 
        "secondary": [], 
        "airports": [
            {"code": "RMQ", "name": "台中国际机场", "name_en": "Taichung International Airport", "note": "台湾中部主要机场"}
        ]
    },
    "台南": {
        "primary": "TNN", 
        "secondary": [], 
        "airports": [
            {"code": "TNN", "name": "台南机场", "name_en": "Tainan Airport", "note": "台湾南部机场"}
        ]
    },
    "花莲": {
        "primary": "HUN", 
        "secondary": [], 
        "airports": [
            {"code": "HUN", "name": "花莲机场", "name_en": "Hualien Airport", "note": "台湾东部机场"}
        ]
    },
    
    # 日本主要城市
    "东京": {
        "primary": "NRT", 
        "secondary": ["HND"], 
        "airports": [
            {"code": "NRT", "name": "成田国际机场", "name_en": "Narita International Airport", "note": "主要国际航班"},
            {"code": "HND", "name": "羽田机场", "name_en": "Haneda Airport", "note": "国内及亚洲航班,距市区近"}
        ]
    },
    "大阪": {
        "primary": "KIX", 
        "secondary": ["ITM"], 
        "airports": [
            {"code": "KIX", "name": "关西国际机场", "name_en": "Kansai International Airport", "note": "国际航班主要机场"},
            {"code": "ITM", "name": "大阪伊丹机场", "name_en": "Osaka International Airport", "note": "主要服务国内航班"}
        ]
    },
    "名古屋": {
        "primary": "NGO", 
        "secondary": [], 
        "airports": [
            {"code": "NGO", "name": "中部国际机场", "name_en": "Chubu Centrair International Airport", "note": "中部地区主要国际机场"}
        ]
    },
    
    # 韩国主要城市  
    "首尔": {
        "primary": "ICN", 
        "secondary": ["GMP"], 
        "airports": [
            {"code": "ICN", "name": "仁川国际机场", "name_en": "Incheon International Airport", "note": "韩国主要国际机场"},
            {"code": "GMP", "name": "金浦机场", "name_en": "Gimpo International Airport", "note": "国内及东北亚航班"}
        ]
    },
    "釜山": {
        "primary": "PUS", 
        "secondary": [], 
        "airports": [
            {"code": "PUS", "name": "釜山金海国际机场", "name_en": "Busan Gimhae International Airport", "note": "韩国第二大机场"}
        ]
    },
    "济州": {
        "primary": "CJU", 
        "secondary": [], 
        "airports": [
            {"code": "CJU", "name": "济州国际机场", "name_en": "Jeju International Airport", "note": "济州岛主要机场"}
        ]
    },
    "大邱": {
        "primary": "TAE", 
        "secondary": [], 
        "airports": [
            {"code": "TAE", "name": "大邱国际机场", "name_en": "Daegu International Airport", "note": "韩国东南部机场"}
        ]
    },
    "光州": {
        "primary": "KWJ", 
        "secondary": [], 
        "airports": [
            {"code": "KWJ", "name": "光州机场", "name_en": "Gwangju Airport", "note": "韩国西南部机场"}
        ]
    },
    "清州": {
        "primary": "CJJ", 
        "secondary": [], 
        "airports": [
            {"code": "CJJ", "name": "清州国际机场", "name_en": "Cheongju International Airport", "note": "韩国中部机场"}
        ]
    },
    "务安": {
        "primary": "MWX", 
        "secondary": [], 
        "airports": [
            {"code": "MWX", "name": "务安国际机场", "name_en": "Muan International Airport", "note": "全罗南道国际机场"}
        ]
    },
    "襄阳": {
        "primary": "YNY", 
        "secondary": [], 
        "airports": [
            {"code": "YNY", "name": "襄阳国际机场", "name_en": "Yangyang International Airport", "note": "江原道东海岸机场"}
        ]
    },
    
    # 补充日本其他重要城市
    "福冈": {
        "primary": "FUK", 
        "secondary": [], 
        "airports": [
            {"code": "FUK", "name": "福冈机场", "name_en": "Fukuoka Airport", "note": "九州地区主要机场"}
        ]
    },
    "札幌": {
        "primary": "CTS", 
        "secondary": [], 
        "airports": [
            {"code": "CTS", "name": "新千岁机场", "name_en": "New Chitose Airport", "note": "北海道主要机场"}
        ]
    },
    "仙台": {
        "primary": "SDJ", 
        "secondary": [], 
        "airports": [
            {"code": "SDJ", "name": "仙台机场", "name_en": "Sendai Airport", "note": "东北地区主要机场"}
        ]
    },
    "广岛": {
        "primary": "HIJ", 
        "secondary": [], 
        "airports": [
            {"code": "HIJ", "name": "广岛机场", "name_en": "Hiroshima Airport", "note": "中国地区主要机场"}
        ]
    },
    "冲绳": {
        "primary": "OKA", 
        "secondary": [], 
        "airports": [
            {"code": "OKA", "name": "那霸机场", "name_en": "Naha Airport", "note": "冲绳主要机场"}
        ]
    },
    "熊本": {
        "primary": "KMJ", 
        "secondary": [], 
        "airports": [
            {"code": "KMJ", "name": "熊本机场", "name_en": "Kumamoto Airport", "note": "九州地区机场"}
        ]
    },
    "鹿儿岛": {
        "primary": "KOJ", 
        "secondary": [], 
        "airports": [
            {"code": "KOJ", "name": "鹿儿岛机场", "name_en": "Kagoshima Airport", "note": "九州南部机场"}
        ]
    },
    "高松": {
        "primary": "TAK", 
        "secondary": [], 
        "airports": [
            {"code": "TAK", "name": "高松机场", "name_en": "Takamatsu Airport", "note": "四国地区主要机场"}
        ]
    },
    "松山": {
        "primary": "MYJ", 
        "secondary": [], 
        "airports": [
            {"code": "MYJ", "name": "松山机场", "name_en": "Matsuyama Airport", "note": "四国地区机场"}
        ]
    },
    # 补充更多日本城市机场 - 基于Wikipedia完整数据
    "秋田": {
        "primary": "AXT", 
        "secondary": [], 
        "airports": [
            {"code": "AXT", "name": "秋田机场", "name_en": "Akita Airport", "note": "东北地区机场"}
        ]
    },
    "青森": {
        "primary": "AOJ", 
        "secondary": [], 
        "airports": [
            {"code": "AOJ", "name": "青森机场", "name_en": "Aomori Airport", "note": "本州北端机场"}
        ]
    },
    "函馆": {
        "primary": "HKD", 
        "secondary": [], 
        "airports": [
            {"code": "HKD", "name": "函馆机场", "name_en": "Hakodate Airport", "note": "北海道南部机场"}
        ]
    },
    "北九州": {
        "primary": "KKJ", 
        "secondary": [], 
        "airports": [
            {"code": "KKJ", "name": "北九州机场", "name_en": "Kitakyushu Airport", "note": "九州北部机场"}
        ]
    },
    "小松": {
        "primary": "KMQ", 
        "secondary": [], 
        "airports": [
            {"code": "KMQ", "name": "小松机场", "name_en": "Komatsu Airport", "note": "石川县主要机场"}
        ]
    },
    "长崎": {
        "primary": "NGS", 
        "secondary": [], 
        "airports": [
            {"code": "NGS", "name": "长崎机场", "name_en": "Nagasaki Airport", "note": "九州西部机场"}
        ]
    },
    "新潟": {
        "primary": "KIJ", 
        "secondary": [], 
        "airports": [
            {"code": "KIJ", "name": "新潟机场", "name_en": "Niigata Airport", "note": "本州日本海侧机场"}
        ]
    },
    "大分": {
        "primary": "OIT", 
        "secondary": [], 
        "airports": [
            {"code": "OIT", "name": "大分机场", "name_en": "Oita Airport", "note": "九州东部机场"}
        ]
    },
    "冈山": {
        "primary": "OKJ", 
        "secondary": [], 
        "airports": [
            {"code": "OKJ", "name": "冈山机场", "name_en": "Okayama Airport", "note": "中国地区机场"}
        ]
    },
    "静冈": {
        "primary": "FSZ", 
        "secondary": [], 
        "airports": [
            {"code": "FSZ", "name": "静冈机场", "name_en": "Shizuoka Airport", "note": "富士山静冈机场"}
        ]
    },
    
    # 东南亚主要城市
    "新加坡": {
        "primary": "SIN", 
        "secondary": [], 
        "airports": [
            {"code": "SIN", "name": "新加坡樟宜机场", "name_en": "Singapore Changi Airport", "note": "世界顶级机场,东南亚枢纽"}
        ]
    },
    "吉隆坡": {
        "primary": "KUL", 
        "secondary": [], 
        "airports": [
            {"code": "KUL", "name": "吉隆坡国际机场", "name_en": "Kuala Lumpur International Airport", "note": "马来西亚主要国际机场"}
        ]
    },
    "曼谷": {
        "primary": "BKK", 
        "secondary": ["DMK"], 
        "airports": [
            {"code": "BKK", "name": "素万那普机场", "name_en": "Suvarnabhumi Airport", "note": "泰国主要国际机场"},
            {"code": "DMK", "name": "廊曼机场", "name_en": "Don Mueang International Airport", "note": "廉价航空主要基地"}
        ]
    },
    "雅加达": {
        "primary": "CGK", 
        "secondary": [], 
        "airports": [
            {"code": "CGK", "name": "苏加诺-哈达国际机场", "name_en": "Soekarno-Hatta International Airport", "note": "印尼主要国际机场"}
        ]
    },
    "马尼拉": {
        "primary": "MNL", 
        "secondary": [], 
        "airports": [
            {"code": "MNL", "name": "尼诺·阿基诺国际机场", "name_en": "Ninoy Aquino International Airport", "note": "菲律宾主要国际机场"}
        ]
    },
    "胡志明市": {
        "primary": "SGN", 
        "secondary": [], 
        "airports": [
            {"code": "SGN", "name": "新山一国际机场", "name_en": "Tan Son Nhat International Airport", "note": "越南南部主要机场"}
        ]
    },
    "河内": {
        "primary": "HAN", 
        "secondary": [], 
        "airports": [
            {"code": "HAN", "name": "内排国际机场", "name_en": "Noi Bai International Airport", "note": "越南北部主要机场"}
        ]
    },
    
    # 补充东南亚其他重要城市
    "清迈": {
        "primary": "CNX", 
        "secondary": [], 
        "airports": [
            {"code": "CNX", "name": "清迈国际机场", "name_en": "Chiang Mai International Airport", "note": "泰国北部主要机场"}
        ]
    },
    "普吉": {
        "primary": "HKT", 
        "secondary": [], 
        "airports": [
            {"code": "HKT", "name": "普吉国际机场", "name_en": "Phuket International Airport", "note": "泰国南部旅游机场"}
        ]
    },
    "芭提雅": {
        "primary": "UTP", 
        "secondary": [], 
        "airports": [
            {"code": "UTP", "name": "乌塔堡国际机场", "name_en": "U-Tapao International Airport", "note": "芭提雅地区机场"}
        ]
    },
    "合艾": {
        "primary": "HDY", 
        "secondary": [], 
        "airports": [
            {"code": "HDY", "name": "合艾机场", "name_en": "Hat Yai Airport", "note": "泰国南部机场"}
        ]
    },
    "苏梅岛": {
        "primary": "USM", 
        "secondary": [], 
        "airports": [
            {"code": "USM", "name": "苏梅机场", "name_en": "Samui Airport", "note": "泰国海岛度假胜地"}
        ]
    },
    "甲米": {
        "primary": "KBV", 
        "secondary": [], 
        "airports": [
            {"code": "KBV", "name": "甲米机场", "name_en": "Krabi Airport", "note": "泰国南部海滨旅游机场"}
        ]
    },
    "素可泰": {
        "primary": "THS", 
        "secondary": [], 
        "airports": [
            {"code": "THS", "name": "素可泰机场", "name_en": "Sukhothai Airport", "note": "泰国古都历史名城"}
        ]
    },
    "乌隆他尼": {
        "primary": "UTH", 
        "secondary": [], 
        "airports": [
            {"code": "UTH", "name": "乌隆他尼机场", "name_en": "Udon Thani Airport", "note": "泰国东北部机场"}
        ]
    },
    "乌汶": {
        "primary": "UBP", 
        "secondary": [], 
        "airports": [
            {"code": "UBP", "name": "乌汶机场", "name_en": "Ubon Ratchathani Airport", "note": "泰国东北部机场"}
        ]
    },
    "巴厘岛": {
        "primary": "DPS", 
        "secondary": [], 
        "airports": [
            {"code": "DPS", "name": "伍拉·赖国际机场", "name_en": "Ngurah Rai International Airport", "note": "巴厘岛登巴萨机场"}
        ]
    },
    "泗水": {
        "primary": "MLG", 
        "secondary": [], 
        "airports": [
            {"code": "MLG", "name": "阿卜杜勒·拉赫曼·萨利赫机场", "name_en": "Abdul Rachman Saleh Airport", "note": "东爪哇主要机场"}
        ]
    },
    "日惹": {
        "primary": "JOG", 
        "secondary": [], 
        "airports": [
            {"code": "JOG", "name": "日惹国际机场", "name_en": "Yogyakarta International Airport", "note": "中爪哇文化名城"}
        ]
    },
    "棉兰": {
        "primary": "KNO", 
        "secondary": [], 
        "airports": [
            {"code": "KNO", "name": "瓜拉纳穆国际机场", "name_en": "Kualanamu International Airport", "note": "苏门答腊北部机场"}
        ]
    },
    "宿务": {
        "primary": "CEB", 
        "secondary": [], 
        "airports": [
            {"code": "CEB", "name": "宿务国际机场", "name_en": "Mactan-Cebu International Airport", "note": "菲律宾第二大机场"}
        ]
    },
    "达沃": {
        "primary": "DVO", 
        "secondary": [], 
        "airports": [
            {"code": "DVO", "name": "达沃国际机场", "name_en": "Francisco Bangoy International Airport", "note": "菲律宾南部主要机场"}
        ]
    },
    "卡加延德奥罗": {
        "primary": "CGY", 
        "secondary": [], 
        "airports": [
            {"code": "CGY", "name": "卡加延德奥罗机场", "name_en": "Cagayan de Oro Airport", "note": "菲律宾棉兰老岛机场"}
        ]
    },
    "仰光": {
        "primary": "RGN", 
        "secondary": [], 
        "airports": [
            {"code": "RGN", "name": "仰光国际机场", "name_en": "Yangon International Airport", "note": "缅甸主要国际机场"}
        ]
    },
    "曼德勒": {
        "primary": "MDL", 
        "secondary": [], 
        "airports": [
            {"code": "MDL", "name": "曼德勒国际机场", "name_en": "Mandalay International Airport", "note": "缅甸第二大机场"}
        ]
    },
    "金边": {
        "primary": "PNH", 
        "secondary": [], 
        "airports": [
            {"code": "PNH", "name": "金边国际机场", "name_en": "Phnom Penh International Airport", "note": "柬埔寨主要机场"}
        ]
    },
    "暹粒": {
        "primary": "REP", 
        "secondary": [], 
        "airports": [
            {"code": "REP", "name": "暹粒国际机场", "name_en": "Siem Reap International Airport", "note": "吴哥窟旅游机场"}
        ]
    },
    "西哈努克城": {
        "primary": "KOS", 
        "secondary": [], 
        "airports": [
            {"code": "KOS", "name": "西哈努克国际机场", "name_en": "Sihanouk International Airport", "note": "柬埔寨海滨城市机场"}
        ]
    },
    "万象": {
        "primary": "VTE", 
        "secondary": [], 
        "airports": [
            {"code": "VTE", "name": "万象瓦岱国际机场", "name_en": "Wattay International Airport", "note": "老挝主要机场"}
        ]
    },
    "琅勃拉邦": {
        "primary": "LPQ", 
        "secondary": [], 
        "airports": [
            {"code": "LPQ", "name": "琅勃拉邦机场", "name_en": "Luang Prabang Airport", "note": "老挝古都旅游机场"}
        ]
    },
    "斯里巴加湾市": {
        "primary": "BWN", 
        "secondary": [], 
        "airports": [
            {"code": "BWN", "name": "文莱国际机场", "name_en": "Brunei International Airport", "note": "文莱唯一国际机场"}
        ]
    },
    "亚庇": {
        "primary": "BKI", 
        "secondary": [], 
        "airports": [
            {"code": "BKI", "name": "亚庇国际机场", "name_en": "Kota Kinabalu International Airport", "note": "东马沙巴州机场"}
        ]
    },
    "古晋": {
        "primary": "KCH", 
        "secondary": [], 
        "airports": [
            {"code": "KCH", "name": "古晋国际机场", "name_en": "Kuching International Airport", "note": "东马砂拉越州机场"}
        ]
    },
    "槟城": {
        "primary": "PEN", 
        "secondary": [], 
        "airports": [
            {"code": "PEN", "name": "槟城国际机场", "name_en": "Penang International Airport", "note": "马来西亚北部机场"}
        ]
    },
    "兰卡威": {
        "primary": "LGK", 
        "secondary": [], 
        "airports": [
            {"code": "LGK", "name": "兰卡威国际机场", "name_en": "Langkawi International Airport", "note": "马来西亚度假岛机场"}
        ]
    },
    
    # 南亚主要城市
    "新德里": {
        "primary": "DEL", 
        "secondary": [], 
        "airports": [
            {"code": "DEL", "name": "英迪拉·甘地国际机场", "name_en": "Indira Gandhi International Airport", "note": "印度首都机场,南亚重要枢纽"}
        ]
    },
    "孟买": {
        "primary": "BOM", 
        "secondary": [], 
        "airports": [
            {"code": "BOM", "name": "贾特拉帕蒂·希瓦吉国际机场", "name_en": "Chhatrapati Shivaji International Airport", "note": "印度商业之都"}
        ]
    },
    "班加罗尔": {
        "primary": "BLR", 
        "secondary": [], 
        "airports": [
            {"code": "BLR", "name": "班加罗尔国际机场", "name_en": "Kempegowda International Airport", "note": "印度IT中心"}
        ]
    },
    "钦奈": {
        "primary": "MAA", 
        "secondary": [], 
        "airports": [
            {"code": "MAA", "name": "钦奈国际机场", "name_en": "Chennai International Airport", "note": "南印度重要机场"}
        ]
    },
    "海得拉巴": {
        "primary": "HYD", 
        "secondary": [], 
        "airports": [
            {"code": "HYD", "name": "海得拉巴国际机场", "name_en": "Rajiv Gandhi International Airport", "note": "印度IT城市"}
        ]
    },
    "加尔各答": {
        "primary": "CCU", 
        "secondary": [], 
        "airports": [
            {"code": "CCU", "name": "内塔吉·苏巴斯·钱德拉·鲍斯国际机场", "name_en": "Netaji Subhash Chandra Bose International Airport", "note": "东印度重要机场"}
        ]
    },
    "加德满都": {
        "primary": "KTM", 
        "secondary": [], 
        "airports": [
            {"code": "KTM", "name": "特里布万国际机场", "name_en": "Tribhuvan International Airport", "note": "尼泊尔唯一国际机场"}
        ]
    },
    "达卡": {
        "primary": "DAC", 
        "secondary": [], 
        "airports": [
            {"code": "DAC", "name": "沙阿贾拉勒国际机场", "name_en": "Hazrat Shahjalal International Airport", "note": "孟加拉国主要机场"}
        ]
    },
    "科伦坡": {
        "primary": "CMB", 
        "secondary": [], 
        "airports": [
            {"code": "CMB", "name": "班达拉奈克国际机场", "name_en": "Bandaranaike International Airport", "note": "斯里兰卡主要机场"}
        ]
    },
    "卡拉奇": {
        "primary": "KHI", 
        "secondary": [], 
        "airports": [
            {"code": "KHI", "name": "真纳国际机场", "name_en": "Jinnah International Airport", "note": "巴基斯坦最大机场"}
        ]
    },
    "拉合尔": {
        "primary": "LHE", 
        "secondary": [], 
        "airports": [
            {"code": "LHE", "name": "阿拉马·伊克巴勒国际机场", "name_en": "Allama Iqbal International Airport", "note": "巴基斯坦第二大机场"}
        ]
    },
    "伊斯兰堡": {
        "primary": "ISB", 
        "secondary": [], 
        "airports": [
            {"code": "ISB", "name": "伊斯兰堡国际机场", "name_en": "Islamabad International Airport", "note": "巴基斯坦首都机场"}
        ]
    },
    "马尔代夫": {
        "primary": "MLE", 
        "secondary": [], 
        "airports": [
            {"code": "MLE", "name": "易卜拉欣·纳西尔国际机场", "name_en": "Velana International Airport", "note": "马尔代夫首都马累机场"}
        ]
    },
    "马累": {
        "primary": "MLE", 
        "secondary": [], 
        "airports": [
            {"code": "MLE", "name": "易卜拉欣·纳西尔国际机场", "name_en": "Velana International Airport", "note": "马尔代夫度假天堂门户"}
        ]
    },
    
    # 西亚中东主要城市
    "伊斯坦布尔": {
        "primary": "IST", 
        "secondary": ["SAW"], 
        "airports": [
            {"code": "IST", "name": "伊斯坦布尔机场", "name_en": "Istanbul Airport", "note": "土耳其新主要国际机场"},
            {"code": "SAW", "name": "萨比哈·格克琴国际机场", "name_en": "Sabiha Gökçen International Airport", "note": "亚洲区机场"}
        ]
    },
    "阿布扎比": {
        "primary": "AUH", 
        "secondary": [], 
        "airports": [
            {"code": "AUH", "name": "阿布扎比国际机场", "name_en": "Abu Dhabi International Airport", "note": "阿联酋首都机场"}
        ]
    },
    "德黑兰": {
        "primary": "IKA", 
        "secondary": [], 
        "airports": [
            {"code": "IKA", "name": "伊玛目霍梅尼国际机场", "name_en": "Imam Khomeini International Airport", "note": "伊朗主要国际机场"}
        ]
    },
    "科威特城": {
        "primary": "KWI", 
        "secondary": [], 
        "airports": [
            {"code": "KWI", "name": "科威特国际机场", "name_en": "Kuwait International Airport", "note": "科威特主要机场"}
        ]
    },
    "利雅得": {
        "primary": "RUH", 
        "secondary": [], 
        "airports": [
            {"code": "RUH", "name": "哈立德国王国际机场", "name_en": "King Khalid International Airport", "note": "沙特阿拉伯首都机场"}
        ]
    },
    "吉达": {
        "primary": "JED", 
        "secondary": [], 
        "airports": [
            {"code": "JED", "name": "阿卜杜勒·阿齐兹国王国际机场", "name_en": "King Abdulaziz International Airport", "note": "沙特第二大机场"}
        ]
    },
    "巴格达": {
        "primary": "BGW", 
        "secondary": [], 
        "airports": [
            {"code": "BGW", "name": "巴格达国际机场", "name_en": "Baghdad International Airport", "note": "伊拉克主要机场"}
        ]
    },
    "贝鲁特": {
        "primary": "BEY", 
        "secondary": [], 
        "airports": [
            {"code": "BEY", "name": "拉菲克·哈里里国际机场", "name_en": "Rafic Hariri International Airport", "note": "黎巴嫩主要机场"}
        ]
    },
    "大马士革": {
        "primary": "DAM", 
        "secondary": [], 
        "airports": [
            {"code": "DAM", "name": "大马士革国际机场", "name_en": "Damascus International Airport", "note": "叙利亚主要机场"}
        ]
    },
    "安曼": {
        "primary": "AMM", 
        "secondary": [], 
        "airports": [
            {"code": "AMM", "name": "阿卜杜拉二世女王国际机场", "name_en": "Queen Alia International Airport", "note": "约旦主要机场"}
        ]
    },
    
    # 中亚主要城市
    "巴库": {
        "primary": "GYD", 
        "secondary": [], 
        "airports": [
            {"code": "GYD", "name": "盖达尔·阿利耶夫国际机场", "name_en": "Heydar Aliyev International Airport", "note": "阿塞拜疆主要机场"}
        ]
    },
    "塔什干": {
        "primary": "TAS", 
        "secondary": [], 
        "airports": [
            {"code": "TAS", "name": "塔什干国际机场", "name_en": "Tashkent International Airport", "note": "乌兹别克斯坦主要机场"}
        ]
    },
    "阿拉木图": {
        "primary": "ALA", 
        "secondary": [], 
        "airports": [
            {"code": "ALA", "name": "阿拉木图国际机场", "name_en": "Almaty International Airport", "note": "哈萨克斯坦最大机场"}
        ]
    },
    "努尔苏丹": {
        "primary": "NUR", 
        "secondary": [], 
        "airports": [
            {"code": "NUR", "name": "努尔苏丹纳扎尔巴耶夫国际机场", "name_en": "Nur-Sultan Nazarbayev International Airport", "note": "哈萨克斯坦首都机场"}
        ]
    },
    "比什凯克": {
        "primary": "FRU", 
        "secondary": [], 
        "airports": [
            {"code": "FRU", "name": "玛纳斯国际机场", "name_en": "Manas International Airport", "note": "吉尔吉斯斯坦主要机场"}
        ]
    },
    "杜尚别": {
        "primary": "DYU", 
        "secondary": [], 
        "airports": [
            {"code": "DYU", "name": "杜尚别国际机场", "name_en": "Dushanbe International Airport", "note": "塔吉克斯坦主要机场"}
        ]
    },
    "阿什哈巴德": {
        "primary": "ASB", 
        "secondary": [], 
        "airports": [
            {"code": "ASB", "name": "奥古兹汗机场", "name_en": "Oguzhan Airport", "note": "土库曼斯坦主要机场"}
        ]
    },

    # 美国主要城市
    "纽约": {
        "primary": "JFK", 
        "secondary": ["LGA", "EWR"], 
        "airports": [
            {"code": "JFK", "name": "约翰·肯尼迪国际机场", "name_en": "John F. Kennedy International Airport", "note": "主要国际航班"},
            {"code": "LGA", "name": "拉瓜迪亚机场", "name_en": "LaGuardia Airport", "note": "主要服务国内航班"},
            {"code": "EWR", "name": "纽瓦克自由国际机场", "name_en": "Newark Liberty International Airport", "note": "国际航班,位于新泽西"}
        ]
    },
    "洛杉矶": {
        "primary": "LAX", 
        "secondary": [], 
        "airports": [
            {"code": "LAX", "name": "洛杉矶国际机场", "name_en": "Los Angeles International Airport", "note": "美西最大机场"}
        ]
    },
    "旧金山": {
        "primary": "SFO", 
        "secondary": [], 
        "airports": [
            {"code": "SFO", "name": "旧金山国际机场", "name_en": "San Francisco International Airport", "note": "湾区主要国际机场"}
        ]
    },
    "芝加哥": {
        "primary": "ORD", 
        "secondary": ["MDW"], 
        "airports": [
            {"code": "ORD", "name": "奥黑尔国际机场", "name_en": "O'Hare International Airport", "note": "美国中部重要枢纽"},
            {"code": "MDW", "name": "中途机场", "name_en": "Midway International Airport", "note": "廉价航空基地"}
        ]
    },
    "西雅图": {
        "primary": "SEA", 
        "secondary": [], 
        "airports": [
            {"code": "SEA", "name": "西雅图-塔科马国际机场", "name_en": "Seattle-Tacoma International Airport", "note": "太平洋西北地区枢纽"}
        ]
    },
    "华盛顿": {
        "primary": "IAD", 
        "secondary": ["DCA"], 
        "airports": [
            {"code": "IAD", "name": "华盛顿杜勒斯国际机场", "name_en": "Washington Dulles International Airport", "note": "主要国际航班"},
            {"code": "DCA", "name": "罗纳德·里根华盛顿国家机场", "name_en": "Ronald Reagan Washington National Airport", "note": "国内航班,距市区近"}
        ]
    },
    "迈阿密": {
        "primary": "MIA", 
        "secondary": [], 
        "airports": [
            {"code": "MIA", "name": "迈阿密国际机场", "name_en": "Miami International Airport", "note": "通往拉美的门户"}
        ]
    },
    
    # 加拿大主要城市
    "多伦多": {
        "primary": "YYZ", 
        "secondary": [], 
        "airports": [
            {"code": "YYZ", "name": "皮尔逊国际机场", "name_en": "Toronto Pearson International Airport", "note": "加拿大最大机场"}
        ]
    },
    "温哥华": {
        "primary": "YVR", 
        "secondary": [], 
        "airports": [
            {"code": "YVR", "name": "温哥华国际机场", "name_en": "Vancouver International Airport", "note": "通往亚洲的门户"}
        ]
    },
    
    # 欧洲主要城市
    "伦敦": {
        "primary": "LHR", 
        "secondary": ["LGW", "STN", "LTN"], 
        "airports": [
            {"code": "LHR", "name": "希思罗机场", "name_en": "Heathrow Airport", "note": "欧洲最繁忙机场"},
            {"code": "LGW", "name": "盖特威克机场", "name_en": "Gatwick Airport", "note": "第二大机场"},
            {"code": "STN", "name": "斯坦斯特德机场", "name_en": "Stansted Airport", "note": "廉价航空基地"},
            {"code": "LTN", "name": "卢顿机场", "name_en": "Luton Airport", "note": "廉价航空基地"}
        ]
    },
    "巴黎": {
        "primary": "CDG", 
        "secondary": ["ORY"], 
        "airports": [
            {"code": "CDG", "name": "夏尔·戴高乐机场", "name_en": "Charles de Gaulle Airport", "note": "欧洲主要枢纽"},
            {"code": "ORY", "name": "奥利机场", "name_en": "Orly Airport", "note": "主要服务欧洲及国内航班"}
        ]
    },
    "法兰克福": {
        "primary": "FRA", 
        "secondary": [], 
        "airports": [
            {"code": "FRA", "name": "法兰克福机场", "name_en": "Frankfurt Airport", "note": "欧洲重要货运及客运枢纽"}
        ]
    },
    "阿姆斯特丹": {
        "primary": "AMS", 
        "secondary": [], 
        "airports": [
            {"code": "AMS", "name": "史基浦机场", "name_en": "Amsterdam Airport Schiphol", "note": "荷兰皇家航空枢纽"}
        ]
    },
    "罗马": {
        "primary": "FCO", 
        "secondary": [], 
        "airports": [
            {"code": "FCO", "name": "菲乌米奇诺机场", "name_en": "Leonardo da Vinci International Airport", "note": "意大利最大机场"}
        ]
    },
    "马德里": {
        "primary": "MAD", 
        "secondary": [], 
        "airports": [
            {"code": "MAD", "name": "阿道弗·苏亚雷斯马德里-巴拉哈斯机场", "name_en": "Adolfo Suárez Madrid-Barajas Airport", "note": "西班牙最大机场"}
        ]
    },
    "苏黎世": {
        "primary": "ZUR", 
        "secondary": [], 
        "airports": [
            {"code": "ZUR", "name": "苏黎世机场", "name_en": "Zurich Airport", "note": "瑞士最大机场"}
        ]
    },
    
    # 澳洲主要城市
    "悉尼": {
        "primary": "SYD", 
        "secondary": [], 
        "airports": [
            {"code": "SYD", "name": "悉尼金斯福德·史密斯机场", "name_en": "Sydney Kingsford Smith Airport", "note": "澳洲最繁忙机场"}
        ]
    },
    "墨尔本": {
        "primary": "MEL", 
        "secondary": [], 
        "airports": [
            {"code": "MEL", "name": "墨尔本机场", "name_en": "Melbourne Airport", "note": "澳洲第二大机场"}
        ]
    },
    "珀斯": {
        "primary": "PER", 
        "secondary": [], 
        "airports": [
            {"code": "PER", "name": "珀斯机场", "name_en": "Perth Airport", "note": "西澳主要机场"}
        ]
    },
    "奥克兰": {
        "primary": "AKL", 
        "secondary": [], 
        "airports": [
            {"code": "AKL", "name": "奥克兰机场", "name_en": "Auckland Airport", "note": "新西兰最大机场"}
        ]
    },
    
    # 中东主要城市
    "迪拜": {
        "primary": "DXB", 
        "secondary": [], 
        "airports": [
            {"code": "DXB", "name": "迪拜国际机场", "name_en": "Dubai International Airport", "note": "中东最重要枢纽"}
        ]
    },
    "多哈": {
        "primary": "DOH", 
        "secondary": [], 
        "airports": [
            {"code": "DOH", "name": "哈马德国际机场", "name_en": "Hamad International Airport", "note": "卡塔尔航空枢纽"}
        ]
    },
}

# 英文城市名映射（小写匹配）
ENGLISH_CITIES_AIRPORTS = {
    # 中国大陆
    "beijing": "北京",
    "shanghai": "上海", 
    "guangzhou": "广州",
    "shenzhen": "深圳",
    "chengdu": "成都",
    "chongqing": "重庆",
    "hangzhou": "杭州",
    "nanjing": "南京",
    "xi'an": "西安",
    "xian": "西安",
    "xiamen": "厦门",
    "kunming": "昆明",
    "tianjin": "天津",
    "wuhan": "武汉",
    "zhengzhou": "郑州",
    "shenyang": "沈阳",
    "dalian": "大连",
    "qingdao": "青岛",
    "changsha": "长沙",
    "nanchang": "南昌",
    "hefei": "合肥",
    
    # 港澳台
    "hong kong": "香港",
    "hongkong": "香港",
    "macau": "澳门",
    "macao": "澳门",
    "taipei": "台北",
    # 新增台湾城市
    "kaohsiung": "高雄",
    "taichung": "台中",
    "tainan": "台南",
    "hualien": "花莲",
    "hualien city": "花莲",
    
    # 日本
    "tokyo": "东京",
    "osaka": "大阪",
    "nagoya": "名古屋",
    "fukuoka": "福冈",
    "sapporo": "札幌",
    "sendai": "仙台",
    "hiroshima": "广岛",
    "okinawa": "冲绳",
    "kumamoto": "熊本",
    "kagoshima": "鹿儿岛",
    "takamatsu": "高松",
    "matsuyama": "松山",
    # 新增日本城市
    "akita": "秋田",
    "aomori": "青森",
    "hakodate": "函馆",
    "kitakyushu": "北九州",
    "komatsu": "小松",
    "nagasaki": "长崎",
    "niigata": "新潟",
    "oita": "大分",
    "okayama": "冈山",
    "shizuoka": "静冈",
    
    # 韩国
    "seoul": "首尔",
    "busan": "釜山",
    "jeju": "济州",
    "daegu": "大邱",
    "gwangju": "光州",
    "cheongju": "清州",
    "muan": "务安",
    "yangyang": "襄阳",
    
    # 东南亚
    "singapore": "新加坡",
    "bangkok": "曼谷",
    "kuala lumpur": "吉隆坡",
    "jakarta": "雅加达",
    "manila": "马尼拉",
    "ho chi minh city": "胡志明市",
    "saigon": "胡志明市",
    "hanoi": "河内",
    "chiang mai": "清迈",
    "phuket": "普吉",
    "pattaya": "芭提雅",
    "hat yai": "合艾",
    "samui": "苏梅岛",
    "koh samui": "苏梅岛",
    "krabi": "甲米",
    "sukhothai": "素可泰",
    "udon thani": "乌隆他尼",
    "ubon ratchathani": "乌汶",
    "bali": "巴厘岛",
    "denpasar": "巴厘岛",
    "surabaya": "泗水",
    "yogyakarta": "日惹",
    "medan": "棉兰",
    "cebu": "宿务",
    "davao": "达沃",
    "yangon": "仰光",
    "mandalay": "曼德勒",
    "phnom penh": "金边",
    "siem reap": "暹粒",
    "sihanoukville": "西哈努克城",
    "vientiane": "万象",
    "luang prabang": "琅勃拉邦",
    "bandar seri begawan": "斯里巴加湾市",
    "kota kinabalu": "亚庇",
    "kuching": "古晋",
    "penang": "槟城",
    "langkawi": "兰卡威",
    
    # 南亚
    "new delhi": "新德里",
    "delhi": "新德里",
    "mumbai": "孟买",
    "bombay": "孟买",
    "bangalore": "班加罗尔",
    "bengaluru": "班加罗尔",
    "chennai": "钦奈",
    "madras": "钦奈",
    "hyderabad": "海得拉巴",
    "kolkata": "加尔各答",
    "calcutta": "加尔各答",
    "kathmandu": "加德满都",
    "dhaka": "达卡",
    "colombo": "科伦坡",
    "karachi": "卡拉奇",
    "lahore": "拉合尔",
    "islamabad": "伊斯兰堡",
    "maldives": "马尔代夫",
    "male": "马累",
    
    # 西亚中东
    "istanbul": "伊斯坦布尔",
    "abu dhabi": "阿布扎比",
    "tehran": "德黑兰",
    "kuwait city": "科威特城",
    "riyadh": "利雅得",
    "jeddah": "吉达",
    "baghdad": "巴格达",
    "beirut": "贝鲁特",
    "damascus": "大马士革",
    "amman": "安曼",
    
    # 中亚
    "baku": "巴库",
    "tashkent": "塔什干",
    "almaty": "阿拉木图",
    "nur-sultan": "努尔苏丹",
    "astana": "努尔苏丹",
    "bishkek": "比什凯克",
    "dushanbe": "杜尚别",
    "ashgabat": "阿什哈巴德",
    
    # 其他地区（保持原有）
    "new york": "纽约",
    "los angeles": "洛杉矶",
    "san francisco": "旧金山",
    "chicago": "芝加哥",
    "seattle": "西雅图",
    "toronto": "多伦多",
    "vancouver": "温哥华",
    "london": "伦敦",
    "paris": "巴黎",
    "frankfurt": "法兰克福",
    "amsterdam": "阿姆斯特丹",
    "dubai": "迪拜",
    "doha": "多哈",
    "sydney": "悉尼",
    "melbourne": "墨尔本",
}

# 常见输入错误和别名映射
CITY_ALIASES = {
    # 中文别名
    "北平": "北京",
    "京城": "北京",
    "申城": "上海",
    "魔都": "上海", 
    "沪": "上海",
    "羊城": "广州",
    "穗": "广州",
    "鹏城": "深圳",
    "圳": "深圳",
    "港": "香港",
    "澳": "澳门",
    
    # 英文别名
    "nyc": "纽约",
    "la": "洛杉矶",
    "sf": "旧金山",
    "chi": "芝加哥",
    "dc": "华盛顿",
    "hk": "香港",
    
    # 国家/地区映射到主要城市 - 注意：不要映射在country_cities_map中已定义的国家
    "英国": "伦敦",
    "法国": "巴黎",
    "德国": "法兰克福",
    "荷兰": "阿姆斯特丹",
    "意大利": "罗马",
    "西班牙": "马德里",
    "瑞士": "苏黎世",
    "澳大利亚": "悉尼",
    "澳洲": "悉尼",
    "新西兰": "奥克兰",
    
    # 城市常见别名和拼写变体
    "胡志明": "胡志明市",
    "西贡": "胡志明市",
    "河内市": "河内",
    "金边市": "金边",
    "万象市": "万象",
    "仰光市": "仰光",
    "曼德勒市": "曼德勒",
    "暹粒市": "暹粒",
    "琅勃拉邦市": "琅勃拉邦",
    "新德里市": "新德里",
    "孟买市": "孟买",
    "班加罗尔市": "班加罗尔",
    "钦奈市": "钦奈",
    "海得拉巴市": "海得拉巴",
    "加尔各答市": "加尔各答",
    "加德满都市": "加德满都",
    "达卡市": "达卡",
    "科伦坡市": "科伦坡",
    "卡拉奇市": "卡拉奇",
    "拉合尔市": "拉合尔",
    "伊斯兰堡市": "伊斯兰堡",
    "迪拜市": "迪拜",
    "多哈市": "多哈",
    "阿布扎比市": "阿布扎比",
    "德黑兰市": "德黑兰",
    "伊斯坦布尔市": "伊斯坦布尔",
    "巴库市": "巴库",
    "塔什干市": "塔什干",
    "阿拉木图市": "阿拉木图",
    "努尔苏丹市": "努尔苏丹",
    "比什凯克市": "比什凯克",
    "杜尚别市": "杜尚别",
    "阿什哈巴德市": "阿什哈巴德",
    
    # 韩国城市别名
    "首尔市": "首尔",
    "釜山市": "釜山",
    "济州岛": "济州",
    "济州市": "济州",
    "大邱市": "大邱",
    "光州市": "光州",
    "清州市": "清州",
    
    # 柬埔寨城市别名
    "金边市": "金边",
    "暹粒市": "暹粒", 
    "西哈努克市": "西哈努克城",
    "西港": "西哈努克城",
}

# 无国际机场城市的建议映射
CITY_SUGGESTIONS = {
    "杭州": {
        "suggestions": [
            {"airport": "SHA", "city": "上海虹桥", "transport": "高铁1小时,同站换乘", "note": "推荐"},
            {"airport": "PVG", "city": "上海浦东", "transport": "高铁1小时+磁悬浮8分钟", "note": "国际航班多"},
            {"airport": "NKG", "city": "南京禄口", "transport": "高铁2小时", "note": "备选"}
        ]
    },
    "苏州": {
        "suggestions": [
            {"airport": "SHA", "city": "上海虹桥", "transport": "高铁30分钟", "note": "推荐"},
            {"airport": "PVG", "city": "上海浦东", "transport": "高铁30分钟+磁悬浮8分钟", "note": "国际航班"}
        ]
    },
    "无锡": {
        "suggestions": [
            {"airport": "SHA", "city": "上海虹桥", "transport": "高铁45分钟", "note": "推荐"},
            {"airport": "NKG", "city": "南京禄口", "transport": "高铁1小时", "note": "备选"}
        ]
    },
    "宁波": {
        "suggestions": [
            {"airport": "SHA", "city": "上海虹桥", "transport": "高铁2小时", "note": "推荐"},
            {"airport": "PVG", "city": "上海浦东", "transport": "高铁2小时+磁悬浮", "note": "国际航班"},
            {"airport": "HGH", "city": "杭州萧山", "transport": "高铁1小时", "note": "就近选择"}
        ]
    }
}

def normalize_city_input(city_input: str) -> str:
    """规范化城市输入"""
    if not city_input:
        return ""
    
    # 去除空格并转为小写（用于英文匹配）
    normalized = city_input.strip()
    
    # 检查别名映射
    if normalized in CITY_ALIASES:
        return CITY_ALIASES[normalized]
    
    # 检查英文城市名映射
    normalized_lower = normalized.lower()
    if normalized_lower in ENGLISH_CITIES_AIRPORTS:
        return ENGLISH_CITIES_AIRPORTS[normalized_lower]
    
    return normalized

def resolve_airport_codes(city_input: str) -> Dict:
    """
    解析城市输入到机场代码
    返回: {
        "status": "success/multiple/not_found/suggestion_needed/country_airports",
        "primary": "主要机场代码", 
        "secondary": ["备选机场代码"],
        "airports": [机场详细信息],
        "suggestions": [建议信息] (仅当需要建议时)
        "country_airports": [国家所有机场] (仅当是国家搜索时)
    }
    """
    if not city_input:
        return {"status": "not_found"}
    
    # 检查是否已经是IATA代码
    if len(city_input) == 3 and city_input.isupper() and city_input.isalpha():
        return {
            "status": "success",
            "primary": city_input,
            "secondary": [],
            "airports": [{"code": city_input, "name": "机场代码", "note": "请确认代码正确"}]
        }
    
    # 规范化输入
    normalized_city = normalize_city_input(city_input)
    
    # 检查是否是国家/地区级别搜索
    country_airports = get_country_airports(normalized_city)
    if country_airports:
        return {
            "status": "country_airports",
            "country": normalized_city,
            "country_airports": country_airports,
            "primary": country_airports[0]["primary"] if country_airports else "",
            "secondary": [],
            "airports": []
        }
    
    # 检查主要城市映射
    if normalized_city in MAJOR_CITIES_AIRPORTS:
        city_info = MAJOR_CITIES_AIRPORTS[normalized_city]
        
        # 判断是单机场还是多机场城市
        if len(city_info["airports"]) == 1:
            return {
                "status": "success",
                "primary": city_info["primary"],
                "secondary": city_info["secondary"],
                "airports": city_info["airports"],
                "city": normalized_city
            }
        else:
            return {
                "status": "multiple",
                "primary": city_info["primary"],
                "secondary": city_info["secondary"], 
                "airports": city_info["airports"],
                "city": normalized_city
            }
    
    # 检查是否需要建议
    if normalized_city in CITY_SUGGESTIONS:
        return {
            "status": "suggestion_needed",
            "city": normalized_city,
            "suggestions": CITY_SUGGESTIONS[normalized_city]["suggestions"]
        }
    
    return {
        "status": "not_found",
        "input": city_input,
        "normalized": normalized_city
    }

def get_country_airports(country_name: str) -> List[Dict]:
    """获取指定国家/地区的所有机场"""
    country_cities_map = {
        # 东亚
        "台湾": ["台北", "高雄", "台中", "台南", "花莲"],
        "日本": ["东京", "大阪", "名古屋", "福冈", "札幌", "仙台", "广岛", "冲绳", "熊本", "鹿儿岛", 
               "秋田", "青森", "函馆", "北九州", "小松", "长崎", "新潟", "大分", "冈山", "静冈", "高松", "松山"],
        "韩国": ["首尔", "釜山", "济州", "大邱", "光州", "清州", "务安", "襄阳"],
        "中国": ["北京", "上海", "广州", "深圳", "成都", "西安", "杭州", "南京", "青岛", "大连", 
               "厦门", "武汉", "长沙", "昆明", "重庆", "天津", "沈阳", "哈尔滨", "乌鲁木齐", "拉萨", 
               "呼和浩特", "银川", "兰州", "西宁", "海口", "三亚", "贵阳", "太原", "石家庄", "郑州", 
               "济南", "合肥", "福州", "南昌", "长春"],
        
        # 东南亚
        "泰国": ["曼谷", "清迈", "普吉", "芭提雅", "合艾", "苏梅岛", "甲米", "素可泰", "乌隆他尼", "乌汶"],
        "新加坡": ["新加坡"],
        "马来西亚": ["吉隆坡", "槟城", "兰卡威", "亚庇", "古晋"],
        "印度尼西亚": ["雅加达", "巴厘岛", "泗水", "日惹", "棉兰"],
        "菲律宾": ["马尼拉", "宿务", "达沃", "卡加延德奥罗"],
        "越南": ["胡志明市", "河内"],
        "缅甸": ["仰光", "曼德勒"],
        "柬埔寨": ["金边", "暹粒", "西哈努克城"],
        "老挝": ["万象", "琅勃拉邦"],
        "文莱": ["斯里巴加湾市"],
        
        # 南亚
        "印度": ["新德里", "孟买", "班加罗尔", "钦奈", "海得拉巴", "加尔各答"],
        "巴基斯坦": ["卡拉奇", "拉合尔", "伊斯兰堡"],
        "尼泊尔": ["加德满都"],
        "孟加拉国": ["达卡"],
        "斯里兰卡": ["科伦坡"],
        "马尔代夫": ["马累", "马尔代夫"],
        
        # 西亚中东
        "土耳其": ["伊斯坦布尔"],
        "阿联酋": ["迪拜", "阿布扎比"],
        "卡塔尔": ["多哈"],
        "伊朗": ["德黑兰"],
        "科威特": ["科威特城"],
        "沙特阿拉伯": ["利雅得", "吉达"],
        "伊拉克": ["巴格达"],
        "黎巴嫩": ["贝鲁特"],
        "叙利亚": ["大马士革"],
        "约旦": ["安曼"],
        
        # 中亚
        "阿塞拜疆": ["巴库"],
        "乌兹别克斯坦": ["塔什干"],
        "哈萨克斯坦": ["阿拉木图", "努尔苏丹"],
        "吉尔吉斯斯坦": ["比什凯克"],
        "塔吉克斯坦": ["杜尚别"],
        "土库曼斯坦": ["阿什哈巴德"],
        
        # 北美洲
        "美国": ["纽约", "洛杉矶", "旧金山", "芝加哥", "西雅图", "华盛顿", "迈阿密"],
        "加拿大": ["多伦多", "温哥华"],
        
        # 欧洲
        "英国": ["伦敦"],
        "法国": ["巴黎"],
        "德国": ["法兰克福"],
        "荷兰": ["阿姆斯特丹"],
        "意大利": ["罗马"],
        "西班牙": ["马德里"],
        "瑞士": ["苏黎世"],
        
        # 大洋洲
        "澳大利亚": ["悉尼", "墨尔本", "珀斯"],
        "新西兰": ["奥克兰"],
    }
    
    if country_name not in country_cities_map:
        return []
    
    country_airports = []
    for city in country_cities_map[country_name]:
        if city in MAJOR_CITIES_AIRPORTS:
            city_info = MAJOR_CITIES_AIRPORTS[city].copy()
            city_info["city"] = city
            country_airports.append(city_info)
    
    return country_airports

def resolve_flight_airports(departure_input: str, arrival_input: str) -> Dict:
    """
    智能解析航班出发和到达机场
    返回完整的解析结果和建议
    """
    departure_result = resolve_airport_codes(departure_input)
    arrival_result = resolve_airport_codes(arrival_input)
    
    return {
        "departure": departure_result,
        "arrival": arrival_result,
        "status": _determine_overall_status(departure_result, arrival_result)
    }

def _determine_overall_status(departure_result: Dict, arrival_result: Dict) -> str:
    """确定整体解析状态"""
    dep_status = departure_result.get("status")
    arr_status = arrival_result.get("status")
    
    # 如果任一方需要建议，优先处理
    if dep_status == "suggestion_needed" or arr_status == "suggestion_needed":
        return "suggestion_needed"
    
    # 如果任一方未找到
    if dep_status == "not_found" or arr_status == "not_found":
        return "not_found"
    
    # 如果任一方有多个选择
    if dep_status == "multiple" or arr_status == "multiple":
        return "multiple_choice"
    
    # 都成功解析
    if dep_status == "success" and arr_status == "success":
        return "ready"
    
    return "unknown"

def format_airport_selection_message(departure_result: Dict, arrival_result: Dict) -> str:
    """格式化机场选择消息"""
    from telegram.helpers import escape_markdown
    
    message_parts = ["🛫 *机场选择确认*\n"]
    
    # 处理出发机场
    dep_status = departure_result.get("status")
    if dep_status == "multiple":
        city = departure_result.get("city", "")
        airports = departure_result.get("airports", [])
        safe_city = escape_markdown(city, version=2)
        message_parts.append(f"📍 *出发* {safe_city} 有{len(airports)}个机场:")
        
        for i, airport in enumerate(airports):
            code = airport.get("code", "")
            name = airport.get("name", "")
            note = airport.get("note", "")
            safe_name = escape_markdown(name, version=2)
            safe_note = escape_markdown(note, version=2)
            
            icon = "🔸" if i == 0 else "🔹"  # 主要机场用实心，次要用空心
            message_parts.append(f"{icon} *{code}* - {safe_name}")
            if note:
                message_parts.append(f"   💡 {safe_note}")
        message_parts.append("")
    elif dep_status == "suggestion_needed":
        city = departure_result.get("city", "")
        suggestions = departure_result.get("suggestions", [])
        safe_city = escape_markdown(city, version=2)
        message_parts.append(f"❓ *{safe_city}* 暂无国际机场\n")
        message_parts.append("🔍 *建议方案*:")
        
        for suggestion in suggestions:
            airport = suggestion.get("airport", "")
            airport_city = suggestion.get("city", "")
            transport = suggestion.get("transport", "")
            note = suggestion.get("note", "")
            
            safe_airport_city = escape_markdown(airport_city, version=2)
            safe_transport = escape_markdown(transport, version=2)
            
            note_icon = "⭐" if note == "推荐" else "🚄"
            message_parts.append(f"{note_icon} *{airport}* - {safe_airport_city}")
            message_parts.append(f"   🚅 {safe_transport}")
        message_parts.append("")
    
    # 处理到达机场
    arr_status = arrival_result.get("status")
    if arr_status == "multiple":
        city = arrival_result.get("city", "")
        airports = arrival_result.get("airports", [])
        safe_city = escape_markdown(city, version=2)
        message_parts.append(f"📍 *到达* {safe_city} 有{len(airports)}个机场:")
        
        for i, airport in enumerate(airports):
            code = airport.get("code", "")
            name = airport.get("name", "")
            note = airport.get("note", "")
            safe_name = escape_markdown(name, version=2)
            safe_note = escape_markdown(note, version=2)
            
            icon = "🔸" if i == 0 else "🔹"
            message_parts.append(f"{icon} *{code}* - {safe_name}")
            if note:
                message_parts.append(f"   💡 {safe_note}")
        message_parts.append("")
    elif arr_status == "suggestion_needed":
        city = arrival_result.get("city", "")
        suggestions = arrival_result.get("suggestions", [])
        safe_city = escape_markdown(city, version=2)
        message_parts.append(f"❓ *{safe_city}* 暂无国际机场\n")
        message_parts.append("🔍 *建议方案*:")
        
        for suggestion in suggestions:
            airport = suggestion.get("airport", "")
            airport_city = suggestion.get("city", "")
            transport = suggestion.get("transport", "")
            note = suggestion.get("note", "")
            
            safe_airport_city = escape_markdown(airport_city, version=2)
            safe_transport = escape_markdown(transport, version=2)
            
            note_icon = "⭐" if note == "推荐" else "🚄"
            message_parts.append(f"{note_icon} *{airport}* - {safe_airport_city}")
            message_parts.append(f"   🚅 {safe_transport}")
        message_parts.append("")
    
    return "\n".join(message_parts)

def get_recommended_airport_pair(departure_result: Dict, arrival_result: Dict) -> Tuple[str, str]:
    """获取推荐的机场对"""
    dep_primary = departure_result.get("primary", "")
    arr_primary = arrival_result.get("primary", "")
    return dep_primary, arr_primary

def format_airport_info(airport_code: str) -> str:
    """格式化单个机场信息显示"""
    from telegram.helpers import escape_markdown
    
    # 从映射中查找机场信息
    for city, city_info in MAJOR_CITIES_AIRPORTS.items():
        for airport in city_info["airports"]:
            if airport["code"] == airport_code:
                name = airport.get("name", "")
                name_en = airport.get("name_en", "")
                note = airport.get("note", "")
                
                safe_name = escape_markdown(name, version=2)
                safe_name_en = escape_markdown(name_en, version=2)
                safe_note = escape_markdown(note, version=2)
                safe_city = escape_markdown(city, version=2)
                
                result = f"✈️ *{safe_name}* ({airport_code})\n"
                result += f"📍 {safe_city}\n"
                if name_en and name_en != name:
                    result += f"🔤 {safe_name_en}\n"
                if note:
                    result += f"💡 {safe_note}\n"
                
                return result
    
    # 如果未找到详细信息，返回基本信息
    safe_code = escape_markdown(airport_code, version=2)
    return f"✈️ 机场代码: {safe_code}"

def get_all_supported_cities() -> List[str]:
    """获取所有支持的城市列表"""
    cities = list(MAJOR_CITIES_AIRPORTS.keys())
    cities.extend(CITY_ALIASES.keys())
    cities.extend(ENGLISH_CITIES_AIRPORTS.values())
    return sorted(set(cities))

def search_airports_by_partial_name(partial_name: str) -> List[Dict]:
    """根据部分名称搜索机场"""
    results = []
    partial_lower = partial_name.lower()
    
    for city, city_info in MAJOR_CITIES_AIRPORTS.items():
        # 检查城市名匹配
        if partial_lower in city.lower():
            results.extend([{
                "city": city,
                "code": airport["code"],
                "name": airport["name"],
                "match_type": "city"
            } for airport in city_info["airports"]])
        else:
            # 检查机场名匹配
            for airport in city_info["airports"]:
                if (partial_lower in airport["name"].lower() or 
                    partial_lower in airport.get("name_en", "").lower() or
                    partial_lower in airport["code"].lower()):
                    results.append({
                        "city": city,
                        "code": airport["code"],
                        "name": airport["name"],
                        "match_type": "airport"
                    })
    
    return results[:10]  # 返回前10个匹配结果