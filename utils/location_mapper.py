"""
酒店位置映射工具
基于 airport_mapper.py 架构，提供智能位置解析和城市到酒店搜索区域的映射
主要用于优化用户输入体验，将自然语言输入转换为Google Hotels API可用的位置查询
"""

import re
from typing import Dict, List, Tuple, Optional
from .country_data import SUPPORTED_COUNTRIES, get_country_flag

# 主要城市位置映射 - 重点支持常用旅游目的地
MAJOR_CITIES_LOCATIONS = {
    # 中国大陆主要城市
    "北京": {
        "primary": "北京",
        "aliases": ["Beijing", "Peking"],
        "areas": [
            {"name": "北京市区", "query": "Beijing, China", "type": "city", "note": "包含王府井、三里屯、国贸等主要区域"},
            {"name": "北京首都机场", "query": "Beijing Capital Airport, China", "type": "airport", "note": "机场及周边酒店"},
            {"name": "北京大兴机场", "query": "Beijing Daxing Airport, China", "type": "airport", "note": "新机场及周边酒店"},
            {"name": "天安门广场", "query": "Tiananmen Square, Beijing", "type": "landmark", "note": "市中心核心区域"},
            {"name": "故宫", "query": "Forbidden City, Beijing", "type": "landmark", "note": "历史文化区域"},
            {"name": "三里屯", "query": "Sanlitun, Beijing", "type": "district", "note": "夜生活和购物区域"},
            {"name": "王府井", "query": "Wangfujing, Beijing", "type": "district", "note": "商业购物区域"},
            {"name": "国贸", "query": "Guomao, Beijing", "type": "business", "note": "商务区"}
        ]
    },
    "上海": {
        "primary": "上海",
        "aliases": ["Shanghai"],
        "areas": [
            {"name": "上海市区", "query": "Shanghai, China", "type": "city", "note": "包含外滩、陆家嘴、淮海路等主要区域"},
            {"name": "外滩", "query": "The Bund, Shanghai", "type": "landmark", "note": "历史建筑群和黄浦江景"},
            {"name": "陆家嘴", "query": "Lujiazui, Shanghai", "type": "business", "note": "金融中心和摩天大楼"},
            {"name": "淮海路", "query": "Huaihai Road, Shanghai", "type": "district", "note": "高端购物区域"},
            {"name": "新天地", "query": "Xintiandi, Shanghai", "type": "district", "note": "时尚休闲区域"},
            {"name": "浦东机场", "query": "Shanghai Pudong Airport, China", "type": "airport", "note": "国际机场及周边"},
            {"name": "虹桥机场", "query": "Shanghai Hongqiao Airport, China", "type": "airport", "note": "国内机场及周边"},
            {"name": "迪士尼度假区", "query": "Shanghai Disneyland, China", "type": "attraction", "note": "主题公园区域"}
        ]
    },
    "广州": {
        "primary": "广州",
        "aliases": ["Guangzhou", "Canton"],
        "areas": [
            {"name": "广州市区", "query": "Guangzhou, China", "type": "city", "note": "包含天河、越秀、荔湾等主要区域"},
            {"name": "天河区", "query": "Tianhe District, Guangzhou", "type": "district", "note": "商务和购物中心"},
            {"name": "珠江新城", "query": "Zhujiang New Town, Guangzhou", "type": "business", "note": "CBD商务区"},
            {"name": "上下九步行街", "query": "Shangxiajiu Pedestrian Street, Guangzhou", "type": "district", "note": "传统商业街区"},
            {"name": "白云机场", "query": "Guangzhou Baiyun Airport, China", "type": "airport", "note": "国际机场及周边"},
            {"name": "长隆旅游度假区", "query": "Chimelong Tourist Resort, Guangzhou", "type": "attraction", "note": "主题公园区域"}
        ]
    },
    "深圳": {
        "primary": "深圳",
        "aliases": ["Shenzhen"],
        "areas": [
            {"name": "深圳市区", "query": "Shenzhen, China", "type": "city", "note": "包含南山、福田、罗湖等主要区域"},
            {"name": "南山区", "query": "Nanshan District, Shenzhen", "type": "district", "note": "科技园和海滨区域"},
            {"name": "福田区", "query": "Futian District, Shenzhen", "type": "district", "note": "商务和购物中心"},
            {"name": "罗湖区", "query": "Luohu District, Shenzhen", "type": "district", "note": "传统商业区和口岸"},
            {"name": "宝安机场", "query": "Shenzhen Bao'an Airport, China", "type": "airport", "note": "国际机场及周边"},
            {"name": "深圳湾", "query": "Shenzhen Bay, China", "type": "landmark", "note": "海滨和公园区域"}
        ]
    },
    
    # 香港澳门台湾
    "香港": {
        "primary": "香港",
        "aliases": ["Hong Kong", "HK"],
        "areas": [
            {"name": "香港岛", "query": "Hong Kong Island, Hong Kong", "type": "district", "note": "中环、铜锣湾、湾仔等核心区域"},
            {"name": "九龙", "query": "Kowloon, Hong Kong", "type": "district", "note": "尖沙咀、旺角、油麻地等区域"},
            {"name": "新界", "query": "New Territories, Hong Kong", "type": "district", "note": "较远郊区，价格相对便宜"},
            {"name": "中环", "query": "Central, Hong Kong", "type": "business", "note": "商务金融中心"},
            {"name": "尖沙咀", "query": "Tsim Sha Tsui, Hong Kong", "type": "district", "note": "购物和观光核心区"},
            {"name": "铜锣湾", "query": "Causeway Bay, Hong Kong", "type": "district", "note": "购物和娱乐区域"},
            {"name": "香港机场", "query": "Hong Kong International Airport", "type": "airport", "note": "国际机场及周边"},
            {"name": "迪士尼乐园", "query": "Hong Kong Disneyland", "type": "attraction", "note": "主题公园区域"}
        ]
    },
    "澳门": {
        "primary": "澳门",
        "aliases": ["Macau", "Macao"],
        "areas": [
            {"name": "澳门半岛", "query": "Macau Peninsula, Macau", "type": "district", "note": "历史城区和赌场区域"},
            {"name": "氹仔", "query": "Taipa, Macau", "type": "district", "note": "威尼斯人、银河等大型度假村"},
            {"name": "路氹城", "query": "Cotai, Macau", "type": "district", "note": "新兴娱乐和度假区"},
            {"name": "澳门机场", "query": "Macau International Airport", "type": "airport", "note": "国际机场及周边"},
            {"name": "大三巴", "query": "Ruins of St. Paul's, Macau", "type": "landmark", "note": "历史文化区域"}
        ]
    },
    "台北": {
        "primary": "台北",
        "aliases": ["Taipei"],
        "areas": [
            {"name": "台北市区", "query": "Taipei, Taiwan", "type": "city", "note": "包含信义、大安、中山等主要区域"},
            {"name": "信义区", "query": "Xinyi District, Taipei", "type": "district", "note": "101大楼和商务区"},
            {"name": "西门町", "query": "Ximending, Taipei", "type": "district", "note": "年轻人聚集的购物娱乐区"},
            {"name": "士林夜市", "query": "Shilin Night Market, Taipei", "type": "landmark", "note": "著名夜市区域"},
            {"name": "桃园机场", "query": "Taiwan Taoyuan International Airport", "type": "airport", "note": "主要国际机场"},
            {"name": "松山机场", "query": "Taipei Songshan Airport", "type": "airport", "note": "市区机场"}
        ]
    },
    
    # 日本主要城市
    "东京": {
        "primary": "东京",
        "aliases": ["Tokyo"],
        "areas": [
            {"name": "东京市区", "query": "Tokyo, Japan", "type": "city", "note": "包含新宿、涩谷、银座等主要区域"},
            {"name": "新宿", "query": "Shinjuku, Tokyo", "type": "district", "note": "商务和娱乐中心"},
            {"name": "涩谷", "query": "Shibuya, Tokyo", "type": "district", "note": "年轻人聚集地和购物区"},
            {"name": "银座", "query": "Ginza, Tokyo", "type": "district", "note": "高端购物和餐饮区"},
            {"name": "浅草", "query": "Asakusa, Tokyo", "type": "district", "note": "传统文化区域"},
            {"name": "秋叶原", "query": "Akihabara, Tokyo", "type": "district", "note": "电子产品和动漫文化区"},
            {"name": "成田机场", "query": "Narita International Airport, Tokyo", "type": "airport", "note": "主要国际机场"},
            {"name": "羽田机场", "query": "Haneda Airport, Tokyo", "type": "airport", "note": "国内机场，距市区近"},
            {"name": "迪士尼度假区", "query": "Tokyo Disney Resort, Japan", "type": "attraction", "note": "主题公园区域"}
        ]
    },
    "大阪": {
        "primary": "大阪",
        "aliases": ["Osaka"],
        "areas": [
            {"name": "大阪市区", "query": "Osaka, Japan", "type": "city", "note": "包含梅田、难波、心斋桥等主要区域"},
            {"name": "梅田", "query": "Umeda, Osaka", "type": "district", "note": "商务和购物中心"},
            {"name": "难波", "query": "Namba, Osaka", "type": "district", "note": "娱乐和美食区域"},
            {"name": "心斋桥", "query": "Shinsaibashi, Osaka", "type": "district", "note": "购物和餐饮街区"},
            {"name": "关西机场", "query": "Kansai International Airport, Osaka", "type": "airport", "note": "国际机场"},
            {"name": "环球影城", "query": "Universal Studios Japan, Osaka", "type": "attraction", "note": "主题公园区域"}
        ]
    },
    
    # 韩国主要城市
    "首尔": {
        "primary": "首尔",
        "aliases": ["Seoul"],
        "areas": [
            {"name": "首尔市区", "query": "Seoul, South Korea", "type": "city", "note": "包含江南、明洞、东大门等主要区域"},
            {"name": "江南区", "query": "Gangnam, Seoul", "type": "district", "note": "高端商务和娱乐区"},
            {"name": "明洞", "query": "Myeongdong, Seoul", "type": "district", "note": "购物和美食街区"},
            {"name": "东大门", "query": "Dongdaemun, Seoul", "type": "district", "note": "24小时购物区"},
            {"name": "弘大", "query": "Hongdae, Seoul", "type": "district", "note": "大学区和夜生活区"},
            {"name": "仁川机场", "query": "Incheon International Airport, Seoul", "type": "airport", "note": "主要国际机场"},
            {"name": "金浦机场", "query": "Gimpo Airport, Seoul", "type": "airport", "note": "国内机场"}
        ]
    },
    
    # 东南亚主要城市
    "新加坡": {
        "primary": "新加坡",
        "aliases": ["Singapore"],
        "areas": [
            {"name": "新加坡市区", "query": "Singapore", "type": "city", "note": "包含乌节路、滨海湾、牛车水等主要区域"},
            {"name": "乌节路", "query": "Orchard Road, Singapore", "type": "district", "note": "购物天堂"},
            {"name": "滨海湾", "query": "Marina Bay, Singapore", "type": "district", "note": "商务和观光区"},
            {"name": "牛车水", "query": "Chinatown, Singapore", "type": "district", "note": "中华文化区"},
            {"name": "小印度", "query": "Little India, Singapore", "type": "district", "note": "印度文化区"},
            {"name": "樟宜机场", "query": "Singapore Changi Airport", "type": "airport", "note": "世界著名机场"},
            {"name": "圣淘沙", "query": "Sentosa Island, Singapore", "type": "attraction", "note": "度假岛屿"}
        ]
    },
    "曼谷": {
        "primary": "曼谷",
        "aliases": ["Bangkok"],
        "areas": [
            {"name": "曼谷市区", "query": "Bangkok, Thailand", "type": "city", "note": "包含暹罗、考山路、素坤逸等主要区域"},
            {"name": "暹罗", "query": "Siam, Bangkok", "type": "district", "note": "购物和娱乐中心"},
            {"name": "考山路", "query": "Khao San Road, Bangkok", "type": "district", "note": "背包客聚集地"},
            {"name": "素坤逸", "query": "Sukhumvit, Bangkok", "type": "district", "note": "国际化区域"},
            {"name": "湄南河", "query": "Chao Phraya River, Bangkok", "type": "landmark", "note": "河畔酒店区域"},
            {"name": "素万那普机场", "query": "Suvarnabhumi Airport, Bangkok", "type": "airport", "note": "主要国际机场"},
            {"name": "廊曼机场", "query": "Don Mueang Airport, Bangkok", "type": "airport", "note": "廉价航空机场"}
        ]
    },
    "吉隆坡": {
        "primary": "吉隆坡",
        "aliases": ["Kuala Lumpur", "KL"],
        "areas": [
            {"name": "吉隆坡市区", "query": "Kuala Lumpur, Malaysia", "type": "city", "note": "包含双子塔、武吉免登等主要区域"},
            {"name": "双子塔", "query": "KLCC, Kuala Lumpur", "type": "landmark", "note": "地标建筑和购物区"},
            {"name": "武吉免登", "query": "Bukit Bintang, Kuala Lumpur", "type": "district", "note": "购物和娱乐区"},
            {"name": "中央车站", "query": "KL Sentral, Kuala Lumpur", "type": "transport", "note": "交通枢纽区域"},
            {"name": "吉隆坡机场", "query": "Kuala Lumpur International Airport", "type": "airport", "note": "国际机场"}
        ]
    },
    
    # 美国主要城市
    "纽约": {
        "primary": "纽约",
        "aliases": ["New York", "NYC", "New York City"],
        "areas": [
            {"name": "曼哈顿", "query": "Manhattan, New York", "type": "district", "note": "核心商务和旅游区"},
            {"name": "时代广场", "query": "Times Square, New York", "type": "landmark", "note": "百老汇和购物区"},
            {"name": "中央公园", "query": "Central Park, New York", "type": "landmark", "note": "公园周边高端区域"},
            {"name": "华尔街", "query": "Wall Street, New York", "type": "business", "note": "金融区"},
            {"name": "布鲁克林", "query": "Brooklyn, New York", "type": "district", "note": "时尚区域，相对便宜"},
            {"name": "JFK机场", "query": "JFK Airport, New York", "type": "airport", "note": "主要国际机场"},
            {"name": "拉瓜迪亚机场", "query": "LaGuardia Airport, New York", "type": "airport", "note": "国内机场"},
            {"name": "纽瓦克机场", "query": "Newark Airport, New York", "type": "airport", "note": "新泽西机场"}
        ]
    },
    "洛杉矶": {
        "primary": "洛杉矶",
        "aliases": ["Los Angeles", "LA"],
        "areas": [
            {"name": "洛杉矶市区", "query": "Los Angeles, California", "type": "city", "note": "包含好莱坞、比佛利山庄等区域"},
            {"name": "好莱坞", "query": "Hollywood, Los Angeles", "type": "district", "note": "娱乐产业中心"},
            {"name": "比佛利山庄", "query": "Beverly Hills, Los Angeles", "type": "district", "note": "高端购物区"},
            {"name": "圣莫尼卡", "query": "Santa Monica, Los Angeles", "type": "district", "note": "海滨度假区"},
            {"name": "洛杉矶机场", "query": "LAX Airport, Los Angeles", "type": "airport", "note": "主要国际机场"},
            {"name": "迪士尼乐园", "query": "Disneyland, Anaheim", "type": "attraction", "note": "主题公园区域"}
        ]
    },
    
    # 欧洲主要城市
    "伦敦": {
        "primary": "伦敦",
        "aliases": ["London"],
        "areas": [
            {"name": "伦敦市区", "query": "London, UK", "type": "city", "note": "包含市中心、肯辛顿等主要区域"},
            {"name": "市中心", "query": "Central London, UK", "type": "district", "note": "主要景点和商务区"},
            {"name": "肯辛顿", "query": "Kensington, London", "type": "district", "note": "高端住宿区域"},
            {"name": "考文特花园", "query": "Covent Garden, London", "type": "district", "note": "购物和餐饮区"},
            {"name": "希思罗机场", "query": "Heathrow Airport, London", "type": "airport", "note": "主要国际机场"},
            {"name": "盖特威克机场", "query": "Gatwick Airport, London", "type": "airport", "note": "第二机场"}
        ]
    },
    "巴黎": {
        "primary": "巴黎",
        "aliases": ["Paris"],
        "areas": [
            {"name": "巴黎市区", "query": "Paris, France", "type": "city", "note": "包含香榭丽舍、卢浮宫等主要区域"},
            {"name": "香榭丽舍", "query": "Champs-Élysées, Paris", "type": "landmark", "note": "著名大街和购物区"},
            {"name": "卢浮宫", "query": "Louvre, Paris", "type": "landmark", "note": "艺术文化区域"},
            {"name": "埃菲尔铁塔", "query": "Eiffel Tower, Paris", "type": "landmark", "note": "地标建筑区域"},
            {"name": "戴高乐机场", "query": "Charles de Gaulle Airport, Paris", "type": "airport", "note": "主要国际机场"},
            {"name": "奥利机场", "query": "Orly Airport, Paris", "type": "airport", "note": "第二机场"}
        ]
    },
    
    # 澳洲主要城市
    "悉尼": {
        "primary": "悉尼",
        "aliases": ["Sydney"],
        "areas": [
            {"name": "悉尼市区", "query": "Sydney, Australia", "type": "city", "note": "包含CBD、环形码头等主要区域"},
            {"name": "环形码头", "query": "Circular Quay, Sydney", "type": "landmark", "note": "港口和歌剧院区域"},
            {"name": "邦迪海滩", "query": "Bondi Beach, Sydney", "type": "landmark", "note": "著名海滩度假区"},
            {"name": "达令港", "query": "Darling Harbour, Sydney", "type": "district", "note": "娱乐和会展区"},
            {"name": "悉尼机场", "query": "Sydney Airport, Australia", "type": "airport", "note": "国际机场"}
        ]
    },
    
    # 中东主要城市
    "迪拜": {
        "primary": "迪拜",
        "aliases": ["Dubai"],
        "areas": [
            {"name": "迪拜市区", "query": "Dubai, UAE", "type": "city", "note": "包含迪拜塔、朱美拉等主要区域"},
            {"name": "迪拜塔", "query": "Burj Khalifa, Dubai", "type": "landmark", "note": "世界最高楼区域"},
            {"name": "朱美拉海滩", "query": "Jumeirah Beach, Dubai", "type": "landmark", "note": "豪华海滨度假区"},
            {"name": "迪拜购物中心", "query": "Dubai Mall, Dubai", "type": "landmark", "note": "购物和娱乐中心"},
            {"name": "迪拜机场", "query": "Dubai International Airport", "type": "airport", "note": "国际航空枢纽"},
            {"name": "棕榈岛", "query": "Palm Jumeirah, Dubai", "type": "landmark", "note": "人工岛豪华度假区"}
        ]
    }
}

