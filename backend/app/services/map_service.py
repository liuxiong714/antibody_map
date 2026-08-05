from typing import Optional

from sqlalchemy import select, func, distinct, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_point import DataPoint
from app.core.term_normalizer import normalize_province, CHINA_PROVINCE_NAMES

# ===== 人口分类标准化映射（合并同类别）=====
POPULATION_MAP: dict[str, str] = {
    # 儿童类
    "儿童": "儿童", "健康儿童": "儿童", "学龄儿童": "儿童", "学龄前儿童": "儿童",
    "散居儿童": "儿童", "集体儿童": "儿童", "托幼儿童": "儿童", "幼托儿童": "儿童",
    "0-14岁儿童": "儿童", "0-6岁儿童": "儿童", "7-14岁儿童": "儿童",
    "0-7岁儿童": "儿童", "0-5岁儿童": "儿童", "6-14岁儿童": "儿童",
    "1-6岁儿童": "儿童", "1-15岁儿童": "儿童",
    # 学生类
    "学生": "学生", "中小学生": "学生", "小学生": "学生", "中学生": "学生",
    "大学生": "学生", "在校学生": "学生", "大中小学生": "学生",
    "高中生": "学生", "初中生": "学生", "职业高中学生": "学生",
    # 医护类
    "医护人员": "医护人员", "医务人员": "医护人员", "卫生人员": "医护人员",
    "医生": "医护人员", "护士": "医护人员", "医技人员": "医护人员",
    "临床医护人员": "医护人员", "一线医务人员": "医护人员",
    "医疗卫生人员": "医护人员", "疾控人员": "医护人员",
    # 孕产妇类
    "孕妇": "孕妇", "孕产妇": "孕妇", "妊娠期妇女": "孕妇",
    "产妇": "孕妇", "妊娠妇女": "孕妇", "孕期妇女": "孕妇",
    "待产妇": "孕妇",
    # 老年人类
    "老年人": "老年人", "老人": "老年人", "60岁以上老年人": "老年人",
    "≥60岁老年人": "老年人", "60岁及以上老年人": "老年人",
    "65岁以上老年人": "老年人", "老年人群": "老年人",
    # 成人/成年人类
    "成人": "成人", "成年人": "成人", "健康成人": "成人",
    "18-45岁成人": "成人", "18-59岁成人": "成人", "18岁以上成人": "成人",
    "15-60岁成人": "成人", "15-59岁成人": "成人",
    # 军人/士兵类
    "军人": "军人", "士兵": "军人", "入伍新兵": "军人",
    "新兵": "军人", "现役军人": "军人", "部队官兵": "军人",
    "军队人员": "军人", "武警": "军人",
    # 婴幼儿/新生儿类
    "新生儿": "婴幼儿", "婴儿": "婴幼儿", "婴幼儿": "婴幼儿",
    "0-1岁婴儿": "婴幼儿", "0-2岁婴幼儿": "婴幼儿",
    # 流动人口类
    "流动人口": "流动人口", "农民工": "流动人口", "外出务工人员": "流动人口",
    "进城务工人员": "流动人口", "外来务工人员": "流动人口",
    # 育龄妇女类
    "育龄期妇女": "育龄妇女", "育龄妇女": "育龄妇女", "已婚育龄妇女": "育龄妇女",
    "已婚育龄期妇女": "育龄妇女",
    # 教师类
    "教师": "教师", "老师": "教师", "教职工": "教师", "教职员工": "教师",
    # 农民/农村居民类
    "农民": "农民", "农村居民": "农民", "农村人口": "农民",
    "务农人员": "农民", "农牧民": "农民",
    # 工人/职工类
    "工人": "工人", "职工": "工人", "企业职工": "工人",
    "企业员工": "工人", "公司职员": "工人",
    # 服务从业人员类
    "餐饮从业人员": "餐饮服务业", "饮食从业人员": "餐饮服务业",
    "公共场所从业人员": "服务业人员", "服务业人员": "服务业人员",
    "服务行业人员": "服务业人员", "商业服务人员": "服务业人员",
    # 干部/公务员类
    "干部": "干部", "机关干部": "干部", "公务员": "干部",
    "机关工作人员": "干部", "行政人员": "干部",
    # 保育员
    "保育员": "保育员", "保育人员": "保育员",
    # 献血员/供血者
    "献血员": "献血员", "献血者": "献血员", "供血者": "献血员",
    "无偿献血者": "献血员", "有偿供血者": "献血员",
    # 密切接触者
    "密切接触者": "密切接触者", "接触者": "密切接触者",
    "家庭接触者": "密切接触者", "家庭成员": "密切接触者",
    # 患者/病人
    "患者": "患者", "病人": "患者", "住院患者": "患者",
    "门诊患者": "患者", "确诊病例": "患者",
    # 健康人群/一般人群
    "健康人群": "健康人群", "一般人群": "健康人群", "正常人群": "健康人群",
    "普通人群": "健康人群", "健康体检人群": "健康人群",
    "体检人群": "健康人群", "健康人": "健康人群",
    # 其他常用
    "司机": "司机", "驾驶员": "司机",
    "警察": "警察", "公安干警": "警察",
    "渔民": "渔民", "船民": "渔民", "船员": "渔民",
    "兽医": "兽医", "畜牧人员": "兽医",
    "收容人员": "收容人员", "羁押人员": "收容人员",
    "归国人员": "归国人员", "境外输入人员": "归国人员",
    "留学生": "留学生",
}


