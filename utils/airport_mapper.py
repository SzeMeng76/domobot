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
        "secondary": ["XSP"], 
        "airports": [
            {"code": "SIN", "name": "新加坡樟宜机场", "name_en": "Singapore Changi Airport", "note": "世界顶级机场,东南亚枢纽"},
            {"code": "XSP", "name": "新加坡实里达机场", "name_en": "Singapore Seletar Airport", "note": "主要用于私人飞机和货运"}
        ]
    },
    "吉隆坡": {
        "primary": "KUL", 
        "secondary": ["SZB"], 
        "airports": [
            {"code": "KUL", "name": "吉隆坡国际机场", "name_en": "Kuala Lumpur International Airport", "note": "马来西亚主要国际机场"},
            {"code": "SZB", "name": "苏丹阿卜杜勒·阿齐兹·沙阿机场", "name_en": "Sultan Abdul Aziz Shah Airport", "note": "雪兰莪州梳邦机场"}
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
        "secondary": ["HLP"], 
        "airports": [
            {"code": "CGK", "name": "苏加诺-哈达国际机场", "name_en": "Soekarno–Hatta International Airport", "note": "印尼主要国际机场"},
            {"code": "HLP", "name": "哈利姆·珀丹库苏马国际机场", "name_en": "Halim Perdanakusuma International Airport", "note": "政府及商务航班"}
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
            {"code": "DPS", "name": "伍拉·赖国际机场", "name_en": "I Gusti Ngurah Rai International Airport", "note": "巴厘岛登巴萨机场"}
        ]
    },
    "泗水": {
        "primary": "SUB", 
        "secondary": [], 
        "airports": [
            {"code": "SUB", "name": "朱安达国际机场", "name_en": "Juanda International Airport", "note": "东爪哇主要机场"}
        ]
    },
    "日惹": {
        "primary": "YIA", 
        "secondary": [], 
        "airports": [
            {"code": "YIA", "name": "日惹国际机场", "name_en": "Yogyakarta International Airport", "note": "新建国际机场"}
        ]
    },
    "棉兰": {
        "primary": "KNO", 
        "secondary": [], 
        "airports": [
            {"code": "KNO", "name": "瓜拉纳穆国际机场", "name_en": "Kualanamu International Airport", "note": "苏门答腊北部机场"}
        ]
    },
    "巴厘巴板": {
        "primary": "BPN", 
        "secondary": [], 
        "airports": [
            {"code": "BPN", "name": "苏丹阿吉·穆罕默德·苏莱曼·塞平加国际机场", "name_en": "Sultan Aji Muhammad Sulaiman Sepinggan International Airport", "note": "东加里曼丹主要机场"}
        ]
    },
    "万鸦老": {
        "primary": "MDC", 
        "secondary": [], 
        "airports": [
            {"code": "MDC", "name": "萨姆·拉图兰吉国际机场", "name_en": "Sam Ratulangi International Airport", "note": "北苏拉威西主要机场"}
        ]
    },
    "望加锡": {
        "primary": "UPG", 
        "secondary": [], 
        "airports": [
            {"code": "UPG", "name": "苏丹哈桑努丁国际机场", "name_en": "Sultan Hasanuddin International Airport", "note": "南苏拉威西主要机场"}
        ]
    },
    "巨港": {
        "primary": "PLM", 
        "secondary": [], 
        "airports": [
            {"code": "PLM", "name": "苏丹马哈茂德·巴达鲁丁二世国际机场", "name_en": "Sultan Mahmud Badaruddin II International Airport", "note": "南苏门答腊主要机场"}
        ]
    },
    "巴淡": {
        "primary": "BTH", 
        "secondary": [], 
        "airports": [
            {"code": "BTH", "name": "韩那定国际机场", "name_en": "Hang Nadim International Airport", "note": "距新加坡很近"}
        ]
    },
    "北干巴鲁": {
        "primary": "PKU", 
        "secondary": [], 
        "airports": [
            {"code": "PKU", "name": "苏丹沙里夫·卡西姆二世国际机场", "name_en": "Sultan Syarif Kasim II International Airport", "note": "廖内省主要机场"}
        ]
    },
    "坤甸": {
        "primary": "PNK", 
        "secondary": [], 
        "airports": [
            {"code": "PNK", "name": "苏帕迪奥国际机场", "name_en": "Supadio International Airport", "note": "西加里曼丹主要机场"}
        ]
    },
    "班达亚齐": {
        "primary": "BTJ", 
        "secondary": [], 
        "airports": [
            {"code": "BTJ", "name": "苏丹伊斯坎达·穆达国际机场", "name_en": "Sultan Iskandar Muda International Airport", "note": "亚齐省主要机场"}
        ]
    },
    "马塔兰": {
        "primary": "LOP", 
        "secondary": [], 
        "airports": [
            {"code": "LOP", "name": "龙目岛国际机场", "name_en": "Lombok International Airport", "note": "西努沙登加拉主要机场"}
        ]
    },
    "三宝垄": {
        "primary": "SRG", 
        "secondary": [], 
        "airports": [
            {"code": "SRG", "name": "阿赫马德·亚尼将军国际机场", "name_en": "Jenderal Ahmad Yani International Airport", "note": "中爪哇主要机场"}
        ]
    },
    "班查马辛": {
        "primary": "BDJ", 
        "secondary": [], 
        "airports": [
            {"code": "BDJ", "name": "夏姆苏丁·努尔国际机场", "name_en": "Syamsudin Noor International Airport", "note": "南加里曼丹主要机场"}
        ]
    },
    "巴东": {
        "primary": "PDG", 
        "secondary": [], 
        "airports": [
            {"code": "PDG", "name": "米南卡堡国际机场", "name_en": "Minangkabau International Airport", "note": "西苏门答腊主要机场"}
        ]
    },
    "万隆": {
        "primary": "KJT", 
        "secondary": [], 
        "airports": [
            {"code": "KJT", "name": "卡尔塔查帝国际机场", "name_en": "Kertajati International Airport", "note": "西爪哇新建机场"}
        ]
    },
    "查雅普拉": {
        "primary": "DJJ", 
        "secondary": [], 
        "airports": [
            {"code": "DJJ", "name": "森塔尼国际机场", "name_en": "Sentani International Airport", "note": "巴布亚省主要机场"}
        ]
    },
    "拉布安巴焦": {
        "primary": "LBJ", 
        "secondary": [], 
        "airports": [
            {"code": "LBJ", "name": "科莫多国际机场", "name_en": "Komodo International Airport", "note": "科莫多岛旅游机场"}
        ]
    },
    "丹戎槟榔": {
        "primary": "TJQ", 
        "secondary": [], 
        "airports": [
            {"code": "TJQ", "name": "H.A.S.哈南朱丁国际机场", "name_en": "H.A.S. Hanandjoeddin International Airport", "note": "邦加岛主要机场"}
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
    "内比都": {
        "primary": "NYT", 
        "secondary": [], 
        "airports": [
            {"code": "NYT", "name": "内比都国际机场", "name_en": "Naypyidaw International Airport", "note": "缅甸首都机场"}
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
    "新山": {
        "primary": "JHB", 
        "secondary": [], 
        "airports": [
            {"code": "JHB", "name": "士乃国际机场", "name_en": "Senai International Airport", "note": "柔佛州主要机场，近新加坡"}
        ]
    },
    "怡保": {
        "primary": "IPH", 
        "secondary": [], 
        "airports": [
            {"code": "IPH", "name": "苏丹阿兹兰沙阿机场", "name_en": "Sultan Azlan Shah Airport", "note": "霹雳州主要机场"}
        ]
    },
    "哥打巴鲁": {
        "primary": "KBR", 
        "secondary": [], 
        "airports": [
            {"code": "KBR", "name": "苏丹依斯迈布特拉机场", "name_en": "Sultan Ismail Petra Airport", "note": "吉兰丹州主要机场"}
        ]
    },
    "瓜拉丁加奴": {
        "primary": "TGG", 
        "secondary": [], 
        "airports": [
            {"code": "TGG", "name": "苏丹马哈茂德机场", "name_en": "Sultan Mahmud Airport", "note": "丁加奴州主要机场"}
        ]
    },
    "关丹": {
        "primary": "KUA", 
        "secondary": [], 
        "airports": [
            {"code": "KUA", "name": "苏丹哈芝阿末沙阿机场", "name_en": "Sultan Haji Ahmad Shah Airport", "note": "彭亨州主要机场"}
        ]
    },
    "纳闽": {
        "primary": "LBU", 
        "secondary": [], 
        "airports": [
            {"code": "LBU", "name": "纳闽国际机场", "name_en": "Labuan International Airport", "note": "纳闽联邦直辖区机场"}
        ]
    },
    "亚罗士打": {
        "primary": "AOR", 
        "secondary": [], 
        "airports": [
            {"code": "AOR", "name": "苏丹阿卜杜勒·哈利姆机场", "name_en": "Sultan Abdul Halim Airport", "note": "吉打州主要机场"}
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
    "亚特兰大": {
        "primary": "ATL", 
        "secondary": [], 
        "airports": [
            {"code": "ATL", "name": "哈茨菲尔德-杰克逊亚特兰大国际机场", "name_en": "Hartsfield–Jackson Atlanta International Airport", "note": "世界最繁忙机场"}
        ]
    },
    "波士顿": {
        "primary": "BOS", 
        "secondary": [], 
        "airports": [
            {"code": "BOS", "name": "洛根国际机场", "name_en": "Logan International Airport", "note": "新英格兰地区枢纽"}
        ]
    },
    "达拉斯": {
        "primary": "DFW", 
        "secondary": ["DAL"], 
        "airports": [
            {"code": "DFW", "name": "达拉斯/沃思堡国际机场", "name_en": "Dallas/Fort Worth International Airport", "note": "美国航空枢纽"},
            {"code": "DAL", "name": "达拉斯爱田机场", "name_en": "Dallas Love Field", "note": "西南航空基地"}
        ]
    },
    "丹佛": {
        "primary": "DEN", 
        "secondary": [], 
        "airports": [
            {"code": "DEN", "name": "丹佛国际机场", "name_en": "Denver International Airport", "note": "美国面积最大机场"}
        ]
    },
    "底特律": {
        "primary": "DTW", 
        "secondary": [], 
        "airports": [
            {"code": "DTW", "name": "底特律都会韦恩县机场", "name_en": "Detroit Metropolitan Airport", "note": "达美航空枢纽"}
        ]
    },
    "休斯顿": {
        "primary": "IAH", 
        "secondary": ["HOU"], 
        "airports": [
            {"code": "IAH", "name": "乔治·布什洲际机场", "name_en": "George Bush Intercontinental Airport", "note": "联合航空枢纽"},
            {"code": "HOU", "name": "威廉·霍比机场", "name_en": "William P. Hobby Airport", "note": "西南航空基地"}
        ]
    },
    "拉斯维加斯": {
        "primary": "LAS", 
        "secondary": [], 
        "airports": [
            {"code": "LAS", "name": "哈里·里德国际机场", "name_en": "Harry Reid International Airport", "note": "娱乐之都门户"}
        ]
    },
    "明尼阿波利斯": {
        "primary": "MSP", 
        "secondary": [], 
        "airports": [
            {"code": "MSP", "name": "明尼阿波利斯-圣保罗国际机场", "name_en": "Minneapolis/St. Paul International Airport", "note": "达美航空枢纽"}
        ]
    },
    "奥兰多": {
        "primary": "MCO", 
        "secondary": [], 
        "airports": [
            {"code": "MCO", "name": "奥兰多国际机场", "name_en": "Orlando International Airport", "note": "迪士尼世界门户"}
        ]
    },
    "费城": {
        "primary": "PHL", 
        "secondary": [], 
        "airports": [
            {"code": "PHL", "name": "费城国际机场", "name_en": "Philadelphia International Airport", "note": "美国航空枢纽"}
        ]
    },
    "凤凰城": {
        "primary": "PHX", 
        "secondary": [], 
        "airports": [
            {"code": "PHX", "name": "凤凰城天港国际机场", "name_en": "Phoenix Sky Harbor International Airport", "note": "西南地区枢纽"}
        ]
    },
    "波特兰": {
        "primary": "PDX", 
        "secondary": [], 
        "airports": [
            {"code": "PDX", "name": "波特兰国际机场", "name_en": "Portland International Airport", "note": "俄勒冈州主要机场"}
        ]
    },
    "圣地亚哥": {
        "primary": "SAN", 
        "secondary": [], 
        "airports": [
            {"code": "SAN", "name": "圣地亚哥国际机场", "name_en": "San Diego International Airport", "note": "南加州重要机场"}
        ]
    },
    "圣安东尼奥": {
        "primary": "SAT", 
        "secondary": [], 
        "airports": [
            {"code": "SAT", "name": "圣安东尼奥国际机场", "name_en": "San Antonio International Airport", "note": "德州南部枢纽"}
        ]
    },
    "圣何塞": {
        "primary": "SJC", 
        "secondary": [], 
        "airports": [
            {"code": "SJC", "name": "圣何塞国际机场", "name_en": "San Jose International Airport", "note": "硅谷门户"}
        ]
    },
    "盐湖城": {
        "primary": "SLC", 
        "secondary": [], 
        "airports": [
            {"code": "SLC", "name": "盐湖城国际机场", "name_en": "Salt Lake City International Airport", "note": "达美航空枢纽"}
        ]
    },
    "圣路易斯": {
        "primary": "STL", 
        "secondary": [], 
        "airports": [
            {"code": "STL", "name": "圣路易斯兰伯特国际机场", "name_en": "St. Louis Lambert International Airport", "note": "中西部重要机场"}
        ]
    },
    "坦帕": {
        "primary": "TPA", 
        "secondary": [], 
        "airports": [
            {"code": "TPA", "name": "坦帕国际机场", "name_en": "Tampa International Airport", "note": "佛州西海岸枢纽"}
        ]
    },
    "安克雷奇": {
        "primary": "ANC", 
        "secondary": [], 
        "airports": [
            {"code": "ANC", "name": "安克雷奇国际机场", "name_en": "Anchorage International Airport", "note": "阿拉斯加最大机场"}
        ]
    },
    "火奴鲁鲁": {
        "primary": "HNL", 
        "secondary": [], 
        "airports": [
            {"code": "HNL", "name": "丹尼尔·井上国际机场", "name_en": "Daniel K. Inouye International Airport", "note": "夏威夷主要机场"}
        ]
    },
    "夏洛特": {
        "primary": "CLT", 
        "secondary": [], 
        "airports": [
            {"code": "CLT", "name": "夏洛特道格拉斯国际机场", "name_en": "Charlotte Douglas International Airport", "note": "美国航空枢纽"}
        ]
    },
    "纳什维尔": {
        "primary": "BNA", 
        "secondary": [], 
        "airports": [
            {"code": "BNA", "name": "纳什维尔国际机场", "name_en": "Nashville International Airport", "note": "音乐之城门户"}
        ]
    },
    "新奥尔良": {
        "primary": "MSY", 
        "secondary": [], 
        "airports": [
            {"code": "MSY", "name": "路易·阿姆斯特朗新奥尔良国际机场", "name_en": "Louis Armstrong New Orleans International Airport", "note": "爵士乐之都"}
        ]
    },
    "堪萨斯城": {
        "primary": "MCI", 
        "secondary": [], 
        "airports": [
            {"code": "MCI", "name": "堪萨斯城国际机场", "name_en": "Kansas City International Airport", "note": "中西部枢纽"}
        ]
    },
    "印第安纳波利斯": {
        "primary": "IND", 
        "secondary": [], 
        "airports": [
            {"code": "IND", "name": "印第安纳波利斯国际机场", "name_en": "Indianapolis International Airport", "note": "联邦快递枢纽"}
        ]
    },
    "哥伦布": {
        "primary": "CMH", 
        "secondary": [], 
        "airports": [
            {"code": "CMH", "name": "约翰·格伦哥伦布国际机场", "name_en": "John Glenn Columbus International Airport", "note": "俄亥俄州枢纽"}
        ]
    },
    "密尔沃基": {
        "primary": "MKE", 
        "secondary": [], 
        "airports": [
            {"code": "MKE", "name": "米切尔将军国际机场", "name_en": "General Mitchell International Airport", "note": "威斯康星州主要机场"}
        ]
    },
    "俄克拉荷马城": {
        "primary": "OKC", 
        "secondary": [], 
        "airports": [
            {"code": "OKC", "name": "威尔·罗杰斯世界机场", "name_en": "Will Rogers World Airport", "note": "俄克拉荷马州枢纽"}
        ]
    },
    "孟菲斯": {
        "primary": "MEM", 
        "secondary": [], 
        "airports": [
            {"code": "MEM", "name": "孟菲斯国际机场", "name_en": "Memphis International Airport", "note": "联邦快递全球枢纽"}
        ]
    },
    "路易维尔": {
        "primary": "SDF", 
        "secondary": [], 
        "airports": [
            {"code": "SDF", "name": "路易维尔国际机场", "name_en": "Louisville International Airport", "note": "UPS全球枢纽"}
        ]
    },
    "里诺": {
        "primary": "RNO", 
        "secondary": [], 
        "airports": [
            {"code": "RNO", "name": "里诺-塔霍国际机场", "name_en": "Reno–Tahoe International Airport", "note": "内华达州北部机场"}
        ]
    },
    "奥马哈": {
        "primary": "OMA", 
        "secondary": [], 
        "airports": [
            {"code": "OMA", "name": "埃普利机场", "name_en": "Eppley Airfield", "note": "内布拉斯加州枢纽"}
        ]
    },
    "阿尔伯克基": {
        "primary": "ABQ", 
        "secondary": [], 
        "airports": [
            {"code": "ABQ", "name": "阿尔伯克基国际太阳港", "name_en": "Albuquerque International Sunport", "note": "新墨西哥州枢纽"}
        ]
    },
    "图森": {
        "primary": "TUS", 
        "secondary": [], 
        "airports": [
            {"code": "TUS", "name": "图森国际机场", "name_en": "Tucson International Airport", "note": "南亚利桑那机场"}
        ]
    },
    "杰克逊维尔": {
        "primary": "JAX", 
        "secondary": [], 
        "airports": [
            {"code": "JAX", "name": "杰克逊维尔国际机场", "name_en": "Jacksonville International Airport", "note": "佛州东北部机场"}
        ]
    },
    "奥克兰": {
        "primary": "OAK", 
        "secondary": [], 
        "airports": [
            {"code": "OAK", "name": "奥克兰国际机场", "name_en": "Oakland International Airport", "note": "湾区廉价航空基地"}
        ]
    },
    "巴尔的摩": {
        "primary": "BWI", 
        "secondary": [], 
        "airports": [
            {"code": "BWI", "name": "巴尔的摩/华盛顿国际机场", "name_en": "Baltimore/Washington International Airport", "note": "华盛顿地区第三机场"}
        ]
    },
    "罗利": {
        "primary": "RDU", 
        "secondary": [], 
        "airports": [
            {"code": "RDU", "name": "罗利-达勒姆国际机场", "name_en": "Raleigh–Durham International Airport", "note": "北卡州主要机场"}
        ]
    },
    "辛辛那提": {
        "primary": "CVG", 
        "secondary": [], 
        "airports": [
            {"code": "CVG", "name": "辛辛那提/北肯塔基国际机场", "name_en": "Cincinnati/Northern Kentucky International Airport", "note": "达美航空枢纽"}
        ]
    },
    "克利夫兰": {
        "primary": "CLE", 
        "secondary": [], 
        "airports": [
            {"code": "CLE", "name": "克利夫兰霍普金斯国际机场", "name_en": "Cleveland Hopkins International Airport", "note": "俄亥俄州北部机场"}
        ]
    },
    "匹兹堡": {
        "primary": "PIT", 
        "secondary": [], 
        "airports": [
            {"code": "PIT", "name": "匹兹堡国际机场", "name_en": "Pittsburgh International Airport", "note": "宾州西部枢纽"}
        ]
    },
    "伯明翰": {
        "primary": "BHM", 
        "secondary": [], 
        "airports": [
            {"code": "BHM", "name": "伯明翰-沙特尔沃思国际机场", "name_en": "Birmingham–Shuttlesworth International Airport", "note": "阿拉巴马州主要机场"}
        ]
    },
    "小石城": {
        "primary": "LIT", 
        "secondary": [], 
        "airports": [
            {"code": "LIT", "name": "比尔和希拉里·克林顿国家机场", "name_en": "Bill and Hillary Clinton National Airport", "note": "阿肯色州主要机场"}
        ]
    },
    "里奇蒙": {
        "primary": "RIC", 
        "secondary": [], 
        "airports": [
            {"code": "RIC", "name": "里奇蒙国际机场", "name_en": "Richmond International Airport", "note": "弗吉尼亚州枢纽"}
        ]
    },
    "诺福克": {
        "primary": "ORF", 
        "secondary": [], 
        "airports": [
            {"code": "ORF", "name": "诺福克国际机场", "name_en": "Norfolk International Airport", "note": "弗州沿海机场"}
        ]
    },
    "萨凡纳": {
        "primary": "SAV", 
        "secondary": [], 
        "airports": [
            {"code": "SAV", "name": "萨凡纳/希尔顿海德国际机场", "name_en": "Savannah/Hilton Head International Airport", "note": "乔治亚州沿海机场"}
        ]
    },
    "大急流城": {
        "primary": "GRR", 
        "secondary": [], 
        "airports": [
            {"code": "GRR", "name": "杰拉尔德·福特国际机场", "name_en": "Gerald R. Ford International Airport", "note": "密歇根州西部机场"}
        ]
    },
    "博伊西": {
        "primary": "BOI", 
        "secondary": [], 
        "airports": [
            {"code": "BOI", "name": "博伊西机场", "name_en": "Boise Airport", "note": "爱达荷州主要机场"}
        ]
    },
    "塔尔萨": {
        "primary": "TUL", 
        "secondary": [], 
        "airports": [
            {"code": "TUL", "name": "塔尔萨国际机场", "name_en": "Tulsa International Airport", "note": "俄克拉荷马州第二大机场"}
        ]
    },
    "萨克拉门托": {
        "primary": "SMF", 
        "secondary": [], 
        "airports": [
            {"code": "SMF", "name": "萨克拉门托国际机场", "name_en": "Sacramento International Airport", "note": "加州首府机场"}
        ]
    },
    "弗雷斯诺": {
        "primary": "FAT", 
        "secondary": [], 
        "airports": [
            {"code": "FAT", "name": "弗雷斯诺优胜美地国际机场", "name_en": "Fresno Yosemite International Airport", "note": "加州中央谷地机场"}
        ]
    },
    "奥尔巴尼": {
        "primary": "ALB", 
        "secondary": [], 
        "airports": [
            {"code": "ALB", "name": "奥尔巴尼国际机场", "name_en": "Albany International Airport", "note": "纽约州首府机场"}
        ]
    },
    "罗切斯特": {
        "primary": "ROC", 
        "secondary": [], 
        "airports": [
            {"code": "ROC", "name": "大罗切斯特国际机场", "name_en": "Greater Rochester International Airport", "note": "纽约州西部机场"}
        ]
    },
    "锡拉丘兹": {
        "primary": "SYR", 
        "secondary": [], 
        "airports": [
            {"code": "SYR", "name": "锡拉丘兹汉考克国际机场", "name_en": "Syracuse Hancock International Airport", "note": "纽约州中部机场"}
        ]
    },
    "布法罗": {
        "primary": "BUF", 
        "secondary": [], 
        "airports": [
            {"code": "BUF", "name": "布法罗尼亚加拉国际机场", "name_en": "Buffalo Niagara International Airport", "note": "尼亚加拉大瀑布门户"}
        ]
    },
    "哈特福德": {
        "primary": "BDL", 
        "secondary": [], 
        "airports": [
            {"code": "BDL", "name": "布拉德利国际机场", "name_en": "Bradley International Airport", "note": "康涅狄格州主要机场"}
        ]
    },
    "普罗维登斯": {
        "primary": "PVD", 
        "secondary": [], 
        "airports": [
            {"code": "PVD", "name": "罗德岛T.F.格林国际机场", "name_en": "Rhode Island T. F. Green International Airport", "note": "罗德岛机场"}
        ]
    },
    "南卡查尔斯顿": {
        "primary": "CHS", 
        "secondary": [], 
        "airports": [
            {"code": "CHS", "name": "查尔斯顿国际机场", "name_en": "Charleston International Airport", "note": "南卡沿海机场"}
        ]
    },
    "哥伦比亚": {
        "primary": "CAE", 
        "secondary": [], 
        "airports": [
            {"code": "CAE", "name": "哥伦比亚都会机场", "name_en": "Columbia Metropolitan Airport", "note": "南卡州首府机场"}
        ]
    },
    "绿湾": {
        "primary": "GRB", 
        "secondary": [], 
        "airports": [
            {"code": "GRB", "name": "绿湾-奥斯汀·斯特劳贝尔国际机场", "name_en": "Green Bay–Austin Straubel International Airport", "note": "威州东北部机场"}
        ]
    },
    "麦迪逊": {
        "primary": "MSN", 
        "secondary": [], 
        "airports": [
            {"code": "MSN", "name": "戴恩县地区机场", "name_en": "Dane County Regional Airport", "note": "威州首府机场"}
        ]
    },
    "得梅因": {
        "primary": "DSM", 
        "secondary": [], 
        "airports": [
            {"code": "DSM", "name": "得梅因国际机场", "name_en": "Des Moines International Airport", "note": "爱荷华州主要机场"}
        ]
    },
    "斯波坎": {
        "primary": "GEG", 
        "secondary": [], 
        "airports": [
            {"code": "GEG", "name": "斯波坎国际机场", "name_en": "Spokane International Airport", "note": "华盛顿州东部机场"}
        ]
    },
    "班戈": {
        "primary": "BGR", 
        "secondary": [], 
        "airports": [
            {"code": "BGR", "name": "班戈国际机场", "name_en": "Bangor International Airport", "note": "缅因州东部机场"}
        ]
    },
    "基韦斯特": {
        "primary": "EYW", 
        "secondary": [], 
        "airports": [
            {"code": "EYW", "name": "基韦斯特国际机场", "name_en": "Key West International Airport", "note": "佛州最南端机场"}
        ]
    },
    "达顿": {
        "primary": "DAY", 
        "secondary": [], 
        "airports": [
            {"code": "DAY", "name": "代顿国际机场", "name_en": "Dayton International Airport", "note": "俄亥俄州西南机场"}
        ]
    },
    "诺克斯维尔": {
        "primary": "TYS", 
        "secondary": [], 
        "airports": [
            {"code": "TYS", "name": "麦吉·泰森机场", "name_en": "McGhee Tyson Airport", "note": "田纳西州东部机场"}
        ]
    },
    "格林斯伯勒": {
        "primary": "GSO", 
        "secondary": [], 
        "airports": [
            {"code": "GSO", "name": "皮埃蒙特三合会国际机场", "name_en": "Piedmont Triad International Airport", "note": "北卡州中部机场"}
        ]
    },
    "格林维尔": {
        "primary": "GSP", 
        "secondary": [], 
        "airports": [
            {"code": "GSP", "name": "格林维尔-斯帕坦堡国际机场", "name_en": "Greenville-Spartanburg International Airport", "note": "南卡州北部机场"}
        ]
    },
    "塔拉哈西": {
        "primary": "TLH", 
        "secondary": [], 
        "airports": [
            {"code": "TLH", "name": "塔拉哈西国际机场", "name_en": "Tallahassee International Airport", "note": "佛州首府机场"}
        ]
    },
    "彭萨科拉": {
        "primary": "PNS", 
        "secondary": [], 
        "airports": [
            {"code": "PNS", "name": "彭萨科拉国际机场", "name_en": "Pensacola International Airport", "note": "佛州西北部机场"}
        ]
    },
    "萨拉索塔": {
        "primary": "SRQ", 
        "secondary": [], 
        "airports": [
            {"code": "SRQ", "name": "萨拉索塔-布雷登顿国际机场", "name_en": "Sarasota–Bradenton International Airport", "note": "佛州西海岸机场"}
        ]
    },
    "罗德岱尔堡": {
        "primary": "FLL", 
        "secondary": [], 
        "airports": [
            {"code": "FLL", "name": "劳德代尔堡-好莱坞国际机场", "name_en": "Fort Lauderdale–Hollywood International Airport", "note": "南佛州第二大机场"}
        ]
    },
    "西棕榈滩": {
        "primary": "PBI", 
        "secondary": [], 
        "airports": [
            {"code": "PBI", "name": "棕榈滩国际机场", "name_en": "Palm Beach International Airport", "note": "南佛州机场"}
        ]
    },
    "迈尔斯堡": {
        "primary": "RSW", 
        "secondary": [], 
        "airports": [
            {"code": "RSW", "name": "西南佛罗里达国际机场", "name_en": "Southwest Florida International Airport", "note": "佛州西南部机场"}
        ]
    },
    "亨茨维尔": {
        "primary": "HSV", 
        "secondary": [], 
        "airports": [
            {"code": "HSV", "name": "亨茨维尔国际机场", "name_en": "Huntsville International Airport", "note": "阿拉巴马州北部机场"}
        ]
    },
    "杰克逊": {
        "primary": "JAN", 
        "secondary": [], 
        "airports": [
            {"code": "JAN", "name": "杰克逊-梅德加·威利·埃弗斯国际机场", "name_en": "Jackson–Medgar Wiley Evers International Airport", "note": "密西西比州首府机场"}
        ]
    },
    "哈里斯堡": {
        "primary": "MDT", 
        "secondary": [], 
        "airports": [
            {"code": "MDT", "name": "哈里斯堡国际机场", "name_en": "Harrisburg International Airport", "note": "宾州首府机场"}
        ]
    },
    "艾瑞": {
        "primary": "ERI", 
        "secondary": [], 
        "airports": [
            {"code": "ERI", "name": "艾瑞国际机场", "name_en": "Erie International Airport", "note": "宾州西北机场"}
        ]
    },
    "德卢斯": {
        "primary": "DLH", 
        "secondary": [], 
        "airports": [
            {"code": "DLH", "name": "德卢斯国际机场", "name_en": "Duluth International Airport", "note": "明尼苏达州北部机场"}
        ]
    },
    "兰辛": {
        "primary": "LAN", 
        "secondary": [], 
        "airports": [
            {"code": "LAN", "name": "首府地区国际机场", "name_en": "Capital Region International Airport", "note": "密歇根州首府机场"}
        ]
    },
    "费尔班克斯": {
        "primary": "FAI", 
        "secondary": [], 
        "airports": [
            {"code": "FAI", "name": "费尔班克斯国际机场", "name_en": "Fairbanks International Airport", "note": "阿拉斯加内陆机场"}
        ]
    },
    "朱诺": {
        "primary": "JNU", 
        "secondary": [], 
        "airports": [
            {"code": "JNU", "name": "朱诺国际机场", "name_en": "Juneau International Airport", "note": "阿拉斯加州首府机场"}
        ]
    },
    "科纳": {
        "primary": "KOA", 
        "secondary": [], 
        "airports": [
            {"code": "KOA", "name": "科纳国际机场", "name_en": "Kona International Airport", "note": "夏威夷大岛西部机场"}
        ]
    },
    "希洛": {
        "primary": "ITO", 
        "secondary": [], 
        "airports": [
            {"code": "ITO", "name": "希洛国际机场", "name_en": "Hilo International Airport", "note": "夏威夷大岛东部机场"}
        ]
    },
    "埃尔帕索": {
        "primary": "ELP", 
        "secondary": [], 
        "airports": [
            {"code": "ELP", "name": "埃尔帕索国际机场", "name_en": "El Paso International Airport", "note": "德州西部机场"}
        ]
    },
    "阿马里洛": {
        "primary": "AMA", 
        "secondary": [], 
        "airports": [
            {"code": "AMA", "name": "里克·赫斯班德阿马里洛国际机场", "name_en": "Rick Husband Amarillo International Airport", "note": "德州北部机场"}
        ]
    },
    "科珀斯克里斯蒂": {
        "primary": "CRP", 
        "secondary": [], 
        "airports": [
            {"code": "CRP", "name": "科珀斯克里斯蒂国际机场", "name_en": "Corpus Christi International Airport", "note": "德州沿海机场"}
        ]
    },
    "拉伯克": {
        "primary": "LBB", 
        "secondary": [], 
        "airports": [
            {"code": "LBB", "name": "拉伯克普雷斯顿·史密斯国际机场", "name_en": "Lubbock Preston Smith International Airport", "note": "德州北部平原机场"}
        ]
    },
    "棕榈泉": {
        "primary": "PSP", 
        "secondary": [], 
        "airports": [
            {"code": "PSP", "name": "棕榈泉国际机场", "name_en": "Palm Springs International Airport", "note": "加州沙漠度假区机场"}
        ]
    },
    "安大略": {
        "primary": "ONT", 
        "secondary": [], 
        "airports": [
            {"code": "ONT", "name": "安大略国际机场", "name_en": "Ontario International Airport", "note": "大洛杉矶地区机场"}
        ]
    },
    "橙县": {
        "primary": "SNA", 
        "secondary": [], 
        "airports": [
            {"code": "SNA", "name": "约翰·韦恩机场", "name_en": "John Wayne Airport", "note": "橙县机场"}
        ]
    },
    "伯班克": {
        "primary": "BUR", 
        "secondary": [], 
        "airports": [
            {"code": "BUR", "name": "好莱坞伯班克机场", "name_en": "Hollywood Burbank Airport", "note": "洛杉矶北部机场"}
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
    # 新增印度尼西亚城市
    "balikpapan": "巴厘巴板",
    "manado": "万鸦老",
    "makassar": "望加锡", 
    "ujung pandang": "望加锡",  # 别名
    "palembang": "巨港",
    "batam": "巴淡",
    "pekanbaru": "北干巴鲁",
    "pontianak": "坤甸",
    "banda aceh": "班达亚齐",
    "mataram": "马塔兰",
    "semarang": "三宝垄", 
    "banjarmasin": "班查马辛",
    "padang": "巴东",
    "bandung": "万隆",
    "jayapura": "查雅普拉",
    "labuan bajo": "拉布安巴焦",
    "tanjungpandan": "丹戎槟榔",
    "cebu": "宿务",
    "davao": "达沃",
    "yangon": "仰光",
    "mandalay": "曼德勒",
    "nay pyi taw": "内比都",
    "naypyidaw": "内比都",  # 别名
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
    # 新增马来西亚城市
    "johor bahru": "新山",
    "johor": "新山",  # 别名
    "ipoh": "怡保",
    "kota bharu": "哥打巴鲁",
    "kota baru": "哥打巴鲁",  # 别名
    "kuala terengganu": "瓜拉丁加奴",
    "terengganu": "瓜拉丁加奴",  # 简称
    "kuantan": "关丹",
    "labuan": "纳闽",
    "alor setar": "亚罗士打",
    "alor star": "亚罗士打",  # 别名
    
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
    
    # 美国城市
    "new york": "纽约",
    "los angeles": "洛杉矶", 
    "san francisco": "旧金山",
    "chicago": "芝加哥",
    "seattle": "西雅图",
    "washington": "华盛顿",
    "washington dc": "华盛顿",
    "miami": "迈阿密",
    "atlanta": "亚特兰大",
    "boston": "波士顿",
    "dallas": "达拉斯",
    "denver": "丹佛",
    "detroit": "底特律",
    "houston": "休斯顿",
    "las vegas": "拉斯维加斯",
    "minneapolis": "明尼阿波利斯",
    "orlando": "奥兰多",
    "philadelphia": "费城",
    "phoenix": "凤凰城",
    "portland": "波特兰",
    "san diego": "圣地亚哥",
    "san antonio": "圣安东尼奥",
    "san jose": "圣何塞",
    "salt lake city": "盐湖城",
    "st louis": "圣路易斯",
    "saint louis": "圣路易斯",
    "tampa": "坦帕",
    "anchorage": "安克雷奇",
    "honolulu": "火奴鲁鲁",
    "charlotte": "夏洛特",
    "nashville": "纳什维尔",
    "new orleans": "新奥尔良",
    "kansas city": "堪萨斯城",
    "indianapolis": "印第安纳波利斯",
    "columbus": "哥伦布",
    "milwaukee": "密尔沃基",
    "oklahoma city": "俄克拉荷马城",
    "memphis": "孟菲斯",
    "louisville": "路易维尔",
    "reno": "里诺",
    "omaha": "奥马哈",
    "albuquerque": "阿尔伯克基",
    "tucson": "图森",
    "jacksonville": "杰克逊维尔",
    "oakland": "奥克兰",
    "baltimore": "巴尔的摩",
    "raleigh": "罗利",
    "cincinnati": "辛辛那提",
    "cleveland": "克利夫兰",
    "pittsburgh": "匹兹堡",
    "birmingham": "伯明翰",
    "little rock": "小石城",
    "richmond": "里奇蒙",
    "norfolk": "诺福克",
    "savannah": "萨凡纳",
    "grand rapids": "大急流城",
    "boise": "博伊西",
    "tulsa": "塔尔萨",
    "sacramento": "萨克拉门托",
    "fresno": "弗雷斯诺",
    "albany": "奥尔巴尼",
    "rochester": "罗切斯特",
    "syracuse": "锡拉丘兹",
    "buffalo": "布法罗",
    "hartford": "哈特福德",
    "providence": "普罗维登斯",
    "charleston": "南卡查尔斯顿",
    "columbia": "哥伦比亚",
    "green bay": "绿湾",
    "madison": "麦迪逊",
    "des moines": "得梅因",
    "spokane": "斯波坎",
    "bangor": "班戈",
    "key west": "基韦斯特",
    "dayton": "达顿",
    "knoxville": "诺克斯维尔",
    "greensboro": "格林斯伯勒",
    "greenville": "格林维尔",
    "tallahassee": "塔拉哈西",
    "pensacola": "彭萨科拉",
    "sarasota": "萨拉索塔",
    "fort lauderdale": "罗德岱尔堡",
    "west palm beach": "西棕榈滩",
    "fort myers": "迈尔斯堡",
    "huntsville": "亨茨维尔",
    "jackson": "杰克逊",
    "harrisburg": "哈里斯堡",
    "erie": "艾瑞",
    "duluth": "德卢斯",
    "lansing": "兰辛",
    "fairbanks": "费尔班克斯",
    "juneau": "朱诺",
    "kona": "科纳",
    "hilo": "希洛",
    "el paso": "埃尔帕索",
    "amarillo": "阿马里洛",
    "corpus christi": "科珀斯克里斯蒂",
    "lubbock": "拉伯克",
    "palm springs": "棕榈泉",
    "ontario": "安大略",
    "orange county": "橙县",
    "burbank": "伯班克",
    
    # 加拿大和其他地区
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
    "内比都市": "内比都",
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
        "马来西亚": ["吉隆坡", "槟城", "兰卡威", "亚庇", "古晋", "新山", "怡保", "哥打巴鲁", "瓜拉丁加奴", "关丹", "纳闽", "亚罗士打"],
        "印度尼西亚": ["雅加达", "巴厘岛", "泗水", "日惹", "棉兰", "巴厘巴板", "万鸦老", "望加锡", "巨港", "巴淡", "北干巴鲁", "坤甸", "班达亚齐", "马塔兰", "三宝垄", "班查马辛", "巴东", "万隆", "查雅普拉", "拉布安巴焦", "丹戎槟榔"],
        "菲律宾": ["马尼拉", "宿务", "达沃", "卡加延德奥罗"],
        "越南": ["胡志明市", "河内"],
        "缅甸": ["仰光", "曼德勒", "内比都"],
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
        "美国": ["纽约", "洛杉矶", "旧金山", "芝加哥", "西雅图", "华盛顿", "迈阿密", "亚特兰大", "波士顿", "达拉斯", 
               "丹佛", "底特律", "休斯顿", "拉斯维加斯", "明尼阿波利斯", "奥兰多", "费城", "凤凰城", "波特兰", 
               "圣地亚哥", "圣安东尼奥", "圣何塞", "盐湖城", "圣路易斯", "坦帕", "安克雷奇", "火奴鲁鲁", "夏洛特", 
               "纳什维尔", "新奥尔良", "堪萨斯城", "印第安纳波利斯", "哥伦布", "密尔沃基", "俄克拉荷马城", "孟菲斯", 
               "路易维尔", "里诺", "奥马哈", "阿尔伯克基", "图森", "杰克逊维尔", "奥克兰", "巴尔的摩", "罗利", 
               "辛辛那提", "克利夫兰", "匹兹堡", "伯明翰", "小石城", "里奇蒙", "诺福克", "萨凡纳", "大急流城", 
               "博伊西", "塔尔萨", "萨克拉门托", "弗雷斯诺", "奥尔巴尼", "罗切斯特", "锡拉丘兹", "布法罗", 
               "哈特福德", "普罗维登斯", "南卡查尔斯顿", "哥伦比亚", "绿湾", "麦迪逊", "得梅因", "斯波坎", 
               "班戈", "基韦斯特", "达顿", "诺克斯维尔", "格林斯伯勒", "格林维尔", "塔拉哈西", "彭萨科拉", 
               "萨拉索塔", "罗德岱尔堡", "西棕榈滩", "迈尔斯堡", "亨茨维尔", "杰克逊", "哈里斯堡", "艾瑞", 
               "德卢斯", "兰辛", "费尔班克斯", "朱诺", "科纳", "希洛", "埃尔帕索", "阿马里洛", "科珀斯克里斯蒂", 
               "拉伯克", "棕榈泉", "安大略", "橙县", "伯班克"],
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