# 英文城市名映射（小写匹配）- 复用airport_mapper的映射
ENGLISH_CITIES_LOCATIONS = {
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
    "kaohsiung": "高雄",
    "taichung": "台中",
    "tainan": "台南",
    "hualien": "花莲",
    
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
    
    # 韩国
    "seoul": "首尔",
    "busan": "釜山",
    "jeju": "济州",
    "daegu": "大邱",
    "gwangju": "光州",
    "cheongju": "清州",
    
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
    "bali": "巴厘岛",
    "denpasar": "巴厘岛",
    
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
    "dubai": "迪拜",
    "abu dhabi": "阿布扎比",
    "doha": "多哈",
    "tehran": "德黑兰",
    "kuwait city": "科威特城",
    "riyadh": "利雅得",
    "jeddah": "吉达",
    "baghdad": "巴格达",
    "beirut": "贝鲁特",
    "damascus": "大马士革",
    "amman": "安曼",
    
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
    "orlando": "奥兰多",
    "philadelphia": "费城",
    "phoenix": "凤凰城",
    "portland": "波特兰",
    "san diego": "圣地亚哥",
    "salt lake city": "盐湖城",
    
    # 加拿大和其他地区
    "toronto": "多伦多",
    "vancouver": "温哥华",
    "london": "伦敦",
    "paris": "巴黎",
    "frankfurt": "法兰克福",
    "amsterdam": "阿姆斯特丹",
    "rome": "罗马",
    "madrid": "马德里",
    "zurich": "苏黎世",
    "sydney": "悉尼",
    "melbourne": "墨尔本",
    "perth": "珀斯",
    "auckland": "奥克兰"
}