def _normalize_population(population: str) -> str:
    """标准化人口分类名称，合并同类别。
    
    1. 先精确匹配 POPULATION_MAP
    2. 再模糊匹配（包含关系）
    3. 无匹配则保留原文
    """
    if not population:
        return population
    p = population.strip()
    # 精确匹配
    if p in POPULATION_MAP:
        return POPULATION_MAP[p]
    # 模糊匹配：p 包含某个 key 或 key 包含在 p 中
    for key, value in POPULATION_MAP.items():
        if key and len(key) >= 2:
            if key in p or p in key:
                return value
    # 年龄范围模式匹配："x-y岁"或"≥x岁"等
    import re
    age_pattern = re.match(r'^(\d+)[-~](\d+)岁', p)
    if age_pattern:
        return "儿童"  # 有年龄范围的默认为儿童
    
    age_single = re.match(r'^(≥|>=|>)?(\d+)岁(以上|以下)?(成人|儿童|老年人)?$', p)
    if age_single:
        suffix = age_single.group(3) or ""
        if "老年" in p or "60" in p or "65" in p:
            return "老年人"
        if "儿童" in p or "幼儿" in p:
            return "儿童"
        if "成人" in p or "成年" in p:
            return "成人"
        return "儿童"  # 有年龄信息但无法判断的默认归为儿童
    
    return p


# ===== 中国城市坐标查找表（省-市-经纬度）=====
# 覆盖全国主要地级市和常用县级市，用于地图散点展示
CITY_COORDS: dict[str, dict[str, tuple[float, float]]] = {
    # 北京
    "北京": {"北京市": (116.4074, 39.9042), "朝阳区": (116.4432, 39.9215), "海淀区": (116.2992, 39.9592),
             "丰台区": (116.2870, 39.8585), "东城区": (116.4163, 39.9285), "西城区": (116.3660, 39.9123),
             "通州区": (116.6571, 39.9022), "大兴区": (116.3387, 39.7264), "昌平区": (116.2312, 40.2207)},
    # 天津
    "天津": {"天津市": (117.2004, 39.0842), "滨海新区": (117.6466, 39.0208), "武清区": (117.0444, 39.3841)},
    # 上海
    "上海": {"上海市": (121.4737, 31.2304), "浦东新区": (121.5447, 31.2220), "闵行区": (121.3817, 31.1128),
             "宝山区": (121.4894, 31.4053), "松江区": (121.2277, 31.0322), "嘉定区": (121.2655, 31.3753)},
    # 重庆
    "重庆": {"重庆市": (106.5516, 29.5648), "渝中区": (106.5689, 29.5530), "江北区": (106.5743, 29.6067),
             "沙坪坝区": (106.4569, 29.5411), "万州区": (108.4087, 30.8079), "涪陵区": (107.3897, 29.7031)},
    # 河北
    "河北": {"石家庄市": (114.5149, 38.0428), "唐山市": (118.1801, 39.6304), "秦皇岛市": (119.5996, 39.9358),
             "邯郸市": (114.5391, 36.6257), "保定市": (115.4648, 38.8741), "张家口市": (114.8863, 40.7685),
             "承德市": (117.9624, 40.9542), "沧州市": (116.8387, 38.3044), "廊坊市": (116.6839, 39.5380),
             "衡水市": (115.6862, 37.7391), "邢台市": (114.5044, 37.0706)},
    # 山西
    "山西": {"太原市": (112.5509, 37.8706), "大同市": (113.3001, 40.0768), "阳泉市": (113.5805, 37.8569),
             "长治市": (113.1163, 36.1954), "晋城市": (112.8518, 35.4907), "朔州市": (112.4328, 39.3319),
             "晋中市": (112.7527, 37.6873), "运城市": (111.0080, 35.0156), "忻州市": (112.7342, 38.4167),
             "临汾市": (111.5189, 36.0878), "吕梁市": (111.1444, 37.5183)},
    # 内蒙古
    "内蒙古": {"呼和浩特市": (111.7500, 40.8422), "包头市": (109.9535, 40.6212), "乌海市": (106.7956, 39.6552),
               "赤峰市": (118.9569, 42.2575), "通辽市": (122.2450, 43.6525), "鄂尔多斯市": (109.7813, 39.6083),
               "呼伦贝尔市": (119.7657, 49.2119), "巴彦淖尔市": (107.3877, 40.7432), "乌兰察布市": (113.1338, 40.9927)},
    # 辽宁
    "辽宁": {"沈阳市": (123.4315, 41.8057), "大连市": (121.6147, 38.9132), "鞍山市": (122.9943, 41.1086),
             "抚顺市": (123.9572, 41.8808), "本溪市": (123.7668, 41.2945), "丹东市": (124.3560, 40.0006),
             "锦州市": (121.1270, 41.0952), "营口市": (122.2354, 40.6670), "阜新市": (121.6703, 42.0216),
             "辽阳市": (123.2369, 41.2677), "盘锦市": (122.0707, 41.1200), "铁岭市": (123.8420, 42.2863),
             "朝阳市": (120.4508, 41.5728), "葫芦岛市": (120.8369, 40.7110)},
    # 吉林
    "吉林": {"长春市": (125.3236, 43.8171), "吉林市": (126.5494, 43.8378), "四平市": (124.3504, 43.1665),
             "辽源市": (125.1450, 42.9513), "通化市": (125.9397, 41.7283), "白山市": (126.4236, 41.9397),
             "松原市": (124.8251, 45.1418), "白城市": (122.8388, 45.6199)},
    # 黑龙江
    "黑龙江": {"哈尔滨市": (126.5350, 45.8030), "齐齐哈尔市": (123.9182, 47.3543), "鸡西市": (130.9693, 45.2953),
               "鹤岗市": (130.2979, 47.3501), "双鸭山市": (131.1595, 46.6467), "大庆市": (125.1037, 46.5887),
               "伊春市": (128.8405, 47.7270), "佳木斯市": (130.3190, 46.7998), "牡丹江市": (129.6325, 44.5516),
               "黑河市": (127.5285, 50.2449), "绥化市": (126.9688, 46.6538)},
    # 江苏
    "江苏": {"南京市": (118.7969, 32.0603), "无锡市": (120.3119, 31.4901), "徐州市": (117.2841, 34.2058),
             "常州市": (119.9737, 31.8107), "苏州市": (120.5853, 31.2990), "南通市": (120.8943, 31.9799),
             "连云港市": (119.2216, 34.5967), "淮安市": (119.0152, 33.6104), "盐城市": (120.1626, 33.3473),
             "扬州市": (119.4130, 32.3946), "镇江市": (119.4250, 32.1878), "泰州市": (119.9228, 32.4556),
             "宿迁市": (118.2752, 33.9630)},
    # 浙江
    "浙江": {"杭州市": (120.1551, 30.2741), "宁波市": (121.5440, 29.8683), "温州市": (120.6994, 28.0028),
             "嘉兴市": (120.7555, 30.7460), "湖州市": (120.0868, 30.8942), "绍兴市": (120.5801, 30.0302),
             "金华市": (119.6474, 29.0792), "衢州市": (118.8743, 28.9417), "舟山市": (122.2072, 29.9855),
             "台州市": (121.4207, 28.6564), "丽水市": (119.9228, 28.4669)},
    # 安徽
    "安徽": {"合肥市": (117.2272, 31.8206), "芜湖市": (118.4331, 31.3525), "蚌埠市": (117.3894, 32.9167),
             "淮南市": (117.0186, 32.6421), "马鞍山市": (118.5068, 31.6705), "淮北市": (116.7983, 33.9553),
             "铜陵市": (117.8122, 30.9449), "安庆市": (117.0635, 30.5438), "黄山市": (118.3387, 29.7152),
             "滁州市": (118.3169, 32.3019), "阜阳市": (115.8142, 32.8902), "宿州市": (116.9642, 33.6461),
             "六安市": (116.5213, 31.7348), "亳州市": (115.7790, 33.8455), "池州市": (117.4916, 30.6649),
             "宣城市": (118.7587, 30.9402)},
    # 福建
    "福建": {"福州市": (119.2965, 26.0745), "厦门市": (118.0894, 24.4798), "莆田市": (119.0077, 25.4541),
             "三明市": (117.6392, 26.2634), "泉州市": (118.5894, 24.9080), "漳州市": (117.6474, 24.5130),
             "南平市": (118.1777, 26.6418), "龙岩市": (117.0172, 25.0751), "宁德市": (119.5479, 26.6657)},
    # 江西
    "江西": {"南昌市": (115.8581, 28.6829), "景德镇市": (117.1784, 29.2689), "萍乡市": (113.8870, 27.6389),
             "九江市": (115.9522, 29.6620), "新余市": (114.9171, 27.8178), "鹰潭市": (117.0420, 28.2726),
             "赣州市": (114.9349, 25.8315), "吉安市": (114.9925, 27.1130), "宜春市": (114.4162, 27.8146),
             "抚州市": (116.3581, 27.9492), "上饶市": (117.9432, 28.4550)},
    # 山东
    "山东": {"济南市": (117.1201, 36.6512), "青岛市": (120.3826, 36.0671), "淄博市": (118.0550, 36.8130),
             "枣庄市": (117.3235, 34.8106), "东营市": (118.6746, 37.4347), "烟台市": (121.4479, 37.4638),
             "潍坊市": (119.1075, 36.7069), "济宁市": (116.5872, 35.4149), "泰安市": (117.0882, 36.1999),
             "威海市": (122.1204, 37.5133), "日照市": (119.5272, 35.4164), "临沂市": (118.3564, 35.1047),
             "德州市": (116.3121, 37.4364), "聊城市": (115.9854, 36.4570), "滨州市": (117.9707, 37.3819),
             "菏泽市": (115.4807, 35.2338)},
    # 河南
    "河南": {"郑州市": (113.6254, 34.7466), "开封市": (114.3074, 34.7973), "洛阳市": (112.4539, 34.6197),
             "平顶山市": (113.1926, 33.7661), "安阳市": (114.3924, 36.0982), "鹤壁市": (114.2974, 35.7472),
             "新乡市": (113.9267, 35.3030), "焦作市": (113.2418, 35.2159), "濮阳市": (115.0295, 35.7618),
             "许昌市": (113.8523, 34.0365), "漯河市": (114.0169, 33.5814), "三门峡市": (111.2001, 34.7726),
             "南阳市": (112.5285, 32.9908), "商丘市": (115.6563, 34.4143), "信阳市": (114.0913, 32.1470),
             "周口市": (114.6969, 33.6259), "驻马店市": (114.0220, 32.9803)},
    # 湖北
    "湖北": {"武汉市": (114.3054, 30.5931), "黄石市": (115.0770, 30.1999), "十堰市": (110.8000, 32.6344),
             "宜昌市": (111.2864, 30.6920), "襄阳市": (112.1224, 32.0090), "鄂州市": (114.8950, 30.3912),
             "荆门市": (112.1993, 31.0354), "孝感市": (113.9166, 30.9248), "荆州市": (112.2406, 30.3349),
             "黄冈市": (114.8723, 30.4535), "咸宁市": (114.3224, 29.8413), "随州市": (113.3826, 31.6902),
             "恩施市": (109.4792, 30.2950)},
    # 湖南
    "湖南": {"长沙市": (112.9388, 28.2282), "株洲市": (113.1340, 27.8277), "湘潭市": (112.9441, 27.8297),
             "衡阳市": (112.5720, 26.8932), "邵阳市": (111.4677, 27.2389), "岳阳市": (113.1287, 29.3572),
             "常德市": (111.6985, 29.0316), "张家界市": (110.4792, 29.1171), "益阳市": (112.3551, 28.5553),
             "郴州市": (113.0148, 25.7706), "永州市": (111.6134, 26.4206), "怀化市": (109.9985, 27.5550),
             "娄底市": (112.0011, 27.6971)},
    # 广东
    "广东": {"广州市": (113.2644, 23.1292), "深圳市": (114.0579, 22.5431), "珠海市": (113.5767, 22.2708),
             "汕头市": (116.6821, 23.3539), "佛山市": (113.1217, 23.0219), "江门市": (113.0816, 22.5788),
             "湛江市": (110.3566, 21.2699), "茂名市": (110.9253, 21.6628), "肇庆市": (112.4650, 23.0469),
             "惠州市": (114.4159, 23.1107), "梅州市": (116.1222, 24.2886), "汕尾市": (115.3652, 22.7863),
             "河源市": (114.7005, 23.7437), "阳江市": (111.9826, 21.8579), "清远市": (113.0562, 23.6818),
             "东莞市": (113.7518, 23.0205), "中山市": (113.3928, 22.5176), "潮州市": (116.6224, 23.6569),
             "揭阳市": (116.3728, 23.5497), "云浮市": (112.0445, 22.9151)},
    # 广西
    "广西": {"南宁市": (108.3665, 22.8174), "柳州市": (109.4280, 24.3254), "桂林市": (110.2900, 25.2736),
             "梧州市": (111.2792, 23.4769), "北海市": (109.1200, 21.4812), "防城港市": (108.3542, 21.6869),
             "钦州市": (108.6542, 21.9793), "贵港市": (109.5989, 23.1160), "玉林市": (110.1412, 22.6470),
             "百色市": (106.6182, 23.9023), "贺州市": (111.5667, 24.4035), "河池市": (108.0854, 24.6929),
             "来宾市": (109.2215, 23.7503), "崇左市": (107.3649, 22.3789)},
    # 海南
    "海南": {"海口市": (110.1983, 20.0442), "三亚市": (109.5119, 18.2528), "儋州市": (109.5808, 19.5211),
             "琼海市": (110.4746, 19.2591), "文昌市": (110.7977, 19.5435), "万宁市": (110.3910, 18.7952)},
    # 四川
    "四川": {"成都市": (104.0665, 30.5728), "自贡市": (104.7784, 29.3390), "攀枝花市": (101.7190, 26.5823),
             "泸州市": (105.4430, 28.8892), "德阳市": (104.3979, 31.1268), "绵阳市": (104.6790, 31.4675),
             "广元市": (105.8434, 32.4360), "遂宁市": (105.5928, 30.5314), "内江市": (105.0584, 29.5802),
             "乐山市": (103.7654, 29.5522), "南充市": (106.1107, 30.8378), "眉山市": (103.8485, 30.0755),
             "宜宾市": (104.6430, 28.7513), "广安市": (106.6332, 30.4560), "达州市": (107.4680, 31.2096),
             "雅安市": (103.0133, 29.9802), "巴中市": (106.7473, 31.8679), "资阳市": (104.6271, 30.1289)},
    # 贵州
    "贵州": {"贵阳市": (106.6302, 26.6470), "六盘水市": (104.8304, 26.5930), "遵义市": (106.9274, 27.7260),
             "安顺市": (105.9476, 26.2531), "毕节市": (105.3052, 27.2987), "铜仁市": (109.1896, 27.6909)},
    # 云南
    "云南": {"昆明市": (102.8329, 24.8801), "曲靖市": (103.7962, 25.4900), "玉溪市": (102.5272, 24.3473),
             "保山市": (99.1617, 25.1121), "昭通市": (103.7170, 27.3380), "丽江市": (100.2271, 26.8568),
             "普洱市": (100.9662, 22.8252), "临沧市": (100.0895, 23.8850), "楚雄市": (101.5459, 25.0330),
             "蒙自市": (103.3648, 23.3962), "文山市": (104.2446, 23.3865), "景洪市": (100.7980, 22.0120),
             "大理市": (100.2297, 25.5916), "芒市": (98.5881, 24.4337), "泸水市": (98.8573, 25.8229),
             "香格里拉市": (99.7014, 27.8295)},
    # 西藏
    "西藏": {"拉萨市": (91.1721, 29.6530), "日喀则市": (88.8809, 29.2670), "昌都市": (97.1730, 31.1400),
             "林芝市": (94.3615, 29.6490), "山南市": (91.7740, 29.2350), "那曲市": (92.0510, 31.4760),
             "阿里地区": (80.1050, 32.5010)},
    # 陕西
    "陕西": {"西安市": (108.9402, 34.2611), "铜川市": (108.9453, 34.8968), "宝鸡市": (107.2372, 34.3620),
             "咸阳市": (108.7091, 34.3299), "渭南市": (109.5100, 34.4999), "延安市": (109.4902, 36.5856),
             "汉中市": (107.0237, 33.0882), "榆林市": (109.7345, 38.2852), "安康市": (109.0289, 32.6841),
             "商洛市": (109.9404, 33.8704)},
    # 甘肃
    "甘肃": {"兰州市": (103.8343, 36.0611), "嘉峪关市": (98.2892, 39.7726), "金昌市": (102.1880, 38.5201),
             "白银市": (104.1386, 36.5447), "天水市": (105.7250, 34.5809), "武威市": (102.6380, 37.9282),
             "张掖市": (100.4498, 38.9259), "平凉市": (106.6652, 35.5430), "酒泉市": (98.4939, 39.7328),
             "庆阳市": (107.6429, 35.7092), "定西市": (104.6262, 35.5806), "陇南市": (104.9218, 33.3990)},
    # 青海
    "青海": {"西宁市": (101.7782, 36.6171), "海东市": (102.4025, 36.5029), "格尔木市": (94.9260, 36.4064)},
    # 宁夏
    "宁夏": {"银川市": (106.2309, 38.4872), "石嘴山市": (106.3834, 38.9840), "吴忠市": (106.2011, 37.9975),
             "固原市": (106.2426, 36.0158), "中卫市": (105.1940, 37.5149)},
    # 新疆
    "新疆": {"乌鲁木齐市": (87.6168, 43.8256), "克拉玛依市": (84.8689, 45.5950), "吐鲁番市": (89.1897, 42.9513),
             "哈密市": (93.5158, 42.8190), "阿克苏市": (80.2640, 41.1685), "喀什市": (75.9938, 39.4679),
             "库尔勒市": (86.1746, 41.7259), "伊宁市": (81.2773, 43.9085), "昌吉市": (87.3041, 44.0146),
             "石河子市": (86.0790, 44.3060), "和田市": (79.9135, 37.1140),
             # 县/县级市
             "疏附县": (75.8623, 39.3750), "疏勒县": (76.0584, 39.4015), "英吉沙县": (76.1763, 38.9300),
             "泽普县": (77.2737, 38.1850), "莎车县": (77.2300, 38.4100), "叶城县": (77.4200, 37.8800),
             "麦盖提县": (77.6490, 38.8980), "岳普湖县": (76.7760, 39.2350), "伽师县": (76.7300, 39.4900),
             "巴楚县": (78.5500, 39.7900), "塔什库尔干县": (75.2300, 37.7800), "塔什库尔干塔吉克自治县": (75.2300, 37.7800),
             "墨玉县": (79.7300, 37.2700), "皮山县": (78.2800, 37.6200), "洛浦县": (80.1900, 37.0700),
             "策勒县": (80.8100, 36.9900), "于田县": (81.6700, 36.8600), "民丰县": (82.6900, 37.0600),
             "鄯善县": (90.2100, 42.8700), "托克逊县": (88.6400, 42.7900), "伊吾县": (94.7000, 43.2500),
             "巴里坤县": (93.0200, 43.6000), "巴里坤哈萨克自治县": (93.0200, 43.6000),
             "温宿县": (80.2400, 41.2800), "库车县": (82.9600, 41.7200), "库车市": (82.9600, 41.7200),
             "沙雅县": (82.7800, 41.2200), "新和县": (82.6100, 41.5500), "拜城县": (81.8700, 41.7900),
             "乌什县": (79.2300, 41.2200), "阿瓦提县": (80.3800, 40.6400), "柯坪县": (79.0500, 40.5100),
             "伊宁县": (81.5200, 43.9800), "霍城县": (80.8700, 44.0500), "巩留县": (82.2300, 43.4800),
             "新源县": (83.2600, 43.4300), "昭苏县": (81.1300, 43.1600), "特克斯县": (81.8600, 43.2200),
             "尼勒克县": (82.5100, 43.8000), "察布查尔锡伯自治县": (81.1300, 43.8400),
             "呼图壁县": (86.9000, 44.1900), "玛纳斯县": (86.2100, 44.3100), "奇台县": (89.5900, 44.0200),
             "吉木萨尔县": (89.1800, 44.0000), "木垒哈萨克自治县": (90.2800, 43.8400),
             "精河县": (82.8900, 44.6000), "温泉县": (81.0300, 44.9700),
             "焉耆回族自治县": (86.5700, 42.0600), "焉耆县": (86.5700, 42.0600),
             "和静县": (86.3900, 42.3200), "和硕县": (86.8600, 42.2700), "博湖县": (86.6300, 41.9800),
             "阿克陶县": (75.9500, 39.1500), "阿合奇县": (78.4500, 40.9400), "乌恰县": (75.2600, 39.7200),
             "塔城市": (82.9800, 46.7500), "乌苏市": (84.6800, 44.4300), "额敏县": (83.6300, 46.5300),
             "沙湾县": (85.6200, 44.3300), "托里县": (83.6100, 45.9400), "裕民县": (82.9800, 46.2000),
             "和布克赛尔蒙古自治县": (85.7300, 46.7900),
             "阿勒泰市": (88.1300, 47.8300), "布尔津县": (86.8700, 47.7000), "富蕴县": (89.5300, 46.9900),
             "福海县": (87.4900, 47.1200), "哈巴河县": (86.4200, 48.0600), "青河县": (90.3800, 46.6800),
             "吉木乃县": (85.8800, 47.4300)},
    # 台湾 — 暂用主要城市
    "台湾": {"台北市": (121.5654, 25.0330), "高雄市": (120.3119, 22.6209), "台中市": (120.6650, 24.1380),
             "台南市": (120.2400, 23.0000), "新北市": (121.4650, 25.0160)},
    # 香港
    "香港": {"香港岛": (114.1772, 22.2664), "九龙": (114.1888, 22.3129), "新界": (114.1600, 22.4000)},
    # 澳门
    "澳门": {"澳门半岛": (113.5491, 22.1987), "氹仔": (113.5537, 22.1566), "路环": (113.5670, 22.1300)},
}