# 常见输入错误和别名映射 - 复用airport_mapper的别名并扩展
LOCATION_ALIASES = {
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
    "kl": "吉隆坡",
    
    # 国家/地区映射到主要城市
    "中国": "北京",
    "台湾": "台北",
    "日本": "东京",
    "韩国": "首尔",
    "泰国": "曼谷",
    "新加坡": "新加坡",
    "马来西亚": "吉隆坡",
    "印尼": "雅加达",
    "印度尼西亚": "雅加达",
    "菲律宾": "马尼拉",
    "越南": "胡志明市",
    "印度": "新德里",
    "阿联酋": "迪拜",
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
    "美国": "纽约",
    "加拿大": "多伦多",
    
    # 酒店相关位置别名
    "机场": "",  # 需要结合具体城市
    "市中心": "",  # 需要结合具体城市
    "海滩": "",  # 需要结合具体城市
    "商务区": "",  # 需要结合具体城市
}

def normalize_location_input(location_input: str) -> str:
    """规范化位置输入"""
    if not location_input:
        return ""
    
    # 去除空格并转为小写（用于英文匹配）
    normalized = location_input.strip()
    
    # 检查别名映射
    if normalized in LOCATION_ALIASES:
        alias_result = LOCATION_ALIASES[normalized]
        if alias_result:  # 非空别名
            return alias_result
    
    # 检查英文城市名映射
    normalized_lower = normalized.lower()
    if normalized_lower in ENGLISH_CITIES_LOCATIONS:
        return ENGLISH_CITIES_LOCATIONS[normalized_lower]
    
    return normalized