# ===== 省份中心坐标（用于城市坐标未匹配时的回退）=====
PROVINCE_CENTERS: dict[str, tuple[float, float]] = {
    "北京": (116.4074, 39.9042), "天津": (117.2004, 39.0842), "河北": (114.5000, 38.0000),
    "山西": (112.5000, 37.9000), "内蒙古": (111.8000, 40.8000), "辽宁": (123.4000, 41.8000),
    "吉林": (125.3000, 43.8000), "黑龙江": (126.5000, 45.8000), "上海": (121.5000, 31.2000),
    "江苏": (118.8000, 32.1000), "浙江": (120.2000, 30.3000), "安徽": (117.2000, 31.8000),
    "福建": (119.3000, 26.1000), "江西": (115.9000, 28.7000), "山东": (117.1000, 36.7000),
    "河南": (113.6000, 34.7000), "湖北": (114.3000, 30.6000), "湖南": (112.9000, 28.2000),
    "广东": (113.3000, 23.1000), "广西": (108.4000, 22.8000), "海南": (110.2000, 20.0000),
    "重庆": (106.6000, 29.6000), "四川": (104.1000, 30.6000), "贵州": (106.6000, 26.6000),
    "云南": (102.8000, 24.9000), "西藏": (91.2000, 29.7000), "陕西": (108.9000, 34.3000),
    "甘肃": (103.8000, 36.1000), "青海": (101.8000, 36.6000), "宁夏": (106.2000, 38.5000),
    "新疆": (87.6000, 43.8000), "台湾": (121.5000, 25.0000), "香港": (114.2000, 22.3000),
    "澳门": (113.5000, 22.2000),
}


def _build_occupation_filter(occupation: Optional[str]):
    """构建多职业筛选条件（逗号分隔的 OR 逻辑）"""
    if not occupation:
        return None
    parts = [p.strip() for p in occupation.split(",") if p.strip()]
    if not parts:
        return None
    if len(parts) == 1:
        return DataPoint.population.ilike(f"%{parts[0]}%")
    return or_(*(DataPoint.population.ilike(f"%{p}%") for p in parts))


def _get_city_coords(province: str, city: str) -> tuple[Optional[float], Optional[float]]:
    """根据省份和城市名获取经纬度坐标，返回 (latitude, longitude)。

    优先精确匹配 CITY_COORDS，其次模糊匹配，最后回退到省份中心坐标。
    """
    province_coords = CITY_COORDS.get(province, {})
    if not province_coords:
        return None, None
    # 直接匹配
    if city in province_coords:
        lng, lat = province_coords[city]  # CITY_COORDS stores (longitude, latitude)
        return lat, lng
    # 模糊匹配：城市名包含某个 key 或 key 包含城市名
    for key, (lng, lat) in province_coords.items():
        if key in city or city in key:
            return lat, lng
    # 回退到省份中心坐标（确保县/区级数据也能在地图上显示）
    center = PROVINCE_CENTERS.get(province)
    if center:
        lng, lat = center
        return lat, lng
    return None, None