def resolve_hotel_location(location_input: str, area_preference: str = None) -> Dict:
    """
    解析酒店位置输入
    返回: {
        "status": "success/multiple/not_found/country_locations",
        "primary_query": "主要搜索查询", 
        "areas": [区域选项],
        "location": "规范化位置名称",
        "suggestions": [建议信息]
    }
    """
    if not location_input:
        return {"status": "not_found"}
    
    # 规范化输入
    normalized_location = normalize_location_input(location_input)
    
    # 检查主要城市映射
    if normalized_location in MAJOR_CITIES_LOCATIONS:
        city_info = MAJOR_CITIES_LOCATIONS[normalized_location]
        areas = city_info["areas"]
        
        # 如果指定了区域偏好，尝试匹配
        selected_area = None
        if area_preference:
            area_pref_lower = area_preference.lower()
            for area in areas:
                if (area_pref_lower in area["name"].lower() or 
                    area_pref_lower in area["type"] or
                    area_pref_lower in area.get("note", "").lower()):
                    selected_area = area
                    break
        
        if selected_area:
            # 找到特定区域
            return {
                "status": "success",
                "primary_query": selected_area["query"],
                "location": normalized_location,
                "area": selected_area,
                "all_areas": areas
            }
        elif len(areas) == 1:
            # 单区域城市
            return {
                "status": "success",
                "primary_query": areas[0]["query"],
                "location": normalized_location,
                "area": areas[0],
                "all_areas": areas
            }
        else:
            # 多区域城市，需要用户选择
            return {
                "status": "multiple",
                "primary_query": f"{normalized_location}",
                "location": normalized_location,
                "areas": areas,
                "default_query": areas[0]["query"]  # 默认使用第一个区域
            }
    
    # 尝试模糊匹配
    partial_matches = search_locations_by_partial_name(location_input)
    if partial_matches:
        if len(partial_matches) == 1:
            match = partial_matches[0]
            return resolve_hotel_location(match["city"], area_preference)
        else:
            return {
                "status": "multiple",
                "suggestions": partial_matches[:5],  # 最多返回5个建议
                "input": location_input
            }
    
    # 如果都没找到，返回原始输入作为搜索查询
    return {
        "status": "not_found",
        "input": location_input,
        "normalized": normalized_location,
        "fallback_query": normalized_location  # 可以直接用于API搜索
    }