def _parse_provinces(raw: Optional[str]) -> list[str]:
    """从原始省份字符串中解析出标准省份名称列表"""
    if not raw:
        return ["unknown"]
    # 先按分号拆分
    parts = [p.strip() for p in raw.replace("；", ";").split(";") if p.strip()]
    result = []
    for part in parts:
        # 尝试标准化
        normalized = normalize_province(part)
        if normalized and normalized in CHINA_PROVINCE_NAMES:
            result.append(normalized)
            continue
        # 尝试从长文本中提取已知省份名称
        found = []
        for province_name in sorted(CHINA_PROVINCE_NAMES, key=len, reverse=True):
            if province_name in part:
                found.append(province_name)
                part = part.replace(province_name, "", 1)
        if found:
            result.extend(found)
        else:
            result.append(part)  # 无法识别的保留原文
    return result if result else ["unknown"]


def _normalize_seroprevalence(value: float) -> float:
    """标准化血清阳性率值：
    - 如果值在 0~1 之间（小数格式），转换为百分比（×100）
    - 上限封顶 100%
    """
    if value is None:
        return None
    v = float(value)
    if 0 < v <= 1:
        v = v * 100
    if v > 100:
        v = 100.0
    if v < 0:
        v = 0.0
    return round(v, 4)


def _calc_weighted_rate(dps: list, target_data_type: Optional[str] = None) -> tuple[Optional[float], int]:
    """计算加权平均率和总样本量。

    - target_data_type='seroprevalence': 仅使用阳性率数据点，值标准化到 0-100%
    - target_data_type='gmc': 仅使用 GMC 数据点
    - target_data_type=None: 仅使用 seroprevalence 数据点（避免与 GMC 混合导致 >100%）
    - 返回 (weighted_rate, total_sample)
    """
    # 未指定数据类型时，默认只计算 seroprevalence（阳性率），避免 GMC 混入导致 >100%
    effective_type = target_data_type or "seroprevalence"

    valid_dps = [
        dp for dp in dps
        if dp.sample_size and dp.value is not None and dp.data_type == effective_type
    ]

    if not valid_dps:
        return None, 0

    if effective_type == "seroprevalence":
        # 阳性率：标准化小数格式并封顶 100%
        weighted_sum = float(sum(_normalize_seroprevalence(dp.value) * dp.sample_size for dp in valid_dps))
    else:
        # GMC: 直接使用原始值
        weighted_sum = float(sum(float(dp.value) * dp.sample_size for dp in valid_dps))

    total_sample = int(sum(dp.sample_size for dp in valid_dps))
    weighted_rate = round(weighted_sum / total_sample, 2) if total_sample > 0 else None

    return weighted_rate, total_sample