def search_locations_by_partial_name(partial_name: str) -> List[Dict]:
    """根据部分名称搜索位置"""
    results = []
    partial_lower = partial_name.lower()
    
    for city, city_info in MAJOR_CITIES_LOCATIONS.items():
        # 检查城市名匹配
        if partial_lower in city.lower():
            results.append({
                "city": city,
                "type": "city",
                "match_type": "city_name",
                "primary_query": city_info["areas"][0]["query"]
            })
        
        # 检查英文别名匹配
        for alias in city_info.get("aliases", []):
            if partial_lower in alias.lower():
                results.append({
                    "city": city,
                    "type": "city",
                    "match_type": "alias",
                    "alias": alias,
                    "primary_query": city_info["areas"][0]["query"]
                })
        
        # 检查区域名匹配
        for area in city_info["areas"]:
            if (partial_lower in area["name"].lower() or 
                partial_lower in area["query"].lower()):
                results.append({
                    "city": city,
                    "area": area["name"],
                    "type": "area",
                    "match_type": "area_name",
                    "primary_query": area["query"]
                })
    
    # 去重并返回前10个结果
    seen = set()
    unique_results = []
    for result in results:
        key = f"{result['city']}_{result.get('area', '')}"
        if key not in seen:
            seen.add(key)
            unique_results.append(result)
    
    return unique_results[:10]