async def get_province_data(
    db: AsyncSession,
    disease: Optional[str] = None,
    data_type: Optional[str] = None,
    province: Optional[str] = None,
    age_min: Optional[int] = None,
    age_max: Optional[int] = None,
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
    gender: Optional[str] = None,
    occupation: Optional[str] = None,
) -> list[dict]:
    """get province aggregated data (approved only, P1-1: primary estimates by default)"""
    base = select(DataPoint).where(
        DataPoint.review_status == "approved",
        DataPoint.estimate_type == "primary",
    )

    if disease:
        base = base.where(DataPoint.disease == disease)
    if data_type:
        base = base.where(DataPoint.data_type == data_type)
    if province:
        base = base.where(DataPoint.province.ilike(f"%{province}%"))
    if age_min is not None:
        base = base.where(DataPoint.age_min >= age_min)
    if age_max is not None:
        base = base.where(DataPoint.age_max <= age_max)
    if year_start:
        base = base.where(DataPoint.collection_year >= year_start)
    if year_end:
        base = base.where(DataPoint.collection_year <= year_end)
    if gender:
        base = base.where(DataPoint.population.ilike(f"%{gender}%"))
    occ_filter = _build_occupation_filter(occupation)
    if occ_filter is not None:
        base = base.where(occ_filter)

    result = await db.execute(base)
    rows = result.scalars().all()

    province_map: dict[str, dict] = {}

    for dp in rows:
        provinces = _parse_provinces(dp.province)

        for key in provinces:
            if key not in province_map:
                province_map[key] = {
                    "province": key,
                    "literature_ids": set(),
                    "data_points": [],
                }
            province_map[key]["literature_ids"].add(str(dp.literature_id) if dp.literature_id else "")
            province_map[key]["data_points"].append(dp)

    result_list = []
    for key, group in province_map.items():
        dps = group["data_points"]
        weighted_rate, total_sample = _calc_weighted_rate(dps, data_type)

        result_list.append({
            "province": key,
            "point_count": len(dps),
            "study_count": len(group["literature_ids"]),
            "total_sample": total_sample,
            "weighted_positivity": weighted_rate,
        })

    result_list.sort(key=lambda x: x["province"])
    return result_list


async def get_city_data(
    db: AsyncSession,
    province: str,
    disease: Optional[str] = None,
    data_type: Optional[str] = None,
) -> list[dict]:
    """get city-level aggregated data with coordinates (P1-1: primary estimates by default)"""
    base = (
        select(DataPoint)
        .where(DataPoint.review_status == "approved")
        .where(DataPoint.estimate_type == "primary")
        .where(DataPoint.province.ilike(f"%{province}%"))
    )
    if disease:
        base = base.where(DataPoint.disease == disease)
    if data_type:
        base = base.where(DataPoint.data_type == data_type)

    result = await db.execute(base)
    rows = result.scalars().all()

    city_map: dict[str, dict] = {}

    for dp in rows:
        city = dp.city or "unknown"
        if city not in city_map:
            city_map[city] = {"data_points": [], "literature_ids": set()}

        city_map[city]["data_points"].append(dp)
        city_map[city]["literature_ids"].add(str(dp.literature_id) if dp.literature_id else "")

    result_list = []
    for city, group in city_map.items():
        dps = group["data_points"]
        weighted_rate, total_sample = _calc_weighted_rate(dps, data_type)

        # 获取城市坐标
        lat, lng = _get_city_coords(province, city)

        result_list.append({
            "city": city,
            "point_count": len(dps),
            "study_count": len(group["literature_ids"]),
            "total_sample": total_sample,
            "weighted_positivity": weighted_rate,
            "latitude": lat,
            "longitude": lng,
        })

    result_list.sort(key=lambda x: x["city"])
    return result_list


async def get_summary(
    db: AsyncSession,
    disease: Optional[str] = None,
    data_type: Optional[str] = None,
) -> dict:
    """get national summary (P1-1: primary estimates by default)"""
    base = select(DataPoint).where(
        DataPoint.review_status == "approved",
        DataPoint.estimate_type == "primary",
    )
    if disease:
        base = base.where(DataPoint.disease == disease)
    if data_type:
        base = base.where(DataPoint.data_type == data_type)

    result = await db.execute(base)
    rows = result.scalars().all()

    if not rows:
        return {
            "province_count": 0,
            "point_count": 0,
            "study_count": 0,
            "total_sample": 0,
            "national_weighted_rate": None,
        }

    provinces = set()
    lit_ids = set()
    for dp in rows:
        for p in (dp.province or "").split(";"):
            p = p.strip()
            if p:
                provinces.add(p)
        if dp.literature_id:
            lit_ids.add(str(dp.literature_id))

    national_rate, total_sample = _calc_weighted_rate(rows, data_type)

    return {
        "province_count": len(provinces),
        "point_count": len(rows),
        "study_count": len(lit_ids),
        "total_sample": total_sample,
        "national_weighted_rate": national_rate,
    }


async def get_province_yearly_data(
    db: AsyncSession,
    disease: Optional[str] = None,
    data_type: Optional[str] = None,
    province: Optional[str] = None,
    age_min: Optional[int] = None,
    age_max: Optional[int] = None,
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
    gender: Optional[str] = None,
    occupation: Optional[str] = None,
) -> list[dict]:
    """按年份分组返回各省抗体水平数据，用于时间序列动态展示 (P1-1: primary estimates by default)"""
    base = select(DataPoint).where(
        DataPoint.review_status == "approved",
        DataPoint.estimate_type == "primary",
    )

    if disease:
        base = base.where(DataPoint.disease == disease)
    if data_type:
        base = base.where(DataPoint.data_type == data_type)
    if province:
        base = base.where(DataPoint.province.ilike(f"%{province}%"))
    if age_min is not None:
        base = base.where(DataPoint.age_min >= age_min)
    if age_max is not None:
        base = base.where(DataPoint.age_max <= age_max)
    if year_start:
        base = base.where(DataPoint.collection_year >= year_start)
    if year_end:
        base = base.where(DataPoint.collection_year <= year_end)
    if gender:
        base = base.where(DataPoint.population.ilike(f"%{gender}%"))
    occ_filter = _build_occupation_filter(occupation)
    if occ_filter is not None:
        base = base.where(occ_filter)

    result = await db.execute(base)
    rows = result.scalars().all()

    # 按年份分组: year -> { province_key -> aggregate }
    year_map: dict[int, dict[str, dict]] = {}

    for dp in rows:
        year = dp.collection_year or 0
        if year not in year_map:
            year_map[year] = {}

        provinces = _parse_provinces(dp.province)
        for key in provinces:
            if key not in year_map[year]:
                year_map[year][key] = {
                    "province": key,
                    "literature_ids": set(),
                    "data_points": [],
                }
            year_map[year][key]["literature_ids"].add(str(dp.literature_id) if dp.literature_id else "")
            year_map[year][key]["data_points"].append(dp)

    result_list = []
    for year in sorted(year_map.keys()):
        year_data = []
        for key, group in year_map[year].items():
            dps = group["data_points"]
            weighted_rate, total_sample = _calc_weighted_rate(dps, data_type)

            year_data.append({
                "province": key,
                "point_count": len(dps),
                "study_count": len(group["literature_ids"]),
                "total_sample": total_sample,
                "weighted_positivity": weighted_rate,
            })

        result_list.append({
            "year": year,
            "data": sorted(year_data, key=lambda x: x["province"]),
        })

    return result_list


async def get_available_years(
    db: AsyncSession,
    disease: Optional[str] = None,
) -> list[int]:
    """获取可用的年份列表（去重排序, P1-1: primary estimates by default）"""
    query = select(DataPoint.collection_year).where(
        DataPoint.review_status == "approved",
        DataPoint.estimate_type == "primary",
        DataPoint.collection_year.isnot(None),
    )
    if disease:
        query = query.where(DataPoint.disease == disease)
    query = query.distinct().order_by(DataPoint.collection_year)

    result = await db.execute(query)
    return [v for v in result.scalars().all() if v]


async def get_population_options(
    db: AsyncSession,
    disease: Optional[str] = None,
) -> list[str]:
    """获取所有已审核数据点中出现的人群分类（population 字段）。

    population 字段可能包含多个值（以分号分隔），这里拆分、去空白、去重、排序。
    仅查询主估计（estimate_type='primary'）避免子组重复。
    结果用于前端"全部职业"下拉框的动态选项。
    """
    query = select(DataPoint.population).where(
        DataPoint.review_status == "approved",
        DataPoint.estimate_type == "primary",
        DataPoint.population.isnot(None),
        DataPoint.population != "",
    )
    if disease:
        query = query.where(DataPoint.disease == disease)

    result = await db.execute(query)
    raw_values = result.scalars().all()

    # 拆分分号分隔的多个值，去空白、去重，并标准化合并同类别
    seen: set[str] = set()
    options: list[str] = []
    for raw in raw_values:
        if not raw:
            continue
        # 兼容中英文分号
        parts = raw.replace("；", ";").split(";")
        for p in parts:
            p = p.strip()
            if not p:
                continue
            # 标准化合并同类别
            normalized = _normalize_population(p)
            if normalized and normalized not in seen:
                seen.add(normalized)
                options.append(normalized)

    # 按拼音/字符排序（中文按 Unicode 排序）
    options.sort()
    return options