def get_area_suggestions(city: str) -> List[Dict]:
    """获取城市的区域建议"""
    if city in MAJOR_CITIES_LOCATIONS:
        return MAJOR_CITIES_LOCATIONS[city]["areas"]
    return []

def format_location_selection_message(location_result: Dict) -> str:
    """格式化位置选择消息"""
    from telegram.helpers import escape_markdown
    
    message_parts = ["🏨 *酒店位置选择*\n"]
    
    status = location_result.get("status")
    if status == "multiple":
        if "areas" in location_result:
            # 多区域城市
            location = location_result.get("location", "")
            areas = location_result.get("areas", [])
            safe_location = escape_markdown(location, version=2)
            message_parts.append(f"📍 *{safe_location}* 有{len(areas)}个主要区域:\n")
            
            for i, area in enumerate(areas):
                name = area.get("name", "")
                type_info = area.get("type", "")
                note = area.get("note", "")
                
                safe_name = escape_markdown(name, version=2)
                safe_note = escape_markdown(note, version=2)
                
                type_icons = {
                    "city": "🏙️",
                    "district": "🏘️", 
                    "business": "🏢",
                    "landmark": "🗼",
                    "airport": "✈️",
                    "attraction": "🎡",
                    "transport": "🚉"
                }
                icon = type_icons.get(type_info, "📍")
                
                message_parts.append(f"{icon} *{safe_name}*")
                if note:
                    message_parts.append(f"   💡 {safe_note}")
                message_parts.append("")
        
        elif "suggestions" in location_result:
            # 模糊匹配建议
            suggestions = location_result.get("suggestions", [])
            input_text = location_result.get("input", "")
            safe_input = escape_markdown(input_text, version=2)
            
            message_parts.append(f"🔍 找到 *{safe_input}* 的相关位置:\n")
            
            for suggestion in suggestions:
                city = suggestion.get("city", "")
                area = suggestion.get("area", "")
                match_type = suggestion.get("match_type", "")
                
                safe_city = escape_markdown(city, version=2)
                
                if area:
                    safe_area = escape_markdown(area, version=2)
                    message_parts.append(f"📍 *{safe_city}* - {safe_area}")
                else:
                    message_parts.append(f"🏙️ *{safe_city}*")
                message_parts.append("")
    
    elif status == "not_found":
        input_text = location_result.get("input", "")
        safe_input = escape_markdown(input_text, version=2)
        message_parts.append(f"❓ 未找到 *{safe_input}* 的位置信息")
        message_parts.append("💡 您可以直接输入完整的城市名称或地区")
        message_parts.append("📝 支持中英文，如：北京、东京、Bangkok、New York")
    
    return "\n".join(message_parts)

def get_location_query(location_result: Dict, area_index: int = 0) -> str:
    """获取用于API搜索的位置查询字符串"""
    status = location_result.get("status")
    
    if status == "success":
        return location_result.get("primary_query", "")
    
    elif status == "multiple":
        if "areas" in location_result:
            areas = location_result.get("areas", [])
            if 0 <= area_index < len(areas):
                return areas[area_index]["query"]
            return location_result.get("default_query", "")
        elif "suggestions" in location_result:
            suggestions = location_result.get("suggestions", [])
            if 0 <= area_index < len(suggestions):
                return suggestions[area_index]["primary_query"]
    
    elif status == "not_found":
        # 使用fallback查询或原始输入
        return location_result.get("fallback_query", location_result.get("input", ""))
    
    return ""

def get_all_supported_locations() -> List[str]:
    """获取所有支持的位置列表"""
    locations = list(MAJOR_CITIES_LOCATIONS.keys())
    locations.extend([alias for alias in LOCATION_ALIASES.keys() if LOCATION_ALIASES[alias]])
    locations.extend(ENGLISH_CITIES_LOCATIONS.values())
    return sorted(set(locations))

def format_location_info(location: str, area: str = None) -> str:
    """格式化位置信息显示"""
    from telegram.helpers import escape_markdown
    
    if location in MAJOR_CITIES_LOCATIONS:
        city_info = MAJOR_CITIES_LOCATIONS[location]
        safe_location = escape_markdown(location, version=2)
        
        result = f"🏨 *{safe_location}*\n"
        
        # 显示别名
        aliases = city_info.get("aliases", [])
        if aliases:
            safe_aliases = [escape_markdown(alias, version=2) for alias in aliases]
            result += f"🔤 {' / '.join(safe_aliases)}\n"
        
        # 如果指定了具体区域
        if area:
            for area_info in city_info["areas"]:
                if area_info["name"] == area or area in area_info["name"]:
                    safe_area = escape_markdown(area_info["name"], version=2)
                    safe_note = escape_markdown(area_info.get("note", ""), version=2)
                    result += f"📍 {safe_area}\n"
                    if safe_note:
                        result += f"💡 {safe_note}\n"
                    break
        else:
            # 显示主要区域数量
            area_count = len(city_info["areas"])
            result += f"🗺️ {area_count}个主要区域可选\n"
        
        return result
    
    # 如果未找到详细信息，返回基本信息
    safe_location = escape_markdown(location, version=2)
    return f"🏨 位置: {safe_location}"